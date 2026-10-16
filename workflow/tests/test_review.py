import copy
import csv
from datetime import date, timedelta
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stderr
import io

import review as r
import publish as p
import git_fixture


class PracticeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = r.curriculum()
        (self.root / "profile.json").write_text('{"daily_minutes":30}')

    def task(self, exercise="E01", key="C", bpm=60, purpose="practice"):
        return r.assign(self.root, self.data, exercise, key, bpm, purpose)["task_id"]

    def success(self, task_id, **overrides):
        payload = {"raw_note": "명시적 테스트 보고: 지정 조건, 음과 박을 지켜 멈추지 않고 연속 두 번",
                   "followed_target": True, "checks": dict.fromkeys(r.CHECKS, True),
                   "clean_runs": 2, "actual_minutes": 20}
        payload.update(overrides)
        return r.record_result(self.root, self.data, task_id, payload)

    def history(self):
        return r.records(r.read_events(self.root))

    def test_empty_history_and_report_do_not_create_performance(self):
        info = r.status(self.root, self.data)
        self.assertEqual(info["reported_attempts"], 0)
        self.assertTrue(all(x["state"] == "unknown" for x in info["goals"]))
        report = Path(r.render_report(self.root, self.data)).read_text()
        self.assertIn("아직 실제 연습 기록이 없습니다", report)
        self.assertFalse((self.root / "practice.csv").exists())

    def test_assignment_is_not_practice_and_pending_is_resumed(self):
        task_id = self.task()
        self.assertEqual(r.status(self.root, self.data)["reported_attempts"], 0)
        self.assertEqual(r.suggestion(self.data, self.history())["task_id"], task_id)
        with self.assertRaises(ValueError):
            self.task("E02")

    def test_lower_bpm_and_changed_hand_do_not_pass_target(self):
        task_id = self.task()
        result = self.success(task_id, actual={"bpm": 50, "arrangement": "right-melody-only"})
        self.assertEqual(result["outcome"], "unmet")
        self.assertEqual(self.history()[0]["target"]["bpm"], 60)
        self.assertEqual(json.loads(self.history()[0]["report"]["actual_json"])["bpm"], 50)

    def test_easy_note_cannot_invent_checks_or_conditions(self):
        task_id = self.task()
        result = r.record_result(self.root, self.data, task_id, {"raw_note": "쉬웠음", "difficulty": "easy"})
        self.assertEqual(result["outcome"], "unknown")
        self.assertEqual(json.loads(self.history()[0]["report"]["actual_json"]), {})

    def test_success_requires_explicit_checks_and_runs(self):
        task_id = self.task()
        result = r.record_result(self.root, self.data, task_id, {"raw_note": "지정 조건대로 했음", "followed_target": True})
        self.assertEqual(result["outcome"], "unknown")
        corrected = self.success_payload()
        self.assertEqual(r.record_result(self.root, self.data, task_id, corrected, True)["outcome"], "success")

    def success_payload(self):
        return {"raw_note": "정정: 음과 박을 지켰고 무중단 연속 2회, 지정 조건 그대로", "followed_target": True,
                "checks": dict.fromkeys(r.CHECKS, True), "clean_runs": 2}

    def test_prerequisites_are_key_specific(self):
        self.success(self.task("E01"))
        self.success(self.task("E02"))
        with self.assertRaises(ValueError):
            self.task("E03", key="F")
        self.task("E03", key="C")

    def test_diagnostic_can_isolate_a_later_skill(self):
        self.task("E03", purpose="diagnostic")
        self.assertEqual(len(self.history()), 1)

    def test_retention_requires_later_date_and_identical_actual_conditions(self):
        self.success(self.task())
        self.success(self.task())
        tasks = self.history()
        self.assertEqual(r.cell(self.data, tasks, "E01", "C")["state"], "success")
        earlier = (date.today() - timedelta(days=3)).isoformat()
        tasks[0]["report"]["practice_date"] = earlier
        self.assertEqual(r.cell(self.data, tasks, "E01", "C")["state"], "retained")
        actual = json.loads(tasks[1]["report"]["actual_json"])
        actual["bpm"] = 80
        tasks[1]["report"]["actual_json"] = r.jdump(actual)
        self.assertEqual(r.cell(self.data, tasks, "E01", "C")["state"], "success")

    def test_review_candidate_preserves_actual_successful_tempo(self):
        self.success(self.task(bpm=80))
        tasks = self.history()
        tasks[0]["report"]["practice_date"] = (date.today() - timedelta(days=3)).isoformat()
        suggested = r.suggestion(self.data, tasks)
        self.assertEqual((suggested["action"], suggested["bpm"]), ("review", 80))

    def test_csv_notes_roundtrip_and_html_escape(self):
        note = '쉼표, "따옴표"\n<script>alert(1)</script> & 다음 줄'
        r.record_result(self.root, self.data, self.task(), {"raw_note": note})
        self.assertEqual(self.history()[0]["report"]["raw_note"], note)
        page = Path(r.render_report(self.root, self.data)).read_text()
        self.assertNotIn("<script>alert", page)
        self.assertIn("&lt;script&gt;", page)

    def test_correction_preserves_original_and_counts_one_attempt(self):
        task_id = self.task()
        first = r.record_result(self.root, self.data, task_id, {"raw_note": "처음 보고"})
        second = r.record_result(self.root, self.data, task_id, self.success_payload(), True)
        events = r.read_events(self.root)
        self.assertEqual(len(events), 3)
        self.assertEqual(events[1]["raw_note"], "처음 보고")
        self.assertEqual(events[2]["supersedes"], first["event_id"])
        self.assertEqual(r.status(self.root, self.data)["reported_attempts"], 1)
        self.assertEqual(second["outcome"], "success")

    def test_duplicate_report_is_rejected_without_mutation(self):
        task_id = self.task()
        self.success(task_id)
        before = (self.root / "practice.csv").read_bytes()
        with self.assertRaises(ValueError):
            self.success(task_id)
        self.assertEqual(before, (self.root / "practice.csv").read_bytes())

    def test_cancel_is_not_failure_or_practice(self):
        task_id = self.task()
        r.cancel(self.root, self.data, task_id, "아직 연습하지 않음")
        self.assertEqual(r.status(self.root, self.data)["reported_attempts"], 0)
        self.assertTrue(self.history()[0]["cancelled"])
        self.task()

    def test_invalid_boolean_number_and_future_report_are_rejected(self):
        task_id = self.task()
        for payload in [
            {"raw_note": "테스트", "actual": {"bpm": True}},
            {"raw_note": "테스트", "checks": {"no_stops": "true"}},
            {"raw_note": "테스트", "practice_date": (date.today() + timedelta(days=1)).isoformat()},
        ]:
            with self.assertRaises(ValueError):
                r.record_result(self.root, self.data, task_id, payload)
        self.assertIsNone(self.history()[0]["report"])

    def test_old_results_keep_original_criteria(self):
        self.success(self.task())
        modified = copy.deepcopy(self.data)
        modified["criteria"]["min_clean_runs"] = 3
        modified["criteria"]["id"] = "three-takes-v2"
        self.assertEqual(r.outcome(self.history()[0]), "success")
        self.assertEqual(r.cell(modified, self.history(), "E01", "C")["state"], "attempted")

    def test_cycle_in_curriculum_is_rejected(self):
        modified = copy.deepcopy(self.data)
        modified["exercises"][0]["prerequisites"] = ["E03"]
        path = self.root / "bad.yaml"
        path.write_text(r.yaml.safe_dump(modified, allow_unicode=True))
        with self.assertRaises(ValueError):
            r.curriculum(path)

    def test_development_cli_cannot_write_live_practice(self):
        with patch.object(r, "assign") as mocked, redirect_stderr(io.StringIO()):
            self.assertEqual(r.main(["assign", "E01"]), 2)
            mocked.assert_not_called()
        with patch.object(r, "render_report") as mocked, redirect_stderr(io.StringIO()):
            self.assertEqual(r.main(["report"]), 2)
            mocked.assert_not_called()

    def test_multiple_easy_tasks_advance_same_day_with_shared_time(self):
        self.success(self.task("E01"), difficulty="easy", actual_minutes=3)
        self.assertEqual(r.suggestion(self.data, self.history())["exercise_id"], "E02")
        self.success(self.task("E02"), difficulty="easy", actual_minutes=4)
        info = r.status(self.root, self.data)
        self.assertEqual(info["next"]["exercise_id"], "E03")
        self.assertEqual(info["today"]["reported_attempts"], 2)
        self.assertEqual(info["today"]["known_minutes"], 7)
        self.assertEqual(info["today"]["remaining_minutes"], 23)
        self.assertEqual([g["state"] for g in info["goals"][:2]], ["success", "success"])
        self.task("E03")

    def test_all_goals_can_pass_same_day_without_claiming_retention(self):
        for milestone in self.data["milestones"]:
            self.assertEqual(r.suggestion(self.data, self.history())["exercise_id"], milestone["exercise_id"])
            self.success(self.task(milestone["exercise_id"]), actual_minutes=2)
        info = r.status(self.root, self.data)
        self.assertEqual(info["next"]["action"], "consolidate")
        self.assertTrue(all(g["state"] == "success" for g in info["goals"]))
        self.assertEqual(info["today"]["known_minutes"], 12)

    def test_easy_without_evidence_gets_quick_check_and_cannot_unlock(self):
        r.record_result(self.root, self.data, self.task(), {"raw_note": "쉬웠음", "difficulty": "easy"})
        next_task = r.suggestion(self.data, self.history())
        self.assertEqual(next_task["exercise_id"], "E01")
        self.assertIn("짧게 확인", next_task["reason"])
        self.assertEqual(r.outcome(self.history()[0]), "unknown")
        with self.assertRaises(ValueError):
            self.task("E03")

    def test_cancel_defers_today_preserves_reason_and_expires_tomorrow(self):
        reason = '너무 어려워 보여서, 오늘은 스킵\n"다른 것부터"'
        r.cancel(self.root, self.data, self.task(), reason)
        next_task = r.suggestion(self.data, self.history())
        self.assertEqual(next_task["exercise_id"], "E02")
        self.assertEqual(next_task["deferred_today"][0]["reason"], reason)
        self.assertEqual(r.status(self.root, self.data)["today"]["reported_attempts"], 0)
        self.success(self.task("E02"), actual_minutes=3)
        self.assertEqual(r.suggestion(self.data, self.history())["action"], "pause")
        with self.assertRaises(ValueError):
            self.task("E03")
        tomorrow = r.suggestion(self.data, self.history(), date.today() + timedelta(days=1))
        self.assertEqual(tomorrow["exercise_id"], "E01")
        self.assertEqual(tomorrow["deferred_today"], [])

    def test_cancel_uses_cancellation_day_and_also_defers_due_review(self):
        self.success(self.task())
        r.cancel(self.root, self.data, self.task(), "오늘 복습은 스킵")
        events = r.read_events(self.root)
        earlier = (date.today() - timedelta(days=3)).isoformat()
        events[0]["recorded_at"] = earlier + "T10:00:00+00:00"
        events[1]["practice_date"] = earlier
        events[2]["recorded_at"] = earlier + "T11:00:00+00:00"
        tasks = r.records(events)
        self.assertEqual(r.suggestion(self.data, tasks)["exercise_id"], "E02")
        tomorrow = r.suggestion(self.data, tasks, date.today() + timedelta(days=1))
        self.assertEqual((tomorrow["action"], tomorrow["exercise_id"]), ("review", "E01"))

    def test_hard_attempt_is_preserved_without_inventing_failure(self):
        note = "5분 해봤는데 너무 어려워서 오늘은 다른 연습"
        r.record_result(self.root, self.data, self.task(),
                        {"raw_note": note, "difficulty": "hard", "actual_minutes": 5})
        info = r.status(self.root, self.data)
        self.assertEqual(info["next"]["exercise_id"], "E02")
        self.assertEqual(info["next"]["deferred_today"][0]["reason"], note)
        self.assertEqual(info["today"]["known_minutes"], 5)
        self.assertEqual(r.outcome(self.history()[0]), "unknown")
        self.assertEqual(info["goals"][0]["state"], "attempted")
        tomorrow = r.suggestion(self.data, self.history(), date.today() + timedelta(days=1))
        self.assertEqual(tomorrow["exercise_id"], "E01")
        self.assertIn("단순화", tomorrow["reason"])

    def test_voluntary_easier_retry_is_allowed_without_passing_original_goal(self):
        r.record_result(self.root, self.data, self.task(), {"raw_note": "어려웠음", "difficulty": "hard"})
        easier = self.task(bpm=50)
        self.assertEqual(r.suggestion(self.data, self.history())["task_id"], easier)
        self.success(easier, actual_minutes=4)
        info = r.status(self.root, self.data)
        self.assertEqual(info["goals"][0]["state"], "attempted")
        self.assertEqual(info["next"]["deferred_today"], [])
        self.assertEqual((info["next"]["exercise_id"], info["next"]["bpm"]), ("E01", 60))
        with self.assertRaises(ValueError):
            self.task("E03")

    def test_hard_but_successful_attempt_can_advance(self):
        self.success(self.task(), difficulty="hard")
        next_task = r.suggestion(self.data, self.history())
        self.assertEqual(next_task["exercise_id"], "E02")
        self.assertEqual(next_task["deferred_today"], [])

    def test_deferral_is_key_specific(self):
        self.data["milestones"].insert(1, {"exercise_id": "E01", "key": "F", "bpm": 60})
        r.cancel(self.root, self.data, self.task(), "C는 오늘 스킵")
        next_task = r.suggestion(self.data, self.history())
        self.assertEqual((next_task["exercise_id"], next_task["key"]), ("E01", "F"))

    def test_correction_recomputes_deferral_without_erasing_history(self):
        task_id = self.task()
        note = "어려워서 중단"
        r.record_result(self.root, self.data, task_id, {"raw_note": note, "difficulty": "hard"})
        self.assertEqual(r.suggestion(self.data, self.history())["exercise_id"], "E02")
        corrected = {**self.success_payload(), "difficulty": "easy", "actual_minutes": 3}
        r.record_result(self.root, self.data, task_id, corrected, True)
        info = r.status(self.root, self.data)
        self.assertEqual(info["next"]["deferred_today"], [])
        self.assertEqual(info["goals"][0]["state"], "success")
        self.assertEqual(info["today"]["reported_attempts"], 1)
        self.assertEqual(info["today"]["known_minutes"], 3)
        self.assertEqual(r.read_events(self.root)[1]["raw_note"], note)

    def test_correcting_earlier_task_does_not_override_later_activity(self):
        earlier = self.task()
        r.record_result(self.root, self.data, earlier, {"raw_note": "어려웠음", "difficulty": "hard"})
        self.success(self.task())
        r.record_result(self.root, self.data, earlier, {"raw_note": "정정: 여전히 어려웠음", "difficulty": "hard"}, True)
        self.assertEqual(r.suggestion(self.data, self.history())["deferred_today"], [])
        r.cancel(self.root, self.data, self.task(), "이제 그만")
        r.record_result(self.root, self.data, earlier, self.success_payload(), True)
        self.assertEqual(len(r.suggestion(self.data, self.history())["deferred_today"]), 1)

    def test_old_report_corrected_today_does_not_defer_today(self):
        task_id = self.task()
        r.record_result(self.root, self.data, task_id, {"raw_note": "어려웠음", "difficulty": "hard"})
        r.record_result(self.root, self.data, task_id, {"raw_note": "정정: 5분", "difficulty": "hard", "actual_minutes": 5}, True)
        events = r.read_events(self.root)
        earlier = (date.today() - timedelta(days=3)).isoformat()
        events[0]["recorded_at"] = earlier + "T10:00:00+00:00"
        events[1]["practice_date"] = events[2]["practice_date"] = earlier
        tasks = r.records(events)
        next_task = r.suggestion(self.data, tasks)
        self.assertEqual(next_task["exercise_id"], "E01")
        self.assertEqual(next_task["deferred_today"], [])
        self.assertEqual(r.daily_summary(self.data, tasks, {})["reported_attempts"], 0)

    def test_unknown_minutes_are_not_zero_and_zero_is_known(self):
        self.success(self.task(), actual_minutes=0)
        self.assertEqual(r.status(self.root, self.data)["today"]["minutes_unknown"], 0)
        unknown = self.task("E02")
        self.success(unknown, actual_minutes=None)
        info = r.status(self.root, self.data)
        self.assertIsNone(info["today"]["remaining_minutes"])
        self.assertEqual(info["today"]["minutes_unknown"], 1)
        r.record_result(self.root, self.data, unknown, {**self.success_payload(), "actual_minutes": 7}, True)
        self.assertEqual(r.status(self.root, self.data)["today"]["remaining_minutes"], 23)

    def test_profile_budget_is_advisory_even_with_unknown_time(self):
        (self.root / "profile.json").write_text('{"daily_minutes":10}')
        self.success(self.task(), actual_minutes=11)
        self.success(self.task("E02"), actual_minutes=None)
        daily = r.status(self.root, self.data)["today"]
        self.assertEqual(daily["budget_minutes"], 10)
        self.assertTrue(daily["budget_reached"])
        self.assertEqual(daily["remaining_minutes"], 0)
        self.assertEqual(daily["minutes_unknown"], 1)
        self.task("E03")

    def test_report_shows_pause_instead_of_claiming_goals_complete(self):
        r.cancel(self.root, self.data, self.task(), "오늘은 스킵")
        r.cancel(self.root, self.data, self.task("E02"), "이것도 스킵")
        report = Path(r.render_report(self.root, self.data)).read_text()
        self.assertIn("오늘은 마치거나 조건을 조정하기", report)
        self.assertNotIn("익힌 내용을 연결해서 연주하기", report)
        self.assertIn("오늘 결과 0개", report)
        self.assertTrue(all(g["state"] == "unknown" for g in r.status(self.root, self.data)["goals"]))


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.source, self.practice = base / "workflow", base / "practice"
        self.source.mkdir()
        self.practice.mkdir()
        (self.practice / "AGENTS.md").write_text("practice")
        (self.practice / "profile.json").write_text("{}")
        for name in p.FILES:
            shutil.copy2(p.SOURCE / name, self.source / name)
        self.version = r.curriculum(self.source / "curriculum.yaml")["version"]
        self.revision = git_fixture.initialize(self.source)

    def bump_version(self):
        data = r.curriculum(self.source / "curriculum.yaml")
        parts = data["version"].split(".")
        data["version"] = ".".join(parts[:2] + [str(int(parts[2]) + 1)])
        (self.source / "curriculum.yaml").write_text(r.yaml.safe_dump(data, allow_unicode=True))
        project = self.source / "pyproject.toml"
        project.write_text(project.read_text().replace(f'version = "{self.version}"', f'version = "{data["version"]}"'))
        lock = self.source / "uv.lock"
        lock.write_text(lock.read_text().replace(self.version, data["version"]))
        git_fixture.commit(self.source)
        return data

    def test_published_copy_is_immutable_and_independent_from_source(self):
        result = p.publish(self.source, self.practice, True)
        installed = Path(result["installed"]) / "COACH.md"
        before = installed.read_bytes()
        (self.source / "COACH.md").write_text("changed source")
        self.assertEqual(installed.read_bytes(), before)
        with self.assertRaises(ValueError):
            p.publish(self.source, self.practice, True)

    def test_release_cannot_switch_while_task_is_pending(self):
        p.publish(self.source, self.practice, True)
        data = r.curriculum(self.source / "curriculum.yaml")
        r.assign(self.practice, data, "E01")
        self.bump_version()
        with self.assertRaises(ValueError):
            p.publish(self.source, self.practice, True)
        self.assertEqual((self.practice / "active-version").read_text().strip(), self.version)
        self.assertEqual(len(r.read_events(self.practice)), 1)

    def test_pending_release_installs_and_only_activates_after_report(self):
        p.publish(self.source, self.practice, True)
        old_data = r.curriculum(self.source / "curriculum.yaml")
        task_id = r.assign(self.practice, old_data, "E01")["task_id"]
        original = (self.practice / "practice.csv").read_bytes()
        new_data = self.bump_version()
        installed = p.publish(self.source, self.practice, False)
        self.assertEqual(installed["active"], self.version)
        self.assertFalse(installed["activated"])
        self.assertTrue((Path(installed["installed"]) / "manifest.json").is_file())
        self.assertEqual((self.practice / "practice.csv").read_bytes(), original)
        with self.assertRaises(ValueError):
            p.publish(self.source, self.practice, True)
        r.record_result(self.practice, old_data, task_id,
                        {"raw_note": "테스트: 어려워서 중단", "difficulty": "hard", "actual_minutes": 3})
        reported = (self.practice / "practice.csv").read_bytes()
        self.assertEqual(p.publish(self.source, self.practice, True)["active"], new_data["version"])
        self.assertEqual((self.practice / "practice.csv").read_bytes(), reported)
        tasks = r.records(r.read_events(self.practice))
        self.assertEqual(tasks[0]["target"]["curriculum_version"], self.version)
        self.assertEqual(tasks[0]["report"]["release"], self.version)
        self.assertEqual(r.suggestion(new_data, tasks)["exercise_id"], "E02")

    def test_pending_release_can_activate_after_cancel_without_practice_credit(self):
        p.publish(self.source, self.practice, True)
        old_data = r.curriculum(self.source / "curriculum.yaml")
        task_id = r.assign(self.practice, old_data, "E01")["task_id"]
        new_data = self.bump_version()
        p.publish(self.source, self.practice, False)
        r.cancel(self.practice, old_data, task_id, "테스트: 아직 연습하지 않아 스킵")
        self.assertEqual(p.publish(self.source, self.practice, True)["active"], new_data["version"])
        info = r.status(self.practice, new_data)
        self.assertEqual(info["reported_attempts"], 0)
        self.assertEqual(info["next"]["exercise_id"], "E02")

    def test_idempotent_publish_does_not_touch_evidence(self):
        p.publish(self.source, self.practice, True)
        r.assign(self.practice, r.curriculum(), "E01")
        before = (self.practice / "practice.csv").read_bytes()
        p.publish(self.source, self.practice, True)
        self.assertEqual(before, (self.practice / "practice.csv").read_bytes())

    def test_explicit_revision_uses_committed_code_despite_dirty_source(self):
        original = (self.source / 'COACH.md').read_bytes()
        (self.source / 'COACH.md').write_text('uncommitted development change')
        result = p.publish(self.source, self.practice, ref=self.revision)
        self.assertEqual((Path(result['installed']) / 'COACH.md').read_bytes(), original)
        self.assertFalse((self.practice / 'runtime.json').exists())

    def test_legacy_migration_preserves_pending_task_and_runtime(self):
        installed = Path(p.publish(self.source, self.practice)['installed'])
        legacy = self.practice / 'releases' / self.version
        shutil.copytree(installed, legacy)
        (self.practice / 'active-version').write_text(self.version + '\n')
        r.assign(self.practice, r.curriculum(self.source / 'curriculum.yaml'), 'E01')
        before = (self.practice / 'practice.csv').read_bytes()
        result = p.publish(self.source, self.practice, True)
        self.assertEqual(result['active'], self.version)
        self.assertEqual(p.runtime.read_pin(self.practice)['revision'], self.revision)
        self.assertEqual((self.practice / 'practice.csv').read_bytes(), before)

    def test_migration_cannot_replace_changed_legacy_runtime_with_pending_task(self):
        legacy = self.practice / 'releases' / self.version
        shutil.copytree(self.source, legacy)
        (legacy / 'COACH.md').write_text('different runtime')
        (self.practice / 'active-version').write_text(self.version + '\n')
        r.assign(self.practice, r.curriculum(self.source / 'curriculum.yaml'), 'E01')
        before = (self.practice / 'practice.csv').read_bytes()
        with self.assertRaises(ValueError):
            p.publish(self.source, self.practice, True)
        self.assertFalse((self.practice / 'runtime.json').exists())
        self.assertEqual((self.practice / 'practice.csv').read_bytes(), before)

    def test_missing_ref_preserves_active_pin_and_evidence(self):
        p.publish(self.source, self.practice, True)
        r.assign(self.practice, r.curriculum(self.source / 'curriculum.yaml'), 'E01')
        before = {name: (self.practice / name).read_bytes() for name in ['runtime.json', 'practice.csv']}
        with self.assertRaises(ValueError):
            p.publish(self.source, self.practice, True, ref='missing-tag')
        for name, content in before.items():
            self.assertEqual((self.practice / name).read_bytes(), content)


if __name__ == "__main__":
    unittest.main()
