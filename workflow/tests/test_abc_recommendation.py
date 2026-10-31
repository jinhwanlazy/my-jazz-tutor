import copy
import unittest

import review
from recommendation import validate_result, make_target, validate_target, prose_fields
from recommendation_fixture import result, abc_result
from difficulty import result_from_target
from localization import translation_input, translated_target
from notation import score_for


class ABCRecommendationTests(unittest.TestCase):
    def test_new_contract_round_trip_and_immutable_notation_identity(self):
        value = abc_result(8)
        validate_result(value)
        target = make_target(value, review.curriculum(), {'provider': 'synthetic-test'})
        validate_target(target)
        self.assertEqual(result_from_target(target), value)
        self.assertEqual(len(score_for(target)['bars']), 8)
        self.assertEqual(target['difficulty']['features']['written_expression'], ['mf', 'p'])
        changed = copy.deepcopy(target)
        changed['exercise']['notation']['abc'] = changed['exercise']['notation']['abc'].replace('[FA]', '[GA]')
        with self.assertRaises(ValueError): validate_target(changed)

    def test_third_fifth_confusion_is_rejected(self):
        value = abc_result()
        value['music_claims'][0]['degree'] = 5
        with self.assertRaisesRegex(ValueError, 'third and fifth'): validate_result(value)
        value['music_claims'][0].update(degree=3, alteration=-1)
        with self.assertRaisesRegex(ValueError, 'chromatic interval'): validate_result(value)

    def test_multiple_chords_in_one_bar_survive_the_saved_summary(self):
        value = abc_result(1)
        value['exercise']['notation']['abc'] = value['exercise']['notation']['abc'].replace('"D"!mf![FA]8 |', '"D"!mf![FA]2 "G"[GB]2 "D"[FA]4 |')
        target = make_target(value, review.curriculum(), {'provider': 'synthetic-test'})
        self.assertEqual(target['material']['chords'], 'D → G → D')
        validate_target(target)

    def test_translation_preserves_abc_and_claims(self):
        value = abc_result(2, 3)
        target = make_target(value, review.curriculum(), {'provider': 'synthetic-test'})
        context, _ = translation_input(target, 'ko', 'en')
        self.assertFalse(any('abc' in key for key in context['strings']))
        translated = translated_target(target, 'ko', 'en', {'strings': {k:'번역: '+v for k,v in context['strings'].items()}})
        self.assertEqual(translated['exercise']['notation'], target['exercise']['notation'])
        self.assertEqual(translated['music_claims'], target['music_claims'])
        self.assertEqual(target['difficulty']['features']['beats_per_bar'], 3)
        self.assertIn('exercise.development.expression', prose_fields(value))

    def test_legacy_contract_is_still_unchanged(self):
        value = result()
        target = make_target(value, review.curriculum(), {'provider':'synthetic-test'})
        validate_target(target)
        self.assertEqual(result_from_target(target), value)
        self.assertNotIn('notation_identity', target)
