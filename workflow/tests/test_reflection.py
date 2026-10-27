"""Quick feedback uses synthetic sessions and never implies musical correctness."""
import copy
from datetime import date, datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import review as r
from sessions import reflection_measurements
from test_webapp import chunk, raw
from webapp import Application


class ReflectionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.data = r.curriculum()
        self.app = Application(self.root, self.data)

    def assign(self, exercise="E01", key="C", bpm=60):
        return r.assign(self.root, self.data, exercise, key, bpm)["task_id"]

    def reflect(self, task, rating="good", **values):
        return self.app.post("/api/reflection", {"task_id": task, "rating": rating, **values})

    def tasks(self):
        return r.records(r.read_events(self.root))

    def session(self, task, interrupted=False):
        sid = self.app.store.start(task)["id"]
        self.app.store.append(sid, chunk(raw((1000, 0, [0x90, 60, 100]), (7000, 0, [0x80, 60, 0])),
            [{"type": "play", "at_ms": 0, "bpm": 80}, {"type": "tempo", "at_ms": 8000, "bpm": 100}]))
        self.app.store.finish(sid, 1, interrupted)
        return sid

    def test_one_label_saves_without_note_conditions_or_success_credit(self):
        task = self.assign()
        self.reflect(task)
        report = self.tasks()[0]["report"]
        self.assertEqual(report["raw_note"], "")
        self.assertEqual(report["actual_json"], "{}")
        self.assertEqual(report["checks_json"], "{}")
        self.assertEqual(report["clean_runs"], "")
        self.assertEqual(report["actual_minutes"], "")
        self.assertEqual(r.outcome(self.tasks()[0]), "unknown")
        self.assertFalse(r.goal_successes(self.data, self.tasks(), "E01", "C", 60))
        self.assertEqual(self.app.state("ko")["history"][0]["feedback"],
                         {"title": "연습을 저장했어요", "details": [], "evidence": "subjective difficulty"})
        self.assertIsNone(r.reflection_observations(report)["metronome_bpm"])

    def test_automatic_sessions_sum_duration_but_setting_is_not_played_bpm(self):
        task = self.assign()
        self.session(task)
        self.session(task)
        self.reflect(task)
        report = self.tasks()[0]["report"]
        measured = r.reflection_observations(report)
        self.assertAlmostEqual(float(report["actual_minutes"]), .2)
        self.assertEqual(measured["metronome_bpm"], 80)
        self.assertEqual([s["duration_source"] for s in measured["sessions"]], ["midi_span"] * 2)
        self.assertEqual(report["actual_json"], "{}")
        self.assertAlmostEqual(self.app.state()["status"]["today"]["known_minutes"], .2)
        self.assertEqual(self.app.state()["status"]["next"]["bpm"], 80)

    def test_interruptions_stay_unknown_and_playback_without_midi_is_measured(self):
        task = self.assign()
        self.session(task)
        self.session(task, interrupted=True)
        self.reflect(task)
        self.assertEqual(self.tasks()[0]["report"]["actual_minutes"], "")
        self.assertEqual(self.app.state()["status"]["today"]["minutes_unknown"], 1)
        task = self.assign("E02")
        sid = self.app.store.start(task)["id"]
        self.app.store.append(sid, chunk(events=[{"type": "play", "at_ms": 1000, "bpm": 70},
                                               {"type": "pause", "at_ms": 7000}]))
        self.app.store.finish(sid, 1)
        self.reflect(task)
        measured = r.reflection_observations(self.tasks()[-1]["report"])
        self.assertAlmostEqual(measured["minutes"], .1)
        self.assertEqual(measured["sessions"][0]["duration_source"], "playback")

    def test_retries_edits_stale_edits_and_raw_archives(self):
        task = self.assign()
        sid = self.session(task)
        original_archive = self.app.store.export(sid)
        first = self.reflect(task)
        self.assertEqual(self.reflect(task), first)
        note = 'Synthetic memo, "quoted"\n<img src=x> 원문'
        second = self.reflect(task, "challenging", note=note, expected_event_id=first["event_id"])
        self.assertEqual(self.reflect(task, "challenging", note=note, expected_event_id=first["event_id"]), second)
        with self.assertRaisesRegex(ValueError, "changed"):
            self.reflect(task, "impossible", expected_event_id=first["event_id"])
        self.assertEqual(len(r.read_events(self.root)), 3)
        self.assertEqual(self.tasks()[0]["report"]["raw_note"], note)
        self.assertEqual(self.app.store.export(sid), original_archive)
        self.assertEqual(r.read_events(self.root)[1]["reason"], r.read_events(self.root)[2]["reason"])
        self.reflect(task, "too_easy", expected_event_id=second["event_id"])
        self.assertEqual(self.tasks()[0]["report"]["raw_note"], "")

    def test_label_correction_preserves_legacy_observations_and_success(self):
        task = self.assign()
        r.record_result(self.root, self.data, task, {"raw_note": "Synthetic prior evidence", "followed_target": True,
            "checks": dict.fromkeys(r.CHECKS, True), "clean_runs": 2, "actual_minutes": 12})
        before = self.tasks()[0]["report"]
        self.reflect(task, "challenging", expected_event_id=before["event_id"])
        after = self.tasks()[0]["report"]
        for key in ("actual_json", "checks_json", "practice_date", "clean_runs", "actual_minutes", "release"):
            self.assertEqual(after[key], before[key])
        self.assertEqual(r.outcome(self.tasks()[0]), "success")
        self.assertEqual(r.read_events(self.root)[1]["raw_note"], before["raw_note"])

    def test_requires_finish_and_rejects_manual_observation_fields(self):
        task = self.assign()
        sid = self.app.store.start(task)["id"]
        with self.assertRaisesRegex(ValueError, "Finish"):
            self.reflect(task)
        self.app.store.finish(sid, 0)
        for values in ({"rating": "easy"}, {"note": None}, {"actual_minutes": 10}, {"practice_date": "2026-01-01"}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.reflect(task, **values)
        self.assertEqual(len(r.read_events(self.root)), 1)

    def test_multi_session_totals_are_not_limited_to_a_single_day(self):
        task = self.assign()
        self.session(task)
        self.session(task)
        sessions = self.app.store.list(task)
        for session in sessions:
            session["summary"]["input_span_ms"] = 24 * 60 * 60 * 1000
        with patch.object(self.app.store, "list", return_value=sessions):
            self.reflect(task)
        self.assertEqual(float(self.tasks()[0]["report"]["actual_minutes"]), 2880)

    def test_comfort_opens_same_key_practice_without_mastery_or_retention(self):
        first = self.assign()
        saved = self.reflect(first)
        self.assertEqual(self.app.state()["status"]["next"]["exercise_id"], "E02")
        self.assertNotIn("C", self.app.state()["exercises"][2]["eligible_keys"])
        self.reflect(self.assign("E02"), "too_easy")
        self.assertEqual(self.app.state()["status"]["next"]["exercise_id"], "E03")
        self.assertIn("C", self.app.state()["exercises"][2]["eligible_keys"])
        self.assertNotIn("F", self.app.state()["exercises"][2]["eligible_keys"])
        self.assertTrue(all(g["state"] in ("unknown", "attempted") for g in self.app.state()["status"]["goals"]))
        with self.assertRaises(ValueError):
            r.assign(self.root, self.data, "E03", purpose="review")
        changed = copy.deepcopy(self.data)
        changed["exercises"][0]["instructions"] += " Changed task."
        self.assertFalse(r.practice_ready(changed, self.tasks(), "E01", "C"))
        self.reflect(first, "impossible", expected_event_id=saved["event_id"])
        self.assertNotIn("C", self.app.state()["exercises"][2]["eligible_keys"])
        with self.assertRaises(ValueError):
            self.assign("E03")

    def test_all_four_ratings_guide_practice_and_respect_tempo_bounds(self):
        task = self.assign(bpm=self.data["minimum_bpm"])
        saved = self.reflect(task, "impossible")
        next_task = self.app.state()["status"]["next"]
        self.assertEqual(next_task["exercise_id"], "E01")
        self.assertEqual(next_task["bpm"], self.data["minimum_bpm"])
        self.reflect(task, "challenging", expected_event_id=saved["event_id"])
        self.assertEqual(self.app.state()["status"]["next"]["bpm"], self.data["minimum_bpm"])
        # Fill the practice route with comfort labels; never fill the mastery cells.
        for lesson in self.data["exercises"]:
            self.reflect(self.assign(lesson["id"], bpm=self.data["maximum_bpm"]), "too_easy")
        next_task = self.app.state()["status"]["next"]
        self.assertEqual(next_task["bpm"], self.data["maximum_bpm"])
        self.assertEqual(next_task["action"], "practice")
        self.assertTrue(all(g["successes"] == 0 for g in self.app.state()["status"]["goals"]))

    def test_cancelled_candidate_is_not_immediately_recommended_again(self):
        self.reflect(self.assign())
        skipped = self.assign("E02")
        r.cancel(self.root, self.data, skipped, "Synthetic skip")
        self.assertNotEqual(self.app.state()["status"]["next"].get("exercise_id"), "E02")

    def test_session_dates_survive_delayed_feedback_and_local_midnight(self):
        (self.root / "profile.json").write_text('{"timezone":"America/Los_Angeles"}')
        original_event = r.new_event
        def old_assignment(*args, **kwargs):
            return original_event(*args, **kwargs) | {"recorded_at": "2026-01-02T01:00:00+00:00"}
        with patch.object(r, "new_event", side_effect=old_assignment):
            task = self.assign()
        for at in ("2026-01-02T01:05:00+00:00", "2026-01-03T01:05:00+00:00"):
            sid = self.session(task)
            with self.app.store.database() as db:
                db.execute("UPDATE sessions SET created_at=? WHERE id=?", (at, sid))
        self.reflect(task)
        report = self.tasks()[0]["report"]
        self.assertEqual(report["practice_date"], "2026-01-02")
        self.assertEqual(r.reflection_observations(report)["days"], {"2026-01-01": .1, "2026-01-02": .1})
        for day in (date(2026, 1, 1), date(2026, 1, 2)):
            self.assertAlmostEqual(r.daily_summary(self.data, self.tasks(), {}, day)["known_minutes"], .1)
        self.assertEqual(r.daily_summary(self.data, self.tasks(), {}, date(2026, 1, 3))["reported_attempts"], 0)
        measured = reflection_measurements([], {"timezone": "Asia/Seoul"}, datetime(2026, 1, 1, 20, tzinfo=timezone.utc))
        self.assertEqual(measured["practice_date"], "2026-01-02")
        self.assertEqual(measured["date_source"], "feedback_date")
