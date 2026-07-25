# linux/amd64 SC2 4.10 headless + python, for the extract stage.
#
# Derived from stephanzlatarev/starcraft, which already carries Blizzard's
# public SC2.4.10.zip Linux build at /StarCraftII (Base75689) — the same build
# the ladder runs, and the one our replays need.
#
# Build (from repo root):
#   docker build --platform=linux/amd64 -t sc2-extract:4.10 docker/
FROM --platform=linux/amd64 stephanzlatarev/starcraft:latest

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir --break-system-packages burnysc2

ENV SC2PATH=/StarCraftII
# python-sc2's start_replay() insists, on Linux, that the replay live here and
# passes only the basename to the client (sc2/controller.py).
ENV REPLAY_DIR="/root/Documents/StarCraft II/Replays"
RUN mkdir -p "$REPLAY_DIR"

WORKDIR /work
ENTRYPOINT ["python3"]
