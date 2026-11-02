import test from 'node:test';
import assert from 'node:assert/strict';
import {analyze,decodeNotes,expectedNotes,makeContract} from '../midi-analysis.mjs';
import {backingFor,chordNotes,drumPattern} from '../backing.mjs';

const score={beats_per_bar:4,bars:[{},{}],events:[
  {id:'a',voice:'RH',bar:0,beat:0,duration:2,pitches:[{midi:60,name:'C4'}],decorations:['accent']},
  {id:'b',voice:'RH',bar:0,beat:2,duration:2,pitches:[{midi:64,name:'E4'}]},
  {id:'c',voice:'LH',bar:1,beat:0,duration:4,pitches:[{midi:48,name:'C3'}]},
]};
const contract=(options={})=>makeContract(score,{bars:2,bpm:60},options);
const frames=(notes)=>notes.flatMap(([pitch,start,end,velocity=80,port=0])=>[
  {at_ms:start,port,data:[0x90,pitch,velocity]}, {at_ms:end,port,data:[0x80,pitch,0]},
]).sort((a,b)=>a.at_ms-b.at_ms);
const good=()=>frames([[60,0,1900,100],[64,2000,3900,70],[48,4000,7900,70]]);
const final={end_ms:9000,final:true};

test('pass requires written pitches, timing and long-note durations; slower BPM is practice only',()=>{
  const result=analyze(contract(),good(),final);
  assert.equal(result.result,'passed');assert.equal(result.qualified_pass,true);
  assert.equal(result.expression.accented_median,100);assert.equal(result.expression.other_median,70);
  const slower=contract({bpm:50}),scale=good().map(m=>({...m,at_ms:m.at_ms*1.2}));
  const result2=analyze(slower,scale,{...final,end_ms:11000});
  assert.equal(result2.result,'passed');assert.equal(result2.qualified_pass,false);
  const short=good();short.find(m=>m.data[0]===0x80).at_ms=300;
  assert.equal(analyze(contract(),short,final).counts.duration_errors,1);
});
test('missing, extra, wrong and late notes stay local to their bars',()=>{
  const result=analyze(contract(),frames([[60,0,1800],[65,2000,3900],[48,4200,8100]]),final);
  assert.equal(result.result,'needs_work');assert.equal(result.counts.missing,1);
  assert.equal(result.counts.extra,1);assert.equal(result.counts.timing_errors,1);
  assert.deepEqual(result.bars.map(b=>b.state),['incorrect','incorrect']);
  const provisional=analyze(contract(),good(),{end_ms:4500});
  assert.deepEqual(provisional.bars.map(b=>b.state),['correct','waiting']);
  assert.equal(provisional.qualified_pass,false);
});
test('repeated-pitch matching recovers after a missing note without time warping',()=>{
  const c={...contract(),expected:Array.from({length:4},(_,at)=>({pitch:60,name:'C4',at,duration:1,bar:0,voices:['RH']}))};
  const r=analyze(c,frames([[60,0,900],[60,2000,2900],[60,3000,3900]]),final);
  assert.equal(r.counts.missing,1);assert.equal(r.counts.timing_errors,0);
  assert.deepEqual(r.matches.map(m=>m.at),[3,2,0]);
});
test('pedal, velocity-zero note-off, ports and channels preserve key vs sounding durations',()=>{
  const messages=[{at_ms:0,port:0,data:[0x90,60,90]},{at_ms:20,port:0,data:[0xb0,64,127]},
    {at_ms:500,port:0,data:[0x90,60,0]},{at_ms:900,port:1,data:[0xb0,64,0]},
    {at_ms:1000,port:0,data:[0xb1,64,0]},{at_ms:1500,port:0,data:[0xb0,64,0]}];
  assert.deepEqual(decodeNotes(messages).map(n=>[n.key_end,n.sound_end]),[[500,1500]]);
  assert.equal(decodeNotes([...messages.slice(0,3),{at_ms:800,port:0,data:[0xb0,120,0]}])[0].sound_end,800);
  const initial=decodeNotes(frames([[60,0,500]]),{initial_state:{pedals:[{port:0,channel:0}]}});
  assert.equal(initial[0].sound_end,null);
});
test('ties across bars and simultaneous unison are one physical onset',()=>{
  const value={...score,events:[
    {id:'a',bar:0,beat:3,duration:1,voice:'RH',pitches:[{midi:60,name:'C4'}]},
    {id:'b',bar:1,beat:0,duration:2,voice:'RH',pitches:[{midi:60,name:'C4',tie_from:'a'}]},
    {id:'c',bar:0,beat:3,duration:1,voice:'LH',pitches:[{midi:60,name:'C4'}]},
  ]};
  const notes=expectedNotes(value);assert.equal(notes.length,1);assert.equal(notes[0].duration,3);
  assert.equal(notes[0].duration_required,true);assert.equal(notes[0].voices.length,2);
});
test('count-in boundary, latency, interruption, open pedal and manual goals never produce false passes',()=>{
  const shifted=good().map(m=>({...m,at_ms:m.at_ms+1000-30}));
  assert.equal(analyze(contract({latency_ms:-30}),shifted,{...final,end_ms:10000,origin_ms:1000}).qualified_pass,true);
  assert.equal(analyze(contract(),good(),{...final,interrupted:true}).result,'unknown');
  assert.equal(analyze(contract(),good(),{...final,initial_state:{held:[{}]}}).result,'unknown');
  assert.equal(analyze(contract(),good().slice(0,-1),final).result,'unknown');
  assert.equal(analyze(contract({manual:true}),good(),final).qualified_pass,false);
  assert.equal(makeContract(score,{bars:2,bpm:60,instructions:'Play with swing.'}).mode,'manual');
  assert.equal(makeContract(null,{bars:8,bpm:60}).mode,'manual');
});
test('bounded matching rejects pathological repetition while preserving recording availability',()=>{
  const c={...contract(),expected:Array.from({length:1500},(_,i)=>({pitch:60,at:i,bar:0,voices:['RH']}))};
  const messages=frames(Array.from({length:1500},()=>[60,0,10]));
  assert.equal(analyze(c,messages,final).result,'unknown');
});
test('written dynamics carry per voice; accent comparison requires comparable varied attacks',()=>{
  const value={...score,events:Array.from({length:4},(_,i)=>({id:String(i),voice:'RH',bar:0,beat:i,duration:1,
    pitches:[{midi:60,name:'C4'}],decorations:i===0?['p','accent']:i===2?['accent']:[]}))};
  assert.deepEqual(expectedNotes(value).map(n=>n.reference_velocity),[75,55,75,55]);
  const c=makeContract(value,{bars:2,bpm:60});
  const input=(marked,other)=>frames(Array.from({length:4},(_,i)=>[60,i*1000,i*1000+900,i%2?other:marked]));
  assert.equal(analyze(c,input(100,75),final).expression.groups[0].status,'distinguished');
  assert.equal(analyze(c,input(75,100),final).expression.groups[0].status,'not_distinguished');
  assert.equal(analyze(c,input(75,75),final).expression.groups[0].status,'unknown');
});
test('pad derives supported changes, preserves assigned backing and leaves unsupported symbols silent',()=>{
  assert.deepEqual(chordNotes('Cm7b5'),[48,51,54,58]);assert.deepEqual(chordNotes('Bbmaj7'),[58,62,65,69]);
  assert.deepEqual(chordNotes('C/E'),[40,48,52,55]);assert.equal(chordNotes('G7alt'),null);
  const backing=backingFor({notation:{beats_per_bar:4,bars:[{chord:'C',harmony:[{beat:0,chord:'Dm7'},{beat:2,chord:'G7'}]},{chord:'Cmaj7'}]}});
  assert.equal(backing.source,'chord_symbols');assert.equal(backing.playback.events.length,12);
  assert.equal(backing.playback.events.filter(n=>n.start===2).length,4);
  const assigned={bars:[{}],beats_per_bar:3};assert.equal(backingFor({playback:assigned}).playback,assigned);
  assert.equal(backingFor({bars:1,material:{chords:'G7alt'}}).source,'unavailable');
  assert.equal(drumPattern(3,'swing').every(e=>e.beat<3),true);
});
