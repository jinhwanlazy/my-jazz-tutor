"""Render all synthetic coaching comparison runs, including failed attempts.

Development artifact only. Requires an explicit experiment directory containing
protocol.json and runs/. This never reads the production workspace or starts a
model. The generated HTML and public-source image crops belong under build/.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from abc_score import parse_score, playback_for
from difficulty import abc_features


def load(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def run(root, name, review):
    folder = root / 'runs' / name
    summary = load(folder / 'summary.json', {'state': 'not_finished', 'error': None})
    artifact = load(folder / 'artifact.json', {})
    target = load(folder / 'target.json')
    result = {'name': name, 'summary': summary, 'review': review.get('runs', {}).get(name),
              'provenance': artifact.get('provenance', {}), 'target': target, 'stage': artifact.get('stage'),
              'plan': artifact.get('context', {}).get('preparation', {}).get('goal_plan'),
              'materials': artifact.get('context', {}).get('preparation', {}).get('materials', []),
              'material_failures': artifact.get('context', {}).get('preparation', {}).get('material_failures', []),
              'attempts': [{k: a.get(k) for k in ('phase', 'error_code', 'validation_error', 'provenance') if k in a} for a in artifact.get('attempts', [])]}
    # The packet has already served its purpose. Do not embed downloaded full
    # text, page images or every example in each recommendation's HTML payload.
    result['materials'] = [{k: m.get(k) for k in ('excerpt_id', 'source', 'locator', 'retrieval', 'example_fit')} for m in result['materials']]
    if target:
        e = target['exercise']
        result['facts'] = abc_features(e, {}) if e.get('notation') else None
        if e.get('notation'):
            parsed = parse_score(e['notation'])
            result['playback'] = playback_for(e['notation'])
            result['facts']['notation_sha256'] = parsed['sha256']
            result['facts']['rhythm_signature'] = hashlib.sha256(json.dumps(
                [(v['voice'], v['bar'], v['beat_fraction'], v['duration_fraction'], bool(v['notes'])) for v in parsed['events']],
                sort_keys=True).encode()).hexdigest()
        originals = [r for r in target.get('source_references', []) if r['mode'] == 'source_original' and r['role'] == 'exercise_source']
        result['reuse_checks'] = []
        for reference in originals:
            example_id = reference.get('example_id')
            example = load(root / 'materials' / 'examples' / (str(example_id) + '.json'))
            result['reuse_checks'].append({'example_id': example_id, 'unchanged_abc': bool(example and example['notation'] == e['notation'])})
    return result


def gallery(root):
    import pypdfium2
    sources = load(root / 'library-new.json', [])
    output = root / 'report' / 'source-images'
    output.mkdir(parents=True, exist_ok=True)
    for item in sources:
        with pypdfium2.PdfDocument(root / 'materials' / 'objects' / item['review']['source_sha256'] / 'original') as pdf:
            image = pdf[item['page'] - 1].render(scale=3).to_pil()
            width, height = image.size
            crop = tuple(round(v * (width if i % 2 == 0 else height)) for i, v in enumerate(item['crop']))
            image.crop(crop).save(output / (item['slug'] + '.png'))
        item['playback'] = playback_for(item['notation'])
        item.pop('event_table', None)
    return sources


HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Coaching consistency · side-by-side review</title><style>
*{box-sizing:border-box}body{margin:0;background:#f2f4f1;color:#172b25;font:16px/1.6 system-ui,sans-serif}main{max-width:1680px;margin:auto;padding:30px 28px 80px}h1{font-size:32px;line-height:1.2;margin:8px 0 18px}h2{font-size:23px;line-height:1.35;margin:9px 0}h3{font-size:16px;margin:22px 0 7px}p{margin:8px 0}a{color:#135c62}.muted{color:#57675f}.eyebrow{font-weight:650;color:#226449}.notice{padding:14px 18px;background:#fff5db;border-left:4px solid #a66a17}.summary{padding:18px 22px;background:#e5efe8;border-radius:8px;margin:20px 0}.summary ul{margin:8px 0;padding-left:22px}.selectors{display:flex;gap:14px;flex-wrap:wrap;align-items:center;margin:26px 0 16px}select,button{font:inherit;color:inherit;background:white;border:1px solid #afbeb5;border-radius:6px;padding:9px 12px}button{cursor:pointer}button:disabled{cursor:default;opacity:.5}button:hover:not(:disabled){background:#e7f1ea}.context{background:#e9edef;padding:14px 20px;border-radius:8px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:20px;align-items:start;margin:20px 0}.card{background:white;padding:24px;border:1px solid #d2dbd5;border-radius:10px;min-width:0}.version{font-size:14px;font-weight:700;color:#356351}.tags{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}.tag{font-size:13px;border-radius:16px;background:#e8f0eb;padding:3px 10px}.bad{background:#ffe6e2;color:#8a2313}.score{background:#fcfcf8;overflow:auto;min-height:100px;margin-top:16px}.score svg{max-width:100%}.audio{display:flex;gap:10px;margin:12px 0 6px}.review{padding:12px 16px;background:#f0f3f9;border-left:3px solid #516a93;margin:18px 0}.findings{padding-left:20px}.facts{font-size:14px;display:flex;gap:12px;flex-wrap:wrap}.table-wrap{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px;text-align:left}th,td{padding:10px 12px;border-bottom:1px solid #d2dbd5;vertical-align:top}th{background:#e8eeea}tr[data-select]{cursor:pointer}tr[data-select]:hover{background:#e5efe9}details{margin:18px 0}summary{cursor:pointer;font-weight:600}pre{font:13px/1.6 ui-monospace,monospace;white-space:pre-wrap;overflow-wrap:anywhere}.source-img{display:block;width:100%;height:auto;margin:16px 0}.source-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}.source-section{background:white;border:1px solid #d2dbd5;border-radius:10px;padding:22px;margin:22px 0}.source-section h2{font-size:20px}.source-meta{font-size:14px}.empty{padding:20px;background:#fff2ef}.links{display:flex;gap:20px;flex-wrap:wrap;margin:14px 0}.feedback{padding:20px;background:#e5efe8;border-radius:8px}.feedback li{margin:6px 0}ol{padding-left:23px}
@media(max-width:900px){main{padding:18px 14px}.comparison-scroll{overflow-x:auto}.pair{min-width:1000px}.source-grid{grid-template-columns:1fr}h1{font-size:26px}.card{padding:18px}}
</style></head><body><main>
<div class="eyebrow">Development comparison · production remains on v0.5.0</div>
<h1>Does the coach keep making useful musical choices?</h1>
<p class="muted">Three synthetic histories, two independent runs per history, compared side by side. Requested model: Sol, high reasoning. Both versions receive the same public material cache.</p>
<p class="notice">This is an exploratory comparison, not proof of long-term improvement. The histories contain subjective feedback and no verified playing accuracy. The baseline is v0.5.0, which already has the revised coaching prompt; the development version adds reviewed-example retrieval and fit checks.</p>
<div class="links"><a href="#all-runs">All attempts</a><a href="#sources">New source excerpts</a><a href="#protocol">Protocol and limitations</a><a href="#feedback">What to review</a></div>
<div id="overview" class="summary"></div>
<div class="selectors"><label for="case">Compare:</label><select id="case"></select><button id="previous" type="button">Previous</button><button id="next" type="button">Next</button><button id="jump-score" type="button">Jump to scores</button></div>
<section class="context" id="context"></section>
<p class="muted">On a narrow screen, scroll the comparison horizontally to keep both versions next to each other.</p>
<div class="comparison-scroll"><div class="pair"><article class="card" id="baseline"></article><article class="card" id="candidate"></article></div></div>
<section id="all-runs"><h2>All attempts</h2><p class="muted">Click a row to open that pair. Failures and validator repairs remain in the report.</p><div class="table-wrap" id="run-table"></div></section>
<section id="sources"><h2>New reviewed source excerpts</h2><p class="muted">Public sources, cached locally. Visual checks were assisted by Codex and a separate note/timing table; they are not independent expert certification. These excerpts expand the references, not a required exercise sequence.</p><div id="gallery"></div></section>
<details id="retrieval"><summary>Targeted retrieval probes and source-review correction</summary><p class="muted">These are five directed queries for known local examples, plus a no-match and source-budget probe. They are not a held-out retrieval benchmark.</p><pre id="retrieval-json"></pre></details>
<details id="protocol"><summary>Experiment protocol, evidence and limitations</summary><pre id="protocol-json"></pre></details>
<section id="feedback" class="feedback"><h2>What to review</h2><ol><li>Which exercise feels more worth playing, and why?</li><li>Does the challenge fit the feedback, or is it too cautious or overloaded?</li><li>Do the melody, rests and accents sound like a coherent phrase?</li><li>Do the two runs reveal useful variety, or the same idea with different wording?</li></ol><p>Refer to the case and run number. Nothing on this page creates a personal practice item or changes the active release.</p></section>
</main><script src="abcjs.js"></script><script>
const data=PAYLOAD;
function el(tag,text,parent,cls){const n=document.createElement(tag);if(text!==null&&text!==undefined)n.textContent=text;if(cls)n.className=cls;parent.append(n);return n;}
function section(root,title,text){if(!text)return;el('h3',title,root);el('p',text,root);}
function bullets(root,items){const list=el('ul',null,root,'findings');for(const item of items||[])el('li',item,list);}
let audio=null;function stop(){if(audio){audio.close();audio=null;}}
function play(playback,bpm=72){stop();if(!playback)return;const ctx=new AudioContext();audio=ctx;const unit=60/bpm,start=ctx.currentTime+.12;let last=0;for(const e of playback.events){const osc=ctx.createOscillator(),gain=ctx.createGain();osc.type='triangle';osc.frequency.value=440*2**((e.pitch-69)/12);const at=start+e.start*unit,end=at+e.duration*unit,level=e.voice.startsWith('LH')?.035:.06;gain.gain.setValueAtTime(0,at);gain.gain.linearRampToValueAtTime(level,at+.012);gain.gain.setValueAtTime(level,Math.max(at+.013,end-.06));gain.gain.linearRampToValueAtTime(0,end);osc.connect(gain).connect(ctx.destination);osc.start(at);osc.stop(end+.01);last=Math.max(last,end);}setTimeout(()=>{if(audio===ctx)stop();},Math.max(0,(last-ctx.currentTime+.2)*1000));}
function controls(root,playback,bpm){const row=el('div',null,root,'audio');const b=el('button','Play written notes',row);b.disabled=!playback;b.onclick=()=>play(playback,bpm);el('button','Stop',row).onclick=stop;el('p','Straight-time synthetic preview; swing, articulation and touch are not evaluated by this audio.',root,'muted');}
function score(root,notation,bars){const target=el('div',null,root,'score');if(notation){try{const tunes=ABCJS.renderAbc(target,notation.abc,{responsive:'resize',staffwidth:620,lineBreaks:[Array.from({length:Math.max(0,Math.ceil(bars/4)-1)},(_,i)=>4*(i+1)-1)],add_classes:true});target.dataset.warnings=JSON.stringify(tunes.flatMap(t=>t.warnings||[]));}catch(e){el('p','Rendering error: '+e.message,target,'bad');}}else el('p','No fixed score was supplied.',target);return target;}
function render(root,run,version){root.replaceChildren();el('div',version,root,'version');if(!run.target){el('h2','Recommendation unavailable',root);el('p',run.summary.state+(run.summary.error?' · '+run.summary.error:''),root,'empty');if(run.summary.error==='timeout')el('p','The '+(run.stage||'generation')+' stage exceeded its time limit. No practice was saved.',root);if(run.summary.message)el('p',String(run.summary.message),root);if(run.summary.validation_errors?.length)bullets(root,run.summary.validation_errors);details(root,run);return;}
 const t=run.target,e=t.exercise,refs=t.source_references||[];el('h2',e.title,root);const tags=el('div',null,root,'tags');for(const label of [e.bars+' bars',e.key,e.bpm+' BPM setting',e.minutes+' min suggested'])el('span',label,tags,'tag');const source=refs.find(r=>r.role==='exercise_source');el('span',source?.mode==='source_original'?'Reviewed source reused':source?.mode==='source_adapted'?'Disclosed source adaptation':'Newly composed score',tags,'tag');if(run.summary.validation_errors?.length)el('span','Validator repair needed',tags,'tag bad');section(root,'Goal',e.objective);section(root,'Why this practice',e.selection_reason);
 const scoreArea=score(root,e.notation,e.bars);scoreArea.dataset.main='true';controls(root,run.playback,e.bpm);section(root,'Right hand',e.right_hand);section(root,'Left hand',e.left_hand);section(root,'Rhythm',e.rhythm);section(root,'Expression',e.development?.expression);section(root,'Application',e.development?.application);section(root,'What changes from recent practice',e.development?.difference_from_recent);
 if(run.review){const r=el('div',null,root,'review');el('strong','Review assessment · interpretive',r);bullets(r,run.review.findings||[]);}
 if(run.facts){el('h3','Computed score facts',root);const facts=el('div',null,root,'facts');for(const [name,hand] of [['RH','right'],['LH','left']]){const f=run.facts.hands[hand];el('span',`${name}: ${f.onsets} attacks · ${f.offbeat_onsets} offbeats · ${f.rhythm_patterns} rhythm patterns`,facts);}el('p','These describe the assigned score, not the learner’s ability or playing accuracy.',root,'muted');}
 const steps=el('details',null,root);el('summary','Practice steps',steps);const list=el('ol',null,steps);for(const text of e.steps)el('li',text,list);el('p',e.instructions,steps);
 el('h3','Sources and scope',root);if(!refs.length)el('p','No source cited.',root);for(const r of refs){const p=el('p',null,root),link=el('a',r.source.author+' · '+r.source.title,p);link.href=r.source.url+(r.locator.page?'#page='+r.locator.page:'');link.target='_blank';link.rel='noreferrer';el('p',r.locator.label+' · '+r.mode+' · '+r.role,root,'source-meta');if(r.source_excerpt)el('p',r.source_excerpt,root);if(r.changes?.length)bullets(root,r.changes);}
 const analysis=el('details',null,root);el('summary','Evidence, interpretation and unknowns',analysis);for(const item of t.analysis.evidence){el('p',item.interpretation,analysis);el('p',item.source_ids.join(', ')+' · confidence '+item.confidence,analysis,'muted');}bullets(analysis,t.analysis.unknowns);details(root,run);
}
function details(root,run){const d=el('details',null,root);el('summary','Generation and validation details',d);el('pre',JSON.stringify({state:run.summary.state,error:run.summary.error,elapsed_seconds:run.summary.elapsed_seconds,requested_model:run.provenance.requested_model,requested_reasoning_effort:run.provenance.requested_reasoning_effort,validation_errors:run.summary.validation_errors,attempts:run.attempts,plan:run.plan,retrieved:run.materials,material_failures:run.material_failures,reuse_checks:run.reuse_checks,score_facts:run.facts},null,2),d);}
function choose(index){stop();document.querySelector('#case').value=index;document.querySelector('#previous').disabled=index===0;document.querySelector('#next').disabled=index===data.pairs.length-1;const p=data.pairs[index],c=document.querySelector('#context');c.replaceChildren();el('strong',p.label+' · independent run '+p.replicate,c);el('p',p.scenario_spec.notes.at(-1),c);if(p.scenario_spec.skip_reason)el('p',p.scenario_spec.skip_reason,c);el('p','Review criterion: '+p.scenario_spec.expectation,c,'muted');render(document.querySelector('#baseline'),p.baseline,'v0.5.0 · baseline');render(document.querySelector('#candidate'),p.candidate,'v0.6.0 development · reviewed-example retrieval');const scores=[...document.querySelectorAll('.pair .score[data-main]')];if(scores.length===2){const top=Math.max(...scores.map(s=>s.getBoundingClientRect().top));for(const s of scores)s.style.marginTop=(16+top-s.getBoundingClientRect().top)+'px';}}
const names={too_easy:'Too easy',challenging:'Challenging but useful',bored_skip:'Skipped because of repetition'};
for(const [i,p] of data.pairs.entries()){p.label=names[p.scenario];el('option',p.label+' · run '+p.replicate,document.querySelector('#case')).value=i;}
document.querySelector('#case').onchange=e=>choose(Number(e.target.value));document.querySelector('#previous').onclick=()=>choose(Number(document.querySelector('#case').value)-1);document.querySelector('#next').onclick=()=>choose(Number(document.querySelector('#case').value)+1);
document.querySelector('#jump-score').onclick=()=>document.querySelector('.pair .score')?.scrollIntoView({behavior:'smooth',block:'start'});
const all=data.pairs.flatMap(p=>[p.baseline,p.candidate]),done=all.filter(r=>r.summary.state==='completed');const overview=document.querySelector('#overview');el('strong',`${done.length} of ${all.length} recommendations completed validation.`,overview);if(data.review?.summary)bullets(overview,data.review.summary);else el('p','Results are awaiting interpretive review.',overview);
const table=el('table',null,document.querySelector('#run-table')),head=el('tr',null,el('thead',null,table));for(const text of ['Case / run','Version','State','Bars / BPM','Exercise','Repair'])el('th',text,head);const body=el('tbody',null,table);for(const [i,p] of data.pairs.entries())for(const version of ['baseline','candidate']){const r=p[version],row=el('tr',null,body),e=r.target?.exercise;row.dataset.select=i;row.tabIndex=0;row.onclick=()=>{choose(i);document.querySelector('#case').scrollIntoView({behavior:'smooth',block:'start'});};row.onkeydown=ev=>{if(ev.key==='Enter')row.click();};for(const text of [p.label+' / '+p.replicate,version,r.summary.state+(r.summary.error?' · '+r.summary.error:''),e?e.bars+' / '+e.bpm:'—',e?.title||'No saved task',r.summary.validation_errors?.length?'Yes':'No'])el('td',text,row);}
const gal=document.querySelector('#gallery');for(const s of data.library){const block=el('article',null,gal,'source-section');el('h2',s.notation.abc.split('\n').find(l=>l.startsWith('T:')).slice(2),block);el('p',s.review.scope,block);const p=el('p',null,block,'source-meta'),a=el('a',s.source.publisher+' · '+s.source.title,p);a.href=s.source.url+'#page='+s.page;a.target='_blank';a.rel='noreferrer';const grid=el('div',null,block,'source-grid'),left=el('div',null,grid),right=el('div',null,grid);el('strong','Published source crop',left);const img=el('img',null,left,'source-img');img.src='source-images/'+s.slug+'.png';img.alt=s.review.scope;el('strong','Reviewed ABC transcription',right);score(right,s.notation,s.bars);controls(right,s.playback,72);section(block,'Review and normalization',s.review.notes);const d=el('details',null,block);el('summary','Provenance',d);el('pre',JSON.stringify({example_id:s.example_id,source_sha256:s.review.source_sha256,reviewer:s.review.reviewer,checked:s.review.checked},null,2),d);}
document.querySelector('#protocol-json').textContent=JSON.stringify(data.protocol,null,2);document.querySelector('#retrieval-json').textContent=JSON.stringify({probes:data.retrieval,source_review_correction:data.source_correction},null,2);choose(0);window.addEventListener('beforeunload',stop);
</script></body></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment', type=Path, required=True)
    args = parser.parse_args()
    root = args.experiment.resolve()
    production = (Path(__file__).resolve().parents[2] / 'practice').resolve()
    if (root == production or production in root.parents or
            any((root / f).exists() for f in ('profile.json', 'practice.csv', 'sessions.sqlite3'))):
        parser.error('A production practice directory is not a comparison experiment.')
    protocol = load(root / 'protocol.json')
    if not protocol:
        parser.error('Missing experiment protocol.')
    review = load(root / 'review.json', {})
    pairs = []
    from coaching_consistency import SCENARIOS
    for scenario in protocol['scenarios']:
        for replicate in range(1, protocol['replicates_per_scenario'] + 1):
            pairs.append({'scenario': scenario, 'replicate': replicate, 'scenario_spec': SCENARIOS[scenario],
                          **{v: run(root, f'{scenario}-{replicate}-{v}', review) for v in ('baseline', 'candidate')}})
    library = gallery(root)
    payload = {'pairs': pairs, 'library': library, 'protocol': protocol, 'review': review,
               'source_correction': load(root / 'library-correction.json'),
               'retrieval': {v: load(root / f'retrieval-{v}.json') for v in ('baseline', 'candidate')}}
    output = root / 'report'
    output.mkdir(exist_ok=True)
    shutil.copyfile(Path(__file__).resolve().parents[1] / 'abcjs.min.js', output / 'abcjs.js')
    (output / 'comparison-data.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    (output / 'index.html').write_text(HTML.replace('PAYLOAD', json.dumps(payload, ensure_ascii=False).replace('<', '\\u003c')))
    print(output / 'index.html')


if __name__ == '__main__':
    main()
