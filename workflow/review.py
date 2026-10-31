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
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

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
RATINGS = {"impossible": "Impossible", "challenging": "Challenging",
           "good": "Good practice", "too_easy": "Too easy to be useful"}
DISCARD_CHOICES = {"already_practiced": "Already familiar", "too_easy": "Too easy"}
STATES = {"unknown": "Unassessed", "attempted": "Attempted", "success": "Same-day success", "retained": "Later retention"}
RESULTS = {"unknown": "Assessment pending", "unmet": "Target not met", "success": "Criteria met"}
DOMAINS = {"melody": "Melody", "rhythm": "Rhythm", "bass": "Bass", "voicing": "Voicing"}
ARRANGEMENTS = {
    "left-bass-only": "Left-hand bass only", "right-melody-only": "Right-hand melody only",
    "melody-and-bass": "Right-hand melody + left-hand bass",
    "left-root-right-guides": "Left-hand root + right-hand thirds and sevenths",
    "left-root-right-improv": "Left-hand root + right-hand improvisation",
}


# English presentation of built-in curriculum text, including historical snapshots.
# Keep canonical material/criteria unchanged so translation cannot reset progress.
DISPLAY_TEXT = {
    '재즈 피아노 — 첫 어휘와 양손 연결': 'Jazz piano — first vocabulary and hand coordination',
    '출발점을 확인할 작은 커리큘럼. 전체 재즈 숙련도를 나타내지 않습니다.': 'A small curriculum to establish a starting point, not a measure of overall jazz mastery.',
    '지정 조건에서 음과 박자를 유지하고 멈추지 않은 연주를 연속 2회 했다고 보고. 즉흥 과제의 음 정확성은 지정 음 범위를 지켰다는 뜻.': 'Report two consecutive runs with correct notes, steady pulse, and no stops under the assigned conditions. For improvisation tasks, correct notes means staying within the assigned note set.',
    '자체 제작 4마디 — 한 마디에 코드 하나, 4/4': 'Original four-bar exercise — one chord per bar, 4/4',
    'E4 | C4 | F4 | B3 (각 온음표)': 'E4 | C4 | F4 | B3 (whole notes)',
    'A4 | F4 | Bb4 | E4 (각 온음표)': 'A4 | F4 | Bb4 | E4 (whole notes)',
    'D4 | Bb3 | Eb4 | A3 (각 온음표)': 'D4 | Bb3 | Eb4 | A3 (whole notes)',
    '자체 제작 ii–V–I, 4마디, 4/4': 'Original ii–V–I exercise, four bars, 4/4',
    '자체 제작 메이저 코드 반복, 8마디, 4/4': 'Original major-chord vamp, eight bars, 4/4',
    'Cmaj7 × 8마디': 'Cmaj7 × 8 bars',
    'Fmaj7 × 8마디': 'Fmaj7 × 8 bars',
    'Bbmaj7 × 8마디': 'Bbmaj7 × 8 bars',
    'C3, 매 마디 첫 박': 'C3 on beat 1 of each bar',
    'F2, 매 마디 첫 박': 'F2 on beat 1 of each bar',
    'Bb2, 매 마디 첫 박': 'Bb2 on beat 1 of each bar',
    'E4, G4, A4 세 음만 사용': 'Use only E4, G4, and A4',
    'A4, C5, D5 세 음만 사용': 'Use only A4, C5, and D5',
    'D4, F4, G4 세 음만 사용': 'Use only D4, F4, and G4',
    '왼손 루트와 박 유지': 'Left-hand roots and steady pulse',
    '오른손 멜로디와 박 유지': 'Right-hand melody and steady pulse',
    '멜로디 + 베이스 연결': 'Melody and bass together',
    'ii–V–I의 루트 + 3도·7도': 'ii–V–I roots, thirds, and sevenths',
    'Charleston 컴핑 첫 패턴': 'Your first Charleston comping pattern',
    '세 음으로 짧게 말하고 쉬기': 'Three-note phrases and rests',
    '1 · 출발점': '1 · Starting point',
    '2 · 첫 어휘': '2 · First vocabulary',
    '메트로놈을 4분음표 한 박에 맞춘다. 1-2-3-4를 세면서 왼손으로 각 마디 루트를 첫 박에 누르고 네 박 유지한다. 오른손은 쉰다.': 'Set the metronome to quarter-note beats. Count 1-2-3-4, play each root with your left hand on beat 1, and hold for four beats. Rest your right hand.',
    '오른손으로 위에 제시된 멜로디 음을 한 마디에 하나씩 네 박 동안 유지한다. 왼손은 쉰다. 4마디를 연결한다.': 'Play one of the melody notes shown above per bar with your right hand, holding each for four beats. Rest your left hand and connect all four bars.',
    'E01의 왼손과 E02의 오른손을 합친다. 두 손이 매 마디 첫 박에 함께 누르고 네 박 유지한다. 처음에는 두 마디씩 해도 되지만 목표 평가는 전체 네 마디다.': 'Combine the left hand from E01 with the right hand from E02. Play both hands together on beat 1 of each bar and hold for four beats. You can start with two-bar sections, but the target covers all four bars.',
    '왼손은 제시된 루트 음, 오른손은 제시된 3도·7도 두 음을 함께 연주한다. 매 마디 첫 박에 누르고 네 박 유지한다. 3도와 7도는 코드 성격을 드러내는 음이다.': 'Play the given root with your left hand and the given third and seventh together with your right. Start on beat 1 of each bar and hold for four beats. Thirds and sevenths define the character of a chord.',
    '왼손 루트는 첫 박에 누르고 유지한다. 오른손 3도·7도는 1박과 2박 뒤의 앤드(2&)에 짧게 친다. 먼저 1 & 2 & 3 & 4 &를 말하며 위치를 익힌다. 이 과제는 타격 위치 확인이며 스윙감 숙련을 인증하지 않는다.': 'Play and hold the left-hand root on beat 1. Play short right-hand thirds and sevenths on beat 1 and the and after beat 2 (2&). First count 1 & 2 & 3 & 4 & aloud. This checks attack placement, not mastery of swing feel.',
    '왼손 루트는 매 마디 첫 박. 오른손은 지정 세 음으로 1~2마디에 짧은 선율을 만들고 3~4마디 쉰다. 5~8마디에 같은 구조를 반복한다. 처음에는 4분음표와 쉼표만 사용한다. 정답 선율은 없으며 박과 쉼을 유지한다.': 'Play the left-hand root on beat 1 of each bar. Use the three assigned notes for a short right-hand phrase in bars 1–2, then rest in bars 3–4. Repeat that structure in bars 5–8. Start with quarter notes and rests. There is no prescribed melody; keep the pulse and rests.',
}


@lru_cache(maxsize=1)
def translations():
    return json.loads((HERE / "translations.json").read_text())["ko"]


def web_text(message, language="en", **values):
    template = translations().get(message, message) if language == "ko" else message
    return template.format_map(values) if values else template


def display_builtin(value, language="en"):
    """Copy curriculum text for display; never apply to user notes or evidence logs."""
    if isinstance(value, str):
        return web_text(DISPLAY_TEXT.get(value, value), language)
    if isinstance(value, dict):
        return {key: display_builtin(item, language) for key, item in value.items()}
    if isinstance(value, list):
        return [display_builtin(item, language) for item in value]
    return value



def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value, name, low=0, high=10000):
    require(type(value) in (int, float) and low <= value <= high, f"{name}: a number between {low} and {high} is required.")
    return value


def iso_day(value):
    require(isinstance(value, str), "The date must be a YYYY-MM-DD string.")
    parsed = date.fromisoformat(value)
    require(parsed.isoformat() == value, "The date must use YYYY-MM-DD format.")
    return parsed


def jdump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def curriculum(path=HERE / "curriculum.yaml"):
    data = yaml.safe_load(Path(path).read_text())
    require(isinstance(data, dict) and data.get("schema_version") == 1, "Unsupported curriculum schema.")
    require(bool(re.fullmatch(r"\d+\.\d+\.\d+", str(data.get("version", "")))), "The version must use x.y.z format.")
    keys = data["allowed_keys"]
    require(isinstance(keys, list) and keys and len(keys) == len(set(keys)), "Invalid allowed_keys.")
    require(data["default_key"] in keys, "The default_key is not an allowed key.")
    number(data["default_bpm"], "default_bpm", data["minimum_bpm"], data["maximum_bpm"])
    number(data["daily_minutes"], "daily_minutes", 1, 120)
    number(data["retention_days"], "retention_days", 1, 365)
    number(data["maintenance_days"], "maintenance_days", data["retention_days"], 365)
    criteria = data["criteria"]
    require(criteria.get("id") and criteria.get("explanation"), "Success criteria need an ID and explanation.")
    require(criteria.get("checks") == CHECKS, "Unsupported success checks.")
    number(criteria["min_clean_runs"], "min_clean_runs", 1, 20)
    require(type(criteria["min_clean_runs"]) is int, "Consecutive successful runs must be an integer.")
    lessons = data["exercises"]
    require(isinstance(lessons, list), "Reference exercises must be a list (it may be empty).")
    ids = [x["id"] for x in lessons]
    require(len(ids) == len(set(ids)), "Duplicate exercise IDs.")
    by_id = {x["id"]: x for x in lessons}
    for lesson in lessons:
        require(lesson.get("title") and lesson.get("instructions"), "A title and specific instructions are required.")
        require(lesson.get("domains") and set(lesson["domains"]) <= set(DOMAINS), "Invalid domain.")
        number(lesson["bars"], "bars", 1, 128)
        require(type(lesson["bars"]) is int, "Bar count must be an integer.")
        for field in SPEC[3:]:
            require(isinstance(lesson.get(field), str) and lesson[field], f"{lesson['id']}: missing {field}")
        material = data["materials"][lesson["material_id"]]
        require(material.get("title"), "A practice material title is required.")
        for key in keys:
            require(isinstance(material.get(key), dict) and material[key].get("chords"), f"Missing material for {key}.")
            if "playback" in data:
                playback = data["playback"][lesson["material_id"]][key]
                require(type(playback["beats_per_bar"]) is int and 1 <= playback["beats_per_bar"] <= 12,
                        "Invalid playback meter.")
                require(len(playback["bars"]) == lesson["bars"], "The accompaniment bar count differs from the exercise.")
                for bar in playback["bars"]:
                    require(isinstance(bar.get("chord"), str) and bar["chord"], "An accompaniment chord name is required.")
                    require(isinstance(bar.get("notes"), list) and 1 <= len(bar["notes"]) <= 8 and
                            all(type(note) is int and 0 <= note <= 127 for note in bar["notes"]),
                            "Invalid accompaniment MIDI notes.")
        require(all(p in by_id for p in lesson["prerequisites"]), "An exercise references a missing prerequisite.")
    def visit(item, trail):
        require(item not in trail, "Prerequisites contain a cycle.")
        for parent in by_id[item]["prerequisites"]:
            visit(parent, trail | {item})
    for item in ids:
        visit(item, set())
    seen = set()
    for milestone in data["milestones"]:
        token = (milestone["exercise_id"], milestone["key"])
        require(token not in seen and token[0] in by_id and token[1] in keys, "Duplicate or invalid milestone.")
        seen.add(token)
        number(milestone["bpm"], "milestone bpm", data["minimum_bpm"], data["maximum_bpm"])
    return data


def target_for(data, exercise_id, key=None, bpm=None):
    lesson = next((x for x in data["exercises"] if x["id"] == exercise_id), None)
    require(lesson is not None, f"Unknown exercise ID: {exercise_id}")
    key = key or data["default_key"]
    bpm = data["default_bpm"] if bpm is None else bpm
    require(key in data["allowed_keys"], "This key is not allowed.")
    number(bpm, "bpm", data["minimum_bpm"], data["maximum_bpm"])
    material = data["materials"][lesson["material_id"]]
    return {
        **{k: lesson[k] for k in SPEC[2:]}, "key": key, "bpm": bpm,
        "title": lesson["title"], "instructions": lesson["instructions"],
        "material": {"title": material["title"], **material[key]},
        "criteria": data["criteria"], "domains": lesson["domains"],
        "curriculum_version": data["version"], "daily_minutes": data["daily_minutes"],
        "playback": data.get("playback", {}).get(lesson["material_id"], {}).get(key),
    }


def incompatible_target_fields(data, task):
    """Compare the assigned contract, not release numbers or display/accompaniment."""
    exercise_id, target = task["assignment"]["exercise_id"], task["target"]
    if target.get("kind") == "generated":
        from recommendation import validate_target
        try:
            validate_target(target)
            return []
        except (ValueError, KeyError, TypeError):
            return ["generated_task_schema"]
    if not any(lesson["id"] == exercise_id for lesson in data["exercises"]):
        return ["exercise_id"]
    if target["key"] not in data["allowed_keys"]:
        return ["key"]
    if not data["minimum_bpm"] <= target["bpm"] <= data["maximum_bpm"]:
        return ["bpm"]
    expected = target_for(data, exercise_id, target["key"], target["bpm"])
    return [field for field in SPEC + ["material", "criteria", "instructions"]
            if target.get(field) != expected[field]]


def read_events(root):
    csv.field_size_limit(2_000_000)  # Immutable generated scores can exceed csv's 128 KiB default.
    path = Path(root) / "practice.csv"
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        require(reader.fieldnames == FIELDS, "The CSV header does not match. Check the schema before making changes.")
        rows = list(reader)
    require(all(set(row) == set(FIELDS) and all(v is not None for v in row.values()) for row in rows), "A CSV row is corrupt.")
    return rows


def records(events):
    """Reconstruct attempts while retaining all corrections in the source CSV."""
    tasks, event_ids = {}, set()
    for event in events:
        require(event["event_id"] and event["event_id"] not in event_ids, "Duplicate or empty event_id.")
        event_ids.add(event["event_id"])
        task_id = event["task_id"]
        require(task_id, "A task_id is required.")
        datetime.fromisoformat(event["recorded_at"])
        kind = event["event_type"]
        if kind == "assigned":
            require(task_id not in tasks, "Duplicate task assignment.")
            target = json.loads(event["target_json"])
            require(all(k in target for k in SPEC + ["criteria", "material"]), "The assigned-condition snapshot is incomplete.")
            number(target["bpm"], "target bpm", 1, 400)
            number(target["bars"], "target bars", 1, 1000)
            if target.get("kind") == "generated":
                from recommendation import validate_target
                validate_target(target)
                require(event["exercise_id"] == target["exercise_id"], "Generated exercise ID changed.")
            else:
                require(target["criteria"].get("checks") == CHECKS, "Unknown task criteria.")
                number(target["criteria"]["min_clean_runs"], "min_clean_runs", 1, 20)
            tasks[task_id] = {"assignment": event, "target": target, "report": None, "completion": None,
                              "cancelled": False, "retired": False, "discarded": False, "cancellation": None}
            continue
        require(task_id in tasks, "This result has no matching assignment.")
        task = tasks[task_id]
        require(event["release"] == task["assignment"]["release"] and event["exercise_id"] == task["assignment"]["exercise_id"], "The task version or exercise ID has changed.")
        if kind in ("cancelled", "retired", "discarded"):
            require(is_pending(task), "A resolved task cannot be cancelled.")
            if kind == "discarded":
                details = json.loads(event["reason"])
                require(isinstance(details, dict) and set(details) == {"choice", "note"}, "Invalid discard reason.")
                validate_discard_reason(details["choice"], details["note"])
            task["cancelled"] = True
            task["retired"] = kind == "retired"
            task["discarded"] = kind == "discarded"
            task["cancellation"] = event
        elif kind in ("reported", "corrected", "completed"):
            require(not task["cancelled"], "A cancelled task cannot receive a report.")
            if kind == "completed":
                require(is_pending(task) and not event["supersedes"], "This task is already resolved.")
                require(reflection_observations(event) is not None and event["actual_json"] == "{}"
                        and event["checks_json"] == "{}" and not event["clean_runs"] and not event["difficulty"],
                        "Completion cannot infer performance or feedback.")
            elif kind == "reported":
                require(task["report"] is None and not event["supersedes"], "A result already exists. Use correct to revise it.")
            else:
                require(task["report"] and event["supersedes"] == task["report"]["event_id"], "The correction does not refer to the latest report.")
            practice_day = iso_day(event["practice_date"])
            observations = reflection_observations(event)
            assigned_at = datetime.fromisoformat(task["assignment"]["recorded_at"])
            assigned_day = assigned_at.astimezone(ZoneInfo(observations["timezone"])).date() if observations else assigned_at.date()
            require(practice_day >= assigned_day, "The practice date is earlier than the assignment date.")
            require(kind == "completed" or event["raw_note"].strip() or event["difficulty"] in RATINGS, "The original user note is required.")
            actual = json.loads(event["actual_json"])
            checks = json.loads(event["checks_json"])
            validate_observations(actual, checks)
            for field, high in [("clean_runs", 1000), ("actual_minutes", 1440)]:
                if field == "actual_minutes" and observations:
                    high *= max(1, len(observations["sessions"]))
                if event[field]:
                    number(float(event[field]), field, 0, high)
            if event["clean_runs"]:
                require(float(event["clean_runs"]).is_integer(), "Consecutive successful runs must be an integer.")
            task["completion" if kind == "completed" else "report"] = event
        else:
            raise ValueError(f"Unsupported event_type: {kind}")
    return list(tasks.values())


def is_pending(task):
    return not task["report"] and not task["completion"] and not task["cancelled"]


def practice_record(task):
    return task["report"] or task["completion"]


def reflection_observations(report):
    """Automatic timing snapshot; legacy reports retain their original observations."""
    if not report or (report["difficulty"] not in RATINGS and report["event_type"] != "completed") or not report["reason"].startswith('{'):
        return None
    try:
        value = json.loads(report["reason"])
    except ValueError:
        return None
    return value if isinstance(value, dict) and value.get("source") == "session-reflection-v1" else None


def validate_discard_reason(choice, note):
    require(isinstance(choice, str) and (choice == "" or choice in DISCARD_CHOICES), "Invalid discard choice.")
    require(isinstance(note, str), "The reason must be text.")


def discard_details(task):
    return json.loads(task["cancellation"]["reason"]) if task["discarded"] else {"choice": "", "note": ""}


def practice_preference(task):
    """An explicit familiarity choice opens practice, without creating performance evidence."""
    if task["report"]:
        return task["report"]["difficulty"]
    choice = discard_details(task)["choice"]
    return {"already_practiced": "good", "too_easy": "too_easy"}.get(choice)


def activity_day(task):
    if practice_record(task):
        return iso_day(practice_record(task)["practice_date"])
    return datetime.fromisoformat(task["cancellation"]["recorded_at"]).date()


def validate_observations(actual, checks):
    require(isinstance(actual, dict) and set(actual) <= set(SPEC), "The actual conditions contain unknown fields.")
    require(isinstance(checks, dict) and set(checks) <= set(CHECKS), "The checks contain unknown fields.")
    for key, value in actual.items():
        if value is None:
            continue
        if key in ("bpm", "bars"):
            number(value, key, 1, 1000)
            if key == "bars":
                require(type(value) is int, "The actual bar count must be an integer.")
        else:
            require(isinstance(value, str) and value.strip(), f"actual.{key} must be a string.")
    require(all(v is None or type(v) is bool for v in checks.values()), "Checks only accept true, false, or null.")


def outcome(task):
    report = task["report"]
    if report is None or task["target"].get("kind") == "generated":
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


def practice_ready(data, tasks, exercise_id, key):
    """Comfort can open practice choices, but never supplies success or retention evidence."""
    if goal_successes(data, tasks, exercise_id, key, data["default_bpm"]):
        return True
    reports = [t for t in tasks if (t["report"] or discard_details(t)["choice"]) and t["assignment"]["exercise_id"] == exercise_id
               and t["target"]["key"] == key and not incompatible_target_fields(data, t)]
    latest = max(enumerate(reports), key=lambda pair: (activity_day(pair[1]), pair[0]), default=(0, None))[1]
    return bool(latest and practice_preference(latest) in ("good", "too_easy"))


def preference_suggestion(data, tasks, today, deferred):
    experiences = latest_activity([t for t in tasks if t["report"] or discard_details(t)["choice"]], today)
    recent = [t for _, t in experiences.values() if practice_preference(t) in RATINGS
              and not incompatible_target_fields(data, t)]
    if not recent:
        return None
    task = max(recent, key=lambda t: (activity_day(t), t["assignment"]["recorded_at"]))
    target, rating = task["target"], practice_preference(task)
    exercise, key = task["assignment"]["exercise_id"], target["key"]
    observations = reflection_observations(task["report"])
    bpm = (observations or {}).get("metronome_bpm") or target["bpm"]
    bpm = min(data["maximum_bpm"], max(data["minimum_bpm"], bpm))
    lesson = next(x for x in data["exercises"] if x["id"] == exercise)
    eligible = all(practice_ready(data, tasks, parent, key) for parent in lesson["prerequisites"])
    if rating in ("impossible", "challenging") and (exercise, key) not in deferred and eligible:
        return {"action": "practice", "exercise_id": exercise, "key": key,
                "bpm": max(data["minimum_bpm"], bpm - 10) if rating == "impossible" else bpm,
                "reason": "Try this exercise more slowly." if rating == "impossible" else "Keep this tempo and try the exercise again."}
    for lesson in data["exercises"]:
        if ((lesson["id"], key) not in deferred and not practice_ready(data, tasks, lesson["id"], key)
                and all(practice_ready(data, tasks, parent, key) for parent in lesson["prerequisites"])):
            return {"action": "practice", "exercise_id": lesson["id"], "key": key, "bpm": bpm,
                    "reason": "Try the next exercise based on your selection." if task["discarded"] else "Try the next exercise based on how the practice felt."}
    if (exercise, key) not in deferred and eligible:
        return {"action": "practice", "exercise_id": exercise, "key": key,
                "bpm": min(data["maximum_bpm"], bpm + 10) if rating == "too_easy" else bpm,
                "reason": "Try a faster tempo." if rating == "too_easy" and bpm < data["maximum_bpm"] else "Keep practicing, or choose another key or exercise."}
    return None


def cell(data, tasks, exercise_id, key, bpm=None):
    bpm = data["default_bpm"] if bpm is None else bpm
    successes = goal_successes(data, tasks, exercise_id, key, bpm)
    attempted = [t for t in tasks if practice_record(t) and t["assignment"]["exercise_id"] == exercise_id
                 and json.loads(practice_record(t)["actual_json"]).get("key", t["target"]["key"]) == key]
    state = "retained" if retained(successes, data["retention_days"]) else "success" if successes else "attempted" if attempted else "unknown"
    return {"state": state, "attempts": len(attempted), "successes": len(successes),
            "last_success": max((t["report"]["practice_date"] for t in successes), default=None)}


def latest_activity(tasks, today):
    """Use the practice day, not the correction time, to order observations."""
    latest = {}
    for task in tasks:
        if task["retired"]:
            continue  # A release transition is not a practice attempt or a skipped exercise.
        if not practice_record(task) and not task["cancellation"]:
            continue
        day = activity_day(task)
        token = (task["assignment"]["exercise_id"], task["target"]["key"])
        if day <= today and (token not in latest or day >= latest[token][0]):
            latest[token] = (day, task)
    return latest


def legacy_suggestion(data, tasks, today=None):
    """Historical algorithm for compatibility tests only; no web/CLI recommendation uses it."""
    today = today or date.today()
    pending = [t for t in tasks if is_pending(t)]
    if pending:
        task = pending[0]
        return {"action": "resume", "task_id": task["assignment"]["task_id"], "target": task["target"], "reason": "You have an unfinished task. Continue it before starting another."}
    latest = latest_activity(tasks, today)
    deferred = {}
    for token, (day, task) in latest.items():
        if day != today:
            continue
        cancellation, report = task["cancellation"], task["report"]
        if cancellation or (report and report["difficulty"] == "hard" and outcome(task) != "success"):
            deferred[token] = {"exercise_id": token[0], "key": token[1],
                               "task_id": task["assignment"]["task_id"],
                               "reason": discard_details(task)["note"] if task["discarded"] else cancellation["reason"] if cancellation else report["raw_note"]}
    context = {"deferred_today": list(deferred.values())}
    for milestone in data["milestones"]:
        if (milestone["exercise_id"], milestone["key"]) in deferred:
            continue
        info = cell(data, tasks, milestone["exercise_id"], milestone["key"], milestone["bpm"])
        delay = data["maintenance_days"] if info["state"] == "retained" else data["retention_days"]
        # A finished review resets its reminder without claiming that retention passed.
        attempts = [activity_day(t) for t in tasks if practice_record(t)
                    and t["assignment"]["exercise_id"] == milestone["exercise_id"] and t["target"]["key"] == milestone["key"]
                    and not incompatible_target_fields(data, t) and activity_day(t) <= today]
        last_review = max(attempts, default=iso_day(info["last_success"]) if info["last_success"] else today)
        if info["last_success"] and (today - last_review).days >= delay:
            successes = goal_successes(data, tasks, milestone["exercise_id"], milestone["key"], milestone["bpm"])
            latest_success = max(successes, key=lambda t: t["report"]["practice_date"])
            actual_bpm = json.loads(latest_success["report"]["actual_json"])["bpm"]
            return {"action": "review", **milestone, "bpm": actual_bpm, **context,
                    "reason": "It is time to check later retention at the tempo of your previous success."}
    reflection_next = preference_suggestion(data, tasks, today, deferred)
    if reflection_next:
        return reflection_next | context
    by_id = {x["id"]: x for x in data["exercises"]}
    unfinished = False
    for milestone in data["milestones"]:
        if goal_successes(data, tasks, **milestone):
            continue
        unfinished = True
        token = (milestone["exercise_id"], milestone["key"])
        if token in deferred:
            continue
        lesson = by_id[milestone["exercise_id"]]
        if all(practice_ready(data, tasks, parent, milestone["key"]) for parent in lesson["prerequisites"]):
            previous = latest.get(token)
            report = previous[1]["report"] if previous else None
            reason = "This milestone is not yet confirmed. Use recent notes to choose a repeat or a focused check."
            if report and report["difficulty"] == "easy":
                reason = "You reported this exercise as easy. Briefly check the missing evidence, then continue today if the criteria are met."
            elif report and report["difficulty"] == "hard" and outcome(previous[1]) != "success":
                reason = "The previous attempt was difficult. Review the original note and consider simplifying tempo, section, or hand arrangement."
            return {"action": "practice", **milestone, **context, "reason": reason}
    if unfinished:
        return {"action": "pause", **context,
                "reason": "The remaining tasks are deferred today or need prerequisites. Finish for today, or simplify one condition of a deferred task and try again."}
    return {"action": "consolidate", **context,
            "reason": "Same-day success is recorded for the milestones. Connect exercises into music, listen, and review on later days. New songs and keys need separate evidence."}


def practice_totals(reports):
    return {"reported_attempts": len(reports),
            "known_minutes": sum(float(r["actual_minutes"]) for r in reports if r["actual_minutes"] != ""),
            "minutes_unknown": sum(r["actual_minutes"] == "" for r in reports)}


def daily_summary(data, tasks, profile, today=None):
    today = today or datetime.now(ZoneInfo(profile.get("timezone", "UTC"))).date()
    budget = profile.get("daily_minutes", data["daily_minutes"])
    number(budget, "daily_minutes", 1, 1440)
    reports = []
    for task in tasks:
        report = practice_record(task)
        if not report:
            continue
        observations = reflection_observations(report)
        days = observations.get("days", {}) if observations else {}
        if days:
            if today.isoformat() in days:
                minutes = days[today.isoformat()]
                reports.append(report | {"actual_minutes": "" if minutes is None else str(minutes)})
        elif iso_day(report["practice_date"]) == today:
            reports.append(report)
    totals = practice_totals(reports)
    reached = totals["known_minutes"] >= budget
    remaining = max(0, budget - totals["known_minutes"]) if reached or not totals["minutes_unknown"] else None
    return {"date": today.isoformat(), "budget_minutes": budget, **totals,
            "remaining_minutes": remaining, "budget_reached": reached}


@contextmanager
def log_lock(root):
    root = Path(root)
    require(root.is_dir(), "The practice directory does not exist.")
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


def assign(root, data, exercise_id, key=None, bpm=None, purpose="practice", reason="", task_id=None):
    require(purpose in ("practice", "diagnostic", "review", "transfer"), "Invalid purpose.")
    target = target_for(data, exercise_id, key, bpm)
    require(task_id is None or isinstance(task_id, str) and re.fullmatch(r"T-[a-f0-9]{10}", task_id), "Invalid task ID.")
    with log_lock(root):
        events = read_events(root)
        tasks = records(events)
        existing = next((t for t in tasks if t["assignment"]["task_id"] == task_id), None)
        if existing:
            require(existing["target"] == target and existing["assignment"]["purpose"] == purpose, "This task ID already belongs to another assignment.")
            return {"task_id": task_id, "target": existing["target"], "reason": existing["assignment"]["reason"]}
        require(not any(is_pending(t) for t in tasks), "Report or cancel the unfinished task first.")
        lesson = next(x for x in data["exercises"] if x["id"] == exercise_id)
        if purpose != "diagnostic":
            for parent in lesson["prerequisites"]:
                ready = practice_ready(data, tasks, parent, target["key"]) if purpose == "practice" else goal_successes(data, tasks, parent, target["key"], data["default_bpm"])
                require(ready, f"First complete prerequisite {parent} in the same key. Use diagnostic explicitly for a diagnostic task.")
        event = new_event("assigned", task_id or "T-" + uuid.uuid4().hex[:10], data, exercise_id, purpose)
        event.update(target_json=jdump(target), reason=reason)
        records(events + [event])
        append_event(root, event)
    return {"task_id": event["task_id"], "target": target, "reason": reason}


def record_result(root, data, task_id, payload, correction=False):
    require(isinstance(payload, dict), "The result must be a JSON object.")
    allowed = {"practice_date", "actual", "checks", "clean_runs", "actual_minutes", "difficulty", "raw_note", "hypothesis", "followed_target"}
    require(set(payload) <= allowed, "The result contains unknown fields.")
    require(isinstance(payload.get("raw_note"), str) and payload["raw_note"].strip(), "The raw_note field must contain the original user note.")
    require(type(payload.get("followed_target", False)) is bool, "The followed_target flag must be a boolean.")
    with log_lock(root):
        events = read_events(root)
        task = next((t for t in records(events) if t["assignment"]["task_id"] == task_id), None)
        require(task is not None and not task["cancelled"], "Active task ID not found.")
        require(bool(task["report"]) == correction, "Use correct for an existing result and record for the first result.")
        actual = {k: task["target"][k] for k in SPEC} if payload.get("followed_target") else {}
        require(isinstance(payload.get("actual", {}), dict), "The actual conditions must be an object.")
        actual.update(payload.get("actual", {}))
        checks = payload.get("checks", {})
        validate_observations(actual, checks)
        practice_day = payload.get("practice_date", date.today().isoformat())
        require(iso_day(practice_day) <= date.today(), "Practice results cannot be dated in the future.")
        for field, high in [("clean_runs", 1000), ("actual_minutes", 1440)]:
            if payload.get(field) is not None:
                number(payload[field], field, 0, high)
        if payload.get("clean_runs") is not None:
            require(type(payload["clean_runs"]) is int, "Consecutive successful runs must be an integer.")
        difficulty = payload.get("difficulty", "unknown")
        require(difficulty in ("easy", "manageable", "hard", "unknown"), "Invalid difficulty.")
        require(isinstance(payload.get("hypothesis", ""), str), "The hypothesis must be a string.")
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
    require(reason.strip(), "A cancellation reason is required.")
    with log_lock(root):
        events = read_events(root)
        task = next((t for t in records(events) if t["assignment"]["task_id"] == task_id), None)
        require(task is not None, "Task not found.")
        event = new_event("cancelled", task_id, data, task["assignment"]["exercise_id"], task["assignment"]["purpose"])
        event.update(release=task["assignment"]["release"], reason=reason)
        records(events + [event])
        append_event(root, event)
    return {"cancelled": task_id}


def discard(root, data, task_id, reason="", choice=""):
    """Close an unfinished assignment without deleting input or inventing a result."""
    from sessions import SessionStore

    validate_discard_reason(choice, reason)
    with log_lock(root):
        events = read_events(root)
        task = next((t for t in records(events) if t["assignment"]["task_id"] == task_id), None)
        require(task is not None, "Task not found.")
        details = {"choice": choice, "note": reason}
        if task["discarded"]:
            require(discard_details(task) == details, "This task was already discarded with a different reason.")
            return {"discarded": task_id}
        require(is_pending(task), "Only an unfinished task can be discarded.")
        require(not any(s["status"] == "recording" for s in SessionStore(root).list(task_id)),
                "Finish and save the current practice session first.")
        event = new_event("discarded", task_id, data, task["assignment"]["exercise_id"], task["assignment"]["purpose"])
        event.update(release=task["assignment"]["release"], reason=jdump(details))
        records(events + [event])
        append_event(root, event)
    return {"discarded": task_id}


def status(root, data):
    tasks = records(read_events(root))
    profile_path = Path(root) / "profile.json"
    profile = json.loads(profile_path.read_text()) if profile_path.exists() else {}
    reported = [t for t in tasks if practice_record(t)]
    goals = [{**m, **cell(data, tasks, **m)} for m in data["milestones"]]
    return {"version": data["version"], "profile": profile, "evidence": "Self-reported / unassessed does not mean failed",
            **practice_totals([practice_record(t) for t in reported]),
            "today": daily_summary(data, tasks, profile),
            "goals": goals, "next": next_action(tasks),
            "recent": [{"task_id": t["assignment"]["task_id"], "exercise": t["assignment"]["exercise_id"],
                        "date": practice_record(t)["practice_date"], "actual": json.loads(practice_record(t)["actual_json"]),
                        "outcome": outcome(t), "difficulty": practice_record(t)["difficulty"],
                        "raw_note": practice_record(t)["raw_note"], "hypothesis": practice_record(t)["hypothesis"]}
                       for t in reported[-5:]]}


def next_action(tasks):
    """Navigation state only. Recommendations require explicit LLM analysis."""
    pending = next((t for t in tasks if is_pending(t)), None)
    if pending:
        return {"action": "resume", "task_id": pending["assignment"]["task_id"], "target": pending["target"],
                "reason": "Open your unfinished practice below to continue or skip it."}
    return {"action": "generate", "reason": "Create a practice from your profile, recent records, feedback, and notes."}


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
    """Read-only history export. It neither generates tasks nor presents a fixed progress plan."""
    root = Path(root)
    tasks = records(read_events(root))
    info = status(root, data)
    escape = lambda value: html.escape(str(value))
    rows = []
    for task in reversed(tasks):
        target, record = task["target"], practice_record(task)
        title = target["title"] if target.get("kind") == "generated" else display_builtin(target["title"])
        state = ("Retired on update" if task["retired"] else "Discarded" if task["discarded"] else
                 "Cancelled" if task["cancelled"] else "Completed" if record else "Ready to practice")
        rating = RATINGS.get(record["difficulty"], RESULTS[outcome(task)]) if record else ""
        note = record["raw_note"] if record else discard_details(task)["note"] if task["discarded"] else (task["cancellation"] or {}).get("reason", "")
        day = record["practice_date"] if record else task["assignment"]["recorded_at"][:10]
        actual = json.loads(record["actual_json"]) if record else {}
        measured = reflection_observations(record)
        observation = f"Metronome setting: {measured['metronome_bpm']} BPM" if measured and measured['metronome_bpm'] is not None else ""
        duration = record["actual_minutes"] if record and record["actual_minutes"] else "Unknown"
        rows.append(f'<article><small>{escape(day)} · {escape(task["assignment"]["task_id"])}</small>'
                    f'<h2>{escape(title)}</h2><p>{escape(state)} · {escape(rating)}</p>'
                    f'<p>Assigned: {escape(target["key"])} · {target["bpm"]} BPM · {target["bars"]} bars</p>'
                    f'<p>Actual reported conditions: {escape(jdump(actual))} · Time: {escape(duration)} min</p>'
                    f'<p>{escape(observation)}</p><p class="note">{escape(note)}</p></article>')
    daily = info["today"]
    empty = '<p>No practice results have been recorded yet.</p>'
    page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Jazz Practice · Practice history</title><style>
body{{font-family:system-ui,sans-serif;max-width:900px;margin:auto;padding:32px;background:#f5f2eb;color:#263d37}}article{{background:#fffef9;border:1px solid #ddd;border-radius:12px;padding:20px;margin:16px 0}}p{{line-height:1.7}}.note{{white-space:pre-wrap}}small{{color:#646b60}}</style></head><body>
<h1>Practice history</h1><p>Reports today: {daily['reported_attempts']} · Recorded time: {daily['known_minutes']:g} min / {daily['budget_minutes']:g} min · Duration unknown: {daily['minutes_unknown']}</p>
<p>Create a practice in the app to request a new Codex recommendation. This export does not generate recommendations.</p>
{''.join(rows) or empty}<footer>Metronome settings are not analyzed playing BPM. Labels are self-reports, not musical accuracy measurements.<br>Version {escape(data['version'])} · Source: practice.csv</footer></body></html>'''
    destination = Path(output) if output else root / "reports" / "index.html"
    atomic_text(destination, page)
    return str(destination)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--practice-root", type=Path, default=HERE.parent / "practice")
    parser.add_argument("--curriculum", type=Path, default=HERE / "curriculum.yaml")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("status", "validate", "validate-curriculum", "recommendation-schema", "recommendation-plan-schema", "material-catalog"):
        sub.add_parser(command)
    for command in ("recommend", "suggest"):
        recommendation = sub.add_parser(command, help="Analyze with Codex and add one validated practice to the list")
        recommendation.add_argument("--request", default="", help="Optional coaching focus")
        recommendation.add_argument("--language", choices=["ko", "en"])
    context = sub.add_parser("recommend-context", help="Explicit context for conversational coaching")
    context.add_argument("--output", type=Path, required=True)
    context.add_argument("--request", default="")
    context.add_argument("--language", choices=["ko", "en"])
    materials = sub.add_parser("recommend-materials", help="Validate a goal plan, retrieve sources and prepare shared coaching context")
    materials.add_argument("--context", type=Path, required=True)
    materials.add_argument("--plan", type=Path, required=True)
    materials.add_argument("--output", type=Path, required=True)
    source = sub.add_parser("material-source", help="Fetch/search a catalog source into the local cache")
    source.add_argument("source_id")
    source.add_argument("--query", default="piano exercise")
    source.add_argument("--pages", type=int, nargs="*", default=[])
    source.add_argument("--refresh", action="store_true")
    imported = sub.add_parser("material-import", help="Cache an ABC excerpt with an explicit source comparison record")
    imported.add_argument("--input", type=Path, required=True)
    acceptance = sub.add_parser("accept-recommendation", help="Validate and save conversational coaching JSON")
    acceptance.add_argument("--context", type=Path, required=True)
    acceptance.add_argument("--input", type=Path, required=True)
    acceptance.add_argument("--request-id", default=None)
    report = sub.add_parser("report")
    report.add_argument("--output", type=Path)
    web = sub.add_parser("serve", help="Local web practice room")
    web.add_argument("--host", default="127.0.0.1", help="IPv4 listen address or localhost; use 0.0.0.0 for trusted LAN access")
    web.add_argument("--port", type=int, default=8765)
    web.add_argument("--open", action="store_true", help="Also open the browser")
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
    reflection = sub.add_parser("reflection", help="Save a difficulty label and optional note")
    reflection.add_argument("task_id")
    reflection.add_argument("--input", type=Path, required=True)
    cancelling = sub.add_parser("cancel")
    cancelling.add_argument("task_id")
    cancelling.add_argument("--reason", required=True)
    discarding = sub.add_parser("discard", help="Close an unfinished task; preserve saved input")
    discarding.add_argument("task_id")
    discarding.add_argument("--reason", default="")
    discarding.add_argument("--choice", choices=list(DISCARD_CHOICES), default="")
    args = parser.parse_args(argv)
    try:
        data = curriculum(args.curriculum)
        development_source = (HERE / "publish.py").exists()
        production_root = (HERE.parent / "practice").resolve()
        if development_source and args.practice_root.resolve() == production_root:
            require(args.command not in ("assign", "record", "correct", "reflection", "cancel", "discard", "serve", "recommend", "suggest", "accept-recommendation", "recommend-materials"),
                    "Development source cannot write the real practice log. Use ./jazz in the practice project. For tests, set --practice-root to a temporary directory.")
            if args.command == "report":
                require(args.output is not None and not args.output.resolve().is_relative_to(production_root),
                        "Write development previews outside the practice project, for example with --output build/preview.html.")
        if args.command == "serve":
            from webapp import serve
            serve(args.practice_root, data, args.port, args.open, host=args.host)
            return 0
        if args.command == "validate-curriculum":
            result = {"valid": True, "version": data["version"], "exercises": len(data["exercises"]), "milestones": len(data["milestones"])}
        elif args.command == "validate":
            events = read_events(args.practice_root)
            tasks = records(events)
            result = {"valid": True, "events": len(events), "tasks": len(tasks)}
        elif args.command == "status":
            result = status(args.practice_root, data)
        elif args.command in ("suggest", "recommend"):
            from recommendation import Recommendations, ERRORS
            result = Recommendations(args.practice_root, data).start("R-" + uuid.uuid4().hex, args.language,
                                                                     args.request, asynchronous=False)
            require(result["state"] == "completed", ERRORS.get(result.get("error_code"), "Recommendation failed."))
        elif args.command == "recommendation-schema":
            from recommendation import SCHEMA
            result = SCHEMA
        elif args.command == "recommendation-plan-schema":
            from coaching_materials import PLAN_SCHEMA
            result = PLAN_SCHEMA
        elif args.command == "material-catalog":
            from materials import catalog
            result = catalog()
        elif args.command == "material-source":
            from materials import MaterialStore
            store = MaterialStore()
            if args.refresh:
                store.fetch(args.source_id, refresh=True)
            result = store.retrieve([{'source_id': args.source_id, 'query': args.query, 'pages': args.pages}])
        elif args.command == "material-import":
            from materials import MaterialStore
            value = json.loads(args.input.read_text())
            result = MaterialStore().import_example(value['source_id'], value['locator'], value['notation'], value['review'])
        elif args.command == "recommend-materials":
            from coaching_materials import prepare_context
            context = prepare_context(args.practice_root, data, json.loads(args.context.read_text()), json.loads(args.plan.read_text()))
            atomic_text(args.output, jdump(context))
            result = {'context': str(args.output), 'images_to_inspect': context['preparation']['images'],
                      'failures': context['preparation']['material_failures']}
        elif args.command == "recommend-context":
            from recommendation import context_for
            with log_lock(args.practice_root):
                context = context_for(args.practice_root, data, args.language, args.request)
            atomic_text(args.output, jdump(context))
            result = {"context": str(args.output), "fingerprint": context["fingerprint"]}
        elif args.command == "accept-recommendation":
            from recommendation import accept_conversation
            result = accept_conversation(args.practice_root, data, json.loads(args.context.read_text()),
                                         json.loads(args.input.read_text()), args.request_id)
        elif args.command == "report":
            result = {"report": render_report(args.practice_root, data, args.output)}
        elif args.command == "assign":
            result = assign(args.practice_root, data, args.exercise_id, args.key, args.bpm, args.purpose, args.reason)
        elif args.command in ("record", "correct"):
            result = record_result(args.practice_root, data, args.task_id, json.loads(args.input.read_text()), args.command == "correct")
        elif args.command == "reflection":
            from sessions import SessionStore
            payload = json.loads(args.input.read_text())
            require(isinstance(payload, dict) and set(payload) <= {"rating", "note", "expected_event_id"}, "Invalid feedback fields.")
            result = SessionStore(args.practice_root).reflect(data, args.task_id, payload.get("rating"),
                                                            payload.get("note", ""), payload.get("expected_event_id"))
        elif args.command == "cancel":
            result = cancel(args.practice_root, data, args.task_id, args.reason)
        elif args.command == "discard":
            result = discard(args.practice_root, data, args.task_id, args.reason, args.choice)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, KeyError, OSError, TypeError, yaml.YAMLError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
