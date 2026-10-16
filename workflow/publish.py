#!/usr/bin/env python3
"""Install an immutable, local runtime. Never copy or mutate practice evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import sys
import tomllib

from review import atomic_text, curriculum, log_lock, read_events, records, require

SOURCE = Path(__file__).resolve().parent
FILES = ["review.py", "COACH.md", "curriculum.yaml", "pyproject.toml", "uv.lock",
         "webapp.py", "sessions.py", "webapp.html", "webapp.css", "webapp.js", "audio.mjs", "capture.mjs"]


def publish(source, practice, activate=False):
    source, practice = Path(source).resolve(), Path(practice).resolve()
    require(source != practice, "소스와 연습 디렉터리가 같을 수 없습니다.")
    require((practice / "AGENTS.md").exists() and (practice / "profile.json").exists(), "연습 프로젝트를 먼저 준비하세요.")
    data = curriculum(source / "curriculum.yaml")
    version = data["version"]
    project = tomllib.loads((source / "pyproject.toml").read_text())
    require(project["project"]["version"] == version, "curriculum과 pyproject의 version을 함께 올리세요.")
    require(all((source / name).is_file() for name in FILES), "발행 파일이 누락되었습니다. uv lock도 생성해야 합니다.")
    hashes = {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in FILES}
    releases = practice / "releases"
    releases.mkdir(exist_ok=True)
    destination = releases / version
    with log_lock(practice):
        tasks = records(read_events(practice))
        marker = practice / "active-version"
        current = marker.read_text().strip() if marker.exists() else None
        pending = [t for t in tasks if not t["report"] and not t["cancelled"]]
        if activate and current != version:
            require(not pending, "미완료 과제가 있어 활성화할 수 없습니다. 현재 버전으로 결과를 기록하거나 과제를 취소하세요.")
        if destination.exists():
            manifest_path = destination / "manifest.json"
            require(manifest_path.is_file(), "기존 발행본에 manifest가 없습니다. 덮어쓰지 않습니다.")
            manifest = json.loads(manifest_path.read_text())
            require(manifest.get("sha256") == hashes, "이 버전은 이미 다른 내용으로 발행되었습니다. version을 올리세요.")
            require(all((destination / name).is_file() and hashlib.sha256((destination / name).read_bytes()).hexdigest() == digest for name, digest in hashes.items()), "설치된 발행본이 변경되었습니다. 덮어쓰지 않습니다.")
        else:
            temporary = Path(tempfile.mkdtemp(prefix=".release-", dir=releases))
            try:
                for name in FILES:
                    shutil.copy2(source / name, temporary / name)
                (temporary / "manifest.json").write_text(json.dumps({"version": version, "sha256": hashes}, ensure_ascii=False, indent=2) + "\n")
                os.rename(temporary, destination)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
        if activate:
            atomic_text(marker, version + "\n")
    return {"installed": str(destination), "active": version if activate else current, "activated": activate}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--practice-root", type=Path, default=SOURCE.parent / "practice")
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(publish(SOURCE, args.practice_root, args.activate), ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
