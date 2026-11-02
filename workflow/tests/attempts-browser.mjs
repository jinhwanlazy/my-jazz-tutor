// End-to-end finite takes using synthetic MIDI, temp records and real Web Audio.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp,mkdir,rm,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const project=resolve(import.meta.dirname,'..'),root=await mkdtemp(join(tmpdir(),'jazz-browser-'));
const output=join(project,'build/attempt-redesign-0.7.0');await mkdir(output,{recursive:true});
await writeFile(join(root,'profile.json'),'{"daily_minutes":30,"language":"en"}');
const server=spawn('uv',['run','python','tests/serve_browser.py',root],{cwd:project});
let browser;
try {
  const url=await new Promise((resolve,reject)=>{
    let text='';const timeout=setTimeout(()=>reject(Error(text||'Server timeout')),15000);
    server.stdout.on('data',chunk=>{text+=chunk;const match=text.match(/http:\/\/127\.0\.0\.1:\d+/);if(match){clearTimeout(timeout);resolve(match[0]);}});
    server.stderr.on('data',chunk=>text+=chunk);server.on('error',reject);
  });
  browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_EXECUTABLE||'/usr/bin/google-chrome',args:['--no-sandbox']});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('dialog',dialog=>dialog.accept());
  await page.addInitScript(()=>{
    const port={id:'synthetic-midi',name:'Synthetic piano',state:'connected',type:'input'};
    Object.defineProperty(navigator,'requestMIDIAccess',{value:async()=>({inputs:new Map([[port.id,port]])})});
    window.sendMidi=(data,timeStamp=performance.now())=>port.onmidimessage?.({data:Uint8Array.from(data),timeStamp});
    window.audioStarts=0;window.drumStarts=0;
    const make=AudioContext.prototype.createOscillator;
    AudioContext.prototype.createOscillator=function(){const osc=make.call(this),start=osc.start.bind(osc);osc.start=(...args)=>{window.audioStarts++;return start(...args);};return osc;};
    const buffer=AudioContext.prototype.createBufferSource;
    AudioContext.prototype.createBufferSource=function(){const source=buffer.call(this),start=source.start.bind(source);source.start=(...args)=>{window.drumStarts++;return start(...args);};return source;};
  });
  await page.goto(url);await page.waitForFunction(()=>document.querySelector('#connection').textContent==='Connected locally');
  const state=()=>page.evaluate(()=>fetch('/api/state').then(r=>r.json()));
  async function create(request='simulate:attempt') {
    if(!await page.locator('#recommendation-request').isVisible())await page.locator('#recommendation-focus summary').click();
    await page.locator('#recommendation-request').fill(request);await page.locator('#new-practice').click();
    await page.waitForFunction(()=>document.querySelector('#new-practice').disabled===false);
    const data=await state();assert.equal(data.recommendation.state,'completed',JSON.stringify(data.recommendation));
    return data.history[0].id;
  }
  const first=await create(),second=await create();assert.notEqual(first,second);
  assert.equal((await state()).history.filter(t=>t.pending).length,2);
  await page.locator(`.practice-item[data-task-id="${first}"] .history-item`).click();
  await page.locator('.abc-score').waitFor();await page.locator('#midi-connect').click();
  assert.equal(await page.locator('#finish-btn').isDisabled(),true);
  assert.equal(await page.locator('#pad-toggle').isEnabled(),true);assert.match(await page.locator('#backing-status').innerText(),/chord symbols/);
  assert.equal(await page.locator('#score-help').count(),0);
  // Independent click/pad/drum controls do not create recordings.
  await page.locator('#click-toggle').check({force:true});await page.locator('#pad-toggle').check({force:true});await page.locator('#drum-toggle').check({force:true});
  await page.waitForFunction(()=>window.audioStarts>3&&window.drumStarts>0);
  assert.equal((await state()).sessions.length,0);
  await page.locator('#pad-toggle').uncheck({force:true});await page.locator('#drum-toggle').uncheck({force:true});
  await page.evaluate(async()=>{
    const {Capture}=await import('/capture.mjs');const old=Capture.prototype.event;
    Capture.prototype.event=function(type,values={},at=performance.now()) {
      old.call(this,type,values,at);
      window.syntheticCapture=this;
      if(type!=='play'||window.syntheticMode==='none')return;
      const contract=window.syntheticContract;
      for(const note of contract.expected){const pitch=note.pitch+(window.syntheticMode==='wrong'?1:0),beat=60000/contract.bpm;
        for(const [when,data] of [[at+note.at*beat,[0x90,pitch,note.accent?105:75]],
          [at+(note.at+note.duration*.95)*beat,[0x80,pitch,0]]])
          setTimeout(()=>window.sendMidi(data,when),Math.max(0,when-performance.now()+2));
      }
    };
  });
  async function take(mode='good') {
    const response=page.waitForResponse(r=>r.url().includes('/api/attempts/start')&&r.request().method()==='POST');
    await page.evaluate(mode=>window.syntheticMode=mode,mode);
    await page.locator('#practice-btn').click();const started=await (await response).json();
    await page.evaluate(contract=>window.syntheticContract=contract,started.attempt.contract);
    return started;
  }
  await take('wrong');assert.equal(await page.locator('#tempo').isDisabled(),true);
  assert.equal(await page.locator('#click-toggle').isEnabled(),true);
  await page.waitForFunction(()=>document.querySelectorAll('.attempt-row').length===1&&document.querySelector('#practice-btn').disabled===false);
  assert.equal(await page.locator('#finish-btn').isDisabled(),true);assert.match(await page.locator('#attempt-feedback').innerText(),/Needs another try/);
  await take();await page.waitForFunction(()=>document.querySelector('.bar-result.correct'));
  await page.waitForFunction(()=>document.querySelectorAll('.attempt-row').length===2&&document.querySelector('#finish-btn').disabled===false);
  assert.match(await page.locator('#attempt-feedback').innerText(),/Successful take/);
  assert.equal((await state()).sessions.length,2);assert.equal(await page.locator('.score-bar-mark.correct').count(),2);
  assert.equal(await page.locator('#score-position').innerText(),'');
  assert.equal(await page.locator('#click-toggle').isChecked(),true);
  await page.screenshot({path:join(output,'successful-attempt-desktop.png'),fullPage:true});
  // Both recorded and reference playback must remain read-only.
  await page.locator('.attempt-row').first().getByText('Play my take',{exact:true}).click();
  await page.locator('#replay-rate').selectOption('0.5');await page.locator('#replay-bar').selectOption('1');
  await page.locator('#replay-pause').click();assert.match(await page.locator('#replay-pause').innerText(),/Resume/);
  await page.locator('#replay-pause').click();await page.locator('#replay-stop').click();
  await page.locator('#reference-play').click();await page.locator('#replay-stop').click();
  assert.equal((await state()).sessions.length,2);
  await page.locator('#finish-btn').click();await page.locator('#complete-cancel').click();
  assert.equal((await state()).history.find(t=>t.id===first).pending,true);
  await page.locator('#finish-btn').click();await page.locator('#complete-confirm').click();
  await page.locator('#record-panel').waitFor({state:'visible'});await page.locator('#close-record').click();
  assert.equal((await state()).history.find(t=>t.id===first).completed,true);
  assert.equal((await state()).history.find(t=>t.id===first).report,null);
  await page.locator(`.practice-item[data-task-id="${first}"] .history-item`).click();
  await page.locator('#reopen-btn').click();await page.locator('#history-dialog').waitFor({state:'hidden'});
  await page.locator(`.practice-item[data-task-id="${first}"] .history-item`).click();
  assert.equal(await page.locator('#finish-btn').isDisabled(),true);
  await take('none');await page.locator('#abort-attempt').click();
  await page.waitForFunction(()=>document.querySelectorAll('.attempt-row').length===3&&document.querySelector('#practice-btn').disabled===false);
  assert.equal((await state()).history.find(t=>t.id===first).attempts.at(-1).state,'aborted');
  // Save retry after a sealed take is idempotent and does not add a second attempt.
  await page.locator('#manual-mode').check({force:true});await page.locator('#click-toggle').uncheck({force:true});
  let failOnce=true;await page.route('**/api/sessions/finish*',async route=>{
    if(failOnce){failOnce=false;await route.fulfill({status:503,contentType:'application/json',body:'{"error":"Synthetic temporary failure"}'});}else await route.continue();
  });
  await take('none');await page.waitForFunction(()=>document.querySelector('#abort-attempt').textContent==='Retry save');
  await page.locator('#abort-attempt').click();
  await page.waitForFunction(()=>document.querySelectorAll('.attempt-row').length===4&&document.querySelector('#finish-btn').disabled===false);
  await page.unroute('**/api/sessions/finish*');
  await page.locator('#finish-btn').click();await page.locator('#complete-confirm').click();
  assert.equal(await page.locator('#complete-dialog').isVisible(),true);
  await page.locator('#manual-confirm').check({force:true});await page.locator('#complete-confirm').click();
  await page.locator('#record-panel').waitFor({state:'visible'});await page.locator('[data-rating="challenging"]').click();
  await page.locator('#memo-details').evaluate(e=>e.open=true);await page.locator('#raw-note').fill('Synthetic optional note');await page.locator('#save-note').click();await page.locator('#close-record').click();
  const completed=(await state()).history.find(t=>t.id===first);assert.equal(completed.completions.length,2);
  assert.equal(completed.report.raw_note,'Synthetic optional note');assert.equal(completed.attempts.length,4);
  // Skip is beside attempt/complete and requires a written reason.
  await page.locator(`.practice-item[data-task-id="${second}"] .history-item`).click();
  await page.locator('#discard-btn').click();await page.locator('#discard-submit').click();
  assert.equal(await page.locator('#discard-dialog').isVisible(),true);
  await page.locator('#discard-reason').fill('Synthetic: already familiar');await page.locator('#discard-submit').click();
  await page.locator('#view-list').waitFor({state:'visible'});
  assert.equal((await state()).history.find(t=>t.id===second).reason,'Synthetic: already familiar');
  // Reload an unfinished take after a durable checkpoint; recovery preserves it
  // as interrupted and never enters the room or awards completion.
  const recoveredTask=await create();
  await page.locator(`.practice-item[data-task-id="${recoveredTask}"] .history-item`).click();
  await take('none');await page.waitForFunction(()=>document.querySelector('#transport-state').textContent==='Recording one pass');
  await page.evaluate(async()=>{sendMidi([0x90,60,80]);sendMidi([0x80,60,0]);await syntheticCapture.checkpoint();});
  await page.reload();await page.locator('#recovery').waitFor({state:'visible'});await page.locator('#recover-btn').click();
  await page.locator('#recovery').waitFor({state:'hidden'});
  const recovered=(await state()).history.find(t=>t.id===recoveredTask);
  assert.equal(recovered.pending,true);assert.equal(recovered.attempts[0].state,'interrupted');
  assert.equal(recovered.assessment.eligible,false);assert.equal(await page.locator('#view-list').isVisible(),true);
  await page.locator('[data-view="settings"]').click();await page.locator('#language-select').selectOption('ko');
  await page.locator('#settings-back').click();await page.locator(`.practice-item[data-task-id="${first}"] .history-item`).click();
  await page.locator('#view-score-btn').click();await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:join(output,'attempt-history-mobile-ko.png'),fullPage:true});
  assert.match(await page.locator('#practice-btn').innerText(),/시도/);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
  assert.equal(await page.locator('#score-viewport').evaluate(e=>e.scrollWidth<=e.clientWidth+1),true);
  assert.deepEqual(errors,[]);console.log('Finite attempts, live analysis, completion/reopen, multiple tasks, backing, replay, retry, skip and mobile Korean passed.');
} catch(error) {const page=browser?.contexts()[0]?.pages()[0];if(page){await page.screenshot({path:join(output,'failure.png'),fullPage:true});console.error(await page.locator('body').innerText());}throw error;} finally {await browser?.close();server.kill('SIGTERM');await rm(root,{recursive:true,force:true});}
