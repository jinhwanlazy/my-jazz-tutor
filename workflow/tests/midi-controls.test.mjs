import test from 'node:test';
import assert from 'node:assert/strict';
import {MidiControls,controlOnlyPort,defaultMidiPreferences,keyboardAction,midiPreferences,portReference,resolvePort} from '../midi-controls.mjs';

const piano={id:'keys',name:'MiniLab 3 MIDI',manufacturer:'Arturia',state:'connected'};
const surface={id:'control',name:'MiniLab 3 MCU/HUI',manufacturer:'Arturia',state:'connected'};
const ports=[piano,surface];
const note=(number,velocity=127)=>[0x90,number,velocity];
const off=number=>[0x80,number,0];

test('learned press never runs a command; subsequent presses trigger once until release',()=>{
  const router=new MidiControls();router.learn('record');
  const learned=router.process(surface,note(95),ports);
  assert.equal(learned.learned,'record');assert.equal(learned.action,undefined);assert.equal(learned.consume,true);
  assert.equal(router.process(surface,note(95,55),ports).action,undefined);
  assert.equal(router.process(surface,off(95),ports).consume,true);
  assert.equal(router.process(surface,note(95),ports).action,'record');
  assert.equal(router.process(surface,[0xa0,95,50],ports).consume,true);
  assert.equal(router.process(surface,note(95,75),ports).action,undefined,'pressure/repeated note-on retriggered');
  router.process(surface,note(95,0),ports);
  assert.equal(router.process(surface,note(95),ports).action,'record');
});

test('ordinary keys on another port/channel are never confused with transport notes',()=>{
  const router=new MidiControls();router.learn('stop');router.process(surface,note(93),ports);
  assert.equal(router.process(piano,note(93),ports).consume,false);
  assert.equal(router.process(surface,[0x91,93,127],ports).consume,false);
  assert.equal(router.process(piano,[0xb0,64,127],ports).consume,false);
  assert.equal(controlOnlyPort(surface),true);assert.equal(controlOnlyPort(piano),false);
});

test('MiniLab Shift and HUI zone messages cannot steal a learning assignment',()=>{
  const router=new MidiControls();router.learn('record');
  for(const data of [[0xb0,9,127],[0xb0,27,127],[0xb0,15,14],[0xb0,47,5]]){
    const result=router.process(surface,data,ports);assert.equal(result.consume,true);assert.equal(result.learned,undefined);
    assert.equal(router.learning,'record');
  }
  assert.equal(router.process(surface,note(95),ports).learned,'record');
});

test('CC press values can share a control number without duplicate or release commands',()=>{
  const router=new MidiControls();router.learn('stop');router.process(surface,[0xb0,47,66],ports);
  router.process(surface,[0xb0,47,2],ports);router.learn('play');router.process(surface,[0xb0,47,68],ports);
  router.process(surface,[0xb0,47,4],ports);
  assert.equal(router.process(surface,[0xb0,47,66],ports).action,'stop');
  assert.equal(router.process(surface,[0xb0,47,66],ports).action,undefined);
  assert.equal(router.process(surface,[0xb0,47,2],ports).action,undefined);
  assert.equal(router.process(surface,[0xb0,47,68],ports).action,'play');
});

test('same pad cannot silently overwrite a different action',()=>{
  const router=new MidiControls();router.learn('record');router.process(surface,note(95),ports);router.process(surface,off(95),ports);
  router.learn('stop');const conflict=router.process(surface,note(95),ports);
  assert.equal(conflict.conflict,'record');assert.equal(conflict.action,undefined);assert.equal(router.learning,'stop');
  assert.equal(router.bindings.stop,null);router.cancel();
  assert.equal(router.process(surface,note(95),ports).action,undefined,'canceling a held learning press started a take');
  router.process(surface,off(95),ports);assert.equal(router.process(surface,note(95),ports).action,'record');router.clear('record');
  assert.equal(router.process(surface,note(95),ports).consume,false);
});

test('stable port references survive a changed ID but not an ambiguous replacement',()=>{
  const reference=portReference(piano),replugged={...piano,id:'new-id'},duplicate={...piano,id:'other-id'};
  assert.equal(resolvePort(reference,[replugged]),replugged);
  assert.equal(resolvePort(reference,[replugged,duplicate]),null);
  assert.equal(resolvePort(reference,[piano,duplicate]),piano);
  assert.equal(resolvePort(reference,[{...piano,state:'disconnected'}]),null);
  const router=new MidiControls();router.learn('record');router.process(surface,note(95),ports);
  router.disconnect(surface);assert.equal(router.process({...surface,id:'new-control'},note(95),[{...surface,id:'new-control'}]).action,'record');
});

test('preferences preserve explicit no-recording/opt-out choices and validate learned messages',()=>{
  const saved=defaultMidiPreferences();saved.connectedBefore=true;saved.remember=false;saved.keyboard=false;saved.selection={mode:'none'};
  assert.deepEqual(midiPreferences(saved),{...saved,keyboard:true});
  const device={...saved,selection:{mode:'device',...portReference(piano)}};
  assert.deepEqual(midiPreferences(device),{...device,keyboard:true});
  const previous={...device};delete previous.assessment;
  assert.deepEqual(midiPreferences(previous),{...device,keyboard:true,assessment:'automatic'});
  device.assessment='self_report';assert.equal(midiPreferences(device).assessment,'self_report');
  device.bindings.record={kind:'note',channel:16,number:95,port:portReference(surface)};
  assert.deepEqual(midiPreferences(device),defaultMidiPreferences());
  assert.deepEqual(midiPreferences(null),defaultMidiPreferences());
});

test('non-note/CC and invalid messages cannot become a pad or run a transport command',()=>{
  const router=new MidiControls();router.learn('play');
  for(const data of [[0xf8],[0xfa],[0xc0,1],[0xa0,95,127],[0xf0,1,0xf7],[0x90,200,100]]){
    assert.equal(router.process(surface,data,ports).learned,undefined);assert.equal(router.learning,'play');
  }
});

test('keyboard shortcuts use physical keys, ignore repeats/IME/editors, and preserve native Space',()=>{
  const event={code:'KeyR',key:'ㄱ',target:{closest:()=>null}};
  assert.equal(keyboardAction(event),'record');assert.equal(keyboardAction({...event,code:'KeyS'}),'stop');
  assert.equal(keyboardAction({...event,code:'Space'}),'play');
  for(const flag of ['repeat','isComposing','altKey','ctrlKey','metaKey','shiftKey','defaultPrevented'])
    assert.equal(keyboardAction({...event,[flag]:true}),null);
  assert.equal(keyboardAction({...event,target:{closest:()=>({})}}),null);
  const button={closest:selector=>selector.startsWith('button')?{}:null};
  assert.equal(keyboardAction({...event,code:'Space',target:button}),null);
  assert.equal(keyboardAction({...event,target:button}),'record');
});
