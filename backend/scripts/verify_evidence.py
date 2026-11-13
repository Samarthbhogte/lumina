"""Check a Lumina evidence pack offline: python -m backend.scripts.verify_evidence pack.pdf"""

import sys
from pathlib import Path

from backend.evidence import verify_pack


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    valid, message, record = verify_pack(Path(sys.argv[1]).read_bytes())
    print(message)
    if record:
        print(
            f"Exported {record.get('exported_at')} by {record.get('exported_by', {}).get('email')}, "
            f"{len(record.get('answers', []))} answer(s), workspace {record.get('workspace', {}).get('name')}"
        )
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
