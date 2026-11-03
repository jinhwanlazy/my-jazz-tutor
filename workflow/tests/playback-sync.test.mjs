import test from 'node:test';
import assert from 'node:assert/strict';
import {AttemptTransport} from '../attempt-audio.mjs';

// Drive the real scheduler with a controlled audio clock. Sources retain their
// scheduled start/stop times so canceled lookahead cannot count as audible sound.
globalThis.cancelAnimationFrame=()=>{};
function engine() {
  const calls=[],beats=[],frames=[],t=new AttemptTransport({
    onBeat:event=>beats.push(event),onReplayFrame:(position,ms)=>frames.push({position,ms})});
  t.context={currentTime:0,getOutputTimestamp:()=>({
    contextTime:t.context.currentTime-(t.outputLag||0),performanceTime:performance.now()})};
  t.performanceAt=time=>time*1000;
  t.ensureClock=(defer=false)=>{
    if(t.playing)return;t.playing=true;t.beatIndex=0;t.nextTime=t.context.currentTime+.1;t.queue=[];
    if(!defer)t.schedule();
  };
  const sound=(kind,at,pitch,duration=0)=>{
    const call={kind,at,pitch,duration,stopAt:Infinity};calls.push(call);
    const osc={stop:time=>call.stopAt=Math.min(call.stopAt,time)};t.voices.add(osc);
    if(kind==='pad')t.padVoices.push({osc});
    if(kind==='drum')t.drumVoices.add(osc);
    if(kind==='score')t.replayVoices.add(osc);
  };
  t.tick=(at,accent)=>sound('click',at,accent);
  t.note=(at,pitch,duration)=>sound('pad',at,pitch,duration);
  t.drum=(at,kind)=>sound('drum',at,kind);
  t.replayNote=(at,pitch,duration)=>sound('score',at,pitch,duration);
  const advance=end=>{
    for(let now=t.context.currentTime+.025;now<end+.00001;now+=.025){
      t.context.currentTime=now;t.schedule();t.flush();t.draw();
    }
  };
  return {t,calls,beats,frames,advance};
}
const audible=calls=>calls.filter(c=>c.stopAt>c.at+1e-7);
const near=(actual,expected)=>assert.ok(Math.abs(actual-expected)<.001,`${actual} != ${expected}`);
const progression=beats=>({beats_per_bar:beats,bars:[{notes:[48]},{notes:[50]},{notes:[52]}]});

test('pad and drums are armed silently; only metronome can play outside a take/replay',()=>{
  const {t,calls,advance}=engine();t.configure(progression(4),120);
  t.setPad(true);t.setDrums(true);assert.equal(t.playing,false);
  t.setMetronome(true);advance(3);
  assert.ok(calls.length>3);assert.ok(calls.every(c=>c.kind==='click'));
  t.setMetronome(false);advance(3.1);assert.equal(t.playing,false);
});

test('backing starts with the take after count-in and never loops while idle',()=>{
  const {t,calls,advance}=engine();const backing=progression(3);
  t.configure(backing,120);t.setPad(true);t.setDrums(true);
  t.startAttempt(backing,120);const {start,end}=t.attempt;
  advance(9);
  const pad=calls.filter(c=>c.kind==='pad'),drums=calls.filter(c=>c.kind==='drum');
  assert.equal(pad.length,3);assert.ok(drums.length>3);
  for(const call of [...pad,...drums])assert.ok(call.at>=start&&call.at<end);
  for(const call of pad)assert.ok(call.at+call.duration<=end+.001);
  assert.equal(t.playing,false);assert.equal(t.attempt,null);
});

test('notation and click start together after a different-tempo idle metronome',()=>{
  const {t,calls,advance}=engine();t.configure(progression(4),73);
  t.setMetronome(true);advance(.7);const mark=calls.length;
  t.playRecording([{pitch:60,velocity:90,at_ms:0,sound_end:1000}],
    {bpm:120,beats:4,bars:1,duration:2000,rate:.5});
  advance(1.5);
  const heard=audible(calls.slice(mark)),first=heard.find(c=>c.kind==='score');
  assert.ok(heard.some(c=>c.kind==='click'&&Math.abs(c.at-first.at)<.001));
});

for(const beats of [3,4])for(const rate of [.5,.75,1])for(const offset of [0,beats+.5]) {
  test(`shared replay origin: ${beats}/4, ${rate}x, seek ${offset} beats, previously running click`,()=>{
    const {t,calls,frames,advance}=engine(),bpm=120,backing=progression(beats),total=3*beats;
    t.configure(backing,73);t.setMetronome(true);advance(1.275);
    t.setPad(true);t.setDrums(true);const mark=calls.length;
    const notes=Array.from({length:total},(_,i)=>({pitch:60+i,velocity:80,at_ms:i*500,sound_end:(i+1)*500}));
    t.playRecording(notes,{bpm,beats,bars:3,duration:total*500,from:offset*500,rate});
    const origin=t.replay.start;near(t.replayPosition(),offset*500);
    advance(origin+(total-offset)*.5/rate+.05);
    const heard=audible(calls.slice(mark));
    const score=heard.filter(c=>c.kind==='score'),clicks=heard.filter(c=>c.kind==='click'&&c.at<origin+(total-offset)*.5/rate-.001);
    assert.ok(score.length>=Math.floor(total-offset));assert.ok(clicks.length>1);
    for(const call of score){const beat=Math.max(offset,call.pitch-60);near(call.at,origin+(beat-offset)*.5/rate);}
    for(const call of clicks){
      const beat=offset+(call.at-origin)*bpm*rate/60;near(beat,Math.round(beat));
      assert.equal(call.pitch,Math.round(beat)%beats===0);
    }
    for(const call of heard.filter(c=>c.kind==='pad')) {
      const bar=[48,50,52].indexOf(call.pitch),beat=Math.max(offset,bar*beats);
      near(call.at,origin+(beat-offset)*.5/rate);
      near(call.duration,((bar+1)*beats-beat)*.5/rate);
    }
    assert.equal(heard.filter(c=>c.kind==='pad').length,Math.ceil(3-offset/beats));
    assert.ok(heard.some(c=>c.kind==='drum'&&Math.abs(c.at-score[0].at)<.001)||offset%1!==0);
    for(const frame of frames)near(frame.position.absolute,frame.ms*bpm/60000);
    assert.equal(t.replay,null);assert.equal(t.requestedBpm,73);
    const after=calls.length;advance(t.context.currentTime+2);
    assert.ok(calls.slice(after).every(c=>c.kind==='click'),'backing kept playing after replay');
  });
}

test('cursor uses the audible output clock; pause cancels all channels and resume restores held notes',()=>{
  const {t,calls,advance}=engine();t.outputLag=.08;t.configure(progression(4),96);
  t.setPad(true);t.setDrums(true);t.setMetronome(true);
  const notes=[{pitch:60,velocity:80,at_ms:0,sound_end:4000}];
  t.playRecording(notes,{bpm:120,beats:4,bars:3,duration:6000,rate:.75});
  const start=t.replay.start;advance(1);
  near(t.replayPosition(),(t.context.currentTime-.08-start)*750);
  const paused=t.replayPosition(),pauseTime=t.context.currentTime;t.pauseReplay();
  assert.equal(t.playing,false);assert.equal(t.replay.paused,true);
  assert.ok(calls.every(c=>c.stopAt<=pauseTime));
  const mark=calls.length;advance(1.5);assert.equal(calls.length,mark);near(t.replayPosition(),paused);
  t.playRecording(notes,{bpm:120,beats:4,bars:3,duration:6000,from:paused,rate:.5});
  const resumed=t.replay.start,newCalls=calls.slice(mark);
  near(t.replayPosition(),paused);
  const note=newCalls.find(c=>c.kind==='score'),pad=newCalls.find(c=>c.kind==='pad');
  near(note.at,resumed);near(pad.at,resumed);near(note.duration,(4000-paused)/500);
});

test('enabling pad mid-play restores the current chord; disabling/aborting cancels queued backing',()=>{
  const {t,calls,advance}=engine();t.configure(progression(4),120);
  t.startAttempt(progression(4),120);const start=t.attempt.start;advance(start+.5);
  t.setPad(true);t.setDrums(true);advance(t.context.currentTime+.5);
  assert.ok(calls.some(c=>c.kind==='pad'&&c.pitch===48));
  const mark=calls.length;t.abortAttempt();advance(t.context.currentTime+2);
  assert.equal(calls.length,mark);assert.equal(t.playing,false);
  assert.ok(calls.filter(c=>c.kind==='pad'||c.kind==='drum').every(c=>c.stopAt<Infinity));
});

test('fractional chord changes, short recordings and seeking beyond their end stay bounded',()=>{
  const {t,calls,advance}=engine();t.configure({beats_per_bar:4,bars:[{}],events:[
    {start:0,duration:1.5,pitch:48},{start:1.5,duration:2.5,pitch:55}]},120);
  t.setPad(true);t.setDrums(true);
  t.playRecording([{pitch:60,velocity:80,at_ms:0,sound_end:600}],
    {bpm:120,beats:4,bars:1,duration:600,rate:.5});
  const start=t.replay.start;advance(2);
  const pad=calls.filter(c=>c.kind==='pad');assert.equal(pad.length,1);
  near(pad[0].at,start);near(pad[0].duration,1.2);
  assert.ok(calls.every(c=>c.at<start+1.2));
  t.playRecording([],{bpm:120,beats:4,bars:1,duration:600,from:2000});
  assert.equal(t.replay.from,600);advance(2.25);assert.equal(t.replay,null);
});

test('natural replay end leaves one idle animation loop, without reviving the old callback',()=>{
  const {t}=engine(),frames=new Map();let serial=0;
  const previousRequest=globalThis.requestAnimationFrame,previousCancel=globalThis.cancelAnimationFrame;
  globalThis.requestAnimationFrame=callback=>{frames.set(++serial,callback);return serial;};
  globalThis.cancelAnimationFrame=id=>frames.delete(id);
  t.ensureClock=AttemptTransport.prototype.ensureClock;
  try {
    t.configure(progression(4),120);t.setMetronome(true);
    t.playRecording([],{bpm:120,beats:4,bars:1,duration:500});
    t.context.currentTime=1;
    const callbacks=[...frames.values()];frames.clear();callbacks.forEach(callback=>callback());
    assert.equal(t.replay,null);assert.equal(t.playing,true);assert.equal(frames.size,1);
  } finally {
    t.pause();globalThis.requestAnimationFrame=previousRequest;globalThis.cancelAnimationFrame=previousCancel;
  }
});
