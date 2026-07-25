"""Read the length-delimited-gzip capture format used by tests/fixtures/.

Format documented in tests/fixtures/README.md.
"""

import gzip
import struct
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def read_records(path: Path, msg_type):
    with gzip.open(path, "rb") as f:
        while header := f.read(4):
            (length,) = struct.unpack("<I", header)
            yield msg_type.FromString(f.read(length))
