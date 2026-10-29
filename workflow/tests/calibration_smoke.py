"""Opt-in model regression check on synthetic, fixed music; no practice records.

This checks reproducibility and ordinal comparisons, not empirical validity.
It intentionally lives outside unittest discovery and consumes Codex allowance.
"""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import difficulty as d
import recommendation as rec
from recommendation_fixture import result


def exercise(offbeat=False):
    e=result()['exercise']
    e.update(title='Synthetic rhythm reference', section='Original four bars', key='C', bpm=80, bars=4,
             objective='Maintain the written rhythm on a single pitch.', selection_reason='Synthetic calibration test.',
             left_hand='Rest throughout.',right_hand='Play C4 at the written onsets.',
             notes='C4 only.',rhythm='Even eighth notes and rests in changing patterns.' if offbeat else 'Quarter notes on each beat.',
             instructions='Play the written pattern evenly at mezzo-forte without additional accents.',
             steps=['Play the four-bar phrase at the assigned tempo.'],accompaniment=None)
    bars=[]
    for i in range(4):
        # A variation not copied verbatim from the anchor miniature.
        mask=([False,True,False,True,True,True,False,True] if i%2 else
              [True,False,True,True,False,True,False,True]) if offbeat else [True]*4
        duration=.5 if offbeat else 1
        bars.append({'chord':'C','left':[{'beat':0,'duration':4,'notes':[]}],
                     'right':[{'beat':j*duration,'duration':duration,'notes':['C4'] if sound else []} for j,sound in enumerate(mask)]})
    e['notation']={'beats_per_bar':4,'bars':bars}
    return e


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',action='store_true');args=parser.parse_args()
    if not args.run:parser.error('Use --run to enable the real connection test.')
    schema=rec.SCHEMA['properties']['difficulty']
    cases=[('quarter_en',exercise()),('quarter_reworded',exercise()),('changing_offbeats',exercise(True))]
    cases[1][1].update(title='합성 리듬 비교',instructions='추가 강세 없이 고른 메조포르테로 쓰인 패턴을 연주한다.')
    outputs=[];started=time.monotonic()
    output_path=Path(__file__).resolve().parents[1]/'build/calibration-smoke.json'
    output_path.parent.mkdir(exist_ok=True)
    for name,e in cases:
        context={'rubric':d.RUBRIC,'exercise':e,'computed_features':d.score_features(e),
                 'sources':[{'id':'profile','kind':'synthetic_profile','data':{'evidence':'No individual practice history is supplied.'}}]}
        prompt=('Assess only the supplied fixed piano exercise using the supplied rubric. Do not generate or change music. '
                'Do not use tools or read/write files. No previous conversation is shared. Return the assessment schema in English. '
                'Compare each axis to the rubric anchors at the assigned tempo and cite the corresponding anchor IDs. '
                'Use null levels for unknown/inapplicable/out-of-range axes. Personal burden must be unknown without learner evidence. '
                'Wording and display language do not change musical demands. This is a synthetic regression test, not observed ability.\n'
                +json.dumps(context,ensure_ascii=False))
        def validate(value):
            rec.validate_shape(value,schema);d.validate(value,context)
        assessed,provenance=rec.CodexRunner().complete(prompt,schema,validate)
        outputs.append({'case':name,'assessment':assessed,'provenance':provenance})
        output_path.write_text(json.dumps({'results':outputs,'status':'running'},indent=2))
        print(json.dumps({'case':name,'levels':{k:a['level'] for k,a in assessed['axes'].items()}}),flush=True)
    a,b,c=[o['assessment'] for o in outputs]
    stable=all((a['axes'][k]['status'],a['axes'][k]['level'])==(b['axes'][k]['status'],b['axes'][k]['level']) for k in d.AXES)
    ordered=a['axes']['rhythm']['level']==1 and c['axes']['rhythm']['level'] in (2,3)
    unknown=all(o['assessment']['prediction']['burden']=='unknown' for o in outputs)
    summary={'passed':stable and ordered and unknown,'stable_under_rewording':stable,'rhythm_comparison_ordered':ordered,
             'no_invented_personal_burden':unknown,'seconds':round(time.monotonic()-started,1),
             'limitation':'Small synthetic regression check, not validated human difficulty or calibration accuracy.',
             'results':outputs}
    output_path.write_text(json.dumps(summary,indent=2))
    print(json.dumps({k:v for k,v in summary.items() if k!='results'},indent=2))
    if not summary['passed']:raise AssertionError('Calibration regression failed; inspect build/calibration-smoke.json')


if __name__=='__main__':main()
