"""The only module in this codebase that talks to SC2.

Owns SC2Process / start_replay / step. Not unit tested — that needs a running SC2
client, which does not launch on this Mac (docs/SPEC.md § Chief risk) and instead
runs in the `sc2-extract` Docker image. Verified by running extract end-to-end
against the fixture replay; every other module here is pure and unit-tested without
SC2.
"""

from pathlib import Path
from typing import AsyncIterator

from s2clientprotocol import data_pb2, sc2api_pb2 as sc_pb
from sc2.client import Client
from sc2.sc2process import SC2Process


async def _start_replay(server, replay: Path, observed_id: int) -> None:
    """python-sc2's start_replay() rewrites the path to a basename on Linux, and the
    client then fails to resolve it ("Unable to open replay"). Issue the request
    ourselves: absolute path first, falling back to the raw replay bytes.

    Fog stays enabled throughout — disable_fog is never set, so we only ever observe
    what `observed_id` could see.
    """
    ifopts = sc_pb.InterfaceOptions(
        raw=True, score=True, show_cloaked=True, raw_affects_selection=True, raw_crop_to_playable_area=False
    )
    for kwargs in ({"replay_path": str(replay)}, {"replay_data": replay.read_bytes()}):
        result = await server._execute(
            start_replay=sc_pb.RequestStartReplay(
                observed_player_id=observed_id, realtime=False, options=ifopts, **kwargs
            )
        )
        if result.status == 4:
            return
    raise RuntimeError(f"could not start replay: {replay}")


class ReplaySession:
    """One SC2 process, one replay, from `async with` to game end.

        async with ReplaySession(replay, observed_id=2) as session:
            header_source = session.game_info          # ResponseGameInfo
            async for obs in session.observations(sample_loops=4):
                ...                                     # ResponseObservation

    game_info and structure_type_ids are both fetched once, right after the replay
    starts, so the frame file header, the per-unit structure classification, and the
    frame stream all come from a single SC2 launch.
    """

    def __init__(self, replay: Path, observed_id: int):
        self._replay = replay
        self._observed_id = observed_id
        self._process = SC2Process(fullscreen=False)
        self._server = None
        self._client: Client | None = None
        self.game_info: sc_pb.ResponseGameInfo | None = None
        # unit_type -> is a Structure (building), per SC2's own game data (the
        # Structure attribute) rather than a guess from radius/health — a Thor or
        # Ultralisk has a large radius too, but isn't a structure. This is static
        # per SC2 build, not per-replay, but fetching it is cheap and reuses the
        # one SC2 launch this replay already needs.
        self.structure_type_ids: frozenset[int] = frozenset()

    async def __aenter__(self) -> "ReplaySession":
        self._server = await self._process.__aenter__()
        await self._server.ping()
        await _start_replay(self._server, self._replay, self._observed_id)
        self._client = Client(self._server._ws)
        result = await self._server._execute(game_info=sc_pb.RequestGameInfo())
        self.game_info = result.game_info

        data_result = await self._server._execute(data=sc_pb.RequestData(unit_type_id=True))
        self.structure_type_ids = frozenset(
            u.unit_id for u in data_result.data.units if data_pb2.Attribute.Structure in u.attributes
        )
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self._process.__aexit__(*exc_info)

    async def observations(self, sample_loops: int) -> AsyncIterator[sc_pb.ResponseObservation]:
        """One ResponseObservation per sampled game loop until the replay ends."""
        assert self._client is not None, "use within 'async with ReplaySession(...)'"
        while True:
            result = await self._client.observation()
            yield result.observation
            if result.observation.player_result:
                return
            await self._client.step(sample_loops)
