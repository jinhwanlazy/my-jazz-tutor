// Optional browser integration check. Requires Playwright and Chrome; all records are temporary.
import assert from 'node:assert/strict';
import {spawn, execFileSync} from 'node:child_process';
import {once} from 'node:events';
import {mkdtemp, mkdir, readFile, rm, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const project = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const root = await mkdtemp(join(tmpdir(), 'jazz-browser-'));
await writeFile(join(root, 'profile.json'), '{"daily_minutes":30}');
await mkdir(join(project, 'build/browser'), {recursive:true});
const server = spawn('uv', ['run', 'python', 'tests/serve_browser.py', root], {cwd:project});
let browser;
try {
  const url = await new Promise((resolve, reject) => {
    let output='';
    const timeout=setTimeout(()=>reject(new Error('preview startup timed out')),10000);
    server.stdout.on('data', chunk => {output+=chunk;const match=output.match(/http:\/\/127\.0\.0\.1:\d+/);if(match){clearTimeout(timeout);resolve(match[0]);}});
    server.stderr.on('data',chunk=>process.stderr.write(chunk));
    server.on('exit',code=>{clearTimeout(timeout);reject(new Error(`preview exited ${code}`));});
  });
  browser = await chromium.launch({headless:true, ...(process.env.CHROME_EXECUTABLE ? {executablePath:process.env.CHROME_EXECUTABLE} : {}), args:['--no-sandbox']});
  const context=await browser.newContext({viewport:{width:1440,height:1080}});
  await context.addInitScript(() => {
    const port={id:'synthetic-test-input',name:'Synthetic test MIDI',manufacturer:'Browser test',state:'connected',type:'input',onmidimessage:null};
    const access={inputs:new Map([[port.id,port]]),onstatechange:null};
    window.sent=[];window.denyMidi=true;window.audioStarts=[];
    Object.defineProperty(navigator,'requestMIDIAccess',{configurable:true,value:async()=>{if(window.denyMidi) throw new Error('denied');return access;}});
    window.sendMidi = data => {const timeStamp=performance.now();window.sent.push({timeStamp,data});port.onmidimessage?.({data:Uint8Array.from(data),timeStamp});};
    const create=AudioContext.prototype.createOscillator;
    AudioContext.prototype.createOscillator=function(){
      const osc=create.call(this),start=osc.start.bind(osc);
      osc.start=time=>{window.audioStarts.push({time,frequency:osc.frequency.value});start(time);};
      return osc;
    };
  });
  const page=await context.newPage(), errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('dialog',dialog=>dialog.accept());
  const state=()=>page.evaluate(()=>fetch('/api/state').then(r=>r.json()));
  const visible=selector=>page.locator(selector).waitFor({state:'visible'});
  const hidden=selector=>page.locator(selector).waitFor({state:'hidden'});
  const changeLanguage = async language => {
    await page.locator('[data-view="settings"]').click();
    await page.locator('#language-select').selectOption(language);
    await page.waitForFunction(language => document.documentElement.lang === language &&
      document.querySelector('#connection').textContent === (language === 'ko' ? '로컬에 연결됨' : 'Connected locally'), language);
    await page.locator('#settings-back').click();
  };
  let loseAddResponse = true;
  const add = async () => {
    if (loseAddResponse) await page.route('**/api/recommend*', async route => { await route.fetch(); await route.abort(); });
    await page.locator('#new-practice').click();
    if (loseAddResponse) {
      await visible('#error');
      await page.unroute('**/api/recommend*');
      loseAddResponse=false;
    }
    await page.waitForFunction(()=>document.querySelector('#generation-panel').getAttribute('aria-busy')==='false' &&
      document.querySelector('#generation-title').textContent===(document.documentElement.lang==='ko' ? '새 연습이 목록에 추가됐어요.' : 'Your new practice is in the list.'));
    await visible('#view-list'); await hidden('#view-practice');
    const data=await state();
    assert.match(data.history[0].exercise_id,/^G-/);
    return data.history[0].id;
  };
  const item = id => page.locator(`.practice-item[data-task-id="${id}"]`);
  const enter = async id => {await item(id).locator('.history-item').click(); await visible('#view-practice');};
  const rate = async value => {
    await page.locator(`[data-rating="${value}"]`).click();
    await page.waitForFunction(value => document.querySelector(`[data-rating="${value}"]`).getAttribute('aria-pressed')==='true' && !document.querySelector(`[data-rating="${value}"]`).disabled, value);
  };
  await page.goto(url);
  await page.waitForFunction(()=>document.querySelector('#connection').textContent==='Connected locally');
  await visible('#view-list'); await hidden('#view-practice');
  assert.equal((await page.locator('[data-view="list"]').textContent()).trim(),'≡ Practice');
  await visible('.sidebar #midi-connect');await visible('.sidebar #midi-status');
  assert.equal((await state()).history.length,0);
  assert.equal(await page.locator('[data-view="history"], [data-view="progress"], #next-btn').count(),0);
  assert.doesNotMatch(await page.locator('body').innerText(),/[가-힣]/);
  await page.locator('.recommendation-focus summary').click();
  assert.ok(await page.evaluate(()=>{
    const focus=document.querySelector('#recommendation-focus').getBoundingClientRect();
    const button=document.querySelector('#new-practice').getBoundingClientRect();
    const filters=document.querySelector('.list-filters').getBoundingClientRect();
    return focus.bottom<=button.top && button.top-focus.bottom<30 && button.bottom<filters.top;
  }));
  await page.locator('#recommendation-request').fill('simulate:auth');
  await page.locator('#new-practice').click();
  await hidden('#recommendation-focus');
  await visible('#generation-panel');
  await page.waitForFunction(()=>document.querySelector('#generation-panel').getAttribute('aria-busy')==='true');
  assert.match(await page.locator('#generation-message').textContent(),/Your (?:requested )?focus is included/);
  await visible('#retry-recommendation');
  await visible('#recommendation-focus');
  assert.equal(await page.locator('#recommendation-request').inputValue(),'simulate:auth');
  assert.match(await page.locator('#generation-message').textContent(),/login/);
  assert.equal((await state()).history.length,0);
  await page.locator('#recommendation-request').fill('');
  const first=await add('E01');
  await visible('#recommendation-focus');
  assert.equal((await state()).sessions.length,0);
  await hidden('#view-practice');
  assert.match(await item(first).textContent(),/Ready to practice/);
  assert.deepEqual(await item(first).locator('.characteristic-chip').allTextContents(),
    ['Repeating left-hand rhythm', 'Notes played together', 'Hands enter together', 'Written expression']);
  assert.match(await item(first).locator('.burden-prediction').innerText(),/Not enough evidence/);
  assert.ok(await item(first).evaluate(card=>Math.abs(card.querySelector('h3').getBoundingClientRect().left-
    card.querySelector('.task-overview').getBoundingClientRect().left)<2));
  assert.equal(await item(first).locator('.demand-chip').count(),0);
  assert.equal(await page.locator('#new-practice').isEnabled(),true);
  await page.reload();await visible('#view-list');
  await page.waitForFunction(()=>document.querySelector('.history-item'));
  await hidden('#view-practice');
  assert.equal((await state()).history.length,1);
  await enter(first);
  assert.equal(await page.locator('#lesson-steps').isVisible(),false);
  await page.locator('#lesson-guide summary').click();
  assert.match(await page.locator('#lesson-steps').innerText(),/Play each hand separately/);
  await page.locator('#lesson-guide summary').click();
  for(const width of [320,390,768,1024,1440]){
    await page.setViewportSize({width,height:1000});
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    const layout=await page.evaluate(()=>{
      const rect=selector=>document.querySelector(selector).getBoundingClientRect();
      const player=rect('.score-card'),score=rect('#score-viewport'),controls=rect('.practice-controls');
      const buttons=['#practice-btn','#finish-btn','#tempo-down','#tempo-up'].map(rect);
      return {noOverflow:document.documentElement.scrollWidth<=innerWidth,
        controlsBeforeScore:controls.bottom<=score.top,
        buttonsFit:buttons.every(r=>r.left>=player.left&&r.right<=player.right&&r.height>=44),
        scoreHeight:rect('.practice-score').height};
    });
    assert.ok(layout.noOverflow,`page overflow at ${width}`);
    assert.ok(layout.controlsBeforeScore);
    assert.ok(layout.buttonsFit,`controls overflow at ${width}`);
    assert.ok(layout.scoreHeight<=321,`short score enlarged at ${width}`);
  }
  await page.setViewportSize({width:390,height:844});
  await page.locator('a[href="#practice-player"]').focus();
  await page.keyboard.press('Enter');
  assert.ok(await page.evaluate(()=>document.activeElement.id==='practice-player'&&
    document.querySelector('.score-card').getBoundingClientRect().top>=document.querySelector('.sidebar').getBoundingClientRect().bottom));
  await page.setViewportSize({width:1440,height:1080});
  assert.match(await page.locator('#lesson-overview').innerText(),/Not enough evidence/);
  assert.ok(await page.evaluate(()=>document.querySelector('#lesson-overview').getBoundingClientRect().bottom <=
    document.querySelector('#lesson-instructions').getBoundingClientRect().top));
  await page.locator('#lesson-overview .task-context-detail summary').click();
  assert.equal(await page.locator('#lesson-overview .characteristic-chip').count(),4);
  assert.match(await page.locator('#lesson-overview .task-context-detail').innerText(),/assigned task, not measured performance/);
  assert.match(await page.locator('#lesson-overview .task-parts').innerText(),/Hold D3/);
  assert.doesNotMatch(await page.locator('#lesson-overview').innerText(),/reference|[Ll]ow demand|[Hh]igh demand/);
  await page.locator('#lesson-overview .task-context-detail summary').click();
  assert.equal(await page.getByRole('button',{name:'Start attempt',exact:true}).count(),1);
  assert.equal(await page.getByRole('button',{name:'Complete practice',exact:true}).count(),1);
  assert.equal(await page.locator('#finish-btn').isEnabled(),false);
  assert.ok(await page.evaluate(()=>document.querySelector('.lesson-card').getBoundingClientRect().bottom<=document.querySelector('.score-card').getBoundingClientRect().top));
  assert.equal(await page.locator('.score-hand,.score-bar-number').count(),0);
  assert.ok(await page.locator('.abc-score .abcjs-note').count()>0);
  await page.evaluate(()=>document.fonts.load('40px Bravura'));
  const notationFixtures = JSON.parse(execFileSync('uv', ['run','python','-c', "import json,review;from notation import score_for;print(json.dumps({i:score_for(review.target_for(review.curriculum(),i,'Bb')) for i in ('E04','E06')}))"], {cwd:project}).toString());
  const displayChecks = await page.evaluate(async fixtures => {
    const {ScoreView} = await import('/score.mjs');

    const host = document.createElement('div'); host.style.width = '300px';
    const root = document.createElement('div'); root.className = 'score-viewport'; host.append(root);
    document.body.append(host);
    const follow = document.createElement('input'); follow.type = 'checkbox'; follow.checked = true;
    const status = document.createElement('span');
    const view = new ScoreView({root, status, follow});
    const score = id => fixtures[id];
    const at = (absolute, bars) => ({absolute, bar: Math.floor(absolute / 4) % bars, pass: Math.floor(absolute / (bars * 4)), beat: absolute % 4});
    view.setScore({...score('E06'),bars:score('E06').bars.slice(0,2)});
    const shortGlyphHeight=root.querySelector('.score-glyph').getBoundingClientRect().height;
    view.setScore(score('E04')); view.begin(); view.frame(at(8.1, 4));
    const hollowWhole = getComputedStyle(root.querySelector('.score-whole')).fill === 'none';
    view.midi([0x90, 50, 100], 'test', at(8.1, 4)); // D3 belongs to the right hand here.
    const low = root.querySelector('.score-live-note[data-midi="50"]');
    const lowRight = low.dataset.hand === 'right' && Boolean(low.querySelector('.score-input-head')) && !low.querySelector('.score-edge-note');
    const centerY = node => new DOMPoint(+node.getAttribute('cx'), +node.getAttribute('cy')).matrixTransform(node.getCTM()).y;
    const alignedY = Math.abs(centerY(low.querySelector('.score-input-head')) -
      centerY(root.querySelector('.score-target[data-bar="2"][data-hand="right"] [data-midi="50"] ellipse'))) < .001;
    view.setScore(score('E06')); view.begin();
    const consistentNoteSize=Math.abs(root.querySelector('.score-glyph').getBoundingClientRect().height-shortGlyphHeight)<.1;
    const canvas = root.querySelector('svg');
    const cursorX = () => view.cursor.transform.baseVal.consolidate().matrix.e;
    const positions = [];
    for (let beat = 0; beat <= 31.9; beat += .1) {
      view.frame(at(beat, 8)); positions.push({x: cursorX(), row: +view.cursor.dataset.system});
    }
    const continuous = positions.every((value, i) => !i ||
      (value.row !== positions[i - 1].row ? value.row === positions[i - 1].row + 1 && value.x < positions[i - 1].x :
       Math.abs(value.x - positions[i - 1].x - 5.2) < .001));
    const oneCanvas = canvas === root.querySelector('svg') && root.querySelectorAll('.score-chord').length === 8;
    view.begin(); view.frame(at(15.8, 8));
    const tailStart = cursorX();
    view.midi([0x90, 62, 100], 'test', at(15.8, 8));
    view.frame(at(16.2, 8)); view.midi([0x80, 62, 0], 'test', at(16.2, 8));
    const tails = [...root.querySelectorAll('.score-hold')];
    const wrappedTail = tails.length === 2 &&
      Math.abs(Number(tails[0].getAttribute('x1')) - tailStart) < .001 &&
      Math.abs(Number(tails[1].getAttribute('x2')) - cursorX()) < .001 &&
      Number(tails[1].getAttribute('y1')) > Number(tails[0].getAttribute('y1'));
    view.frame(at(20, 8));
    const followingScroll = window.scrollY;
    follow.checked = false; window.scrollTo(0, 0);
    view.frame(at(22, 8));
    const manualScroll = window.scrollY === 0 && followingScroll > 0;
    follow.checked = true;
    view.frame(at(31.8, 8));
    view.midi([0x90, 62, 100], 'test', at(31.8, 8));
    view.frame(at(32.2, 8)); view.drawNotes();
    const loop = /Pass 2/.test(status.textContent) && view.cursor.dataset.system === '0' && root.scrollLeft === 0;
    const continuedHold = Boolean(root.querySelector('.score-hold')) && !root.querySelector('.score-input-head');
    view.pause(at(32.4, 8));
    const interrupted = Boolean(root.querySelector('.score-hold.interrupted'));
    view.begin();
    const reset = root.querySelectorAll('.score-live-note').length === 0;
    view.frame(at(14, 8));
    const verticalFollow = window.scrollY > 0 && root.scrollWidth === root.clientWidth;
    host.style.width = '1200px'; view.setScore(score('E04')); view.begin(); view.frame(at(14, 4));
    const fittingScore = root.scrollLeft === 0 && root.scrollWidth === root.clientWidth;
    view.setScore(null); view.frame(at(15, 4));
    const fallback = !root.querySelector('svg') && root.textContent.includes('not available');
    view.resizeObserver.disconnect(); host.remove();
    return {hollowWhole, lowRight, alignedY, consistentNoteSize, continuous, oneCanvas, wrappedTail, manualScroll, loop, continuedHold, interrupted, reset, verticalFollow, fittingScore, fallback};
  }, notationFixtures);
  assert.ok(Object.values(displayChecks).every(Boolean), JSON.stringify(displayChecks));
  
  await page.locator('#midi-connect').click();
  assert.match(await page.locator('#midi-status').textContent(),/denied/);
  // Finite transport/analysis/recovery/replay integration is in attempts-browser.mjs.
  await page.evaluate(()=>window.denyMidi=false);
  await page.locator('#midi-connect').click();
  await page.locator('#tempo').fill('240');await page.locator('#tempo').dispatchEvent('change');
  await page.locator('#manual-mode').check();
  await page.locator('#practice-btn').click();
  await page.waitForFunction(()=>!document.querySelector('#finish-btn').disabled);
  await page.locator('#finish-btn').click();await page.locator('#manual-confirm').check();
  await page.locator('#complete-confirm').click();await visible('#view-list');await visible('#record-panel');
  await rate('good');await page.locator('#close-record').click();
  assert.equal((await state()).history[0].completed,true);
  await page.locator('.recommendation-focus').evaluate(e=>e.open=true);
  await page.locator('#recommendation-request').fill('simulate:no-pad');
  const withoutPad=await add();await enter(withoutPad);
  assert.equal(await page.locator('#pad-toggle').isEnabled(),true);
  assert.match(await page.locator('#backing-status').innerText(),/chord symbols/);
  await page.locator('#back-list').click();
  // A failed translation stays on the original until explicitly retried; success is cached.
  await page.locator('#recommendation-request').fill('simulate:translation-auth');
  const translationTask=await add();
  let translationRequests=0;
  page.on('request',request=>{if(request.url().includes('/api/translate') && request.postDataJSON()?.task_id===translationTask) translationRequests++;});
  const original=(await state()).history.find(task=>task.id===translationTask).target;
  await changeLanguage('ko');
  await item(translationTask).getByRole('button',{name:'번역 재시도'}).waitFor({state:'visible'});
  assert.equal(translationRequests,1);
  assert.match(await item(translationTask).textContent(),/Synthetic translation authentication failure/);
  await item(translationTask).getByRole('button',{name:'번역 재시도'}).click();
  await page.waitForFunction(id=>document.querySelector(`.practice-item[data-task-id="${id}"] h3`).textContent.startsWith('번역: '),translationTask);
  assert.equal(translationRequests,2);
  await page.reload();await visible('#view-list');
  await page.waitForFunction(id=>document.querySelector(`.practice-item[data-task-id="${id}"] h3`)?.textContent.startsWith('번역: '),translationTask);
  assert.equal(translationRequests,2);
  const saved=(await state()).history.find(task=>task.id===translationTask).target;
  assert.deepEqual(saved.exercise,original.exercise);
  assert.deepEqual(saved.difficulty,original.difficulty);
  await enter(translationTask);
  await page.locator('#lesson-overview .task-context-detail summary').click();
  assert.equal(await page.locator('#lesson-overview .characteristic-chip').count(),4);
  assert.match(await page.locator('#lesson-overview').innerText(),/개인 예상 부담 · 출제 당시/);
  assert.match(await page.locator('#lesson-overview .task-parts').innerText(),/번역:/);
  assert.equal(await page.locator('.demand-chip, .demand-reasons, .difficulty-detail').count(),0);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
  await page.screenshot({path:join(project,'build/browser/task-overview-mobile-ko.png'),fullPage:true});
  await page.screenshot({path:join(project,'build/browser/translation-recovered-mobile.png'),fullPage:true});
  // Validation repairs stay inside the original job, without a retry button or extra POST.
  await page.locator('#discard-btn').click();await page.locator('#discard-reason').fill('Synthetic translation test finished');await page.locator('#discard-submit').click();await hidden('#discard-dialog');
  await page.locator('.recommendation-focus').evaluate(e=>e.open=true);
  await page.locator('#recommendation-request').fill('simulate:translation-repair');
  const repairPosts=[];
  page.on('request',request=>{if(request.url().includes('/api/translate')&&request.method()==='POST')repairPosts.push(request.postDataJSON());});
  const repairTask=await add();
  await page.waitForFunction(id=>document.querySelector(`.practice-item[data-task-id="${id}"] h3`)?.textContent.startsWith('번역: '),repairTask);
  assert.equal(repairPosts.filter(request=>request.task_id===repairTask).length,1);
  assert.equal(await item(repairTask).getByRole('button',{name:'번역 재시도'}).count(),0);
  assert.doesNotMatch(await item(repairTask).textContent(),/99 BPM/);
  // Older schema and rubric snapshots use the same presentation without migration.
  const oldTasks = JSON.parse(execFileSync('uv', ['run','python','-c', `
import json, sys
from pathlib import Path
import review as r, recommendation as rec
sys.path.insert(0, 'tests')
from recommendation_fixture import result
root = Path(sys.argv[1])
assert root.name.startswith('jazz-browser-')
data = r.curriculum(); data['version'] = '0.4.0'
ids = []
for i, version in enumerate((1, 2)):
    value = result()
    value['schema_version'] = version
    if version == 1:
        value.pop('difficulty')
    else:
        value['difficulty']['rubric_version'] = 'task-demands-v1'
        value['difficulty']['axes']['rhythm'].update(level=3, anchor_ids=['rhythm-3'])
        value['difficulty']['prediction'].update(burden='challenging', reason='Synthetic saved forecast.')
    target = rec.make_target(value, data, {'source_language': 'en'})
    tid = 'T-' + str(i)*10; ids.append(tid)
    assigned = r.new_event('assigned', tid, data, target['exercise_id'])
    assigned.update(recorded_at='2026-01-01T10:00:00+00:00', target_json=r.jdump(target))
    reported = r.new_event('reported', tid, data, target['exercise_id'])
    reported.update(recorded_at='2026-01-01T10:10:00+00:00', practice_date='2026-01-01',
                    actual_json='{}', checks_json='{}', difficulty='good', raw_note='Synthetic historical report.')
    for event in (assigned, reported): r.append_event(root, event)
r.records(r.read_events(root))
print(json.dumps(ids))
`,root], {cwd:project}).toString());
  const ledgerBefore = await readFile(join(root,'practice.csv'));
  const sessionsBefore = (await state()).sessions;
  await page.reload();await visible('#view-list');
  for (const [index,id] of oldTasks.entries()) {
    await item(id).waitFor({state:'visible'});
    assert.equal(await item(id).locator('.characteristic-chip').count(),3);
    assert.match(await item(id).locator('.burden-prediction').innerText(),index===0 ? /저장된 예상 없음/ : /도전/);
    await item(id).locator('.history-item').click();
    await visible('#history-dialog');
    const detail=page.locator('#history-detail');
    await detail.locator('.task-context-detail').evaluate(node=>node.open=true);
    assert.equal(await detail.locator('.characteristic-chip').count(),3);
    assert.equal(await detail.locator('.demand-chip, .difficulty-detail').count(),0);
    assert.doesNotMatch(await detail.innerText(),/높은 요구 수준|보통 요구 수준|낮은 요구 수준|task-demands-v1|first reference/);
    if(index===1) assert.match(await detail.innerText(),/Synthetic saved forecast/);
    await page.screenshot({path:join(project,`build/browser/historical-overview-${index}-ko.png`),fullPage:true});
    await page.locator('#dialog-close').click();
  }
  assert.deepEqual(await readFile(join(root,'practice.csv')),ledgerBefore);
  assert.deepEqual((await state()).sessions,sessionsBefore);
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({passed:true,checks:['generation/authentication errors','response-loss idempotency','multiple active tasks','list landing and explicit entry','finite manual completion and feedback','task descriptions and responsive layout','legacy score continuity','translation repair/retry/cache','historical schema/rubric views preserve originals'],screenshots:'workflow/build/browser'}));
} finally {
  if(browser)await browser.close();
  const exited=once(server,'exit');server.kill('SIGTERM');await exited;
  await rm(root,{recursive:true,force:true});
}
