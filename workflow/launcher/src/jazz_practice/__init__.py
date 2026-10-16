"""Delegate to the practice launcher and its locally pinned Git runtime."""
import os
from pathlib import Path
import runpy
import sys


def main():
    # Editable and regular installs both stay attached to their practice workspace.
    # An isolated uv environment can still resolve it from the working directory.
    candidates = [*Path(__file__).resolve().parents, Path.cwd()]
    root = next((path for path in candidates
                 if (path / "runtime-ref").is_file() and (path / "jazz").is_file()), None)
    if root is None:
        print("오류: 연습 디렉터리를 찾지 못했습니다. practice 폴더에서 실행하세요.", file=sys.stderr)
        return 2
    sys.argv = [str(root / "jazz"), *(sys.argv[1:] or ["serve", "--open"])]
    # The installed release owns its dependency environment, independently of this shim.
    os.environ.pop("VIRTUAL_ENV", None)
    os.environ.pop("UV_PROJECT_ENVIRONMENT", None)
    runpy.run_path(str(root / "jazz"), run_name="__main__")
    return 0
