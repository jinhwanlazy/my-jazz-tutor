// Browser-local controller routing. These messages are commands, never a take's music.
export const CONTROL_ACTIONS=['record','stop','play'];
export function portReference(port) {
  return Object.fromEntries(['id','name','manufacturer'].map(key=>[key,String(port?.[key]||'')]));
}
export function controlOnlyPort(port) {return /\b(?:MCU|HUI)\b/i.test(port.name||'');}
export function resolvePort(reference,ports) {
  const connected=[...ports].filter(port=>port.state==='connected');
  const exact=connected.find(port=>port.id===reference.id);if(exact)return exact;
  if(!reference.name)return null;
  const matches=connected.filter(port=>port.name===reference.name&&(port.manufacturer||'')===reference.manufacturer);
  return matches.length===1?matches[0]:null;
}
export function validBinding(value) {
  return value===null||Boolean(value&&['note','cc'].includes(value.kind)&&
    Number.isInteger(value.channel)&&value.channel>=0&&value.channel<16&&
    Number.isInteger(value.number)&&value.number>=0&&value.number<128&&
    (value.kind==='note'||Number.isInteger(value.value)&&value.value>0&&value.value<128)&&
    value.port&&['id','name','manufacturer'].every(key=>typeof value.port[key]==='string'&&value.port[key].length<=512));
}
export function defaultMidiPreferences() {
  return {version:1,remember:true,connectedBefore:false,keyboard:true,selection:{mode:'all'},
    bindings:Object.fromEntries(CONTROL_ACTIONS.map(action=>[action,null]))};
}
export function midiPreferences(value) {
  const fallback=defaultMidiPreferences();
  if(!value||value.version!==1||!['remember','connectedBefore','keyboard'].every(key=>typeof value[key]==='boolean'))return fallback;
  const selection=value.selection;
  if(!selection||!['all','none','device'].includes(selection.mode)||selection.mode==='device'&&
    !['id','name','manufacturer'].every(key=>typeof selection[key]==='string'&&selection[key].length<=512))return fallback;
  if(!value.bindings||!CONTROL_ACTIONS.every(action=>validBinding(value.bindings[action])))return fallback;
  return structuredClone(value);
}
export function keyboardAction(event) {
  if(event.defaultPrevented||event.repeat||event.isComposing||event.altKey||event.ctrlKey||event.metaKey||event.shiftKey)return null;
  const target=event.target;
  const field=target?.closest?.('input,textarea,select,[contenteditable="true"],[role="textbox"]');
  if(target?.isContentEditable||field&&!(field.tagName==='INPUT'&&['checkbox','radio','range'].includes(field.type)&&event.code!=='Space'))return null;
  if(event.code==='Space'&&target?.closest?.('button,a,summary,[role="button"]'))return null;
  return {KeyR:'record',KeyS:'stop',Space:'play'}[event.code]||null;
}
function descriptor(data) {
  if(!data||data.length!==3)return null;
  if(![data[1],data[2]].every(value=>Number.isInteger(value)&&value>=0&&value<128))return null;
  const type=data[0]&0xf0;
  if(![0x80,0x90,0xa0,0xb0].includes(type))return null;
  return {kind:type===0xb0?'cc':'note',channel:data[0]&15,number:data[1],
    value:data[2],pressure:type===0xa0,pressed:[0x90,0xb0].includes(type)&&data[2]>0};
}
function sameSignal(left,right) {
  return left.kind===right.kind&&left.channel===right.channel&&left.number===right.number&&
    (left.kind==='note'||left.value===right.value);
}
export class MidiControls {
  constructor(bindings=defaultMidiPreferences().bindings) {this.bindings=structuredClone(bindings);this.held=new Set();this.learning=null;}
  learn(action) {if(CONTROL_ACTIONS.includes(action))this.learning=action;}
  cancel() {this.learning=null;}
  clear(action) {this.bindings[action]=null;this.held.clear();this.cancel();}
  disconnect(port) {for(const key of this.held)if(key.startsWith(port.id+'\0'))this.held.delete(key);}
  process(port,data,ports=[port]) {
    const message=descriptor(data);if(!message)return {consume:false};
    const minilab=/minilab\s*3/i.test(port.name||'');
    const candidates=CONTROL_ACTIONS.filter(action=>{
      const binding=this.bindings[action];return binding&&resolvePort(binding.port,ports)?.id===port.id&&
        binding.kind===message.kind&&binding.channel===message.channel&&binding.number===message.number;
    });
    if(message.pressure)return {consume:Boolean(candidates.length)||Boolean(this.learning)};
    // Shift and HUI zone-selection CCs precede the actual transport pad event.
    const modifier=minilab&&message.kind==='cc'&&([9,15,27].includes(message.number)||
      controlOnlyPort(port)&&message.number===47&&message.value<64);
    if(this.learning&&message.pressed&&!modifier) {
      const binding={...message,port:portReference(port)};delete binding.pressed;delete binding.pressure;
      const conflict=CONTROL_ACTIONS.find(action=>action!==this.learning&&this.bindings[action]&&
        resolvePort(this.bindings[action].port,ports)?.id===port.id&&sameSignal(this.bindings[action],binding));
      if(conflict){this.held.add(port.id+'\0'+conflict);return {consume:true,conflict};}
      const learned=this.learning;this.bindings[learned]=binding;this.held.add(port.id+'\0'+learned);this.cancel();
      return {consume:true,learned,binding};
    }
    let action;
    for(const candidate of candidates) {
      const binding=this.bindings[candidate],key=port.id+'\0'+candidate;
      const pressed=message.pressed&&(binding.kind==='note'||message.value===binding.value);
      if(pressed){if(!this.held.has(key)&&!this.learning)action=candidate;this.held.add(key);}
      else if(binding.kind==='note'||message.value===0||minilab&&controlOnlyPort(port)&&message.number===47&&message.value<64)this.held.delete(key);
    }
    return {consume:Boolean(candidates.length)||Boolean(this.learning),action};
  }
}
