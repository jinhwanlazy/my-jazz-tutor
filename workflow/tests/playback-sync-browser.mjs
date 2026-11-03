// Real app/Web Audio, synthetic notation and a disposable practice directory.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp,mkdir,rm,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const project=resolve(import.meta.dirname,'..'),root=await mkdtemp(join(tmpdir(),'jazz-browser-sync-'));
const output=join(project,'build/playback-sync-0.7.3');await mkdir(output,{recursive:true});
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
  await page.goto(url);await page.waitForFunction(()=>document.querySelector('#connection').textContent==='Connected locally');
  await page.evaluate(async()=>{
    const {AttemptTransport}=await import('/attempt-audio.mjs'),{Transport}=await import('/audio.mjs');
    const {ScoreView}=await import('/score.mjs'),{audioTimeAt}=await import('/timeline.mjs');
    window.sounds=[];window.syncFrames=[];window.playRequests=[];window.changeEvents=[];window.run='idle';let sound;
    document.addEventListener('change',e=>window.changeEvents.push([e.target.id,e.target.value]),true);
    const play=AttemptTransport.prototype.playRecording;
    AttemptTransport.prototype.playRecording=function(notes,options){window.playRequests.push({from:options.from,rate:options.rate,bar:document.querySelector('#replay-bar').value});return play.call(this,notes,options);};
    for(const [method,kind] of [['tick','click'],['note','pad'],['drum','drum'],['replayNote','score']]){
      const original=AttemptTransport.prototype[method];
      AttemptTransport.prototype[method]=function(...args){
        const r=this.replay,a=this.attempt;
        sound={kind,run:window.run,pitch:args[1],origin:r?.start??a?.start,
          from:r?.from||0,bpm:r?.bpm??a?.bpm??this.bpm,rate:r?.rate||1,end:a?.end};
        try{return original.apply(this,args);}finally{sound=null;}
      };
    }
    const voice=Transport.prototype.voice;
    Transport.prototype.voice=function(source,gain,time){
      const call={...sound,at:time,stop:Infinity},start=source.start.bind(source),stop=source.stop.bind(source);
      source.start=(at,...args)=>{call.at=at;window.sounds.push(call);return start(at,...args);};
      source.stop=(at,...args)=>{call.stop=at;return stop(at,...args);};
      return voice.call(this,source,gain,time);
    };
    const ensure=AttemptTransport.prototype.ensureClock;
    AttemptTransport.prototype.ensureClock=function(...args){window.syncTransport=this;return ensure.apply(this,args);};
    const frame=ScoreView.prototype.frame;
    ScoreView.prototype.frame=function(position){
      const result=frame.call(this,position),t=window.syncTransport,r=t?.replay;
      if(r&&!r.paused&&this.root.id==='score-viewport'&&position){
        const matrix=this.cursor.transform.baseVal.consolidate().matrix;
        const head=this.root.querySelector('.abcjs-notehead'),box=head.getBoundingClientRect();
        const first=new DOMPoint((box.left+box.right)/2,(box.top+box.bottom)/2).matrixTransform(this.svg.getScreenCTM().inverse());
        window.syncFrames.push({run:window.run,audio:audioTimeAt(t.context,performance.now()),origin:r.start,from:r.from,bpm:r.bpm,rate:r.rate,
          beat:position.absolute,x:matrix.e,firstX:first.x});
      }
      return result;
    };
  });
  await page.locator('#recommendation-focus summary').click();await page.locator('#recommendation-request').fill('simulate:attempt');
  await page.locator('#new-practice').click();await page.waitForFunction(()=>document.querySelector('.practice-item'));
  await page.locator('.history-item').first().click();await page.locator('.abc-score').waitFor();
  const settings=async()=>page.locator('#playback-settings').evaluate(e=>e.open=true);
  await settings();await page.locator('#pad-toggle').check({force:true});await page.locator('#drum-toggle').check({force:true});
  await page.waitForTimeout(300);assert.equal(await page.evaluate(()=>sounds.length),0,'idle backing sounded');
  await page.locator('#click-toggle').check({force:true});await page.waitForFunction(()=>sounds.length>=3);
  assert.equal(await page.evaluate(()=>sounds.some(c=>c.kind!=='click')),false);
  await page.locator('#replay-rate').selectOption('0.5');await page.evaluate(()=>window.run='full');
  await page.locator('#reference-play').click();await page.waitForFunction(()=>syncTransport.replay);
  assert.equal(await page.locator('#tempo').inputValue(),'120');assert.equal(await page.locator('#tempo').isDisabled(),true);
  await page.waitForFunction(()=>syncFrames.filter(f=>f.run==='full').length>30);
  await page.waitForFunction(()=>!syncTransport.replay);
  await page.evaluate(()=>window.run='after');await page.waitForTimeout(600);
  assert.equal(await page.evaluate(()=>sounds.some(c=>c.run==='after'&&c.kind!=='click')),false,'backing continued after playback');
  // Seek, pause, change speed while paused, then resume on the selected bar.
  await page.evaluate(()=>window.run='seek');await page.locator('#reference-play').click();await page.waitForFunction(()=>syncTransport.replay);await page.locator('#replay-bar').selectOption({value:'1'});
  await page.waitForFunction(()=>syncTransport.replay?.from===1000,null,{timeout:5000});
  await page.waitForTimeout(350);await page.locator('#replay-pause').click();
  await page.evaluate(()=>window.run='paused');await page.waitForTimeout(250);
  assert.equal(await page.evaluate(()=>sounds.some(c=>c.run==='paused')),false);
  await page.locator('#replay-rate').selectOption('0.75');await page.locator('#replay-bar').selectOption({value:'0'});
  assert.equal(await page.evaluate(()=>syncTransport.replay.paused),true);assert.equal(await page.locator('#tempo').inputValue(),'180');
  await page.evaluate(()=>window.run='resume');await page.locator('#replay-pause').click();
  await page.waitForFunction(()=>syncFrames.filter(f=>f.run==='resume').length>25);
  await page.locator('#replay-stop').click();assert.equal(await page.locator('#tempo').inputValue(),'240');
  // Keep pad/drums armed for a real finite manual take. No idle accompaniment.
  await page.locator('#click-toggle').uncheck({force:true});await page.evaluate(()=>window.run='take');
  await page.locator('#practice-btn').click();await page.waitForFunction(()=>document.querySelector('#transport-state').textContent==='Recording one pass');
  await page.waitForFunction(()=>document.querySelector('.attempt-row')&&!document.querySelector('#practice-btn').disabled);
  await page.evaluate(()=>window.run='after-take');await page.waitForTimeout(400);
  assert.equal(await page.evaluate(()=>sounds.some(c=>c.run==='after-take')),false);
  const result=await page.evaluate(()=>({sounds,frames:syncFrames}));
  const full=result.sounds.filter(c=>c.run==='full'&&Number.isFinite(c.origin)&&c.stop>c.at),first=full.find(c=>c.kind==='score');
  for(const kind of ['click','pad','drum'])assert.ok(full.some(c=>c.kind===kind&&Math.abs(c.at-first.at)<.002),kind+' has a different origin');
  for(const call of full.filter(c=>c.kind==='click')){
    const beat=(call.at-call.origin)*call.bpm*call.rate/60;
    assert.ok(Math.abs(beat-Math.round(beat))<.002,JSON.stringify(call));
  }
  for(const sample of result.frames){
    const expected=sample.from*sample.bpm/60000+Math.max(0,sample.audio-sample.origin)*sample.bpm*sample.rate/60;
    assert.ok(Math.abs(sample.beat-Math.min(8,expected))<.08,JSON.stringify(sample));
    if(sample.from===0&&sample.beat<.01)assert.ok(Math.abs(sample.x-sample.firstX)<4,JSON.stringify(sample));
  }
  const take=result.sounds.filter(c=>c.run==='take'&&(c.kind==='pad'||c.kind==='drum'));
  assert.ok(take.length>4);assert.ok(take.every(c=>c.at>=c.origin&&c.at<c.end));
  const state=await page.evaluate(()=>fetch('/api/state').then(r=>r.json()));assert.equal(state.sessions.length,1);assert.equal(state.history[0].attempts.length,1);
  assert.equal(await page.locator('#error').isVisible(),false);assert.deepEqual(errors,[]);
  await writeFile(join(output,'browser-timing.json'),JSON.stringify(result));
  console.log('Real Web Audio sync passed: idle silence, shared origin, cursor, speed/seek/pause, finite backing and read-only playback.');
} catch(error){const page=browser?.contexts()[0]?.pages()[0];if(page){await page.screenshot({path:join(output,'failure.png'),fullPage:true});await writeFile(join(output,'failure.txt'),await page.locator('body').innerText());await writeFile(join(output,'failure-trace.json'),JSON.stringify(await page.evaluate(()=>({sounds,frames:syncFrames,playRequests,changeEvents,requested:syncTransport?.requestedBpm,replay:syncTransport?.replay})),null,2));}throw error;
} finally {await browser?.close();server.kill('SIGTERM');await rm(root,{recursive:true,force:true});}
