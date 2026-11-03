// Synthetic MiniLab ports/permissions and disposable records; no physical MIDI.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp,mkdir,rm,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const project=resolve(import.meta.dirname,'..'),root=await mkdtemp(join(tmpdir(),'jazz-browser-controls-'));
const output=join(project,'build/score-layout-0.10.0');await mkdir(output,{recursive:true});
await writeFile(join(root,'profile.json'),'{"daily_minutes":30,"language":"en"}');
const server=spawn('uv',['run','python','tests/serve_browser.py',root],{cwd:project});let browser;
try {
  const url=await new Promise((resolve,reject)=>{
    let log='';const timer=setTimeout(()=>reject(Error(log||'Server timeout')),15000);
    server.stdout.on('data',chunk=>{log+=chunk;const match=log.match(/http:\/\/127\.0\.0\.1:\d+/);if(match){clearTimeout(timer);resolve(match[0]);}});
    server.stderr.on('data',chunk=>log+=chunk);server.on('error',reject);
  });
  browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_EXECUTABLE||'/usr/bin/google-chrome',args:['--no-sandbox']});
  const page=await browser.newPage({viewport:{width:1280,height:900}}),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.addInitScript(()=>{
    const keys={id:'keys-a',name:'MiniLab 3 MIDI',manufacturer:'Arturia',type:'input',state:localStorage.getItem('synthetic.absent')?'disconnected':'connected'};
    const other={id:'keys-b',name:'Other keyboard',manufacturer:'Synthetic',type:'input',state:'connected'};
    const surface={id:'control',name:'MiniLab 3 MCU/HUI',manufacturer:'Arturia',type:'input',state:'connected'};
    const access={inputs:new Map([keys,other,surface].map(port=>[port.id,port]))};window.midiRequests=0;
    Object.defineProperty(navigator,'requestMIDIAccess',{value:async()=>{
      window.midiRequests++;if(localStorage.getItem('synthetic.permission')==='denied')throw Error('denied');
      localStorage.setItem('synthetic.permission','granted');return access;
    }});
    const query=navigator.permissions.query.bind(navigator.permissions);
    Object.defineProperty(navigator.permissions,'query',{value:async descriptor=>descriptor.name==='midi'?
      {state:localStorage.getItem('synthetic.permission')||'prompt'}:query(descriptor)});
    window.sendMidi=(id,data)=>access.inputs.get(id)?.onmidimessage?.({data:Uint8Array.from(data),timeStamp:performance.now()});
    window.tapPad=number=>{sendMidi('control',[0x90,number,127]);sendMidi('control',[0x80,number,0]);};
    window.replugKeys=()=>{
      keys.state='disconnected';access.onstatechange?.({port:keys});access.inputs.delete(keys.id);
      keys.id='keys-a-replug';keys.state='connected';access.inputs.set(keys.id,keys);access.onstatechange?.({port:keys});
    };
    window.forgetKeys=()=>{keys.state='disconnected';access.inputs.delete(keys.id);access.onstatechange?.({port:keys});};
  });
  const state=()=>page.evaluate(()=>fetch('/api/state').then(r=>r.json()));
  const waitList=()=>page.waitForFunction(()=>document.querySelector('.practice-item'));
  const enter=async()=>{await page.locator('.history-item').first().click();await page.locator('#view-practice').waitFor({state:'visible'});};
  const settings=async()=>{await page.locator('.nav-button[data-view="settings"]').click();};
  const room=async()=>{await page.locator('#settings-back').click();};
  const selectInput=async value=>{await page.locator('#midi-options').evaluate(e=>e.open=true);await page.locator('#midi-input').selectOption({value});};
  const pad=number=>page.evaluate(number=>tapPad(number),number);
  await page.goto(url);await page.waitForFunction(()=>document.querySelector('#connection').textContent==='Connected locally');
  await page.locator('#recommendation-focus summary').click();await page.locator('#recommendation-request').fill('simulate:attempt');
  await page.locator('#new-practice').click();await waitList();await enter();
  assert.equal(await page.evaluate(()=>midiRequests),0);assert.equal(await page.locator('#practice-btn').isDisabled(),true);
  await page.locator('#score-viewport').focus();await page.keyboard.press('r');assert.equal((await state()).sessions.length,0);
  await page.locator('#midi-connect').click();await selectInput('keys-a');
  assert.equal(await page.locator('#midi-input option[value="control"]').count(),0,'MCU was offered as performance input');
  for(const [action,number] of [['record',95],['stop',93],['play',94]]){
    await settings();await page.locator(`[data-learn-action="${action}"]`).click();
    await page.locator('#midi-learn-dialog').waitFor({state:'visible'});
    await page.evaluate(()=>sendMidi('control',[0xb0,27,127]));
    assert.equal(await page.locator('#midi-learn-dialog').isVisible(),true,'learned the Shift modifier');
    if(action==='stop'){
      await pad(95);assert.match(await page.locator('#midi-learn-status').innerText(),/already assigned/);
      assert.equal(await page.locator('#midi-learn-dialog').isVisible(),true);
    }
    await pad(number);await page.locator('#midi-learn-dialog').waitFor({state:'hidden'});
    assert.match(await page.locator(`[data-midi-binding="${action}"]`).innerText(),new RegExp('Note '+number));
    assert.equal((await state()).sessions.length,0,'learning a pad started an attempt');
  }
  // A reload restores prior permission, device selection and pad assignments.
  await page.reload();await waitList();await enter();await page.waitForFunction(()=>!document.querySelector('#practice-btn').disabled);
  assert.equal(await page.evaluate(()=>midiRequests),1);assert.equal(await page.locator('#midi-input').inputValue(),'keys-a');
  await settings();assert.match(await page.locator('[data-midi-binding="record"]').innerText(),/Note 95/);await room();
  for(const id of ['score-follow','tempo-range','keyboard-shortcuts','controller-shortcuts','manual-mode'])assert.equal(await page.locator('#'+id).count(),0);
  assert.match(await page.locator('#practice-btn').getAttribute('title'),/R.*Shift \+ Pad 7/);
  await page.locator('#go-score').click();
  await page.keyboard.press('r');await page.waitForFunction(()=>document.querySelector('#transport-state').textContent==='Recording one pass');
  await page.evaluate(()=>{sendMidi('keys-a',[0x90,95,75]);sendMidi('keys-a',[0x80,95,0]);});
  const scroll=await page.evaluate(()=>scrollY);
  await page.waitForFunction(()=>document.querySelectorAll('.attempt-row').length===1&&!document.querySelector('#practice-btn').disabled);
  assert.ok(Math.abs(await page.evaluate(()=>scrollY)-scroll)<20,'automatic completion moved the page');
  assert.notEqual(await page.evaluate(()=>document.activeElement.id),'attempt-review');
  let saved=await state();assert.equal(saved.sessions.length,1);
  // Record retries once; pressure/repeated press and Play cannot interrupt a take.
  await page.evaluate(()=>{sendMidi('control',[0x90,95,127]);sendMidi('control',[0xa0,95,100]);sendMidi('control',[0x90,95,100]);});
  await page.waitForFunction(()=>document.querySelector('#transport-state').textContent==='Recording one pass');
  await pad(94);await page.evaluate(()=>{sendMidi('keys-a',[0x90,60,80]);sendMidi('keys-a',[0x80,60,0]);});
  assert.equal(await page.locator('#replay-actions').isVisible(),false);
  await pad(93);await page.evaluate(()=>sendMidi('control',[0x80,95,0]));
  await page.waitForFunction(()=>document.querySelectorAll('.attempt-row').length===2&&!document.querySelector('#practice-btn').disabled);
  saved=await state();assert.equal(saved.sessions.length,2);assert.equal(saved.history[0].attempts[1].state,'aborted');
  const raw=await page.evaluate(async ids=>{
    const {decodeMidiFrames}=await import('/capture.mjs');return Promise.all(ids.map(async id=>decodeMidiFrames(await (await fetch('/api/recordings/'+id+'/midi')).arrayBuffer())));
  },saved.sessions.map(s=>s.id));
  assert.deepEqual(raw.flat().filter(f=>(f.data[0]&0xf0)===0x90).map(f=>f.data[1]),[95,60], 'transport pads polluted the recorded MIDI');
  // Explicit feedback selection may scroll; keyboard/controller playback does not steal focus.
  await page.locator('.attempt-row').last().getByText('View feedback',{exact:true}).click();
  await page.waitForFunction(()=>document.activeElement.id==='attempt-review'&&document.querySelector('#attempt-feedback').textContent.includes('Attempt 1'));
  await page.keyboard.press('Space');await page.locator('#replay-actions').waitFor({state:'visible'});
  await pad(94);assert.match(await page.locator('#replay-pause').innerText(),/Resume/);
  await pad(94);assert.match(await page.locator('#replay-pause').innerText(),/Pause/);
  await page.keyboard.press('s');await page.locator('#replay-actions').waitFor({state:'hidden'});
  assert.equal((await state()).sessions.length,2);
  await page.locator('#tempo').focus();await page.keyboard.press('r');assert.equal((await state()).sessions.length,2);
  await settings();await page.keyboard.press('r');await pad(95);assert.equal((await state()).sessions.length,2);await room();
  await page.locator('#back-list').click();await page.keyboard.press('r');await pad(95);assert.equal((await state()).sessions.length,2);
  // Explicit opt-out and revoked permission never pretend to be connected.
  await page.locator('#midi-options').evaluate(e=>e.open=true);await page.locator('#midi-reconnect').uncheck({force:true});
  await page.reload();await waitList();await enter();assert.equal(await page.evaluate(()=>midiRequests),0);
  assert.equal(await page.locator('#practice-btn').isDisabled(),true);
  await page.locator('#midi-options').evaluate(e=>e.open=true);await page.locator('#midi-reconnect').check({force:true});
  await page.evaluate(()=>localStorage.setItem('synthetic.permission','denied'));await page.reload();await waitList();await enter();
  await page.waitForFunction(()=>document.querySelector('#midi-status').textContent.includes('Allow MIDI'));
  assert.equal(await page.evaluate(()=>midiRequests),0);assert.equal(await page.locator('#practice-btn').isDisabled(),true);
  await page.evaluate(()=>{localStorage.setItem('synthetic.permission','granted');localStorage.setItem('synthetic.absent','yes');});
  await page.reload();await waitList();await enter();await page.waitForFunction(()=>midiRequests===1);
  assert.equal(await page.locator('#midi-input').inputValue(),'keys-a');assert.equal(await page.locator('#practice-btn').isDisabled(),true,'fell back to another keyboard');
  await page.evaluate(()=>forgetKeys());await selectInput('keys-a');
  await page.reload();await waitList();await enter();await page.waitForFunction(()=>midiRequests===1);
  assert.equal(await page.locator('#midi-input').inputValue(),'keys-a','missing input selection was lost');
  await page.evaluate(()=>replugKeys());await page.waitForFunction(()=>!document.querySelector('#practice-btn').disabled);
  assert.equal(await page.locator('#midi-input').inputValue(),'keys-a-replug');
  await settings();await page.locator('#assessment-mode').selectOption('self_report');await room();
  await selectInput('none');await page.reload();await waitList();await enter();await page.waitForFunction(()=>midiRequests===1);
  assert.equal(await page.locator('#midi-input').inputValue(),'none');assert.equal(await page.locator('#practice-btn').isDisabled(),true);
  assert.equal(await page.locator('#assessment-mode').inputValue(),'self_report','assessment preference was lost on reload');
  assert.equal(await page.locator('#error').isVisible(),false);assert.deepEqual(errors,[]);
  await page.setViewportSize({width:390,height:844});await settings();
  await page.locator('[data-midi-binding="stop"]').scrollIntoViewIfNeeded();
  await page.screenshot({path:join(output,'controller-settings-mobile.png')});
  await writeFile(join(output,'checks.json'),JSON.stringify({passed:true,checks:['no automatic result scrolling','keyboard record/retry/play/stop','MiniLab learn and conflict guards','no pad contamination','auto reconnect and selection','permission/absence/opt-out handling'],errors},null,2));
  console.log('Controller, keyboard, scroll preservation and MIDI reconnect regressions passed.');
} catch(error){const page=browser?.contexts()[0]?.pages()[0];if(page){await page.screenshot({path:join(output,'failure.png'),fullPage:true});await writeFile(join(output,'failure.txt'),await page.locator('body').innerText());}throw error;
} finally {await browser?.close();server.kill('SIGTERM');await rm(root,{recursive:true,force:true});}
