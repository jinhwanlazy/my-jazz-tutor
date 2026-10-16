#!/usr/bin/env python3
"""Versioned practice CLI. CSV is evidence; the HTML report is disposable."""
from __future__ import annotations

import argparse
import csv
import fcntl
import html
import io
import json
import os
import re
import sys
import tempfile
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
FIELDS = [
    "event_id", "task_id", "event_type", "recorded_at", "practice_date",
    "release", "exercise_id", "purpose", "target_json", "actual_json",
    "checks_json", "clean_runs", "actual_minutes", "difficulty", "raw_note",
    "hypothesis", "reason", "supersedes",
]
SPEC = ["key", "bpm", "bars", "arrangement", "rhythm", "bass", "voicing", "melody", "material_id"]
CHECKS = ["notes_correct", "steady_pulse", "no_stops"]
STATES = {"unknown": "미평가", "attempted": "연습 기록", "success": "당일 성공", "retained": "후일 재현"}
RESULTS = {"unknown": "근거 부족", "unmet": "목표 미충족", "success": "조건 충족"}
DOMAINS = {"melody": "멜로디", "rhythm": "리듬", "bass": "베이스", "voicing": "보이싱"}
ARRANGEMENTS = {
    "left-bass-only": "왼손 베이스만", "right-melody-only": "오른손 멜로디만",
    "melody-and-bass": "오른손 멜로디 + 왼손 베이스",
    "left-root-right-guides": "왼손 루트 + 오른손 3도·7도",
    "left-root-right-improv": "왼손 루트 + 오른손 즉흥",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value, name, low=0, high=10000):
    require(type(value) in (int, float) and low <= value <= high, f"{name}: {low}~{high} 숫자가 필요합니다.")
    return value


def iso_day(value):
    require(isinstance(value, str), "날짜는 YYYY-MM-DD 문자열이어야 합니다.")
    parsed = date.fromisoformat(value)
    require(parsed.isoformat() == value, "날짜는 YYYY-MM-DD 형식이어야 합니다.")
    return parsed


def jdump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def curriculum(path=HERE / "curriculum.yaml"):
    data = yaml.safe_load(Path(path).read_text())
    require(isinstance(data, dict) and data.get("schema_version") == 1, "지원하지 않는 curriculum schema입니다.")
    require(bool(re.fullmatch(r"\d+\.\d+\.\d+", str(data.get("version", "")))), "version은 x.y.z 형식이어야 합니다.")
    keys = data["allowed_keys"]
    require(isinstance(keys, list) and keys and len(keys) == len(set(keys)), "allowed_keys가 잘못되었습니다.")
    require(data["default_key"] in keys, "default_key가 허용 키에 없습니다.")
    number(data["default_bpm"], "default_bpm", data["minimum_bpm"], data["maximum_bpm"])
    number(data["daily_minutes"], "daily_minutes", 1, 120)
    number(data["retention_days"], "retention_days", 1, 365)
    number(data["maintenance_days"], "maintenance_days", data["retention_days"], 365)
    criteria = data["criteria"]
    require(criteria.get("id") and criteria.get("explanation"), "통과 기준 ID와 설명이 필요합니다.")
    require(criteria.get("checks") == CHECKS, "지원하지 않는 통과 검사입니다.")
    number(criteria["min_clean_runs"], "min_clean_runs", 1, 20)
    require(type(criteria["min_clean_runs"]) is int, "연속 성공 횟수는 정수여야 합니다.")
    lessons = data["exercises"]
    require(isinstance(lessons, list) and lessons, "연습 항목이 필요합니다.")
    ids = [x["id"] for x in lessons]
    require(len(ids) == len(set(ids)), "exercise ID가 중복됩니다.")
    by_id = {x["id"]: x for x in lessons}
    for lesson in lessons:
        require(lesson.get("title") and lesson.get("instructions"), "제목과 구체적 지침이 필요합니다.")
        require(lesson.get("domains") and set(lesson["domains"]) <= set(DOMAINS), "domain이 잘못되었습니다.")
        number(lesson["bars"], "bars", 1, 128)
        require(type(lesson["bars"]) is int, "마디 수는 정수여야 합니다.")
        for field in SPEC[3:]:
            require(isinstance(lesson.get(field), str) and lesson[field], f"{lesson['id']}: {field} 누락")
        material = data["materials"][lesson["material_id"]]
        require(material.get("title"), "연습 자료 제목이 필요합니다.")
        for key in keys:
            require(isinstance(material.get(key), dict) and material[key].get("chords"), f"{key} 자료가 없습니다.")
        require(all(p in by_id for p in lesson["prerequisites"]), "없는 선행 항목을 참조했습니다.")
    def visit(item, trail):
        require(item not in trail, "선행 조건에 순환이 있습니다.")
        for parent in by_id[item]["prerequisites"]:
            visit(parent, trail | {item})
    for item in ids:
        visit(item, set())
    seen = set()
    for milestone in data["milestones"]:
        token = (milestone["exercise_id"], milestone["key"])
        require(token not in seen and token[0] in by_id and token[1] in keys, "대표 목표가 중복되거나 잘못되었습니다.")
        seen.add(token)
        number(milestone["bpm"], "milestone bpm", data["minimum_bpm"], data["maximum_bpm"])
    require(seen, "고정 대표 목표가 필요합니다.")
    return data


def target_for(data, exercise_id, key=None, bpm=None):
    lesson = next((x for x in data["exercises"] if x["id"] == exercise_id), None)
    require(lesson is not None, f"없는 exercise ID: {exercise_id}")
    key = key or data["default_key"]
    bpm = data["default_bpm"] if bpm is None else bpm
    require(key in data["allowed_keys"], "허용되지 않은 키입니다.")
    number(bpm, "bpm", data["minimum_bpm"], data["maximum_bpm"])
    material = data["materials"][lesson["material_id"]]
    return {
        **{k: lesson[k] for k in SPEC[2:]}, "key": key, "bpm": bpm,
        "title": lesson["title"], "instructions": lesson["instructions"],
        "material": {"title": material["title"], **material[key]},
        "criteria": data["criteria"], "domains": lesson["domains"],
        "curriculum_version": data["version"], "daily_minutes": data["daily_minutes"],
    }


def read_events(root):
    path = Path(root) / "practice.csv"
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        require(reader.fieldnames == FIELDS, "CSV 헤더가 다릅니다. 임의 수정하지 말고 schema를 확인하세요.")
        rows = list(reader)
    require(all(set(row) == set(FIELDS) and all(v is not None for v in row.values()) for row in rows), "CSV 행이 손상되었습니다.")
    return rows


def records(events):
    """Reconstruct attempts while retaining all corrections in the source CSV."""
    tasks, event_ids = {}, set()
    for event in events:
        require(event["event_id"] and event["event_id"] not in event_ids, "중복/빈 event_id입니다.")
        event_ids.add(event["event_id"])
        task_id = event["task_id"]
        require(task_id, "task_id가 필요합니다.")
        datetime.fromisoformat(event["recorded_at"])
        kind = event["event_type"]
        if kind == "assigned":
            require(task_id not in tasks, "중복 과제 발급입니다.")
            target = json.loads(event["target_json"])
            require(all(k in target for k in SPEC + ["criteria", "material"]), "과제 조건 스냅샷이 불완전합니다.")
            number(target["bpm"], "target bpm", 1, 400)
            number(target["bars"], "target bars", 1, 1000)
            require(target["criteria"].get("checks") == CHECKS, "알 수 없는 과제 기준입니다.")
            number(target["criteria"]["min_clean_runs"], "min_clean_runs", 1, 20)
            tasks[task_id] = {"assignment": event, "target": target, "report": None, "cancelled": False}
            continue
        require(task_id in tasks, "발급되지 않은 과제의 결과입니다.")
        task = tasks[task_id]
        require(event["release"] == task["assignment"]["release"] and event["exercise_id"] == task["assignment"]["exercise_id"], "과제의 버전/항목이 바뀌었습니다.")
        if kind == "cancelled":
            require(not task["report"] and not task["cancelled"], "종료된 과제를 취소할 수 없습니다.")
            task["cancelled"] = True
        elif kind in ("reported", "corrected"):
            require(not task["cancelled"], "취소한 과제의 결과를 기록할 수 없습니다.")
            if kind == "reported":
                require(task["report"] is None and not event["supersedes"], "중복 결과입니다. 정정은 correct를 사용하세요.")
            else:
                require(task["report"] and event["supersedes"] == task["report"]["event_id"], "정정 대상이 최신 결과가 아닙니다.")
            practice_day = iso_day(event["practice_date"])
            assigned_day = datetime.fromisoformat(task["assignment"]["recorded_at"]).date()
            require(practice_day >= assigned_day, "연습일이 과제 발급일보다 빠릅니다.")
            require(event["raw_note"].strip(), "사용자 원문 노트가 필요합니다.")
            actual = json.loads(event["actual_json"])
            checks = json.loads(event["checks_json"])
            validate_observations(actual, checks)
            for field, high in [("clean_runs", 1000), ("actual_minutes", 1440)]:
                if event[field]:
                    number(float(event[field]), field, 0, high)
            if event["clean_runs"]:
                require(float(event["clean_runs"]).is_integer(), "연속 성공 횟수는 정수여야 합니다.")
            task["report"] = event
        else:
            raise ValueError(f"지원하지 않는 event_type: {kind}")
    return list(tasks.values())


def validate_observations(actual, checks):
    require(isinstance(actual, dict) and set(actual) <= set(SPEC), "actual에 알 수 없는 항목이 있습니다.")
    require(isinstance(checks, dict) and set(checks) <= set(CHECKS), "checks에 알 수 없는 항목이 있습니다.")
    for key, value in actual.items():
        if value is None:
            continue
        if key in ("bpm", "bars"):
            number(value, key, 1, 1000)
            if key == "bars":
                require(type(value) is int, "실제 마디 수는 정수여야 합니다.")
        else:
            require(isinstance(value, str) and value.strip(), f"actual.{key}는 문자열이어야 합니다.")
    require(all(v is None or type(v) is bool for v in checks.values()), "checks는 true/false/null만 허용합니다.")


def outcome(task):
    report = task["report"]
    if report is None:
        return "unknown"
    actual, checks = json.loads(report["actual_json"]), json.loads(report["checks_json"])
    missing = False
    for key in SPEC:
        value = actual.get(key)
        if value is None:
            missing = True
        elif key == "bpm":
            if value < task["target"][key]:
                return "unmet"
        elif value != task["target"][key]:
            return "unmet"
    for key in task["target"]["criteria"]["checks"]:
        if checks.get(key) is False:
            return "unmet"
        if checks.get(key) is not True:
            missing = True
    if not report["clean_runs"]:
        missing = True
    elif float(report["clean_runs"]) < task["target"]["criteria"]["min_clean_runs"]:
        return "unmet"
    return "unknown" if missing else "success"


def goal_successes(data, tasks, exercise_id, key, bpm):
    expected = target_for(data, exercise_id, key, bpm)
    successful = []
    for task in tasks:
        if task["assignment"]["exercise_id"] != exercise_id or outcome(task) != "success":
            continue
        actual = json.loads(task["report"]["actual_json"])
        if actual["bpm"] < bpm or any(actual[k] != expected[k] for k in SPEC if k != "bpm"):
            continue
        if task["target"]["criteria"] != expected["criteria"] or task["target"]["material"] != expected["material"]:
            continue
        successful.append(task)
    return successful


def retained(tasks, days):
    groups = {}
    for task in tasks:
        fingerprint = jdump({"actual": json.loads(task["report"]["actual_json"]), "criteria": task["target"]["criteria"]})
        groups.setdefault(fingerprint, []).append(iso_day(task["report"]["practice_date"]))
    return any((max(dates) - min(dates)).days >= days for dates in groups.values())


def cell(data, tasks, exercise_id, key, bpm=None):
    bpm = data["default_bpm"] if bpm is None else bpm
    successes = goal_successes(data, tasks, exercise_id, key, bpm)
    attempted = [t for t in tasks if t["report"] and t["assignment"]["exercise_id"] == exercise_id
                 and json.loads(t["report"]["actual_json"]).get("key", t["target"]["key"]) == key]
    state = "retained" if retained(successes, data["retention_days"]) else "success" if successes else "attempted" if attempted else "unknown"
    return {"state": state, "attempts": len(attempted), "successes": len(successes),
            "last_success": max((t["report"]["practice_date"] for t in successes), default=None)}


def suggestion(data, tasks, today=None):
    today = today or date.today()
    pending = [t for t in tasks if not t["report"] and not t["cancelled"]]
    if pending:
        task = pending[0]
        return {"action": "resume", "task_id": task["assignment"]["task_id"], "target": task["target"], "reason": "미완료 과제가 있습니다. 새로 발급하지 않고 이어갑니다."}
    for milestone in data["milestones"]:
        info = cell(data, tasks, milestone["exercise_id"], milestone["key"], milestone["bpm"])
        delay = data["maintenance_days"] if info["state"] == "retained" else data["retention_days"]
        if info["last_success"] and (today - iso_day(info["last_success"])).days >= delay:
            successes = goal_successes(data, tasks, milestone["exercise_id"], milestone["key"], milestone["bpm"])
            latest = max(successes, key=lambda t: t["report"]["practice_date"])
            actual_bpm = json.loads(latest["report"]["actual_json"])["bpm"]
            return {"action": "review", **milestone, "bpm": actual_bpm, "reason": "이전 성공과 같은 템포로 후일 재현을 확인할 시점입니다."}
    by_id = {x["id"]: x for x in data["exercises"]}
    for milestone in data["milestones"]:
        if goal_successes(data, tasks, **milestone):
            continue
        lesson = by_id[milestone["exercise_id"]]
        if all(goal_successes(data, tasks, parent, milestone["key"], data["default_bpm"]) for parent in lesson["prerequisites"]):
            return {"action": "practice", **milestone, "reason": "아직 확인하지 못한 대표 목표입니다. 최근 노트에 따라 반복 또는 확인 과제를 선택하세요."}
    return {"action": "consolidate", "reason": "대표 목표의 당일 성공을 기록했습니다. 연결 연주·듣기·후일 복습을 진행하세요. 새 곡/키는 별도 증거가 필요합니다."}


@contextmanager
def log_lock(root):
    root = Path(root)
    require(root.is_dir(), "practice 디렉터리가 없습니다.")
    with (root / ".practice.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def append_event(root, event):
    path = Path(root) / "practice.csv"
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if f.tell() == 0:
            writer.writeheader()
        writer.writerow(event)
        f.flush()
        os.fsync(f.fileno())


def new_event(kind, task_id, data, exercise_id, purpose="practice"):
    event = dict.fromkeys(FIELDS, "")
    event.update(event_id="EV-" + uuid.uuid4().hex[:12], task_id=task_id, event_type=kind,
                 recorded_at=datetime.now(timezone.utc).isoformat(), release=data["version"],
                 exercise_id=exercise_id, purpose=purpose)
    return event


def assign(root, data, exercise_id, key=None, bpm=None, purpose="practice", reason=""):
    require(purpose in ("practice", "diagnostic", "review", "transfer"), "purpose 값이 잘못되었습니다.")
    target = target_for(data, exercise_id, key, bpm)
    with log_lock(root):
        events = read_events(root)
        tasks = records(events)
        require(not any(not t["report"] and not t["cancelled"] for t in tasks), "미완료 과제를 먼저 기록하거나 취소하세요.")
        lesson = next(x for x in data["exercises"] if x["id"] == exercise_id)
        if purpose != "diagnostic":
            for parent in lesson["prerequisites"]:
                require(goal_successes(data, tasks, parent, target["key"], data["default_bpm"]), f"같은 키의 선행 항목 {parent}를 먼저 확인하세요. 원인 확인 목적이면 diagnostic을 명시하세요.")
        event = new_event("assigned", "T-" + uuid.uuid4().hex[:10], data, exercise_id, purpose)
        event.update(target_json=jdump(target), reason=reason)
        records(events + [event])
        append_event(root, event)
    return {"task_id": event["task_id"], "target": target, "reason": reason}


def record_result(root, data, task_id, payload, correction=False):
    require(isinstance(payload, dict), "결과 JSON은 object여야 합니다.")
    allowed = {"practice_date", "actual", "checks", "clean_runs", "actual_minutes", "difficulty", "raw_note", "hypothesis", "followed_target"}
    require(set(payload) <= allowed, "결과 JSON에 알 수 없는 필드가 있습니다.")
    require(isinstance(payload.get("raw_note"), str) and payload["raw_note"].strip(), "raw_note에 사용자 원문이 필요합니다.")
    require(type(payload.get("followed_target", False)) is bool, "followed_target은 boolean입니다.")
    with log_lock(root):
        events = read_events(root)
        task = next((t for t in records(events) if t["assignment"]["task_id"] == task_id), None)
        require(task is not None and not task["cancelled"], "활성 과제 ID를 찾지 못했습니다.")
        require(bool(task["report"]) == correction, "이미 결과가 있으면 correct, 최초 결과는 record를 사용하세요.")
        actual = {k: task["target"][k] for k in SPEC} if payload.get("followed_target") else {}
        require(isinstance(payload.get("actual", {}), dict), "actual은 object입니다.")
        actual.update(payload.get("actual", {}))
        checks = payload.get("checks", {})
        validate_observations(actual, checks)
        practice_day = payload.get("practice_date", date.today().isoformat())
        require(iso_day(practice_day) <= date.today(), "미래의 연습 결과를 기록할 수 없습니다.")
        for field, high in [("clean_runs", 1000), ("actual_minutes", 1440)]:
            if payload.get(field) is not None:
                number(payload[field], field, 0, high)
        if payload.get("clean_runs") is not None:
            require(type(payload["clean_runs"]) is int, "연속 성공 횟수는 정수여야 합니다.")
        difficulty = payload.get("difficulty", "unknown")
        require(difficulty in ("easy", "manageable", "hard", "unknown"), "difficulty 값이 잘못되었습니다.")
        require(isinstance(payload.get("hypothesis", ""), str), "hypothesis는 문자열입니다.")
        event = new_event("corrected" if correction else "reported", task_id, data, task["assignment"]["exercise_id"], task["assignment"]["purpose"])
        event.update(release=task["assignment"]["release"], practice_date=practice_day,
                     actual_json=jdump(actual), checks_json=jdump(checks),
                     difficulty=difficulty, raw_note=payload["raw_note"], hypothesis=payload.get("hypothesis", ""),
                     clean_runs="" if payload.get("clean_runs") is None else str(payload["clean_runs"]),
                     actual_minutes="" if payload.get("actual_minutes") is None else str(payload["actual_minutes"]),
                     supersedes=task["report"]["event_id"] if correction else "")
        updated = records(events + [event])
        append_event(root, event)
    result = next(t for t in updated if t["assignment"]["task_id"] == task_id)
    return {"task_id": task_id, "event_id": event["event_id"], "outcome": outcome(result), "evidence": "self-report"}


def cancel(root, data, task_id, reason):
    require(reason.strip(), "취소 이유가 필요합니다.")
    with log_lock(root):
        events = read_events(root)
        task = next((t for t in records(events) if t["assignment"]["task_id"] == task_id), None)
        require(task is not None, "없는 과제입니다.")
        event = new_event("cancelled", task_id, data, task["assignment"]["exercise_id"], task["assignment"]["purpose"])
        event.update(release=task["assignment"]["release"], reason=reason)
        records(events + [event])
        append_event(root, event)
    return {"cancelled": task_id}


def status(root, data):
    tasks = records(read_events(root))
    profile_path = Path(root) / "profile.json"
    profile = json.loads(profile_path.read_text()) if profile_path.exists() else {}
    reported = [t for t in tasks if t["report"]]
    goals = [{**m, **cell(data, tasks, **m)} for m in data["milestones"]]
    return {"version": data["version"], "profile": profile, "evidence": "자기보고 기반 / 미평가는 실패가 아님",
            "reported_attempts": len(reported), "known_minutes": sum(float(t["report"]["actual_minutes"]) for t in reported if t["report"]["actual_minutes"]),
            "minutes_unknown": sum(not bool(t["report"]["actual_minutes"]) for t in reported),
            "goals": goals, "next": suggestion(data, tasks),
            "recent": [{"task_id": t["assignment"]["task_id"], "exercise": t["assignment"]["exercise_id"],
                        "date": t["report"]["practice_date"], "actual": json.loads(t["report"]["actual_json"]),
                        "outcome": outcome(t), "raw_note": t["report"]["raw_note"], "hypothesis": t["report"]["hypothesis"]}
                       for t in reported[-5:]]}


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".write-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def render_report(root, data, output=None):
    root = Path(root)
    tasks = records(read_events(root))
    info = status(root, data)
    escape = lambda x: html.escape(str(x))
    goals = info["goals"]
    passed = sum(g["state"] in ("success", "retained") for g in goals)
    held = sum(g["state"] == "retained" for g in goals)
    required = {(g["exercise_id"], g["key"]) for g in goals}
    table = []
    for lesson in data["exercises"]:
        cells = []
        for key in data["allowed_keys"]:
            metric = cell(data, tasks, lesson["id"], key)
            tag = "대표 목표" if (lesson["id"], key) in required else "선택 키"
            cells.append(f'<td class="{metric["state"]}"><b>{STATES[metric["state"]]}</b><small>{tag} · 결과 {metric["attempts"]}회</small></td>')
        table.append(f'<tr><th>{escape(lesson["id"])} · {escape(lesson["title"])}<small>{escape(lesson["phase"])}</small></th>{"".join(cells)}</tr>')
    bars = []
    for domain, label in DOMAINS.items():
        domain_ids = {x["id"] for x in data["exercises"] if domain in x["domains"]}
        relevant = [g for g in goals if g["exercise_id"] in domain_ids]
        count = sum(g["state"] in ("success", "retained") for g in relevant)
        width = 100 * count / len(relevant) if relevant else 0
        bars.append(f'<div class="domain"><span>{label}</span><div class="track"><div style="width:{width:.1f}%"></div></div><span>{count}/{len(relevant)}</span></div>')
    history = []
    for task in reversed([t for t in tasks if t["report"]][-20:]):
        r = task["report"]
        actual = json.loads(r["actual_json"])
        history.append(f'<tr><td>{escape(r["practice_date"])}<small>{escape(r["task_id"])}</small></td><td>{escape(task["target"]["title"])}</td>'
                       f'<td>{escape(task["target"]["key"])} / {task["target"]["bpm"]} BPM<small>{escape(ARRANGEMENTS.get(task["target"]["arrangement"], task["target"]["arrangement"]))}</small></td>'
                       f'<td>{escape(actual.get("key", "미확인"))} / {escape(actual.get("bpm", "미확인"))}<small>{escape(ARRANGEMENTS.get(actual.get("arrangement"), actual.get("arrangement", "미확인")))}</small></td>'
                       f'<td>{RESULTS[outcome(task)]}</td><td class="note">{escape(r["raw_note"])}</td></tr>')
    next_task = info["next"]
    candidate = next_task.get("target")
    if not candidate and "exercise_id" in next_task:
        candidate = target_for(data, next_task["exercise_id"], next_task["key"], next_task["bpm"])
    if candidate:
        labels = {"chords": "코드 진행", "roots": "왼손 베이스", "melody": "오른손 멜로디", "guide_tones": "오른손 3도·7도"}
        material_rows = []
        for field, label in labels.items():
            if field not in candidate["material"]:
                continue
            if (field == "roots" and candidate["bass"] == "none") or (field == "melody" and candidate["melody"] == "none"):
                continue
            material_rows.append(f'<p><small>{label}</small>{escape(candidate["material"][field])}</p>')
        next_text = f'<h3>{escape(candidate["title"])}</h3><p>{escape(candidate["key"])} · {candidate["bpm"]} BPM · {candidate["bars"]}마디</p><p>{escape(candidate["instructions"])}</p>{"".join(material_rows)}<small>C4 = 가운데 도 · 숫자는 옥타브 번호</small>'
    else:
        next_text = '<h3>익힌 내용을 연결해서 연주하기</h3>'
    empty = '<tr><td colspan="6" class="empty">아직 실제 연습 기록이 없습니다. 예시 데이터로 진도를 채우지 않았습니다.</td></tr>'
    page = f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Jazz Practice · 연습 기록</title><style>
:root{{font-family:system-ui,-apple-system,"Noto Sans KR",sans-serif;color:#e5eaf2;background:#101923}}*{{box-sizing:border-box}}body{{margin:0}}main{{max-width:1160px;margin:auto;padding:42px 24px}}header{{display:flex;justify-content:space-between;gap:20px;align-items:center}}h1{{font-size:32px;margin:8px 0}}h2{{font-size:21px;margin:0 0 18px}}h3{{margin:0 0 10px}}p{{line-height:1.7;color:#b8c6d6}}.eyebrow{{letter-spacing:3px;color:#e8bd79;font-size:12px}}.badge{{border:1px solid #46515e;padding:8px 14px;border-radius:20px;white-space:nowrap;font-size:13px}}.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:28px 0}}.card,section{{background:#192634;border:1px solid #2b3b4b;border-radius:14px;padding:22px}}.card strong{{display:block;font-size:30px;margin:10px 0}}.card span,small{{color:#a8b9ca;font-size:12px}}small{{display:block;margin-top:7px}}section{{margin:20px 0}}.split{{display:grid;grid-template-columns:1.2fr 1fr;gap:20px}}.split section{{margin:0}}table{{border-collapse:collapse;width:100%;font-size:13px}}th,td{{padding:15px 12px;text-align:left;border-bottom:1px solid #334353;vertical-align:top}}thead th{{color:#a8b9ca;font-weight:500}}td.unknown{{color:#acb5c0}}td.attempted{{background:#273956}}td.success{{background:#304236}}td.retained{{background:#155345}}.scroll{{overflow:auto}}.legend{{font-size:12px;color:#a8b9ca}}.domain{{display:grid;grid-template-columns:65px 1fr 35px;gap:12px;align-items:center;margin:20px 0;font-size:13px}}.track{{height:8px;border-radius:8px;background:#354454;overflow:hidden}}.track div{{height:100%;background:#e8bd79}}pre{{white-space:pre-wrap;font-size:12px;line-height:1.7;color:#cee1ef}}.note{{white-space:pre-wrap;min-width:180px}}.empty{{text-align:center;padding:36px;color:#a8b9ca}}footer{{color:#899bac;font-size:12px;line-height:1.8;margin-top:28px}}@media(max-width:760px){{.cards{{grid-template-columns:repeat(2,1fr)}}.split{{grid-template-columns:1fr}}header{{align-items:flex-start}}main{{padding:24px 14px}}th,td{{min-width:115px}}}}
</style></head><body><main><header><div><div class="eyebrow">JAZZ PRACTICE</div><h1>오늘의 기록, 다음 연습</h1><p>하루 30분 · 피아노 기초 있음 · 재즈 입문</p></div><div class="badge">활성 버전 {escape(data['version'])}</div></header>
<div class="cards"><div class="card">결과를 남긴 과제<strong>{info['reported_attempts']}</strong><span>과제 발급만으로는 증가하지 않음</span></div><div class="card">기록된 연습 시간<strong>{info['known_minutes']:g}<span> 분</span></strong><span>시간 미확인 {info['minutes_unknown']}건</span></div><div class="card">대표 목표 성공<strong>{passed}<span> / {len(goals)}</span></strong><span>현재 버전의 고정 목표 · 자기보고</span></div><div class="card">후일 같은 조건 재현<strong>{held}<span> / {len(goals)}</span></strong><span>{data['retention_days']}일 이상 간격 · 자기보고</span></div></div>
<div class="split"><section><h2>{'진행 중인 과제' if next_task['action']=='resume' else '다음 과제 후보 · 아직 발급되지 않음'}</h2>{next_text}<p>{escape(next_task['reason'])}</p></section><section><h2>영역별 대표 목표</h2>{''.join(bars)}<p>각 영역에 해당하는 목표의 성공 수입니다. 영역은 서로 겹칩니다. 전체 재즈 실력이나 독립적인 벡터 점수가 아닙니다.</p></section></div>
<section><h2>어떤 조건을 확인했나</h2><p class="legend">미평가 → 연습 기록 → 당일 성공 → 후일 재현. 미평가는 실패가 아닙니다. 기본 비교 템포는 {data['default_bpm']} BPM이며 성공은 해당 항목의 손·리듬·음 조건을 모두 충족한 보고만 셉니다.</p><div class="scroll"><table><thead><tr><th>연습 항목</th>{''.join(f'<th>{escape(k)}</th>' for k in data['allowed_keys'])}</tr></thead><tbody>{''.join(table)}</tbody></table></div></section>
<section><h2>최근 수행 기록</h2><div class="scroll"><table><thead><tr><th>연습일</th><th>과제</th><th>목표</th><th>실제</th><th>판정</th><th>원문 노트</th></tr></thead><tbody>{''.join(history) or empty}</tbody></table></div></section>
<footer>자기보고 기반 기록입니다. 음정·스윙감·음색을 자동으로 듣고 평가하지 않습니다.<br>생성: {escape(datetime.now(timezone.utc).isoformat(timespec='seconds'))} · 원본: practice.csv · 새 기록 후 ./jazz report 로 갱신</footer></main></body></html>'''
    destination = Path(output) if output else root / "reports" / "index.html"
    atomic_text(destination, page)
    return str(destination)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--practice-root", type=Path, default=HERE.parent / "practice")
    parser.add_argument("--curriculum", type=Path, default=HERE / "curriculum.yaml")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("status", "suggest", "validate", "validate-curriculum"):
        sub.add_parser(command)
    report = sub.add_parser("report")
    report.add_argument("--output", type=Path)
    assignment = sub.add_parser("assign")
    assignment.add_argument("exercise_id")
    assignment.add_argument("--key")
    assignment.add_argument("--bpm", type=int)
    assignment.add_argument("--purpose", choices=["practice", "diagnostic", "review", "transfer"], default="practice")
    assignment.add_argument("--reason", default="")
    for command in ("record", "correct"):
        recording = sub.add_parser(command)
        recording.add_argument("task_id")
        recording.add_argument("--input", type=Path, required=True, help="UTF-8 JSON file; preserves original multiline notes")
    cancelling = sub.add_parser("cancel")
    cancelling.add_argument("task_id")
    cancelling.add_argument("--reason", required=True)
    args = parser.parse_args(argv)
    try:
        data = curriculum(args.curriculum)
        development_source = (HERE / "publish.py").exists()
        production_root = (HERE.parent / "practice").resolve()
        if development_source and args.practice_root.resolve() == production_root:
            require(args.command not in ("assign", "record", "correct", "cancel"),
                    "개발 소스에서 실제 연습 로그를 쓸 수 없습니다. 연습 프로젝트의 ./jazz를 사용하세요. 테스트는 --practice-root로 임시 디렉터리를 지정하세요.")
            if args.command == "report":
                require(args.output is not None and not args.output.resolve().is_relative_to(production_root),
                        "개발 미리보기는 --output build/preview.html처럼 연습 프로젝트 밖에 생성하세요.")
        if args.command == "validate-curriculum":
            result = {"valid": True, "version": data["version"], "exercises": len(data["exercises"]), "milestones": len(data["milestones"])}
        elif args.command == "validate":
            events = read_events(args.practice_root)
            tasks = records(events)
            result = {"valid": True, "events": len(events), "tasks": len(tasks)}
        elif args.command == "status":
            result = status(args.practice_root, data)
        elif args.command == "suggest":
            result = suggestion(data, records(read_events(args.practice_root)))
        elif args.command == "report":
            result = {"report": render_report(args.practice_root, data, args.output)}
        elif args.command == "assign":
            result = assign(args.practice_root, data, args.exercise_id, args.key, args.bpm, args.purpose, args.reason)
        elif args.command in ("record", "correct"):
            result = record_result(args.practice_root, data, args.task_id, json.loads(args.input.read_text()), args.command == "correct")
        elif args.command == "cancel":
            result = cancel(args.practice_root, data, args.task_id, args.reason)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, KeyError, OSError, TypeError, yaml.YAMLError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
