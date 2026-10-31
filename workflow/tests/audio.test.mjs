import test from 'node:test';
import assert from 'node:assert/strict';
import {Transport} from '../audio.mjs';
import {BeatTimeline} from '../timeline.mjs';

test('explicit backing shares the quarter-note clock across triplets, ties and 3/4 loops', () => {
  const transport = new Transport();
  transport.context = {currentTime:0};
  transport.playback = {beats_per_bar:3, bars:[{},{}], events:[
    {start:0,duration:1/3,pitch:60}, {start:1/3,duration:1/3,pitch:62},
    {start:2/3,duration:1/3,pitch:64}, {start:2,duration:2,pitch:67},
  ]};
  transport.playing = true; transport.padEnabled = true;
  transport.bpm = transport.requestedBpm = 120;
  transport.beatIndex = 0; transport.nextTime = 0;
  transport.timeline = new BeatTimeline(3,2);
  const notes = [], clicks = [];
  transport.note = (time,pitch,duration) => notes.push({time,pitch,duration});
  transport.tick = (time,accent) => clicks.push({time,accent});
  for (let beat=0;beat<=6;beat++) {
    transport.context.currentTime=beat*.5; transport.schedule();
  }
  assert.deepEqual(clicks.map(c=>c.time),[0,.5,1,1.5,2,2.5,3]);
  assert.deepEqual(clicks.map(c=>c.accent),[true,false,false,true,false,false,true]);
  assert.deepEqual(notes.filter(n=>n.pitch===67),[{time:1,pitch:67,duration:1}]);
  assert.equal(notes.filter(n=>n.time===1.5).length,0,'a cross-bar tie must not reattack');
  assert.deepEqual(notes.filter(n=>n.pitch===60).map(n=>n.time),[0,3]);
  assert.ok(Math.abs(notes[1].time-1/6)<1e-10);
  assert.ok(Math.abs(notes[1].duration-1/6)<1e-10);
  assert.equal(transport.timeline.position(3.01).pass,1);
});

test('pause stops all scheduled/held backing and resume starts a fresh loop', () => {
  const oldCancel=globalThis.cancelAnimationFrame;
  globalThis.cancelAnimationFrame=()=>{};
  try {
    const transport=new Transport(); const stopped=[];
    transport.context={currentTime:2}; transport.playing=true;
    transport.timeline=new BeatTimeline(4,2);transport.timeline.add(0,0,60);
    transport.position=()=>({absolute:2});
    transport.voices.add({stop:time=>stopped.push(time)});
    transport.padVoices=[{}];transport.queue=[];
    transport.pause();
    assert.deepEqual(stopped,[2]);assert.equal(transport.playing,false);
    assert.equal(transport.padVoices.length,0);assert.equal(transport.voices.size,0);
  } finally {globalThis.cancelAnimationFrame=oldCancel;}
});
