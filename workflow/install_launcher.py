#!/usr/bin/env python3
"""Install the uv entry point without changing the active runtime or practice data."""
import argparse
import json
from pathlib import Path
import sys

from review import atomic_text, require

SOURCE = Path(__file__).resolve().parent / "launcher"
FILES = ["pyproject.toml", "uv.lock", "src/jazz_practice/__init__.py",
         "src/jazz_practice/runtime.py", "jazz", "runtime-ref"]


def install(practice):
    practice = Path(practice).resolve()
    require(all((practice / name).is_file() for name in ("AGENTS.md", "profile.json")),
            "기존 practice 디렉터리를 지정하세요.")
    contents = {name: (SOURCE / name).read_text() for name in FILES}
    for name, text in contents.items():
        atomic_text(practice / name, text)
    (practice / "jazz").chmod(0o755)
    return {"installed": str(practice), "command": "uv run jazz"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--practice-root", type=Path, default=SOURCE.parent.parent / "practice")
    args = parser.parse_args()
    try:
        print(json.dumps(install(args.practice_root), ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
