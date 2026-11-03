// UI regressions use synthetic records in a disposable workspace, without Codex.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp,mkdir,writeFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const project=resolve(import.meta.dirname,'..'),root=await mkdtemp(join(tmpdir(),'jazz-browser-ux-review-'));
const output=join(project,'build/practice-polish-0.8.0');await mkdir(output,{recursive:true});
const server=spawn('uv',['run','python','tests/serve_ux_browser.py',root],{cwd:project});let browser;
try {
  const fixture=await new Promise((resolve,reject)=>{
    let out='',errors='';const timeout=setTimeout(()=>reject(Error(errors||'Startup timeout')),30000);
    server.stdout.on('data',chunk=>{out+=chunk;try{const value=JSON.parse(out.split('\n')[0]);clearTimeout(timeout);resolve(value);}catch{}});
    server.stderr.on('data',chunk=>errors+=chunk);server.on('exit',code=>reject(Error('Server exited '+code+' '+errors)));
  });
  browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_EXECUTABLE||'/usr/bin/google-chrome',args:['--no-sandbox']});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>{
    const Audio=window.AudioContext;window.AudioContext=class extends Audio{constructor(...args){super(...args);window.syntheticAudio=this;}};
    const port={id:'synthetic-piano',name:'Synthetic piano',state:'connected',type:'input'};
    const access={inputs:new Map([[port.id,port]])};
    Object.defineProperty(navigator,'requestMIDIAccess',{value:async()=>access});
    window.midiConnected=connected=>{port.state=connected?'connected':'disconnected';access.onstatechange?.({port});};
    window.sendMidi=data=>port.onmidimessage?.({data:Uint8Array.from(data),timeStamp:performance.now()});
  });
  const state=()=>page.evaluate(()=>fetch('/api/state').then(r=>r.json()));
  const card=name=>page.locator(`.practice-item[data-task-id="${fixture.tasks[name]}"]`);
  const enter=async name=>{await card(name).locator('.history-item').click();await page.locator('#view-practice').waitFor({state:'visible'});};
  const list=async()=>{await page.locator('#back-list').click();await page.locator('#view-list').waitFor({state:'visible'});};
  const settings=async()=>{await page.locator('#playback-settings').evaluate(e=>e.open=true);};
  const layout=()=>page.evaluate(()=>{
    const rect=id=>{const r=document.querySelector(id).getBoundingClientRect();return {top:r.top,bottom:r.bottom,left:r.left,right:r.right,height:r.height};};
    return {height:innerHeight,width:innerWidth,overflow:document.documentElement.scrollWidth-innerWidth,
      toolbar:rect('#practice-toolbar'),header:rect('.sidebar'),score:rect('#score-viewport'),stop:rect('#abort-attempt'),status:rect('#transport-state')};
  });
  await page.goto(fixture.url);await page.waitForFunction(()=>document.querySelector('.practice-item'));
  await page.locator('[data-status-filter="active"]').click();assert.equal(await page.locator('.practice-item').count(),5);
  await page.locator('[data-status-filter="completed"]').click();assert.equal(await page.locator('.practice-item').count(),3);
  await page.locator('[data-status-filter=""]').click();
  const inset=await card('blank').evaluate(c=>{
    const x=s=>c.querySelector(s).getBoundingClientRect().left;return {delta:x('.attempt-count')-x('h3'),height:c.getBoundingClientRect().height};
  });
  assert.ok(Math.abs(inset.delta)<=1,JSON.stringify(inset));assert.ok(inset.height<300,JSON.stringify(inset));
  assert.equal(await page.getByRole('button',{name:/^(Continue practice|Open practice room)$/}).count(),0);
  assert.equal(await card('blank').locator('.copy-task-id svg').count(),1);
  assert.equal(await card('blank').locator('.copy-task-id').innerText(),'');
  const legacy=(await state()).history.find(t=>t.recording_coverage.mode==='legacy');
  assert.match(await page.locator(`.practice-item[data-task-id="${legacy.id}"] .attempt-count`).innerText(),/Legacy practice record/);
  await page.screenshot({path:join(output,'journal-desktop-final.png')});
  await enter('main');assert.equal(await page.locator('#practice-btn').isDisabled(),true);
  await page.locator('.nav-button[data-view="settings"]').click();await page.locator('#assessment-mode').selectOption('self_report');await page.locator('#settings-back').click();assert.equal(await page.locator('#practice-btn').isDisabled(),true);
  await page.locator('.nav-button[data-view="settings"]').click();await page.locator('#assessment-mode').selectOption('automatic');await page.locator('#settings-back').click();
  assert.equal(await page.locator('#finish-btn').isDisabled(),false,'missing MIDI must not erase an earlier qualifying take');
  await page.locator('#midi-connect').click();assert.equal(await page.locator('#practice-btn').isDisabled(),false);
  await page.evaluate(()=>midiConnected(false));assert.equal(await page.locator('#practice-btn').isDisabled(),true);
  await page.evaluate(()=>midiConnected(true));assert.equal(await page.locator('#practice-btn').isDisabled(),false);
  assert.equal(await page.locator('#playback-settings>summary svg').count(),1);
  assert.equal(await page.locator('#playback-settings>summary').evaluate(e=>getComputedStyle(e).listStyleType),'none');
  assert.equal(await page.locator('#score-follow,#tempo-range,#keyboard-shortcuts,#manual-mode').count(),0);
  await page.waitForFunction(()=>document.querySelector('#attempt-feedback').dataset.attemptId);
  assert.match(await page.locator('#attempt-feedback').innerText(),/No notes were matched/);
  assert.equal(await page.locator('.result-metrics strong').nth(2).innerText(),'Not assessed');
  assert.equal(await page.locator('.attempt-row').count(),5);
  for(const [width,height] of [[1440,1000],[1280,720],[768,1024],[390,844],[320,800]]){
    await page.setViewportSize({width,height});await page.locator('#go-score').click();
    await page.waitForFunction(()=>document.querySelector('#score-viewport').getBoundingClientRect().top>=document.querySelector('#practice-toolbar').getBoundingClientRect().bottom-1);
    const m=await layout();assert.ok(m.overflow<=1,JSON.stringify(m));
    const midiOverlap=await page.evaluate(()=>{
      const button=document.querySelector('#midi-connect').getBoundingClientRect(),selector=document.querySelector('#midi-options>summary').getBoundingClientRect();
      return button.left<selector.right&&selector.left<button.right&&button.top<selector.bottom&&selector.top<button.bottom;
    });
    assert.equal(midiOverlap,false,'MIDI connection and input controls overlap');
    assert.ok(m.score.top<m.height-100,'first staff hidden '+JSON.stringify(m));
    assert.ok(m.toolbar.top>=0&&m.toolbar.bottom<m.height-120,'toolbar too large '+JSON.stringify(m));
    assert.ok(m.score.bottom<=m.height-10,'last staff hidden '+JSON.stringify(m));
    await page.screenshot({path:join(output,`score-${width}-final.png`)});
  }
  await page.setViewportSize({width:1280,height:720});await page.locator('#all-attempts').click();
  assert.equal(await page.locator('.attempt-row').count(),14);
  const oldest=await page.locator('.attempt-row').last().getAttribute('data-attempt-id');
  await page.locator('.attempt-row').last().getByText('View feedback',{exact:true}).click();
  await page.waitForFunction(id=>document.querySelector('#attempt-feedback').dataset.attemptId===id&&document.activeElement.id==='attempt-review',oldest);
  assert.equal(await page.locator('.attempt-row.is-selected').getAttribute('data-attempt-id'),oldest);
  assert.match(await page.locator('#attempt-feedback').innerText(),/Attempt 1 · 72 BPM/);
  const result=await page.locator('#attempt-review').boundingBox(),toolbar=await page.locator('#practice-toolbar').boundingBox();
  assert.ok(result.y>=toolbar.y+toolbar.height-1&&result.y<600);
  const recordedCount=(await state()).sessions.length;
  await page.locator('#selected-play').click();await page.locator('#replay-actions').waitFor({state:'visible'});
  assert.match(await page.locator('#transport-state').innerText(),/Playing attempt 1/);
  await page.locator('#replay-pause').click();assert.match(await page.locator('#replay-pause').innerText(),/Resume/);
  await page.locator('#replay-rate').selectOption('0.75');await page.locator('#replay-bar').selectOption({value:'1'});
  await page.locator('#replay-stop').click();await page.locator('#reference-play').click();
  await page.waitForFunction(()=>document.querySelector('#transport-state').textContent==='Written score playback');
  assert.equal(await page.locator('.score-live-note').count(),0,'reference playback was painted as user input');
  await page.locator('#replay-stop').click();assert.equal((await state()).sessions.length,recordedCount);
  // Selecting another result cancels an earlier take's slow playback download.
  await page.route('**/api/recordings/*/metadata*',async route=>{await new Promise(r=>setTimeout(r,500));await route.continue();});
  const pendingMetadata=page.waitForRequest('**/api/recordings/*/metadata*');
  await page.locator('.attempt-row').last().getByText('Play my take',{exact:true}).click();await pendingMetadata;
  const newest=await page.locator('.attempt-row').first().getAttribute('data-attempt-id');
  await page.locator('.attempt-row').first().getByText('View feedback',{exact:true}).click();
  await page.waitForFunction(id=>document.querySelector('#attempt-feedback').dataset.attemptId===id,newest);
  await page.waitForTimeout(650);assert.equal(await page.locator('#replay-actions').isVisible(),false);
  assert.equal(await page.locator('#attempt-feedback').getAttribute('data-attempt-id'),newest);
  assert.match(await page.locator('#replay-title').innerText(),/Attempt 14/);
  await page.unroute('**/api/recordings/*/metadata*');
  // A delayed analysis response cannot paint a different task.
  await page.route('**/api/attempts/'+oldest+'*',async route=>{await new Promise(r=>setTimeout(r,500));await route.continue();});
  await page.locator(`.attempt-row[data-attempt-id="${oldest}"]`).getByText('View feedback',{exact:true}).click();
  await list();await enter('blank');await page.waitForTimeout(650);
  assert.equal(await page.locator('#bar-results .bar-result').count(),0);assert.equal(await page.locator('.score-bar-mark').count(),0);
  assert.equal(await page.locator('#attempt-feedback').isVisible(),false);await page.unroute('**/api/attempts/'+oldest+'*');
  // Real count-in/one-pass capture, with a synthetic wrong note, preserves the
  // finite transport and keeps stop/status in view as the score scrolls.
  await list();await enter('ready');await page.setViewportSize({width:390,height:844});
  await page.locator('#tempo').fill('120');await page.locator('#tempo').dispatchEvent('change');await page.locator('#practice-btn').click();
  await page.waitForFunction(()=>document.querySelector('#transport-state').textContent==='Recording one pass');
  await page.evaluate(()=>{sendMidi([0x90,60,90]);sendMidi([0x80,60,0]);scrollBy(0,180);});
  const during=await layout();assert.ok(during.stop.top>=during.header.bottom-1&&during.stop.bottom<during.height,JSON.stringify(during));
  assert.ok(during.status.top>=during.header.bottom-1&&during.status.bottom<during.height);
  assert.equal(await page.locator('#tempo').isDisabled(),true);assert.equal(await page.locator('#click-toggle').isEnabled(),true);
  await page.screenshot({path:join(output,'recording-mobile-final.png')});
  const recording=(await state()).sessions.find(s=>s.status==='recording');
  await page.evaluate(()=>sendMidi([0x90,62,80]));
  await page.locator('.nav-button[data-view="settings"]').click();await page.locator('#language-select').selectOption('ko');await page.locator('#settings-back').click();
  assert.equal(await page.locator('#tempo').inputValue(),'120');assert.equal(await page.locator('#tempo').isDisabled(),true);
  assert.ok(await page.locator('.score-live-note').count()>0,'language refresh discarded the input trace');
  assert.equal((await state()).sessions.find(s=>s.status==='recording').id,recording.id);
  await page.locator('.nav-button[data-view="settings"]').click();await page.locator('#language-select').selectOption('en');await page.locator('#settings-back').click();
  await page.evaluate(()=>sendMidi([0x80,62,0]));
  await page.locator('#abort-attempt').click();await page.waitForFunction(()=>!document.querySelector('#practice-btn').disabled);
  assert.equal(await page.locator('.bar-result.incorrect').count(),0,'an interrupted take received failure paint');
  assert.match(await page.locator('#attempt-feedback').innerText(),/interrupted/);
  // Both exercises have byte-identical music, but different task IDs.
  await list();await enter('blank');
  assert.equal(await page.locator('#bar-results .bar-result').count(),0);assert.equal(await page.locator('.score-live-note').count(),0);
  assert.equal(await page.locator('.score-bar-mark').count(),0);assert.equal(await page.locator('#elapsed').innerText(),'00:00');
  assert.equal((await state()).history.find(t=>t.id===fixture.tasks.blank).attempts.length,0);
  await list();await enter('reopened');assert.equal(await page.locator('#finish-btn').isDisabled(),true);
  assert.match(await page.locator('#completion-hint').innerText(),/after resuming/);
  assert.match(await page.locator('.attempt-row .cycle-label').innerText(),/Before resuming/);
  await list();await card('completed').locator('.history-item').click();await page.locator('#history-dialog').waitFor({state:'visible'});
  for(const [width,height] of [[1280,720],[390,844],[320,800]]){
    await page.setViewportSize({width,height});
    for(const id of ['reopen-btn','view-score-btn','correct-btn','repeat-btn']){
      const box=await page.locator('#'+id).boundingBox();assert.ok(box.y>=0&&box.y+box.height<=height&&box.width>=90,JSON.stringify({id,width,box}));
    }
    assert.equal(await page.locator('#history-dialog').evaluate(d=>d.scrollWidth<=d.clientWidth+1),true);
  }
  await page.screenshot({path:join(output,'completed-detail-mobile-final.png')});
  // Delete has an explicit confirmation, keeps MIDI, and removes the journal item.
  const completed=(await state()).history.find(t=>t.id===fixture.tasks.completed),session=completed.attempts[0].session_id;
  const archive=await page.evaluate(id=>fetch('/api/recordings/'+id+'/metadata').then(r=>r.json()),session);
  await page.locator('#delete-practice').click();await page.locator('#delete-dialog').waitFor({state:'visible'});
  await page.screenshot({path:join(output,'delete-confirm-mobile.png')});await page.locator('#delete-cancel').click();
  assert.ok((await state()).history.some(t=>t.id===completed.id));
  await page.locator('#delete-practice').click();await page.locator('#delete-confirm').click();
  await page.locator('#delete-dialog').waitFor({state:'hidden'});await page.locator('#history-dialog').waitFor({state:'hidden'});
  assert.equal(await card('completed').count(),0);
  assert.deepEqual(await page.evaluate(id=>fetch('/api/recordings/'+id+'/metadata').then(r=>r.json()),session),archive);
  // Shared preferences survive leaving, another task, reload and another browser.
  await enter('blank');await page.locator('#click-toggle').check({force:true});await settings();
  await page.locator('#pad-toggle').check({force:true});await page.locator('#drum-toggle').check({force:true});
  const volume=async(target,id,value)=>target.locator('#'+id).evaluate((e,v)=>{e.value=v;e.dispatchEvent(new Event('input',{bubbles:true}));},value);
  await volume(page,'click-volume',.13);await volume(page,'pad-volume',.07);await volume(page,'drum-volume',.09);
  await page.locator('#backing-feel').selectOption('swing');
  await page.waitForFunction(async()=>{const s=await fetch('/api/playback-settings').then(r=>r.json());return s.values.drum_feel==='swing'&&s.values.pad_volume===.07&&s.values.metronome_enabled&&s.values.pad_enabled&&s.values.drums_enabled;});
  await list();await enter('ready');assert.equal(await page.locator('#click-toggle').isChecked(),true);
  await settings();assert.equal(await page.locator('#pad-toggle').isChecked(),true);assert.equal(await page.locator('#drum-toggle').isChecked(),true);
  await list();await page.reload();await page.waitForFunction(()=>document.querySelector('.practice-item'));await enter('blank');
  assert.equal(await page.locator('#click-toggle').isChecked(),true);assert.equal(await page.locator('#practice-btn').isDisabled(),true);
  assert.match(await page.locator('#completion-hint').innerText(),/Connect MIDI/);
  await settings();assert.equal(await page.locator('#backing-feel').inputValue(),'swing');assert.equal(await page.locator('#pad-volume').inputValue(),'0.07');
  const other=await browser.newPage();await other.goto(fixture.url);await other.waitForFunction(()=>document.querySelector('.practice-item'));
  await other.locator(`.practice-item[data-task-id="${fixture.tasks.blank}"] .history-item`).click();
  await other.locator('#playback-settings').evaluate(e=>e.open=true);assert.equal(await other.locator('#pad-toggle').isChecked(),true);
  await other.locator('#drum-toggle').uncheck({force:true});await volume(other,'click-volume',.21);
  await page.waitForFunction(()=>!document.querySelector('#drum-toggle').checked&&document.querySelector('#click-volume').value==='0.21');
  await page.route('**/api/playback-settings*',async route=>route.request().method()==='GET'?route.fulfill({status:503,contentType:'application/json',body:'{}'}):route.continue());
  await page.waitForTimeout(3200);assert.equal(await page.locator('#pad-toggle').isChecked(),true);assert.equal(await page.locator('#click-volume').inputValue(),'0.21');
  await page.unroute('**/api/playback-settings*');await other.close();
  await page.evaluate(()=>syntheticAudio.suspend());await page.locator('#error').waitFor({state:'visible'});
  assert.equal(await page.locator('#click-toggle').isChecked(),true);assert.equal(await page.locator('#pad-toggle').isChecked(),true);
  await list();
  await page.locator('.nav-button[data-view="settings"]').click();await page.locator('#language-select').selectOption('ko');await page.locator('#settings-back').click();
  await page.waitForFunction(()=>document.querySelector('#connection').textContent==='로컬에 연결됨');
  assert.doesNotMatch(await page.locator('.attempt-count').first().innerText(),/attempts|successes/);
  await page.screenshot({path:join(output,'journal-mobile-ko-final.png')});await enter('main');await page.locator('#go-score').click();
  await page.locator('.nav-button[data-view="settings"]').click();await page.locator('#assessment-mode').selectOption('self_report');await page.locator('#settings-back').click();
  assert.equal(await page.locator('#assessment-mode').inputValue(),'self_report');
  await page.screenshot({path:join(output,'score-mobile-ko-final.png')});
  assert.deepEqual(errors,[]);
  await writeFile(join(output,'ux-result.json'),JSON.stringify({passed:true,viewports:5,checks:['task-scoped paint and late-response guards','visible score/stop/status','selected take identity and playback','unknown assessment presentation','reopen gate explanation','compact cards/status filters','fixed dialog actions','MIDI connection gate','icons and full score fit','legacy coverage','delete confirmation and preserved MIDI','shared sound settings across tasks/reload/clients/read failure','English/Korean'],errors},null,2));
  console.log('UX regressions passed: scoped paint, five viewports, fixed controls, selected playback, journal and completed details.');
} catch(error) {
  const page=browser?.contexts()[0]?.pages()[0];if(page){await page.screenshot({path:join(output,'ux-failure.png'),fullPage:true});await writeFile(join(output,'ux-failure.txt'),await page.locator('body').innerText());}throw error;
} finally {await browser?.close();server.kill('SIGTERM');await rm(root,{recursive:true,force:true});}
