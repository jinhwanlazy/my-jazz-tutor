"""Notation is a display of assigned material, not new performance evidence."""
import copy
import unittest

import review
from notation import score_for
from webapp import display_target


class NotationTests(unittest.TestCase):
    def setUp(self):
        self.data = review.curriculum()

    def target(self, exercise, key="C"):
        return review.target_for(self.data, exercise, key)

    def test_all_six_exercises_in_all_three_keys_have_complete_staves(self):
        for exercise in self.data["exercises"]:
            for key in self.data["allowed_keys"]:
                with self.subTest(exercise=exercise["id"], key=key):
                    target = self.target(exercise["id"], key)
                    score = score_for(target)
                    self.assertIsNotNone(score)
                    self.assertEqual(len(score["bars"]), target["bars"])
                    for bar in score["bars"]:
                        for hand in ("left", "right"):
                            events = bar[hand]
                            if events[0]["kind"] == "onset":
                                self.assertIsNone(events[0]["duration"])
                            else:
                                self.assertEqual(sum(e["duration"] for e in events), 4)

    def test_melody_keeps_octaves_flats_and_resting_hand(self):
        expected = {"C": [("E4", 64), ("C4", 60), ("F4", 65), ("B3", 59)],
                    "F": [("A4", 69), ("F4", 65), ("Bb4", 70), ("E4", 64)],
                    "Bb": [("D4", 62), ("Bb3", 58), ("Eb4", 63), ("A3", 57)]}
        for key, notes in expected.items():
            score = score_for(self.target("E02", key))
            self.assertEqual([(b["right"][0]["pitches"][0]["name"], b["right"][0]["pitches"][0]["midi"]) for b in score["bars"]], notes)
            self.assertTrue(all(b["left"][0]["kind"] == "rest" for b in score["bars"]))

    def test_guide_tones_and_bass_come_from_assignment_not_accompaniment(self):
        target = self.target("E04")
        target["playback"]["bars"][0]["notes"] = [99, 100, 101]
        score = score_for(target)
        self.assertEqual([p["midi"] for p in score["bars"][0]["left"][0]["pitches"]], [38])
        self.assertEqual([p["midi"] for p in score["bars"][0]["right"][0]["pitches"]], [53, 60])

    def test_charleston_attacks_on_one_and_two_and_with_rests(self):
        score = score_for(self.target("E05"))
        for bar in score["bars"]:
            self.assertEqual([e["beat"] for e in bar["right"] if e["kind"] == "notes"], [0, 1.5])
            self.assertEqual([e["duration"] for e in bar["right"] if e["kind"] == "notes"], [.5, .5])
            self.assertEqual(bar["left"][0]["duration"], 4)

    def test_improvisation_does_not_invent_a_melody_or_bass_hold_length(self):
        score = score_for(self.target("E06", "Bb"))
        self.assertEqual([p["name"] for p in score["allowed_pitches"]], ["D4", "F4", "G4"])
        self.assertEqual([b["right"][0]["kind"] for b in score["bars"]], ["improv", "improv", "rest", "rest"] * 2)
        self.assertTrue(all(b["left"][0]["duration"] is None for b in score["bars"]))

    def test_historical_snapshot_is_used_without_modifying_it(self):
        target = self.target("E02")
        target["material"]["melody"] = "D4 | A3 | G4 | C4"
        before = copy.deepcopy(target)
        english, korean = display_target(target, "en"), display_target(target, "ko")
        self.assertEqual(english["notation"], korean["notation"])
        self.assertEqual(english["notation"]["bars"][0]["right"][0]["pitches"][0]["midi"], 62)
        self.assertEqual(before, target)
        self.assertNotIn("notation", target)

    def test_unknown_conditions_and_incomplete_material_have_no_fabricated_score(self):
        for field, value in [("rhythm", "future-rhythm"), ("bars", 5), ("key", "G"), ("arrangement", "free")]:
            target = self.target("E02")
            target[field] = value
            self.assertIsNone(score_for(target))
        target = self.target("E02")
        target["material"]["melody"] = "E4 | ? | F4 | B3"
        self.assertIsNone(score_for(target))
