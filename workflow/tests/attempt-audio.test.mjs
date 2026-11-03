import test from 'node:test';
import assert from 'node:assert/strict';
import {AttemptTransport} from '../attempt-audio.mjs';

function engine(callbacks={}) {
  const t=new AttemptTransport(callbacks);t.context={currentTime:0};
  t.performanceAt=time=>time*1000;t.tick=()=>{};t.countInTick=()=>{};t.note=()=>{};t.drum=()=>{};
  t.ensureClock=()=>{if(!t.playing){t.playing=true;t.beatIndex=0;t.nextTime=.1;t.queue=[];}};
  t.stopClock=()=>{t.playing=false;};return t;
}
const playback={beats_per_bar:3,bars:[{},{}],events:[{start:0,duration:1,pitch:60}]};
test('one count-in bar and one sweep; no automatic second pass; click remains independent',()=>{
  let started=0,ended=0,saved=0;const ticks=[],sticks=[],notes=[];
  const t=engine({onStart:()=>started++,onAttemptEnd:()=>ended++,onAttemptFinished:()=>saved++});
  t.click=true;t.padEnabled=true;t.tick=(at)=>ticks.push(at);t.countInTick=at=>sticks.push(at);t.note=(at)=>notes.push(at);
  const p=t.startAttempt(playback,120);assert.equal(p.performanceTime,1600);assert.equal(p.durationMs,3000);
  for(let time=0;time<6;time+=.025){t.context.currentTime=time;t.schedule();t.draw();}
  assert.equal(started,1);assert.equal(ended,1);assert.equal(saved,1);assert.equal(t.attempt,null);
  assert.equal(t.playing,true);assert.equal(sticks.length,3);assert.ok(ticks.length>6);
  assert.ok(ticks.every(n=>n>=1.6));assert.ok(notes.every(n=>n>=1.6));
});
test('count-in sounds even with click off; abort retains a callback and produces no completion',()=>{
  let ticks=0,sticks=0,aborted=0,saved=0;const t=engine({onAbort:()=>aborted++,onAttemptFinished:()=>saved++});
  t.tick=()=>ticks++;t.countInTick=()=>sticks++;t.startAttempt(playback,120);
  for(let time=0;time<1.3;time+=.025){t.context.currentTime=time;t.schedule();t.draw();}
  assert.equal(sticks,3);assert.equal(ticks,0);t.abortAttempt();t.context.currentTime=1.4;t.draw();
  assert.equal(aborted,1);assert.equal(saved,0);assert.equal(t.playing,false);
});
test('replay schedules recorded velocity/durations with rate and seeking without starting an attempt',()=>{
  const calls=[];const t=engine();t.replayNote=(...args)=>calls.push(args);
  t.playRecording([{pitch:60,velocity:97,at_ms:0,sound_end:2000},{pitch:64,velocity:72,at_ms:2000,sound_end:3000}],
    {bpm:60,beats:4,bars:1,duration:4000,from:1000,rate:.5});
  assert.deepEqual(calls,[[.1,60,2,97]]);assert.equal(t.attempt,null);
  for(let time=0;time<=2.01;time+=.025){t.context.currentTime=time;t.schedule();}
  assert.equal(calls[1][1],64);assert.equal(calls[1][2],2);
  t.pauseReplay();assert.equal(t.replay.paused,true);t.stopReplay();assert.equal(t.replay,null);
});

test('count-in uses a short decaying impact buffer, without a metronome oscillator',()=>{
  const t=new AttemptTransport(),started=[];let samples;
  const source={connect(){},disconnect(){},start:time=>started.push(time),stop(){}};
  t.clickBus={gain:{value:0}};
  t.context={sampleRate:48000,createBuffer:(channels,length)=>({getChannelData:()=>samples=new Float32Array(length)}),
    createBufferSource:()=>source,createGain:()=>({connect(){},disconnect(){},gain:{setValueAtTime(){},exponentialRampToValueAtTime(){}}}),
    createOscillator:()=>{throw Error('Count-in must not use the pitched metronome');}};
  t.countInTick(2,true);assert.deepEqual(started,[2]);assert.equal(samples.length,2640);
  const energy=(from,to)=>samples.slice(from,to).reduce((n,v)=>n+v*v,0)/(to-from);
  assert.ok(energy(0,200)>energy(2100,2600)*100);
});
