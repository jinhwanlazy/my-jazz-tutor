import test from 'node:test';
import assert from 'node:assert/strict';
import {analyze,expectedNotes,makeContract,noteFeedback} from '../midi-analysis.mjs';

const music=events=>({beats_per_bar:4,bars:[{},{}],allowed_pitches:[],events});
const event=(id,beat,pitches,duration=1,voice='RH')=>({id,voice,bar:Math.floor(beat/4),beat:beat%4,duration,
  pitches:pitches.map(pitch=>({midi:pitch,name:['C','C♯','D','E♭','E','F','F♯','G','A♭','A','B♭','B'][pitch%12]+(Math.floor(pitch/12)-1)}))});
const contract=events=>makeContract(music(events),{bars:2,bpm:60});
const frames=notes=>notes.flatMap(([pitch,start,end])=>[{at_ms:start,port:0,data:[0x90,pitch,80]},
  {at_ms:end,port:0,data:[0x80,pitch,0]}]).sort((a,b)=>a.at_ms-b.at_ms);
const final={end_ms:9000,final:true};

test('a completed note is graded before its bar ends; future notes wait for their own window',()=>{
  const c=contract([event('a',0,[60]),event('b',1,[62]),event('c',2,[64])]);
  const r=analyze(c,frames([[60,0,100]]),{end_ms:150});
  assert.deepEqual(r.notes.map(n=>n.state),['correct','waiting','waiting']);
  assert.equal(r.bars[0].state,'waiting');assert.equal(r.qualified_pass,false);
  assert.equal(noteFeedback(c,r).notes[0].state,'correct','a provisional overall result hid observed notes');
  assert.equal(analyze(c,[],{end_ms:c.tolerance_ms}).notes[0].state,'waiting');
  assert.equal(analyze(c,[],{end_ms:c.tolerance_ms+.01}).notes[0].state,'missing');
});

test('one wrong pitch in a chord does not grade its other pitches as wrong',()=>{
  const c=contract([event('chord',0,[60,64,67])]);
  const r=analyze(c,frames([[61,0,200],[64,0,200],[67,0,200]]),final);
  assert.deepEqual(r.notes.map(n=>[n.pitch,n.state]),[[60,'missing'],[64,'correct'],[67,'correct']]);
  assert.deepEqual(r.extra_notes.map(n=>[n.pitch,n.state,n.at]),[[61,'extra',0]]);
  assert.equal(r.qualified_pass,false);
});

test('timing and required note length produce separate per-note reasons',()=>{
  const c=contract([event('a',0,[60],2),event('b',2,[64],2)]);
  let r=analyze(c,frames([[60,0,400],[64,2200,3900]]),final);
  assert.deepEqual(r.notes.map(n=>[n.state,n.issues]),[['incorrect',['too_short']],['incorrect',['late']]]);
  const held=[{at_ms:0,port:0,data:[0x90,60,80]}];
  r=analyze(c,held,{end_ms:300});assert.equal(r.notes[0].state,'holding');
  r=analyze(c,frames([[60,0,1500]]),{end_ms:1550});assert.equal(r.notes[0].state,'correct');
  c.expected[0].staccato=true;
  r=analyze(c,frames([[60,0,1900],[64,2000,3900]]),final);assert.deepEqual(r.notes[0].issues,['too_long']);
});

test('latency correction applies to the live missing-note deadline as well as played notes',()=>{
  const c={...contract([event('a',0,[60])]),latency_ms:250};
  assert.equal(analyze(c,[],{end_ms:350}).notes[0].state,'waiting');
  assert.equal(analyze(c,[],{end_ms:371}).notes[0].state,'missing');
  const r=analyze(c,frames([[60,250,500]]),{end_ms:550});assert.equal(r.notes[0].timing_ms,0);assert.equal(r.notes[0].state,'correct');
});

test('ties and unison preserve all written head identities while requiring one physical onset',()=>{
  const a=event('a',3,[60]),b=event('b',4,[60],2),u=event('u',3,[60],1,'LH');b.pitches[0].tie_from='a';
  const notes=expectedNotes(music([a,b,u]));assert.equal(notes.length,1);
  assert.equal(notes[0].duration,3);
  assert.deepEqual(notes[0].locations,[{event_id:'a',pitch_index:0},{event_id:'b',pitch_index:0},{event_id:'u',pitch_index:0}]);
});

test('manual, interrupted and incomplete takes retain unknown grades',()=>{
  const c=contract([event('a',0,[60],2)]),input=frames([[60,0,1500]]);
  for(const [value,options] of [[{...c,mode:'manual'},final],[c,{...final,interrupted:true}],[c,{...final,initial_state:{held:[{}]}}]]){
    const r=analyze(value,input,options);assert.equal(r.result,'unknown');assert.equal(r.notes[0].state,'unknown');assert.equal(r.qualified_pass,false);
  }
  const held=analyze(c,input.slice(0,1),final);assert.equal(held.notes[0].state,'unknown');
  const r=analyze(c,input,final);assert.equal(noteFeedback(c,r,{unassessed:true}).notes[0].state,'unknown');
  assert.equal(r.notes[0].state,'correct','display masking changed the original analysis');
});

test('older saved analyses project known missing/matched notes without rematching or altering originals',()=>{
  const c=contract([event('a',0,[60]),event('b',1,[62]),event('c',2,[64])]);
  const old=analyze(c,frames([[60,0,300],[65,1000,1300],[64,2200,2500]]),final);
  delete old.notes;delete old.extra_notes;delete old.final;old.version='midi-analysis-1';
  const snapshot=JSON.stringify(old),projected=noteFeedback(c,old);
  assert.deepEqual(projected.notes.map(n=>n.state),['correct','missing','incorrect']);
  assert.equal(projected.extra[0].pitch,65);assert.equal(JSON.stringify(old),snapshot);
  old.matches=old.matches.filter(n=>n.expected_index!==0);old.omitted_matches=1;
  assert.equal(noteFeedback(c,old).notes[0].state,'unknown','an omitted observation became a grade');
});

test('new note results cover the full supported score even when the old matched-note list is truncated',()=>{
  const c=contract([event('seed',0,[60])]);c.bars=16;c.duration_ms=64000;
  c.expected=Array.from({length:1250},(_,i)=>({pitch:60+i%5,name:['C4','C#4','D4','D#4','E4'][i%5],
    at:Math.floor(i/5)*.25,bar:Math.floor(Math.floor(i/5)/16),duration:.25,voices:['RH'],duration_required:false}));
  const input=frames(c.expected.map(n=>[n.pitch,n.at*1000,n.at*1000+200]));
  const r=analyze(c,input,{...final,end_ms:65000});
  assert.equal(r.result,'passed');assert.equal(r.matches.length,1000);assert.equal(r.omitted_matches,250);
  assert.equal(r.notes.length,1250);assert.ok(r.notes.every(n=>n.state==='correct'));
  const old={...r,version:'midi-analysis-1'};delete old.notes;delete old.extra_notes;delete old.final;
  assert.equal(noteFeedback(c,old).notes.filter(n=>n.state==='unknown').length,250);
});
