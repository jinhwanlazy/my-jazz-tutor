// Real app, synthetic provider/MIDI, temporary records. No production access.
import assert from 'node:assert/strict';
import {spawn, execFileSync} from 'node:child_process';
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
  assert.ok(await page.locator('#score-viewport').evaluate(e=>e.scrollWidth<=e.clientWidth+1));
  const layout = await page.evaluate(async()=>{
    const {ScoreView}=await import('/score.mjs');
    const score=(await fetch('/api/state').then(r=>r.json())).history[0].target.notation;
    const original=JSON.stringify(score);
    const host=document.createElement('div');host.style.width='900px';
    const root=document.createElement('div');host.append(root);document.body.append(host);
    const follow=document.createElement('input');follow.type='checkbox';follow.checked=false;
    const view=new ScoreView({root,follow,status:document.createElement('span')});
    const at=absolute=>({absolute,pass:Math.floor(absolute/36),bar:Math.floor(absolute/3)%12,beat:absolute%3});
    const cursor=()=>{const m=view.cursor.transform.baseVal.consolidate().matrix;return {x:m.e,y:m.f};};
    view.setScore(score);view.begin();
    const desktop=view.systems.map(s=>[s.start,s.end]);
    view.frame(at(11.8));const before=cursor();
    view.midi([0x90,66,90],'test',at(11.8));
    view.frame(at(12.2));view.midi([0x80,66,0],'test',at(12.2));const after=cursor();
    const tails=[...root.querySelectorAll('.score-hold')].map(e=>({x1:+e.getAttribute('x1'),x2:+e.getAttribute('x2'),y:+e.getAttribute('y1')}));
    const wrapped=after.x<before.x && after.y>before.y && tails.length===2 && tails[1].y>tails[0].y &&
      Math.abs(tails[0].x1-before.x)<.001 && Math.abs(tails[1].x2-after.x)<.001 && tails.every(t=>t.x2>t.x1);
    const singleHead=root.querySelectorAll('.score-input-head').length===1;
    view.midi([0x90,50,90],'test',at(12.2));
    const input=view.input;
    host.style.width='320px';view.resize();
    const mobile=view.systems.map(s=>[s.start,s.end]);
    const preserved=view.input===input && view.input.held.size===1 && view.position.absolute===12.2 &&
      root.querySelectorAll('.score-live-note').length===2 && root.scrollWidth<=root.clientWidth+1;
    view.frame(at(35.8));view.midi([0x90,66,90],'test',at(35.8));
    view.frame(at(36.2));view.drawNotes();
    const loop=view.cursor.dataset.system==='0' && root.querySelectorAll('.score-input-head').length===0 &&
      root.querySelectorAll('.score-hold').length===2;
    view.pause(at(36.4));
    const interrupted=root.querySelectorAll('.score-hold.interrupted').length===2;
    const unchanged=original===JSON.stringify(score);
    view.resizeObserver.disconnect();host.remove();
    return {desktop,mobile,wrapped,singleHead,preserved,loop,interrupted,unchanged};
  });
  assert.deepEqual(layout.desktop,[[0,12],[12,24],[24,36]]);
  assert.deepEqual(layout.mobile,[[0,12],[12,24],[24,36]]);
  assert.ok(['wrapped','singleHead','preserved','loop','interrupted','unchanged'].every(k=>layout[k]),JSON.stringify(layout));
  const scores=JSON.parse(execFileSync('uv',['run','--frozen','python','-c',`
import json,sys
sys.path.insert(0,'tests')
from recommendation_fixture import abc_result
from abc_score import parse_score
from test_abc_score import notation
values=[abc_result(bars,meter)['exercise']['notation'] for bars,meter in [(1,4),(4,4),(5,4),(8,4),(12,4),(16,3)]]
poly=abc_result(8,4)['exercise']['notation']
poly['abc']=poly['abc'].replace('{ RH LH }','{ (RH RH2) (LH LH2) }').replace('V:LH clef=bass','V:RH2 clef=treble\\nV:LH clef=bass\\nV:LH2 clef=bass')
poly['abc']+='[V:RH2] '+('z4 D4 | '*8)+'\\n[V:LH2] '+('A,,4 z4 | '*8)+'\\n'
values.append(poly)
dense=abc_result(8,4)['exercise']['notation']
dense['abc']=dense['abc'].replace('[FA]8','(3FGA B2 c2 d2').replace('[GB]8','G A B c d e f g')
values.append(dense)
values.append(notation('F8 | F8 | F8 | E8- | E4 F4 | G8 | A8 | B8 |', 'D,8 | '*8))
print(json.dumps([parse_score(n) for n in values]))
`],{encoding:'utf8'}));
  const variants=await page.evaluate(async scores=>{
    const {ScoreView}=await import('/score.mjs');
    const host=document.createElement('div'),root=document.createElement('div');host.append(root);document.body.append(host);
    const view=new ScoreView({root,status:document.createElement('span'),follow:document.createElement('input')});
    const values=[];
    for(const width of [900,320]) for(const score of scores){
      host.style.width=width+'px';view.setScore(score);view.resize();
      values.push({bars:score.bars.length,width,rows:view.systems.length,overflow:root.scrollWidth-root.clientWidth,
        notes:root.querySelectorAll('.abcjs-note').length});
    }
    view.resizeObserver.disconnect();host.remove();return values;
  },scores);
  for(const v of variants){
    assert.equal(v.rows,Math.ceil(v.bars/4),JSON.stringify(v));
    assert.ok(v.overflow<=1 && v.notes>0,JSON.stringify(v));
  }
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
      const cursor=document.querySelector('.score-cursor'), m=cursor.transform.baseVal.consolidate().matrix;
      values.push({at:performance.now(),x:m.e,y:m.f,row:+cursor.dataset.system});
      await new Promise(resolve=>requestAnimationFrame(resolve));
    }return values;
  });
  await writeFile('build/abc-browser/cursor.json',JSON.stringify(samples,null,2));
  assert.ok(samples.every((p,i)=>!i||p.row!==samples[i-1].row||p.x>=samples[i-1].x));
  assert.ok(samples.every((p,i)=>!i||p.row!==samples[i-1].row||p.x-samples[i-1].x<40),'cursor jumped within a line');
  await page.screenshot({path:'build/abc-browser/desktop.png',fullPage:true});
  await page.locator('#practice-btn').click();
  assert.equal(await page.locator('#tempo').isDisabled(),true);
  await page.setViewportSize({width:390,height:844});
  await page.waitForFunction(()=>document.querySelector('#score-viewport').scrollWidth<=document.querySelector('#score-viewport').clientWidth+1);
  await page.screenshot({path:'build/abc-browser/mobile.png',fullPage:true});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.locator('#finish-btn').click();
  await page.locator('#view-list').waitFor({state:'visible'});
  const state=await page.evaluate(()=>fetch('/api/state').then(r=>r.json()));
  assert.equal(state.history[0].pending,false);
  assert.equal(state.history[0].target.schema_version,3);
  assert.ok(state.sessions[0].status!=='recording');
  await page.locator('.history-item').first().click();
  await writeFile('build/abc-browser/result.json',JSON.stringify({errors,hold,samples,sessionStatus:state.sessions[0].status},null,2));
  assert.deepEqual(errors,[]);
  console.log('ABC browser: wrapped 12 bars, cursor and MIDI across lines/loops, resize, BPM lock and completion passed.');
} finally {await browser?.close();server.kill();await rm(root,{recursive:true,force:true});}
