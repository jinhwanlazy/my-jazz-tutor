import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp,mkdir,writeFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const project=resolve(import.meta.dirname,'..'),root=await mkdtemp(join(tmpdir(),'jazz-browser-note-feedback-'));
const output=join(project,'build/note-feedback-0.11.0');await mkdir(output,{recursive:true});
const server=spawn('uv',['run','python','tests/serve_note_browser.py',root],{cwd:project});let browser;
try {
  const fixture=await new Promise((resolve,reject)=>{
    let log='';const timer=setTimeout(()=>reject(Error(log||'Server timeout')),15000);
    server.stdout.on('data',chunk=>{log+=chunk;try{const value=JSON.parse(log.split('\n')[0]);clearTimeout(timer);resolve(value);}catch{}});
    server.stderr.on('data',chunk=>log+=chunk);server.on('error',reject);
  });
  browser=await chromium.launch({headless:true,executablePath:'/usr/bin/google-chrome',args:['--no-sandbox']});
  const page=await browser.newPage({viewport:{width:1280,height:800}}),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  page.on('console',message=>{if(message.type()==='error')errors.push(message.text());});
  await page.addInitScript(()=>{
    const port={id:'synthetic-piano',name:'Synthetic piano',state:'connected',type:'input'};
    Object.defineProperty(navigator,'requestMIDIAccess',{value:async()=>({inputs:new Map([[port.id,port]])})});
    window.sendMidi=(data,timeStamp=performance.now())=>port.onmidimessage?.({data:Uint8Array.from(data),timeStamp});
  });
  const state=()=>page.evaluate(()=>fetch('/api/state?lang=en').then(r=>r.json()));
  await page.goto(fixture.url);await page.waitForFunction(()=>document.querySelector('.practice-item'));
  const oldBefore=await page.evaluate(id=>fetch('/api/attempts/'+id).then(r=>r.json()),fixture.legacy_attempt);
  await page.locator(`.practice-item[data-task-id="${fixture.current}"] .history-item`).click();
  await page.locator('#midi-connect').click();
  await page.evaluate(async()=>{
    const {Capture}=await import('/capture.mjs'),original=Capture.prototype.event;
    Capture.prototype.event=function(type,values={},at=performance.now()){
      original.call(this,type,values,at);if(type!=='play')return;
      const notes=window.syntheticContract.expected,beat=60000/window.syntheticContract.bpm,bad=window.badTake;
      const send=(when,data)=>setTimeout(()=>sendMidi(data,when),Math.max(0,when-performance.now()+2));
      for(const note of notes){
        if(bad&&note.pitch===60&&note.at===0)continue;
        const offset=bad&&note.pitch===64&&note.at===0?120:0;
        send(at+note.at*beat+offset,[0x90,note.pitch,80]);
        send(at+(note.at+note.duration*(bad&&note.pitch===72?.1:.95))*beat+offset,[0x80,note.pitch,0]);
      }
      if(bad){send(at+5,[0x90,61,80]);send(at+150,[0x80,61,0]);}
    };
  });
  async function take(bad){
    await page.evaluate(bad=>window.badTake=bad,bad);
    const response=page.waitForResponse(r=>r.url().includes('/api/attempts/start')&&r.request().method()==='POST');
    await page.locator('#practice-btn').click();const started=await(await response).json();
    await page.evaluate(contract=>window.syntheticContract=contract,started.attempt.contract);return started;
  }
  await take(true);
  await page.waitForFunction(()=>document.querySelector('.score-written-note[data-midi="67"][data-note-state="correct"]')&&document.querySelector('#score-position').textContent==='Bar 1 / 2');
  await page.waitForFunction(()=>document.querySelector('.score-written-note[data-midi="60"][data-note-state="missing"]')&&document.querySelector('.score-written-note[data-midi="64"][data-note-state="incorrect"]'));
  assert.equal(await page.locator('.score-bar-mark,#bar-results').count(),0);
  assert.equal(await page.locator('.score-extra-note[data-midi="61"]').count(),1);
  assert.ok(await page.locator('.score-written-note[data-note-state="waiting"]').count()>0,'future notes were prematurely graded');
  await page.screenshot({path:join(output,'live-note-feedback.png')});
  const scroll=await page.evaluate(()=>scrollY);
  await page.waitForFunction(()=>document.querySelectorAll('.attempt-row').length===1&&!document.querySelector('#practice-btn').disabled);
  assert.ok(Math.abs(await page.evaluate(()=>scrollY)-scroll)<2,'saving moved the page');
  assert.equal(await page.locator('#finish-btn').isDisabled(),true);
  assert.equal(await page.locator('.score-written-note[data-midi="72"][data-note-state="incorrect"]').count(),1);
  await page.locator('#attempt-feedback details').evaluate(e=>e.open=true);
  assert.equal(await page.locator('.note-analysis tbody tr').count(),9);
  assert.match(await page.locator('.note-analysis').innerText(),/Missing note/);
  assert.match(await page.locator('.note-analysis').innerText(),/Too late/);
  assert.match(await page.locator('.note-analysis').innerText(),/Too short/);
  const failed=(await state()).history.find(t=>t.id===fixture.current).attempts[0];
  assert.equal(failed.analysis_version,'midi-analysis-2');assert.equal(failed.qualified_pass,false);
  await page.locator('#go-score').click();await page.screenshot({path:join(output,'finished-note-feedback.png')});
  await take(false);await page.waitForFunction(()=>document.querySelectorAll('.attempt-row').length===2&&!document.querySelector('#finish-btn').disabled);
  assert.equal(await page.locator('.score-written-note[data-note-state="correct"]').count(),8);
  assert.equal(await page.locator('.score-missing-note,.score-extra-note').count(),0);
  await page.locator('#finish-btn').click();await page.locator('#complete-confirm').click();
  await page.locator('#record-panel').waitFor({state:'visible'});await page.locator('#close-record').click();
  await page.locator(`.practice-item[data-task-id="${fixture.legacy}"] .history-item`).click();
  await page.waitForFunction(()=>document.querySelectorAll('.score-written-note[data-note-state="correct"]').length===8);
  await page.locator('.nav-button[data-view="settings"]').click();await page.locator('#language-select').selectOption('ko');await page.locator('#settings-back').click();
  await page.waitForFunction(()=>document.querySelector('.score-written-note title[data-feedback]')?.textContent.includes('정확'));
  await page.setViewportSize({width:390,height:844});await page.locator('#go-score').click();
  assert.ok(await page.locator('#score-viewport').evaluate(e=>e.scrollWidth<=e.clientWidth+1&&e.getBoundingClientRect().bottom<=innerHeight-10));
  await page.screenshot({path:join(output,'note-feedback-mobile-ko.png')});
  assert.deepEqual(await page.evaluate(id=>fetch('/api/attempts/'+id).then(r=>r.json()),fixture.legacy_attempt),oldBefore);
  await page.locator('#back-list').click();await page.locator(`.practice-item[data-task-id="${fixture.many}"] .history-item`).click();
  await page.waitForFunction(()=>document.querySelectorAll('.score-written-note[data-note-state="correct"]').length===208);
  await page.locator('#attempt-feedback details').evaluate(e=>e.open=true);
  assert.equal(await page.locator('.note-analysis tbody tr').count(),100);
  await page.locator('.note-pagination button').last().click();
  assert.equal(await page.locator('.note-analysis tbody tr').first().getAttribute('data-expected-index'),'100');
  await page.locator('.note-pagination button').last().click();assert.equal(await page.locator('.note-analysis tbody tr').count(),8);
  assert.equal(await page.locator('.note-analysis tbody tr').first().getAttribute('data-expected-index'),'200');
  assert.equal(await page.locator('.note-analysis').evaluate(e=>e.parentElement.scrollTop),0);
  assert.equal((await state()).sessions.length,4);assert.deepEqual(errors,[]);
  await writeFile(join(output,'browser-checks.json'),JSON.stringify({passed:true,checks:['live note feedback before bar end','independent chord tones','missing and extra notes','timing and note length','completion gate','old saved analysis unchanged','Korean and mobile score fit'],errors},null,2));
  console.log('Individual note feedback, live chord isolation, timing/length, completion and immutable legacy analysis passed.');
} catch(error){const page=browser?.contexts()[0]?.pages()[0];if(page){await page.screenshot({path:join(output,'failure.png'),fullPage:true});await writeFile(join(output,'failure.txt'),await page.locator('body').innerText());}throw error;
} finally {await browser?.close();server.kill('SIGTERM');await rm(root,{recursive:true,force:true});}
