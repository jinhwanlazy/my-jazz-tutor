#!/usr/bin/env python3
"""Publish and activate a committed runtime, retiring incompatible unfinished tasks."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from review import append_event, curriculum, incompatible_target_fields, log_lock, new_event, read_events, records, require
from launcher.src.jazz_practice import runtime

SOURCE = Path(__file__).resolve().parent
FILES = runtime.FILES


def publish(source, practice, activate=True, ref="HEAD"):
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
        events = read_events(practice)
        tasks = records(events)
        pin = runtime.read_pin(practice)
        marker = practice / "active-version"
        current = pin["version"] if pin else marker.read_text().strip() if marker.exists() else None
        pending = [t for t in tasks if not t["report"] and not t["cancelled"]]
        retirements, carried = [], []
        if activate:
            for task in pending:
                assignment = task["assignment"]
                changed = incompatible_target_fields(data, task)
                if not changed:
                    carried.append(assignment["task_id"])
                    continue
                event = new_event("retired", assignment["task_id"], data,
                                  assignment["exercise_id"], assignment["purpose"])
                event.update(release=assignment["release"],
                             reason=f"Retired on update to {version}: incompatible assigned conditions ({', '.join(changed)}). No practice result was inferred.")
                retirements.append(event)
            records(events + retirements)
            # A selected snapshot must understand the entire resulting history,
            # including retirement events, before any evidence or pin is changed.
            validation = subprocess.run(
                [sys.executable, "-c", "import json, sys, review; review.records(json.load(sys.stdin))"],
                cwd=destination, input=json.dumps(events + retirements), text=True,
                capture_output=True, timeout=30)
            require(validation.returncode == 0, "선택한 런타임이 연습 기록을 읽을 수 없어 활성화하지 않았습니다.")
            before = {name: (practice / name).read_bytes() if (practice / name).exists() else None
                      for name in ("practice.csv", "runtime.json", "active-version")}
            try:
                for event in retirements:
                    append_event(practice, event)
                runtime.activate(practice, manifest)
            except (OSError, ValueError):
                # Roll back this transition only; the lock excludes other writers.
                for name, content in before.items():
                    path = practice / name
                    if content is None:
                        path.unlink(missing_ok=True)
                    elif not path.exists() or path.read_bytes() != content:
                        runtime.atomic_text(path, content.decode("utf-8"))
                raise
    return {"installed": str(destination), "revision": manifest["revision"], "version": version,
            "active": version if activate else current, "activated": activate,
            "carried_tasks": carried, "retired_tasks": [event["task_id"] for event in retirements]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--practice-root", type=Path, default=SOURCE.parent / "practice")
    activation = parser.add_mutually_exclusive_group()
    activation.add_argument("--activate", dest="activate", action="store_true", help="발행한 버전 활성화 (기본)")
    activation.add_argument("--cache-only", dest="activate", action="store_false", help="활성화나 과제 변경 없이 캐시만 준비")
    parser.set_defaults(activate=True)
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
