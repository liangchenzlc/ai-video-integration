"""Export from application models without binding sockets or reading user settings."""

import argparse
import json
import secrets
import sys
from pathlib import Path
from uuid import uuid4

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.main import create_app  # noqa: E402
from app.runtime.context import RuntimeContext  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    context = RuntimeContext(
        runtime_id=str(uuid4()),
        generation=1,
        token_bytes=secrets.token_bytes(32),
        app_data_dir=BACKEND,
        mode="production",
        port=1,
    )
    schema = create_app(context).openapi()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Exported {len(schema['paths'])} runtime paths")


if __name__ == "__main__":
    main()
