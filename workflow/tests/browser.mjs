// Optional browser integration check. Requires Playwright and Chrome; all records are temporary.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {mkdtemp, mkdir, rm, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const project = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const root = await mkdtemp(join(tmpdir(), 'jazz-browser-'));
await writeFile(join(root, 'profile.json'), '{"daily_minutes":30}');
await mkdir(join(project, 'build/browser'), {recursive:true});
const server = spawn('uv', ['run', 'python', 'review.py', '--practice-root', root, 'serve', '--port', '0'], {cwd:project});
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
  const choose=async id=>{await page.locator('#chooser').evaluate(e=>e.open=true);await page.locator('#exercise-select').selectOption(id);};
  const changeLanguage = async language => {
    await page.locator('[data-view="settings"]').click();
    await page.locator('#language-select').selectOption(language);
    await page.waitForFunction(language => document.documentElement.lang === language &&
      document.querySelector('#connection').textContent === (language === 'ko' ? '로컬에 연결됨' : 'Connected locally'), language);
    await page.locator('[data-view="practice"]').click();
    await page.waitForFunction(language => /[가-힣]/.test(document.querySelector('#lesson-title').textContent) === (language === 'ko'), language);
  };
  await page.goto(url);
  await page.waitForFunction(()=>document.querySelector('#connection').textContent==='Connected locally');
  assert.equal((await state()).history.length,0);
  assert.equal(await page.locator('html').getAttribute('lang'),'en');
  assert.doesNotMatch(await page.locator('body').innerText(),/[가-힣]/);
  assert.equal(await page.getByRole('button', {name: 'Start practice', exact: true}).count(), 1);
  assert.equal(await page.getByRole('button', {name: 'Finish', exact: true}).count(), 1);
  assert.ok(await page.evaluate(() => document.querySelector('.lesson-card').getBoundingClientRect().bottom <=
    document.querySelector('.score-card').getBoundingClientRect().top));
  assert.equal(await page.locator('.score-hand, .score-bar-number').count(), 0);
  assert.equal(await page.locator('.score-whole').first().evaluate(node => getComputedStyle(node).fill), 'none');
  await page.evaluate(() => document.fonts.load('40px Bravura'));
  assert.ok(await page.evaluate(() => [...document.fonts].some(font => font.family === 'Bravura' && font.status === 'loaded')));
  for (const lesson of (await state()).exercises) {
    await choose(lesson.id);
    assert.doesNotMatch(await page.locator('.lesson-card').innerText(),/[가-힣]/);
    for (const key of ['C', 'F', 'Bb']) {
      await page.locator('#key-select').selectOption(key);
      assert.equal(await page.locator('.practice-score').count(), 1);
      assert.equal(await page.locator('.score-chord').count(), lesson.targets[key].notation.bars.length);
      assert.ok(await page.locator('.score-target-note').count() > 0);
    }
  }
  await choose('E05');
  assert.equal(await page.locator('.score-target[data-hand="right"][data-kind="notes"][data-beat="1.5"]').count(), 4);
  await page.locator('.score-card').screenshot({path:join(project,'build/browser/score-charleston.png')});
  await choose('E06');
  assert.equal(await page.locator('.score-improv').count(), 4);
  assert.equal(await page.locator('.score-target[data-hand="right"][data-kind="rest"]').count(), 4);
  assert.equal(await page.locator('.score-target[data-bar="7"]').count(), 2);
  await page.locator('.score-card').screenshot({path:join(project,'build/browser/score-improv.png')});
  await choose('E01');
  await page.locator('#key-select').selectOption('C');
  // Exercise the same renderer at deterministic bar and loop boundaries, without
  // waiting through 32 beats or adding practice evidence to the temporary log.
  const displayChecks = await page.evaluate(async () => {
    const {ScoreView} = await import('/score.mjs');
    const data = await (await fetch('/api/state')).json();
    const host = document.createElement('div'); host.style.width = '300px';
    const root = document.createElement('div'); root.className = 'score-viewport'; host.append(root);
    document.body.append(host);
    const follow = document.createElement('input'); follow.type = 'checkbox'; follow.checked = true;
    const status = document.createElement('span');
    const view = new ScoreView({root, status, follow});
    const score = id => data.exercises.find(e => e.id === id).targets.Bb.notation;
    const at = (absolute, bars) => ({absolute, bar: Math.floor(absolute / 4) % bars, pass: Math.floor(absolute / (bars * 4)), beat: absolute % 4});
    view.setScore(score('E04')); view.begin(); view.frame(at(8.1, 4));
    view.midi([0x90, 50, 100], 'test', at(8.1, 4)); // D3 belongs to the right hand here.
    const low = root.querySelector('.score-live-note[data-midi="50"]');
    const lowRight = low.dataset.hand === 'right' && Boolean(low.querySelector('.score-input-head')) && !low.querySelector('.score-edge-note');
    const alignedY = low.querySelector('.score-input-head').getAttribute('cy') === root.querySelector('.score-target[data-bar="2"][data-hand="right"] [data-midi="50"] ellipse').getAttribute('cy');
    view.setScore(score('E06')); view.begin();
    const canvas = root.querySelector('svg');
    const cursorX = () => view.cursor.transform.baseVal.consolidate().matrix.e;
    const positions = [];
    for (let beat = 0; beat <= 31.9; beat += .1) {
      view.frame(at(beat, 8)); positions.push({x: cursorX(), scroll: root.scrollLeft});
    }
    const continuous = positions.every((value, i) => !i ||
      (Math.abs(value.x - positions[i - 1].x - 5.2) < .001 &&
       value.scroll >= positions[i - 1].scroll && value.scroll - positions[i - 1].scroll <= 5));
    const oneCanvas = canvas === root.querySelector('svg') && root.querySelectorAll('.score-chord').length === 8;
    view.frame(at(15.8, 8));
    const tailStart = cursorX();
    view.midi([0x90, 62, 100], 'test', at(15.8, 8));
    view.frame(at(16.2, 8)); view.midi([0x80, 62, 0], 'test', at(16.2, 8));
    const tail = root.querySelector('.score-hold');
    const joinedTail = root.querySelectorAll('.score-hold').length === 1 &&
      Math.abs(Number(tail.getAttribute('x1')) - tailStart) < .001 &&
      Math.abs(Number(tail.getAttribute('x2')) - cursorX()) < .001;
    view.frame(at(20, 8));
    const followingScroll = root.scrollLeft;
    follow.checked = false; root.scrollLeft = 90;
    view.frame(at(22, 8));
    const manualScroll = root.scrollLeft === 90 && followingScroll > 90;
    follow.checked = true;
    view.frame(at(31.8, 8));
    view.midi([0x90, 62, 100], 'test', at(31.8, 8));
    view.frame(at(32.2, 8)); view.drawNotes();
    const loop = /Pass 2/.test(status.textContent) && root.scrollLeft === 0;
    const continuedHold = Boolean(root.querySelector('.score-hold')) && !root.querySelector('.score-input-head');
    view.pause(at(32.4, 8));
    const interrupted = Boolean(root.querySelector('.score-hold.interrupted'));
    view.begin();
    const reset = root.querySelectorAll('.score-live-note').length === 0;
    view.frame(at(14, 8));
    const localScroll = root.scrollLeft > 0;
    host.style.width = '1200px'; view.setScore(score('E04')); view.begin(); view.frame(at(14, 4));
    const fittingScore = root.scrollLeft === 0 && root.scrollWidth === root.clientWidth;
    view.setScore(null); view.frame(at(15, 4));
    const fallback = !root.querySelector('svg') && root.textContent.includes('not available');
    host.remove();
    return {lowRight, alignedY, continuous, oneCanvas, joinedTail, manualScroll, loop, continuedHold, interrupted, reset, localScroll, fittingScore, fallback};
  });
  assert.ok(Object.values(displayChecks).every(Boolean), JSON.stringify(displayChecks));
  await page.screenshot({path:join(project,'build/browser/desktop.png'),fullPage:true});
  await changeLanguage('ko');
  assert.match(await page.locator('#criterion-text').textContent(), /연속 2회/);
  assert.equal((await state()).history.length, 0);
  await page.reload();
  await page.waitForFunction(()=>document.documentElement.lang==='ko' && document.querySelector('#connection').textContent==='로컬에 연결됨');
  assert.match(await page.locator('#lesson-title').textContent(), /왼손/);
  await page.screenshot({path:join(project,'build/browser/korean.png'),fullPage:true});
  await changeLanguage('en');

  await choose('E03');assert.equal(await page.locator('#practice-btn').isEnabled(),false);
  await choose('E01');
  await page.locator('#playback-settings > summary').click();
  await page.locator('#midi-connect').click();
  assert.match(await page.locator('#midi-status').textContent(),/denied/);
  await page.evaluate(()=>window.denyMidi=false);
  await page.locator('#midi-connect').click();
  await page.waitForFunction(()=>document.querySelector('#midi-status').textContent.includes('1 input(s)'));
  await page.locator('#tempo').fill('65');await page.locator('#tempo').press('Tab');
  await page.locator('.switch-label').filter({has:page.locator('#pad-toggle')}).click();
  assert.equal(await page.locator('#pad-toggle').isChecked(),true);
  await page.locator('#practice-btn').click();
  await page.waitForFunction(()=>document.querySelector('#practice-btn').textContent==='Pause');
  assert.equal(await page.locator('#tempo').inputValue(),'65');
  const activeSession = (await state()).sessions[0].id;
  await changeLanguage('ko');
  assert.equal(await page.locator('#practice-btn').textContent(), '일시정지');
  assert.equal((await state()).sessions.length, 1);
  assert.equal((await state()).sessions[0].id, activeSession);
  assert.equal(await page.locator('#tempo').inputValue(), '65');
  await changeLanguage('en');

  await page.waitForTimeout(150);
  await page.evaluate(()=>window.sendMidi([0x90,60,100]));
  await page.waitForFunction(() => document.querySelectorAll('.score-live-note').length === 1);
  const onset = Number(await page.locator('.score-live-note').getAttribute('data-start'));
  assert.ok(onset > 0 && onset % 1 !== 0);
  const cursor = await page.locator('.score-cursor').getAttribute('transform');
  await page.waitForTimeout(90);
  assert.notEqual(await page.locator('.score-cursor').getAttribute('transform'), cursor);
  await changeLanguage('ko');
  assert.equal(await page.locator('.score-live-note').count(), 1);
  assert.match(await page.locator('#score-position').textContent(), /번째 반복/);
  assert.equal(await page.locator('.score-hand').count(), 0);
  await changeLanguage('en');
  await page.waitForTimeout(180);
  await page.evaluate(()=>{window.sendMidi([0xb0,64,127]);window.sendMidi([0x80,60,0]);});
  await page.locator('#tempo').fill('80');await page.locator('#tempo').press('Tab');
  await page.waitForTimeout(1200);
  await page.evaluate(()=>window.sendMidi([0x90,64,100]));
  await page.waitForTimeout(170);
  await page.evaluate(()=>{window.sendMidi([0x80,64,0]);window.sendMidi([0xb0,64,0]);});
  assert.equal(await page.locator('.score-live-note').count(), 2);
  assert.ok(Number(await page.locator('.score-live-note[data-midi="64"]').getAttribute('data-end')) > 0);
  await page.locator('.score-card').screenshot({path:join(project,'build/browser/score-live.png')});
  const sent=await page.evaluate(()=>window.sent);
  await page.locator('#tempo').fill('100');await page.locator('#tempo').press('Tab');
  await page.waitForTimeout(1000);
  await page.locator('#practice-btn').click();
  await page.waitForTimeout(250);
  assert.equal(await page.locator('.score-cursor').getAttribute('visibility'), 'hidden');
  await page.locator('#practice-btn').click();
  await page.waitForFunction(()=>document.querySelector('#practice-btn').textContent==='Pause');
  assert.equal(await page.locator('.score-live-note').count(), 0);
  await page.waitForTimeout(150);
  await page.locator('#finish-btn').click();
  await visible('#record-panel');
  assert.equal(await page.locator('#actual-bpm, #actual-minutes, #practice-date, #notes-correct, #clean-runs, #difficulty').count(), 0);
  assert.match(await page.locator('#measurements').textContent(), /Metronome 80 BPM/);
  assert.equal(await page.locator('[data-rating][aria-pressed=true]').count(), 0);
  let data=await state();const recording=data.sessions[0], task=data.history[0];
  assert.equal(recording.status,'finished');
  assert.equal(recording.summary.note_ons,2);
  assert.equal(recording.summary.last_note_bpm,80);
  assert.equal(recording.summary.last_setting_bpm,100);
  assert.ok(Math.abs(recording.summary.input_span_ms-(sent.at(-1).timeStamp-sent[0].timeStamp))<0.01);
  assert.equal(recording.summary.pad_used,true);
  assert.ok(recording.summary.active_ms<recording.summary.elapsed_ms);
  const starts=await page.evaluate(()=>window.audioStarts);
  assert.ok(starts.some(n=>n.frequency>800));assert.ok(starts.some(n=>n.frequency<500));
  const raw=await page.evaluate(async id=>Array.from(new Uint8Array(await (await fetch(`/api/recordings/${id}/midi`)).arrayBuffer())),recording.id);
  assert.deepEqual(raw.slice(0,4),[74,80,77,49]);
  assert.equal(raw.length,4+15*sent.length);
  for(let i=0;i<sent.length;i++) assert.deepEqual(raw.slice(4+15*i+12,4+15*(i+1)),sent[i].data);
  // A single label saves with no memo or musical self-assessment.
  await page.locator('[data-rating="good"]').click();
  await visible('#feedback-panel');
  await page.waitForFunction(() => !document.querySelector('[data-rating="good"]').disabled);
  data=await state();assert.equal(data.status.today.reported_attempts,1);
  assert.equal(data.history[0].report.raw_note,'');
  assert.equal(data.history[0].outcome,'unknown');
  assert.deepEqual(JSON.parse(data.history[0].report.actual_json),{});
  assert.match(await page.locator('#reflection-status').textContent(), /Practice saved/);
  assert.doesNotMatch(await page.locator('#record-panel').innerText(), /assessment pending|missing|correct notes/i);
  assert.equal(data.status.next.exercise_id,'E02');
  await page.locator('#record-panel').screenshot({path:join(project,'build/browser/feedback.png')});
  const original='브라우저 테스트 원문, "따옴표"\n<img src=x onerror=alert(1)> 그대로';
  await page.locator('#memo-details').evaluate(e=>e.open=true);
  await page.locator('#raw-note').fill(original);
  await changeLanguage('ko');
  assert.equal(await page.locator('#raw-note').inputValue(), original);
  assert.match(await page.locator('[data-rating="too_easy"]').textContent(), /너무 쉬워서 의미 없었음/);
  await changeLanguage('en');
  await page.locator('#save-note').click();
  await page.waitForFunction(() => !document.querySelector('#save-note').disabled);
  data=await state();assert.equal(data.history[0].report.raw_note,original);
  assert.equal(data.history[0].revisions.length,2);
  await page.locator('[data-view="history"]').click();
  assert.match(await page.locator('.history-item').first().textContent(), /Good practice/);
  await page.locator('.history-item').first().click();
  assert.equal(await page.locator('#history-detail .raw-note').textContent(),original);
  assert.equal(await page.locator('#history-detail img').count(),0);
  await page.locator('#correct-btn').click();
  await page.locator('[data-rating="challenging"]').click();
  await page.waitForFunction(() => !document.querySelector('[data-rating="challenging"]').disabled);
  data=await state();assert.equal(data.history[0].revisions.length,3);assert.equal(data.history[0].outcome,'unknown');
  assert.equal(data.sessions[0].summary.last_note_bpm,80);
  // The next button saves an optional note edit without a second save click.
  await page.locator('#raw-note').fill('정정 테스트: 도전적인 연습');
  await page.locator('#next-btn').click();await hidden('#record-panel');
  assert.equal((await state()).history[0].report.raw_note,'정정 테스트: 도전적인 연습');
  // A preview can be skipped without ever starting audio or recording practice.
  await choose('E01');await page.locator('#skip-btn').click();
  await page.locator('#skip-reason').fill('테스트: 오늘은 다른 항목부터');
  await page.locator('#skip-form button[type=submit]').click();await hidden('#skip-dialog');
  data=await state();assert.equal(data.history[0].cancelled,true);assert.equal(data.status.today.reported_attempts,1);
  // An unavailable server leaves MIDI in IndexedDB; reload sends it once and marks interruption.
  await choose('E02');
  await page.route('**/api/sessions/chunk*',route=>route.abort());
  await page.locator('#practice-btn').click();
  await page.waitForFunction(()=>document.querySelector('#practice-btn').textContent==='Pause');
  await page.evaluate(()=>window.sendMidi([0x90,67,100]));
  await page.waitForTimeout(3300);
  await page.unroute('**/api/sessions/chunk*');
  await page.reload();await visible('#recovery');
  await page.locator('#recover-btn').click();await hidden('#recovery');await visible('#record-panel');
  assert.match(await page.locator('#measurements').textContent(), /Practice time unknown/);
  data=await state();assert.equal(data.sessions.at(-1).status,'interrupted');
  assert.equal(data.sessions.at(-1).summary.note_ons,1);
  assert.equal(data.sessions.at(-1).summary.input_span_ms,null);
  await page.locator('#memo-details').evaluate(e=>e.open=true);
  await page.locator('#raw-note').fill('테스트: 복구된 중단 연습');await page.locator('[data-rating=impossible]').click();
  await visible('#feedback-panel');
  assert.equal((await state()).status.today.reported_attempts,2);
  assert.equal((await state()).history[0].outcome, 'unknown');
  await changeLanguage('ko');
  assert.match(await page.locator('#reflection-status').textContent(), /연습을 저장했어요/);
  await page.locator('[data-view="history"]').click();
  await page.locator('.history-item').first().click();
  assert.equal(await page.locator('.assessment-details').count(), 0);
  assert.match(await page.locator('#history-detail').textContent(), /불가능했음/);
  assert.equal(await page.locator('#history-detail .raw-note').textContent(), '테스트: 복구된 중단 연습');
  await page.locator('#dialog-close').click();
  await changeLanguage('en');

  await page.locator('[data-view="history"]').click();
  await page.locator('#filter-key').selectOption('F');assert.equal(await page.locator('.history-item').count(),0);
  await page.locator('#filter-key').selectOption('');assert.equal(await page.locator('.history-item').count(),3);
  await page.screenshot({path:join(project,'build/browser/history.png'),fullPage:true});
  await page.locator('[data-view="progress"]').click();assert.equal(await page.locator('.goal-card').count(),6);
  await page.locator('[data-view="practice"]').click();
  await page.setViewportSize({width:390,height:844});
  for (const language of ['en', 'ko']) {
    await changeLanguage(language);
    await page.screenshot({path:join(project,`build/browser/mobile-${language}.png`),fullPage:true});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
    await page.locator('#record-panel').screenshot({path:join(project,`build/browser/feedback-mobile-${language}.png`)});
    assert.equal(await page.locator('.rating-options').evaluate(e=>getComputedStyle(e).gridTemplateColumns.split(' ').length), 2);
  }
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({passed:true,checks:['notation in 18 exercise/key combinations','local music font','Charleston offbeat + improv rests','live MIDI overlay + moving cursor','pause/resume resets display','language preference + reload','live language switch preserves capture, notes and draft','one-tap feedback without assessment prompts','empty read-only state','prerequisites','MIDI permission denial','tempo + pad','raw MIDI + sustain trim','report + feedback','correction history','same-day skip','offline + reload recovery','filters + goals','mobile layout'],screenshots:'workflow/build/browser'}));
} finally {
  if(browser) await browser.close();
  const exited=once(server,'exit');server.kill('SIGTERM');await exited;
  await rm(root,{recursive:true,force:true});
}
