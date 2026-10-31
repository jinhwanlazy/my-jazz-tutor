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
    assert.equal(data.history.filter(t=>t.pending).length,1);
    assert.match(data.history.find(t=>t.pending).exercise_id,/^G-/);
    return data.history.find(t=>t.pending).id;
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
  assert.match(await page.locator('#generation-message').textContent(),/Your focus is included/);
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
  assert.equal(await item(first).locator('.characteristic-chip').count(),3);
  assert.match(await item(first).locator('.burden-prediction').innerText(),/Not enough evidence/);
  assert.ok(await item(first).evaluate(card=>Math.abs(card.querySelector('h3').getBoundingClientRect().left-
    card.querySelector('.task-overview').getBoundingClientRect().left)<2));
  assert.equal(await item(first).locator('.demand-chip').count(),0);
  assert.equal(await page.locator('#new-practice').isEnabled(),false);
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
  assert.equal(await page.locator('#lesson-overview .characteristic-chip').count(),3);
  assert.match(await page.locator('#lesson-overview .task-context-detail').innerText(),/assigned task, not measured performance/);
  assert.match(await page.locator('#lesson-overview .task-parts').innerText(),/Hold D3/);
  assert.doesNotMatch(await page.locator('#lesson-overview').innerText(),/reference|[Ll]ow demand|[Hh]igh demand/);
  await page.locator('#lesson-overview .task-context-detail summary').click();
  assert.equal(await page.getByRole('button',{name:'Start practice',exact:true}).count(),1);
  assert.equal(await page.getByRole('button',{name:'Complete practice',exact:true}).count(),1);
  assert.equal(await page.locator('#finish-btn').isEnabled(),false);
  assert.ok(await page.evaluate(()=>document.querySelector('.lesson-card').getBoundingClientRect().bottom<=document.querySelector('.score-card').getBoundingClientRect().top));
  assert.equal(await page.locator('.score-hand,.score-bar-number').count(),0);
  assert.equal(await page.locator('.score-whole').first().evaluate(node=>getComputedStyle(node).fill),'none');
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
    view.midi([0x90, 50, 100], 'test', at(8.1, 4)); // D3 belongs to the right hand here.
    const low = root.querySelector('.score-live-note[data-midi="50"]');
    const lowRight = low.dataset.hand === 'right' && Boolean(low.querySelector('.score-input-head')) && !low.querySelector('.score-edge-note');
    const alignedY = low.querySelector('.score-input-head').getAttribute('cy') === root.querySelector('.score-target[data-bar="2"][data-hand="right"] [data-midi="50"] ellipse').getAttribute('cy');
    view.setScore(score('E06')); view.begin();
    const consistentNoteSize=Math.abs(root.querySelector('.score-glyph').getBoundingClientRect().height-shortGlyphHeight)<.1;
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
    return {lowRight, alignedY, consistentNoteSize, continuous, oneCanvas, joinedTail, manualScroll, loop, continuedHold, interrupted, reset, localScroll, fittingScore, fallback};
  }, notationFixtures);
  assert.ok(Object.values(displayChecks).every(Boolean), JSON.stringify(displayChecks));
  await page.locator('#playback-settings > summary').click();
  await page.locator('#midi-connect').click();
  assert.match(await page.locator('#midi-status').textContent(),/denied/);
  await page.evaluate(()=>window.denyMidi=false);
  await page.locator('#midi-connect').click();
  await page.locator('#tempo').fill('65');await page.locator('#tempo').press('Tab');
  await page.locator('.switch-label').filter({has:page.locator('#pad-toggle')}).click();
  await page.locator('#practice-btn').click();
  await page.waitForFunction(()=>document.querySelector('#practice-btn').textContent==='Pause');
  const activeSession=(await state()).sessions[0].id;
  await changeLanguage('ko');
  assert.equal((await state()).sessions[0].id,activeSession);
  assert.equal(await page.locator('#tempo').inputValue(),'65');
  await page.waitForFunction(()=>document.querySelector('#lesson-title').textContent.startsWith('번역: '));
  assert.match(await page.locator('#hand-notes').textContent(),/F#4\+A4/);
  assert.equal((await state()).history[0].target.title,'D major voice leading');
  await visible('.sidebar #midi-connect');
  await changeLanguage('en');
  assert.equal(await page.locator('#lesson-title').textContent(),'D major voice leading');
  await page.waitForTimeout(150);
  await page.evaluate(()=>window.sendMidi([0x90,60,100]));
  await page.waitForFunction(()=>document.querySelectorAll('.score-live-note').length===1);
  const cursor=await page.locator('.score-cursor').getAttribute('transform');
  await page.waitForTimeout(100);
  assert.notEqual(await page.locator('.score-cursor').getAttribute('transform'),cursor);
  await page.evaluate(()=>{window.sendMidi([0xb0,64,127]);window.sendMidi([0x80,60,0]);});
  for(const id of ['tempo','tempo-range','tempo-down','tempo-up']) assert.equal(await page.locator('#'+id).isDisabled(),true);
  await page.locator('#tempo').evaluate(input=>{input.value='80';input.dispatchEvent(new Event('change'));});
  assert.equal(await page.locator('#tempo').inputValue(),'65');
  await page.waitForTimeout(1200);
  await page.evaluate(()=>window.sendMidi([0x90,64,100]));
  await page.waitForTimeout(100);
  await page.evaluate(()=>{window.sendMidi([0x80,64,0]);window.sendMidi([0xb0,64,0]);});
  await page.locator('#practice-btn').click();
  for(const id of ['tempo','tempo-range','tempo-down','tempo-up']) assert.equal(await page.locator('#'+id).isDisabled(),true);
  await page.locator('#tempo-range').evaluate(input=>{input.value='100';input.dispatchEvent(new Event('input'));});
  assert.equal(await page.locator('#tempo-range').inputValue(),'65');
  await page.locator('#practice-btn').click();
  await page.waitForTimeout(150);
  await page.route('**/api/complete*',async route=>{await route.fetch();await route.abort();});
  await page.locator('#finish-btn').click();
  await visible('#error');await visible('#view-practice');
  await page.waitForFunction(()=>!document.querySelector('#finish-btn').disabled);
  assert.equal((await state()).history[0].completed,true);
  await page.unroute('**/api/complete*');
  await page.locator('#finish-btn').click();
  await visible('#view-list');await visible('#record-panel');await hidden('#view-practice');
  let data=await state();
  assert.equal(data.history[0].completed,true);
  assert.equal(data.history[0].report,null);
  assert.equal(data.status.today.reported_attempts,1);
  assert.equal(data.history.filter(t=>t.pending).length,0);
  assert.match(await item(first).textContent(),/Completed/);
  assert.equal(await page.locator('#actual-bpm,#actual-minutes,#practice-date,#notes-correct,#clean-runs').count(),0);
  const recording=data.sessions[0], sent=await page.evaluate(()=>window.sent);
  assert.equal(recording.summary.last_note_bpm,65);
  assert.equal(recording.summary.last_setting_bpm,65);
  assert.equal(recording.summary.pad_used,true);
  const archive=await page.evaluate(async id=>Array.from(new Uint8Array(await (await fetch(`/api/recordings/${id}/midi`)).arrayBuffer())),recording.id);
  assert.deepEqual(archive.slice(0,4),[74,80,77,49]);
  assert.equal(archive.length,4+15*sent.length);
  for(let i=0;i<sent.length;i++)assert.deepEqual(archive.slice(4+15*i+12,4+15*(i+1)),sent[i].data);
  await rate('good');
  assert.equal((await state()).status.today.reported_attempts,1);
  assert.equal((await state()).history[0].outcome,'unknown');
  assert.equal((await state()).status.next.action,'generate');
  assert.match(await item(first).locator('.practice-result').textContent(),/Good practice/);
  await page.locator('#memo-details').evaluate(e=>e.open=true);
  const note='Synthetic memo, "quoted"\n<img src=x onerror=alert(1)> 원문';
  await page.locator('#raw-note').fill(note);
  await changeLanguage('ko');
  assert.equal(await page.locator('#raw-note').inputValue(),note);
  await changeLanguage('en');
  await page.locator('#save-note').click();
  await page.waitForFunction(()=>!document.querySelector('#save-note').disabled);
  assert.equal(await item(first).locator('.practice-note').textContent(),note);
  await page.locator('#close-record').click();
  await item(first).locator('.history-item').click();
  await visible('#history-dialog');await hidden('#view-practice');
  assert.equal(await page.locator('#history-detail img').count(),0);
  assert.equal(await page.locator('#history-detail .raw-note').textContent(),note);
  await page.locator('#repeat-btn').click();await hidden('#history-dialog');
  const repeated=(await state()).history.find(t=>t.pending).id;
  assert.notEqual(repeated,first);await hidden('#view-practice');
  await enter(repeated);
  await page.locator('#discard-btn').click();
  await page.locator('#discard-submit').click();await hidden('#discard-dialog');await visible('#view-list');
  data=await state();assert.equal(data.history[0].discarded,true);assert.equal(data.history[0].reason,'');
  assert.equal(data.status.today.reported_attempts,1);
  // Leaving the room saves a recording but keeps the task open for a later return.
  const second=await add('E02');await enter(second);
  for(const id of ['tempo','tempo-range','tempo-down','tempo-up']) assert.equal(await page.locator('#'+id).isEnabled(),true);
  await page.locator('#tempo').fill('80');await page.locator('#tempo').dispatchEvent('change');
  await page.locator('#practice-btn').click();
  await page.waitForFunction(()=>document.querySelector('#practice-btn').textContent==='Pause');
  await page.waitForTimeout(100);
  await page.locator('#back-list').click();await visible('#view-list');
  data=await state();assert.equal(data.history[0].pending,true);assert.equal(data.history[0].completed,false);
  assert.equal(data.sessions.at(-1).status,'finished');
  assert.match(await item(second).textContent(),/In progress/);
  await enter(second);
  // A lost chunk upload must keep the room open until save can be retried.
  await page.route('**/api/sessions/chunk*',route=>route.abort());
  await page.locator('#practice-btn').click();
  await page.waitForFunction(()=>document.querySelector('#practice-btn').textContent==='Pause');
  await page.evaluate(()=>window.sendMidi([0x90,67,100]));
  await page.waitForTimeout(100);
  await page.locator('#finish-btn').click();
  await page.waitForFunction(()=>document.querySelector('#finish-btn').textContent==='Retry save' && !document.querySelector('#finish-btn').disabled);
  await visible('#view-practice');assert.equal((await state()).history[0].completed,false);
  await page.unroute('**/api/sessions/chunk*');
  await page.reload();await visible('#recovery');await visible('#view-list');
  await page.locator('#recover-btn').click();await hidden('#recovery');
  await enter(second);await page.locator('#finish-btn').click();await visible('#record-panel');await visible('#view-list');
  await rate('too_easy');
  assert.equal((await state()).status.next.action,'generate');
  // Discard from an active room saves input, preserves an optional reason, and returns to the list.
  await page.locator('#close-record').click();
  const third=await add('E03');await enter(third);
  await page.locator('#practice-btn').click();
  await page.waitForFunction(()=>document.querySelector('#practice-btn').textContent==='Pause');
  await page.evaluate(()=>{window.sendMidi([0x90,64,80]);window.sendMidi([0x80,64,0]);});
  await page.locator('#discard-btn').click();
  await page.locator('[data-discard-choice="already_practiced"]').click();
  await page.locator('#discard-reason').fill('Synthetic skip reason');
  await page.locator('#discard-submit').click();await hidden('#discard-dialog');await visible('#view-list');
  data=await state();assert.equal(data.history[0].discarded,true);
  assert.equal(data.sessions.at(-1).status,'finished');
  assert.equal(data.status.today.reported_attempts,2);
  assert.match(await item(third).textContent(),/Already familiar/);
  assert.match(await item(third).textContent(),/Synthetic skip reason/);
  assert.equal(await page.locator('#new-practice').isEnabled(),true);
  await page.locator('.list-filters').evaluate(e=>e.open=true);
  await page.locator('#filter-key').selectOption('D');assert.equal(await page.locator('.practice-item').count(),4);
  await page.locator('#filter-from').fill('2099-01-01');assert.equal(await page.locator('.practice-item').count(),0);
  await page.locator('#filter-from').fill('');
  await page.locator('#filter-key').selectOption('');assert.equal(await page.locator('.practice-item').count(),4);
  await page.locator('.list-filters').evaluate(e=>e.open=false);
  for(const language of ['en','ko']){
    await changeLanguage(language);
    await page.setViewportSize({width:1440,height:1080});
    await page.screenshot({path:join(project,`build/browser/list-desktop-${language}.png`),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    await visible('.sidebar #midi-connect');
    await page.evaluate(()=>window.scrollTo(0,document.body.scrollHeight));
    assert.ok(await page.locator('#midi-connect').evaluate(node=>{const rect=node.getBoundingClientRect();return rect.top>=0&&rect.bottom<=innerHeight;}));
    await page.evaluate(()=>window.scrollTo(0,0));
    await page.screenshot({path:join(project,`build/browser/list-mobile-${language}.png`),fullPage:true});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
  }
  await changeLanguage('en');
  await page.locator('.recommendation-focus').evaluate(e=>e.open=true);
  await page.locator('#recommendation-request').fill('simulate:no-pad');
  const withoutPad=await add(); await enter(withoutPad);
  assert.equal(await page.locator('#recommendation-request').inputValue(),'');
  assert.equal(await page.locator('#pad-toggle').isEnabled(),false);
  assert.equal(await page.locator('.score-target[data-duration="2"] .score-whole').first().evaluate(n=>getComputedStyle(n).fill),'none');
  await page.locator('#tempo').fill('240'); await page.locator('#tempo').dispatchEvent('change');
  await page.locator('#practice-btn').click();
  await page.waitForFunction(()=>document.querySelector('#bar-position').textContent.startsWith('Bar 2'), {timeout:10000});
  await page.locator('#practice-btn').click();
  await page.screenshot({path:join(project,'build/browser/generated-score.png'),fullPage:true});
  await page.locator('#discard-btn').click();await page.locator('#discard-submit').click();await hidden('#discard-dialog');
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
  assert.equal(await page.locator('#lesson-overview .characteristic-chip').count(),3);
  assert.match(await page.locator('#lesson-overview').innerText(),/개인 예상 부담 · 출제 당시/);
  assert.match(await page.locator('#lesson-overview .task-parts').innerText(),/번역:/);
  assert.equal(await page.locator('.demand-chip, .demand-reasons, .difficulty-detail').count(),0);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
  await page.screenshot({path:join(project,'build/browser/task-overview-mobile-ko.png'),fullPage:true});
  await page.screenshot({path:join(project,'build/browser/translation-recovered-mobile.png'),fullPage:true});
  // Validation repairs stay inside the original job, without a retry button or extra POST.
  await page.locator('#discard-btn').click();await page.locator('#discard-submit').click();await hidden('#discard-dialog');
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
  console.log(JSON.stringify({passed:true,checks:['Codex job progress and authentication failure','response loss without duplicate generation','custom tasks outside the catalog','list landing without writes','explicit create and enter','pending resume after reload','completion before feedback','no duplicate counts','notes and skip reasons inline','repeat creates another item','score continuity and MIDI','failed save and recovery','active discard preserves recordings','languages and mobile layout','translation retry and reload cache','BPM locked during playing and pause','MIDI stays visible in sidebar and mobile header','task characteristics and saved prediction first','historical schema/rubric views without rewriting records'],screenshots:'workflow/build/browser'}));
} finally {
  if(browser)await browser.close();
  const exited=once(server,'exit');server.kill('SIGTERM');await exited;
  await rm(root,{recursive:true,force:true});
}
