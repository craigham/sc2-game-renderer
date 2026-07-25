"""One-off generator: dumps burnysc2's AbilityId/UnitTypeId enums to static JS so the
browser viewer can show human-readable names instead of raw integers.

Emitted as plain `.js` files defining a global const, loaded via a normal
`<script src>` tag — not `.json` fetched with `fetch()`, which most browsers refuse
for local `file://` pages (the whole point of the viewer is opening index.html
directly, no server). A <script> tag has no such restriction.

Static data, independent of any replay — regenerate only if burnysc2 is upgraded to
a version with new/renamed ids.

    uv run python scripts/generate_id_names.py
"""

import json
from pathlib import Path

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId

OUT_DIR = Path(__file__).parent.parent / "viewer" / "data"

ability_names = {str(a.value): a.name for a in AbilityId}
unit_type_names = {str(u.value): u.name for u in UnitTypeId}

(OUT_DIR / "ability_names.js").write_text(
    "const ABILITY_NAMES = " + json.dumps(ability_names, sort_keys=True) + ";\n"
)
(OUT_DIR / "unit_type_names.js").write_text(
    "const UNIT_TYPE_NAMES = " + json.dumps(unit_type_names, sort_keys=True) + ";\n"
)

print(f"wrote {len(ability_names)} ability names, {len(unit_type_names)} unit type names to {OUT_DIR}")
