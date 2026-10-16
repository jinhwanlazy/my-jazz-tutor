#!/usr/bin/env python3
"""Cache a committed Git runtime and optionally activate it for local practice."""
import argparse
import json
from pathlib import Path
import sys

from review import curriculum, log_lock, read_events, records, require
from launcher.src.jazz_practice import runtime

SOURCE = Path(__file__).resolve().parent
FILES = runtime.FILES


def publish(source, practice, activate=False, ref="HEAD"):
    source, practice = Path(source).resolve(), Path(practice).resolve()
    require(source != practice, "소스와 연습 디렉터리가 같을 수 없습니다.")
    require((practice / "AGENTS.md").exists() and (practice / "profile.json").exists(), "연습 프로젝트를 먼저 준비하세요.")
    manifest, contents = runtime.snapshot(runtime.repository(source), ref)
    if ref == "HEAD":
        require(all((source / name).is_file() and (source / name).read_bytes() == data
                    for name, data in contents.items()),
                "실행 소스 변경을 먼저 Git에 커밋하세요. 이전 버전 설치는 --ref로 명시하세요.")
    version = manifest["version"]
    with log_lock(practice):
        destination = runtime.materialize(practice, manifest, contents)
        data = curriculum(destination / "curriculum.yaml")
        require(data["version"] == version, "curriculum과 pyproject의 version이 다릅니다.")
        tasks = records(read_events(practice))
        pin = runtime.read_pin(practice)
        marker = practice / "active-version"
        current = pin["version"] if pin else marker.read_text().strip() if marker.exists() else None
        pending = [t for t in tasks if not t["report"] and not t["cancelled"]]
        same_revision = pin is not None and pin["revision"] == manifest["revision"]
        # Migration can pin an identical legacy installation without changing a pending task.
        legacy = practice / "releases" / version
        same_legacy = pin is None and current == version and all(
            (legacy / name).is_file() and (legacy / name).read_bytes() == content
            for name, content in contents.items())
        if activate and not (same_revision or same_legacy):
            require(not pending, "미완료 과제가 있어 활성화할 수 없습니다. 현재 버전으로 결과를 기록하거나 과제를 취소하세요.")
        if activate:
            runtime.activate(practice, manifest)
    return {"installed": str(destination), "revision": manifest["revision"], "version": version,
            "active": version if activate else current, "activated": activate}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--practice-root", type=Path, default=SOURCE.parent / "practice")
    parser.add_argument("--activate", action="store_true")
    parser.add_argument("--ref", default="HEAD", help="설치할 Git commit/tag (기본: HEAD)")
    args = parser.parse_args()
    try:
        print(json.dumps(publish(SOURCE, args.practice_root, args.activate, args.ref), ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
