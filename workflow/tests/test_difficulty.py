"""Calibration boundaries and bounded history, using synthetic temporary ledgers."""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

import coaching_context as cc
import difficulty as d
import localization as loc
import recommendation as rec
import review as r
from recommendation_fixture import result, SyntheticTranslator


def legacy_result():
    value = result()
    value['schema_version'] = 1
    value.pop('difficulty')
    return value


def synthetic_events(count, note_length=0):
    data = r.curriculum()
    target = rec.make_target(result(), data, {'source_language': 'en'})
    snapshot = r.jdump(target)
    events = []
    for i in range(count):
        day = datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(days=i)
        tid = 'T-' + f'{i:010x}'
        a = r.new_event('assigned', tid, data, target['exercise_id'])
        a.update(recorded_at=day.isoformat(), target_json=snapshot)
        report = r.new_event('reported', tid, data, target['exercise_id'])
        report.update(recorded_at=(day+timedelta(hours=1)).isoformat(), practice_date=day.date().isoformat(),
                      actual_json='{}', checks_json='{}', difficulty=('good','challenging','too_easy','impossible')[i%4],
                      raw_note='Synthetic note ' + str(i) + ' ' + 'a' * note_length)
        events.extend((a, report))
    return events


class DifficultyTests(unittest.TestCase):
    def test_non_object_output_is_a_validation_failure(self):
        for bad in (None, [], 'invalid', 1):
            with self.assertRaises(ValueError):rec.validate_result(bad)

    def test_quoted_old_note_can_be_cited_but_a_bare_example_id_cannot(self):
        context={'sources':[{'id':'profile'}, {'id':'history-summary','data':{
            'latest_reported_excerpts_per_label_or_skip_reason':[{'source_id':'event:quoted','text':'Synthetic old note'}],
            'feedback_example_event_ids':{'good':['event:bare']}}}]}
        value=result();value['evidence'][0]['source_ids']=['event:quoted']
        value['difficulty']['prediction']['source_ids']=['event:quoted']
        rec.validate_result(value,context)
        value['evidence'][0]['source_ids']=['event:bare']
        with self.assertRaises(ValueError):rec.validate_result(value,context)

    def test_v1_snapshots_stay_identical_and_v2_requires_all_axes(self):
        target = rec.make_target(legacy_result(), r.curriculum(), {})
        before = r.jdump(target)
        rec.validate_target(target)
        self.assertEqual(r.jdump(target), before)
        self.assertNotIn('difficulty', target)
        with tempfile.TemporaryDirectory() as directory:
            context = rec.context_for(Path(directory), r.curriculum())
            with self.assertRaisesRegex(ValueError, 'require'):
                rec.validate_result(legacy_result(), context)
        bad = result(); bad['difficulty']['axes'].pop('rhythm')
        with self.assertRaises(ValueError): rec.validate_result(bad)

    def test_anchor_level_axis_and_provenance_are_validated(self):
        mutations = [lambda x: x['axes']['rhythm'].update(anchor_ids=['melody-1']),
                     lambda x: x['axes']['rhythm'].update(level=3),
                     lambda x: x['axes']['rhythm'].update(status='unknown'),
                     lambda x: x.update(rubric_version='invented'),
                     lambda x: x['prediction'].update(source_ids=['event:invented']),
                     lambda x: x['prediction'].update(burden='workable', source_ids=[]),
                     lambda x: x.update(focus_axes=['rhythm','rhythm'])]
        for change in mutations:
            value = result(); change(value['difficulty'])
            with self.subTest(value=value['difficulty']), self.assertRaises(ValueError):
                rec.validate_result(value, {'sources': [{'id':'profile'}]})
        value = result(); value['difficulty']['axes']['rhythm'].update(status='unknown', level=None, anchor_ids=[])
        rec.validate_result(value)

    def test_score_facts_ignore_title_language_and_scale_only_tempo_dependent_values(self):
        exercise = result()['exercise']; original = d.score_features(exercise)
        changed = copy.deepcopy(exercise)
        changed.update(title='다른 이름', instructions='같은 악보의 번역')
        self.assertEqual(d.score_features(changed), original)
        changed['bpm'] *= 2
        faster = d.score_features(changed)
        for hand in ('left','right'):
            a,b = original['hands'][hand], faster['hands'][hand]
            self.assertAlmostEqual(b['onsets_per_second_at_target'], 2*a['onsets_per_second_at_target'])
            self.assertEqual({k:v for k,v in a.items() if k != 'onsets_per_second_at_target'},
                             {k:v for k,v in b.items() if k != 'onsets_per_second_at_target'})
        self.assertEqual(original['hands']['right']['max_simultaneous_notes'], 2)
        self.assertEqual(original['nonshared_onsets'], 0)

    def test_rhythm_benchmarks_have_expected_facts_without_treating_them_as_ability(self):
        e = result()['exercise']; e.update(bars=1, bpm=80, accompaniment=None)
        rest = [{'beat':0,'duration':4,'notes':[]}]
        for durations, expected_onsets, expected_offbeat in [([1]*4,4,0),([.5]*8,8,4)]:
            beat=0; events=[]
            for duration in durations:
                events.append({'beat':beat,'duration':duration,'notes':['C4']});beat+=duration
            e['notation']={'beats_per_bar':4,'bars':[{'chord':'C','left':rest,'right':events}]}
            f=d.score_features(e)['hands']['right']
            self.assertEqual(f['onsets'],expected_onsets);self.assertEqual(f['offbeat_onsets'],expected_offbeat)
        e['notation']=None
        self.assertEqual(d.score_features(e), {'available':False,'source':'assigned_notation','metronome_target_bpm':80,'bars':1})

    def test_translation_cannot_recalibrate_levels_anchors_features_or_prediction(self):
        target = rec.make_target(result(),r.curriculum(),{'source_language':'en'})
        context,_ = loc.translation_input(target,'ko','en')
        translated,_ = SyntheticTranslator().translate(context,loc.output_schema(context))
        localized = loc.translated_target(target,'ko','en',translated)
        for axis in d.AXES:
            for field in ('status','level','anchor_ids'):
                self.assertEqual(localized['difficulty']['axes'][axis][field], target['difficulty']['axes'][axis][field])
            self.assertTrue(localized['difficulty']['axes'][axis]['reason'].startswith('번역: '))
        self.assertEqual(localized['difficulty']['features'],target['difficulty']['features'])
        self.assertEqual(localized['difficulty']['prediction']['burden'],target['difficulty']['prediction']['burden'])
        translated['strings']['difficulty.axes.rhythm.level']='3'
        with self.assertRaises(ValueError): loc.translated_target(target,'ko','en',translated)

    def test_feedback_and_corrections_do_not_rewrite_assignment_or_infer_axis_ability(self):
        events=synthetic_events(1); before=events[0]['target_json']
        task=r.records(events)[0]
        pair=d.prediction_observation(task)
        self.assertEqual(pair['meaning'],'reported_utility_burden_unknown')
        self.assertNotIn('score',pair)
        correction=copy.deepcopy(events[-1]);correction.update(event_id='new-correction',event_type='corrected',
            difficulty='impossible',supersedes=events[-1]['event_id'],raw_note='Synthetic correction')
        task=r.records(events+[correction])[0]
        self.assertEqual(d.prediction_observation(task)['meaning'],'reported_overload')
        self.assertEqual(task['assignment']['target_json'],before)
        summary=cc.summary([task],events+[correction])['data']
        self.assertEqual(summary['latest_feedback_counts'],{'impossible':1})
        self.assertNotIn('good',summary['feedback_example_event_ids'])

    def test_tampered_derived_facts_are_rejected(self):
        target=rec.make_target(result(),r.curriculum(),{})
        target['difficulty']['features']['hands']['right']['onsets']=1000
        with self.assertRaisesRegex(ValueError,'differs'):rec.validate_target(target)


class BoundedContextTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.data=r.curriculum()

    def write(self,events):
        for event in events:r.append_event(self.root,event)

    def test_thousand_records_and_long_notes_are_bounded_and_originals_untouched(self):
        self.write(synthetic_events(1000,1500))
        before=(self.root/'practice.csv').read_bytes()
        context=rec.context_for(self.root,self.data,request='Synthetic request')
        size=len(rec.prompt_for(context).encode())+len(r.jdump(rec.SCHEMA).encode())
        self.assertLessEqual(size,rec.INPUT_BUDGET)
        self.assertLessEqual(context['history_window']['included_tasks'],12)
        self.assertGreater(context['history_window']['included_tasks'],0)
        self.assertEqual(context['history_window']['total_tasks'],1000)
        self.assertIn('omitted_characters',r.jdump(context))
        self.assertNotIn('"notation":',r.jdump(context['sources']))
        self.assertEqual((self.root/'practice.csv').read_bytes(),before)
        facts=next(s for s in context['sources'] if s['id']=='history-summary')['data']
        self.assertEqual(facts['latest_feedback_counts']['good'],250)

    def test_relevant_old_note_and_recent_correction_are_retrieved_with_sources(self):
        events=synthetic_events(30)
        events[1]['raw_note']='Synthetic specific request: lydian colors.'
        correction=copy.deepcopy(events[3]);correction.update(event_id='corrected-old',event_type='corrected',
            supersedes=events[3]['event_id'],raw_note='Synthetic newly corrected note',
            recorded_at=datetime.now(timezone.utc).isoformat())
        self.write(events+[correction])
        context=rec.context_for(self.root,self.data,request='lydian')
        refs={s['id'] for s in context['sources']}
        self.assertIn('event:'+events[1]['event_id'],refs)
        self.assertIn('event:corrected-old',refs)
        self.assertNotIn('event:'+events[3]['event_id'],refs)

    def test_summary_rebuild_and_fingerprint_follow_corrections_to_omitted_history(self):
        events=synthetic_events(25);self.write(events)
        old=rec.context_for(self.root,self.data)
        correction=copy.deepcopy(events[1]);correction.update(event_id='correction',event_type='corrected',
            supersedes=events[1]['event_id'],difficulty='too_easy',raw_note='Synthetic revised note')
        r.append_event(self.root,correction)
        new=rec.context_for(self.root,self.data)
        self.assertNotEqual(old['fingerprint'],new['fingerprint'])
        counts=next(s for s in new['sources'] if s['id']=='history-summary')['data']['latest_feedback_counts']
        self.assertEqual(counts['good'],6);self.assertEqual(counts['too_easy'],7)

    def test_huge_profile_fails_without_dropping_current_request(self):
        (self.root/'profile.json').write_text(json.dumps({'goal':'x'*100000}))
        with self.assertRaises(rec.RecommendationError) as error:rec.context_for(self.root,self.data,request='Keep this request')
        self.assertEqual(error.exception.code,'context')

    def test_context_is_deterministic_and_legacy_history_is_not_given_new_ratings(self):
        target=rec.make_target(legacy_result(),self.data,{})
        e=r.new_event('assigned','T-'+'a'*10,self.data,target['exercise_id']);e['target_json']=r.jdump(target)
        self.write([e])
        a=rec.context_for(self.root,self.data);b=rec.context_for(self.root,self.data)
        self.assertEqual(a,b)
        item=next(s for s in a['sources'] if s['kind']=='assigned_conditions')
        self.assertNotIn('assigned_demand_assessment',item['data']['conditions'])
        self.assertNotIn('difficulty',r.records(r.read_events(self.root))[0]['target'])


if __name__ == '__main__':unittest.main()
