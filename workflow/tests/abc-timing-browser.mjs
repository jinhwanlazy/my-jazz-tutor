// Real app assets and CSP, synthetic music, temporary records. No Codex calls.
import assert from 'node:assert/strict';
import {spawn, execFileSync} from 'node:child_process';
import {mkdtemp, mkdir, writeFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const scores=JSON.parse(execFileSync('uv',['run','--frozen','python',fileURLToPath(new URL('./abc_timing_fixture.py',import.meta.url))],{encoding:'utf8'}));
const root=await mkdtemp(join(tmpdir(),'jazz-browser-abc-timing-'));
await writeFile(join(root,'profile.json'),'{"language":"en","daily_minutes":30}');
await mkdir('build/abc-timing-browser',{recursive:true});
const server=spawn('uv',['run','python','tests/serve_browser.py',root]);let browser;
try {
  const url=await new Promise((resolve,reject)=>{
    let output='';const timer=setTimeout(()=>reject(Error('Server startup timeout')),10000);
    server.stdout.on('data',chunk=>{output+=chunk;const m=output.match(/http:\/\/127\.0\.0\.1:\d+/);if(m){clearTimeout(timer);resolve(m[0]);}});
    server.on('error',reject);
    server.stderr.on('data',chunk=>process.stderr.write(chunk));
    server.on('exit',code=>{clearTimeout(timer);reject(Error(`Preview server exited: ${code}`));});
  });
  browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_EXECUTABLE||'/usr/bin/google-chrome',args:['--no-sandbox']});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('console',message=>{if(message.type()==='error')errors.push(message.text());});
  await page.goto(url);
  await page.waitForFunction(()=>document.querySelector('#connection').textContent==='Connected locally');
  const results=await page.evaluate(async scores=>{
    const {ScoreView}=await import('/score.mjs');
    const host=document.createElement('div'),root=document.createElement('div');
    host.append(root);document.body.append(host);
    const view=new ScoreView({root,status:document.createElement('span'),follow:document.createElement('input')});
    const values=[];
    for(const width of [900,320]) for(const [name,score] of Object.entries(scores)) {
      const original=JSON.stringify(score);host.style.width=width+'px';view.setScore(score);view.resize();view.begin();
      const total=score.bars.length*score.beats_per_bar;
      const at=absolute=>({absolute,pass:Math.floor(absolute/total),bar:Math.floor(absolute/score.beats_per_bar)%score.bars.length,beat:absolute%score.beats_per_bar});
      const samples=[];
      for(let beat=0;beat<total;beat+=.125) {
        view.frame(at(beat));
        const m=view.cursor.transform.baseVal.consolidate().matrix;
        samples.push({beat,x:m.e,y:m.f,line:+view.cursor.dataset.system});
      }
      const rates=samples.slice(1).flatMap((sample,i)=>sample.line===samples[i].line?[(sample.x-samples[i].x)/.125]:[]);
      // Compare the actual rendered noteheads with the clock at their written
      // onset, including both hands, accidentals and secondary voices.
      view.playing=false;
      let noteCount=0,maxAlignmentError=0;
      const voiceCounts=[];
      for(const [voiceIndex,voice] of score.voices.entries()) {
        const events=score.events.filter(e=>e.voice===voice.id&&e.pitches.length);
        const notes=[...root.querySelectorAll(`.abcjs-note.abcjs-v${voiceIndex}`)];
        voiceCounts.push([events.length,notes.length]);
        for(const [index,event] of events.entries()) {
          if(!notes[index])continue;
          view.frame(at(event.bar*score.beats_per_bar+event.beat));
          const x=view.cursor.transform.baseVal.consolidate().matrix.e;
          const inverse=view.svg.getScreenCTM().inverse();
          const centers=[...notes[index].querySelectorAll('.abcjs-notehead')].map(head=>{
            const r=head.getBoundingClientRect();return new DOMPoint((r.left+r.right)/2,(r.top+r.bottom)/2).matrixTransform(inverse).x;
          });
          maxAlignmentError=Math.max(maxAlignmentError,Math.min(...centers.map(center=>Math.abs(center-x))));
          noteCount++;
        }
      }
      view.begin();view.frame(at(.375));view.midi([0x90,60,90],'synthetic',at(.375));
      const midiAligned=Math.abs(+root.querySelector('.score-input-head').getAttribute('cx')-
        view.cursor.transform.baseVal.consolidate().matrix.e)<.001;
      const bounds=view.systems.map(system=>({start:system.start,end:system.end,
        distance:view.x(system.end,system)-view.x(system.start,system)}));
      values.push({name,width,rates:[Math.min(...rates),Math.max(...rates)],bounds,noteCount,voiceCounts,
        maxAlignmentError,midiAligned,overflow:root.scrollWidth-root.clientWidth,unchanged:JSON.stringify(score)===original});
    }
    view.resizeObserver.disconnect();host.remove();return values;
  },scores);
  await writeFile('build/abc-timing-browser/results.json',JSON.stringify(results,null,2));
  for(const result of results) {
    // SVG transform matrices round to float32; allow subpixel numeric noise.
    assert.ok(result.rates[0]>0&&result.rates[1]-result.rates[0]<.01,JSON.stringify(result));
    assert.ok(result.voiceCounts.every(([expected,actual])=>expected===actual),JSON.stringify(result));
    assert.ok(result.noteCount>0&&result.maxAlignmentError<4,JSON.stringify(result));
    assert.ok(result.midiAligned&&result.overflow<=1&&result.unchanged,JSON.stringify(result));
    for(const line of result.bounds)assert.ok(Math.abs(line.distance/(line.end-line.start)-result.rates[0])<.01,JSON.stringify(result));
  }
  assert.deepEqual(errors,[]);
  console.log(`ABC timing: ${results.length} desktop/mobile cases passed constant speed, notehead/MIDI alignment, partial lines and immutable music checks.`);
} finally {await browser?.close();server.kill();await rm(root,{recursive:true,force:true});}
