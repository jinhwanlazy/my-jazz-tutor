// Real app, synthetic provider/MIDI, temporary records. No production access.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp, mkdir, writeFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = await mkdtemp(join(tmpdir(), 'jazz-browser-abc-'));
await writeFile(join(root, 'profile.json'), JSON.stringify({language:'en',daily_minutes:30}));
await mkdir('build/abc-browser', {recursive:true});
const server = spawn('uv', ['run','python','tests/serve_browser.py',root]);
let browser;
try {
  const url = await new Promise((resolve,reject)=>{
    let output='';const timeout=setTimeout(()=>reject(Error('Server startup timeout')),10000);
    server.stdout.on('data',chunk=>{output+=chunk;const match=output.match(/http:\/\/127\.0\.0\.1:\d+/);if(match){clearTimeout(timeout);resolve(match[0]);}});
    server.on('error',reject);
  });
  browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_EXECUTABLE||'/usr/bin/google-chrome',args:['--no-sandbox']});
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  page.on('console',message=>{if(message.type()==='error')errors.push(message.text());});
  await page.addInitScript(()=>{
    const port={id:'synthetic-midi',name:'Synthetic test input',state:'connected',type:'input'};
    Object.defineProperty(navigator,'requestMIDIAccess',{value:async()=>({inputs:new Map([[port.id,port]])})});
    window.sendMidi=data=>port.onmidimessage?.({data:Uint8Array.from(data),timeStamp:performance.now()});
  });
  await page.goto(url);
  await page.waitForFunction(()=>document.querySelector('#connection').textContent==='Connected locally');
  await page.locator('#recommendation-focus summary').click();
  await page.locator('#recommendation-request').fill('simulate:abc12 3/4');
  await page.locator('#new-practice').click();
  await page.waitForFunction(()=>document.querySelector('.history-item'));
  assert.equal(await page.locator('#view-practice').isVisible(),false);
  await page.locator('.history-item').first().click();
  await page.locator('.abc-score').waitFor();
  assert.match(await page.locator('#target-meta').innerText(),/3\/4/);
  assert.equal(await page.locator('#beats span').count(),3);
  assert.equal(await page.locator('.abcjs-staff').count()>0,true);
  assert.ok(await page.locator('#score-viewport').evaluate(e=>e.scrollWidth>e.clientWidth));
  await page.locator('#midi-connect').click();
  await page.locator('#tempo').fill('240');await page.locator('#tempo').dispatchEvent('change');
  await page.locator('#practice-btn').click();
  await page.waitForTimeout(400);
  assert.equal(await page.locator('#tempo').isDisabled(),true);
  await page.evaluate(()=>sendMidi([0x90,66,90]));
  await page.waitForTimeout(700);
  await page.evaluate(()=>sendMidi([0x80,66,0]));
  const hold=await page.locator('.score-live-note').first().evaluate(e=>({start:+e.dataset.start,end:+e.dataset.end,hand:e.dataset.hand}));
  assert.equal(hold.hand,'right');assert.ok(hold.end>hold.start+1);
  await page.evaluate(()=>{sendMidi([0x90,65,90]);sendMidi([0x80,65,0]);});
  assert.match(await page.locator('.score-live-note[data-midi="65"]').textContent(),/♮/,
    'An F natural input must cancel the D-major key signature in the live display.');
  const samples=await page.evaluate(async()=>{
    const values=[];for(let i=0;i<100;i++){
      values.push({at:performance.now(),x:+document.querySelector('.score-cursor').getAttribute('transform').match(/translate\(([^ ]+)/)[1]});
      await new Promise(resolve=>requestAnimationFrame(resolve));
    }return values;
  });
  await writeFile('build/abc-browser/cursor.json',JSON.stringify(samples,null,2));
  assert.ok(samples.every((p,i)=>!i||p.x>=samples[i-1].x));
  assert.ok(samples.every((p,i)=>!i||p.x-samples[i-1].x<40),'cursor jumped at a bar boundary');
  await page.screenshot({path:'build/abc-browser/desktop.png',fullPage:true});
  await page.locator('#practice-btn').click();
  assert.equal(await page.locator('#tempo').isDisabled(),true);
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:'build/abc-browser/mobile.png',fullPage:true});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.locator('#finish-btn').click();
  await page.locator('#view-list').waitFor({state:'visible'});
  const state=await page.evaluate(()=>fetch('/api/state').then(r=>r.json()));
  assert.equal(state.history[0].pending,false);
  assert.equal(state.history[0].target.schema_version,3);
  assert.ok(state.sessions[0].status!=='recording');
  await writeFile('build/abc-browser/result.json',JSON.stringify({errors,hold,samples,sessionStatus:state.sessions[0].status},null,2));
  assert.deepEqual(errors,[]);
  console.log('ABC browser: 12 bars in 3/4, continuous cursor, MIDI hold, BPM lock, mobile and completion passed.');
} finally {await browser?.close();server.kill();await rm(root,{recursive:true,force:true});}
