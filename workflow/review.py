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
    require(isinstance(lessons, list) and lessons, "At least one exercise is required.")
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
    require(seen, "At least one fixed milestone is required.")
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
            require(target["criteria"].get("checks") == CHECKS, "Unknown task criteria.")
            number(target["criteria"]["min_clean_runs"], "min_clean_runs", 1, 20)
            tasks[task_id] = {"assignment": event, "target": target, "report": None,
                              "cancelled": False, "retired": False, "cancellation": None}
            continue
        require(task_id in tasks, "This result has no matching assignment.")
        task = tasks[task_id]
        require(event["release"] == task["assignment"]["release"] and event["exercise_id"] == task["assignment"]["exercise_id"], "The task version or exercise ID has changed.")
        if kind in ("cancelled", "retired"):
            require(not task["report"] and not task["cancelled"], "A resolved task cannot be cancelled.")
            task["cancelled"] = True
            task["retired"] = kind == "retired"
            task["cancellation"] = event
        elif kind in ("reported", "corrected"):
            require(not task["cancelled"], "A cancelled task cannot receive a report.")
            if kind == "reported":
                require(task["report"] is None and not event["supersedes"], "A result already exists. Use correct to revise it.")
            else:
                require(task["report"] and event["supersedes"] == task["report"]["event_id"], "The correction does not refer to the latest report.")
            practice_day = iso_day(event["practice_date"])
            observations = reflection_observations(event)
            assigned_at = datetime.fromisoformat(task["assignment"]["recorded_at"])
            assigned_day = assigned_at.astimezone(ZoneInfo(observations["timezone"])).date() if observations else assigned_at.date()
            require(practice_day >= assigned_day, "The practice date is earlier than the assignment date.")
            require(event["raw_note"].strip() or event["difficulty"] in RATINGS, "The original user note is required.")
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
            task["report"] = event
        else:
            raise ValueError(f"Unsupported event_type: {kind}")
    return list(tasks.values())


def reflection_observations(report):
    """Automatic timing snapshot; legacy reports retain their original observations."""
    if not report or report["difficulty"] not in RATINGS or not report["reason"].startswith('{'):
        return None
    try:
        value = json.loads(report["reason"])
    except ValueError:
        return None
    return value if isinstance(value, dict) and value.get("source") == "session-reflection-v1" else None


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


def practice_ready(data, tasks, exercise_id, key):
    """Comfort can open practice choices, but never supplies success or retention evidence."""
    if goal_successes(data, tasks, exercise_id, key, data["default_bpm"]):
        return True
    reports = [t for t in tasks if t["report"] and t["assignment"]["exercise_id"] == exercise_id
               and t["target"]["key"] == key and not incompatible_target_fields(data, t)]
    latest = max(enumerate(reports), key=lambda pair: (pair[1]["report"]["practice_date"], pair[0]), default=(0, None))[1]
    return bool(latest and latest["report"]["difficulty"] in ("good", "too_easy"))


def reflection_suggestion(data, tasks, latest, deferred):
    recent = [t for _, t in latest.values() if t["report"] and t["report"]["difficulty"] in RATINGS
              and not incompatible_target_fields(data, t)]
    if not recent:
        return None
    task = max(recent, key=lambda t: (t["report"]["practice_date"], t["assignment"]["recorded_at"]))
    target, rating = task["target"], task["report"]["difficulty"]
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
                    "reason": "Try the next exercise based on how the practice felt."}
    if (exercise, key) not in deferred and eligible:
        return {"action": "practice", "exercise_id": exercise, "key": key,
                "bpm": min(data["maximum_bpm"], bpm + 10) if rating == "too_easy" else bpm,
                "reason": "Try a faster tempo." if rating == "too_easy" and bpm < data["maximum_bpm"] else "Keep practicing, or choose another key or exercise."}
    return None


def cell(data, tasks, exercise_id, key, bpm=None):
    bpm = data["default_bpm"] if bpm is None else bpm
    successes = goal_successes(data, tasks, exercise_id, key, bpm)
    attempted = [t for t in tasks if t["report"] and t["assignment"]["exercise_id"] == exercise_id
                 and json.loads(t["report"]["actual_json"]).get("key", t["target"]["key"]) == key]
    state = "retained" if retained(successes, data["retention_days"]) else "success" if successes else "attempted" if attempted else "unknown"
    return {"state": state, "attempts": len(attempted), "successes": len(successes),
            "last_success": max((t["report"]["practice_date"] for t in successes), default=None)}


def latest_activity(tasks, today):
    """Use the practice day, not the correction time, to order observations."""
    latest = {}
    for task in tasks:
        if task["retired"]:
            continue  # A release transition is not a practice attempt or a skipped exercise.
        if task["report"]:
            day = iso_day(task["report"]["practice_date"])
        elif task["cancellation"]:
            day = datetime.fromisoformat(task["cancellation"]["recorded_at"]).date()
        else:
            continue
        token = (task["assignment"]["exercise_id"], task["target"]["key"])
        if day <= today and (token not in latest or day >= latest[token][0]):
            latest[token] = (day, task)
    return latest


def suggestion(data, tasks, today=None):
    today = today or date.today()
    pending = [t for t in tasks if not t["report"] and not t["cancelled"]]
    if pending:
        task = pending[0]
        return {"action": "resume", "task_id": task["assignment"]["task_id"], "target": task["target"], "reason": "You have an unfinished task. Continue it before starting another."}
    latest = latest_activity(tasks, today)
    deferred = {}
    for token, (day, task) in latest.items():
        if day != today:
            continue
        cancellation, report = task["cancellation"], task["report"]
        if cancellation or (report["difficulty"] == "hard" and outcome(task) != "success"):
            deferred[token] = {"exercise_id": token[0], "key": token[1],
                               "task_id": task["assignment"]["task_id"],
                               "reason": cancellation["reason"] if cancellation else report["raw_note"]}
    context = {"deferred_today": list(deferred.values())}
    for milestone in data["milestones"]:
        if (milestone["exercise_id"], milestone["key"]) in deferred:
            continue
        info = cell(data, tasks, milestone["exercise_id"], milestone["key"], milestone["bpm"])
        delay = data["maintenance_days"] if info["state"] == "retained" else data["retention_days"]
        if info["last_success"] and (today - iso_day(info["last_success"])).days >= delay:
            successes = goal_successes(data, tasks, milestone["exercise_id"], milestone["key"], milestone["bpm"])
            latest_success = max(successes, key=lambda t: t["report"]["practice_date"])
            actual_bpm = json.loads(latest_success["report"]["actual_json"])["bpm"]
            return {"action": "review", **milestone, "bpm": actual_bpm, **context,
                    "reason": "It is time to check later retention at the tempo of your previous success."}
    reflection_next = reflection_suggestion(data, tasks, latest, deferred)
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
        report = task["report"]
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


def assign(root, data, exercise_id, key=None, bpm=None, purpose="practice", reason=""):
    require(purpose in ("practice", "diagnostic", "review", "transfer"), "Invalid purpose.")
    target = target_for(data, exercise_id, key, bpm)
    with log_lock(root):
        events = read_events(root)
        tasks = records(events)
        require(not any(not t["report"] and not t["cancelled"] for t in tasks), "Report or cancel the unfinished task first.")
        lesson = next(x for x in data["exercises"] if x["id"] == exercise_id)
        if purpose != "diagnostic":
            for parent in lesson["prerequisites"]:
                ready = practice_ready(data, tasks, parent, target["key"]) if purpose == "practice" else goal_successes(data, tasks, parent, target["key"], data["default_bpm"])
                require(ready, f"First complete prerequisite {parent} in the same key. Use diagnostic explicitly for a diagnostic task.")
        event = new_event("assigned", "T-" + uuid.uuid4().hex[:10], data, exercise_id, purpose)
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


def status(root, data):
    tasks = records(read_events(root))
    profile_path = Path(root) / "profile.json"
    profile = json.loads(profile_path.read_text()) if profile_path.exists() else {}
    reported = [t for t in tasks if t["report"]]
    goals = [{**m, **cell(data, tasks, **m)} for m in data["milestones"]]
    return {"version": data["version"], "profile": profile, "evidence": "Self-reported / unassessed does not mean failed",
            **practice_totals([t["report"] for t in reported]),
            "today": daily_summary(data, tasks, profile),
            "goals": goals, "next": suggestion(data, tasks, datetime.now(ZoneInfo(profile.get("timezone", "UTC"))).date()),
            "recent": [{"task_id": t["assignment"]["task_id"], "exercise": t["assignment"]["exercise_id"],
                        "date": t["report"]["practice_date"], "actual": json.loads(t["report"]["actual_json"]),
                        "outcome": outcome(t), "difficulty": t["report"]["difficulty"],
                        "raw_note": t["report"]["raw_note"], "hypothesis": t["report"]["hypothesis"]}
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
            tag = "Milestone" if (lesson["id"], key) in required else "Optional key"
            cells.append(f'<td class="{metric["state"]}"><b>{STATES[metric["state"]]}</b><small>{tag} · Reports: {metric["attempts"]}</small></td>')
        table.append(f'<tr><th>{escape(lesson["id"])} · {escape(display_builtin(lesson["title"]))}<small>{escape(display_builtin(lesson["phase"]))}</small></th>{"".join(cells)}</tr>')
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
        history.append(f'<tr><td>{escape(r["practice_date"])}<small>{escape(r["task_id"])}</small></td><td>{escape(display_builtin(task["target"]["title"]))}</td>'
                       f'<td>{escape(task["target"]["key"])} / {task["target"]["bpm"]} BPM<small>{escape(ARRANGEMENTS.get(task["target"]["arrangement"], task["target"]["arrangement"]))}</small></td>'
                       f'<td>{escape(actual.get("key", "Unknown"))} / {escape(actual.get("bpm", "Unknown"))}<small>{escape(ARRANGEMENTS.get(actual.get("arrangement"), actual.get("arrangement", "Unknown")))}</small></td>'
                       f'<td>{RESULTS[outcome(task)]}</td><td class="note">{escape(r["raw_note"])}</td></tr>')
    next_task = info["next"]
    candidate = next_task.get("target")
    if not candidate and "exercise_id" in next_task:
        candidate = target_for(data, next_task["exercise_id"], next_task["key"], next_task["bpm"])
    if candidate:
        candidate = display_builtin(candidate)
        labels = {"chords": "Chord progression", "roots": "Left-hand bass", "melody": "Right-hand melody", "guide_tones": "Right-hand thirds and sevenths"}
        material_rows = []
        for field, label in labels.items():
            if field not in candidate["material"]:
                continue
            if (field == "roots" and candidate["bass"] == "none") or (field == "melody" and candidate["melody"] == "none"):
                continue
            material_rows.append(f'<p><small>{label}</small>{escape(candidate["material"][field])}</p>')
        next_text = f'<h3>{escape(candidate["title"])}</h3><p>{escape(candidate["key"])} · {candidate["bpm"]} BPM · {candidate["bars"]} bars</p><p>{escape(candidate["instructions"])}</p>{"".join(material_rows)}<small>C4 = middle C · numbers indicate octaves</small>'
    elif next_task["action"] == "pause":
        next_text = '<h3>Finish today or adjust a condition</h3>'
    else:
        next_text = '<h3>Connect what you have learned into music</h3>'
    daily = info["today"]
    if daily["budget_reached"]:
        time_note = "You have reached your daily time budget. Consider finishing, or continue if you want."
    elif daily["remaining_minutes"] is None:
        time_note = "Some reports have unknown duration, so the remaining time is unknown."
    else:
        time_note = f'Remaining recorded budget: {daily["remaining_minutes"]:g} min, including preparation, listening, and reporting.'
    daily_text = (f'<p>Reports today: {daily["reported_attempts"]} · recorded time: {daily["known_minutes"]:g} min'
                  f' / daily budget: {daily["budget_minutes"]:g} min · duration unknown: {daily["minutes_unknown"]}'
                  f'<br>{time_note}</p>')
    empty = '<tr><td colspan="6" class="empty">No practice results have been recorded yet.</td></tr>'
    page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Jazz Practice · Practice history</title><style>
:root{{font-family:system-ui,-apple-system,"Noto Sans KR",sans-serif;color:#e5eaf2;background:#101923}}*{{box-sizing:border-box}}body{{margin:0}}main{{max-width:1160px;margin:auto;padding:42px 24px}}header{{display:flex;justify-content:space-between;gap:20px;align-items:center}}h1{{font-size:32px;margin:8px 0}}h2{{font-size:21px;margin:0 0 18px}}h3{{margin:0 0 10px}}p{{line-height:1.7;color:#b8c6d6}}.eyebrow{{letter-spacing:3px;color:#e8bd79;font-size:12px}}.badge{{border:1px solid #46515e;padding:8px 14px;border-radius:20px;white-space:nowrap;font-size:13px}}.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:28px 0}}.card,section{{background:#192634;border:1px solid #2b3b4b;border-radius:14px;padding:22px}}.card strong{{display:block;font-size:30px;margin:10px 0}}.card span,small{{color:#a8b9ca;font-size:12px}}small{{display:block;margin-top:7px}}section{{margin:20px 0}}.split{{display:grid;grid-template-columns:1.2fr 1fr;gap:20px}}.split section{{margin:0}}table{{border-collapse:collapse;width:100%;font-size:13px}}th,td{{padding:15px 12px;text-align:left;border-bottom:1px solid #334353;vertical-align:top}}thead th{{color:#a8b9ca;font-weight:500}}td.unknown{{color:#acb5c0}}td.attempted{{background:#273956}}td.success{{background:#304236}}td.retained{{background:#155345}}.scroll{{overflow:auto}}.legend{{font-size:12px;color:#a8b9ca}}.domain{{display:grid;grid-template-columns:65px 1fr 35px;gap:12px;align-items:center;margin:20px 0;font-size:13px}}.track{{height:8px;border-radius:8px;background:#354454;overflow:hidden}}.track div{{height:100%;background:#e8bd79}}pre{{white-space:pre-wrap;font-size:12px;line-height:1.7;color:#cee1ef}}.note{{white-space:pre-wrap;min-width:180px}}.empty{{text-align:center;padding:36px;color:#a8b9ca}}footer{{color:#899bac;font-size:12px;line-height:1.8;margin-top:28px}}@media(max-width:760px){{.cards{{grid-template-columns:repeat(2,1fr)}}.split{{grid-template-columns:1fr}}header{{align-items:flex-start}}main{{padding:24px 14px}}th,td{{min-width:115px}}}}
</style></head><body><main><header><div><div class="eyebrow">JAZZ PRACTICE</div><h1>Your records, your next practice</h1><p>Share a daily budget of {daily['budget_minutes']:g} minutes across tasks</p>{daily_text}</div><div class="badge">Active version {escape(data['version'])}</div></header>
<div class="cards"><div class="card">Reported tasks<strong>{info['reported_attempts']}</strong><span>Assignments alone do not count</span></div><div class="card">Recorded practice time<strong>{info['known_minutes']:g}<span> min</span></strong><span>Duration unknown: {info['minutes_unknown']}</span></div><div class="card">Milestones met<strong>{passed}<span> / {len(goals)}</span></strong><span>Fixed goals for this version · self-reported</span></div><div class="card">Later retention under the same conditions<strong>{held}<span> / {len(goals)}</span></strong><span>At least {data['retention_days']} days apart · self-reported</span></div></div>
<div class="split"><section><h2>{'Current task' if next_task['action']=='resume' else 'Suggested next task · not yet assigned'}</h2>{next_text}<p>{escape(next_task['reason'])}</p></section><section><h2>Milestones by domain</h2>{''.join(bars)}<p>Counts show successful milestones in each domain. Domains overlap; these are not overall jazz ability scores or independent skill measures.</p></section></div>
<section><h2>Conditions you have checked</h2><p class="legend">Unassessed → Attempted → Same-day success → Later retention. Unassessed does not mean failed. The default comparison tempo is {data['default_bpm']} BPM. Only reports meeting all hand, rhythm, and note conditions count as successful.</p><div class="scroll"><table><thead><tr><th>Exercise</th>{''.join(f'<th>{escape(k)}</th>' for k in data['allowed_keys'])}</tr></thead><tbody>{''.join(table)}</tbody></table></div></section>
<section><h2>Recent practice reports</h2><div class="scroll"><table><thead><tr><th>Practice date</th><th>Task</th><th>Target</th><th>Actual</th><th>Outcome</th><th>Original note</th></tr></thead><tbody>{''.join(history) or empty}</tbody></table></div></section>
<footer>These records are self-reported. Pitch, swing, and tone are not automatically assessed.<br>Generated: {escape(datetime.now(timezone.utc).isoformat(timespec='seconds'))} · Source: practice.csv · Run ./jazz report after new records to refresh</footer></main></body></html>'''
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
    web = sub.add_parser("serve", help="Local web practice room")
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
    cancelling = sub.add_parser("cancel")
    cancelling.add_argument("task_id")
    cancelling.add_argument("--reason", required=True)
    args = parser.parse_args(argv)
    try:
        data = curriculum(args.curriculum)
        development_source = (HERE / "publish.py").exists()
        production_root = (HERE.parent / "practice").resolve()
        if development_source and args.practice_root.resolve() == production_root:
            require(args.command not in ("assign", "record", "correct", "cancel", "serve"),
                    "Development source cannot write the real practice log. Use ./jazz in the practice project. For tests, set --practice-root to a temporary directory.")
            if args.command == "report":
                require(args.output is not None and not args.output.resolve().is_relative_to(production_root),
                        "Write development previews outside the practice project, for example with --output build/preview.html.")
        if args.command == "serve":
            from webapp import serve
            serve(args.practice_root, data, args.port, args.open)
            return 0
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
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
