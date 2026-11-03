// Shared browser/server MIDI analysis. Original bytes and timestamps stay intact.
export const ANALYSIS_VERSION = 'midi-analysis-1';
export const POLICY_VERSION = 'attempt-policy-1';
const median = values => { const a=[...values].sort((a,b)=>a-b); return a.length ? a[Math.floor(a.length/2)] : null; };

export function expectedNotes(score) {
  if (!score) return [];
  const beats=score.beats_per_bar||4;
  const events=score.events||score.bars.flatMap((bar,i)=>['right','left'].flatMap(hand=>
    bar[hand].map((event,j)=>({...event,id:`${hand}:${i}:${j}`,voice:hand,bar:i}))));
  const notes=[],ties=new Map(),dynamics=new Map();
  const levels={ppp:35,pp:45,p:55,mp:65,mf:80,f:95,ff:110,fff:120};
  for (const event of [...events].sort((a,b)=>a.bar-b.bar||a.beat-b.beat)) {
    for(const mark of event.decorations||[])if(Object.hasOwn(levels,mark))dynamics.set(event.voice,levels[mark]);
    for (const pitch of event.pitches) {
    const at=event.bar*beats+event.beat, prior=pitch.tie_from&&ties.get(`${pitch.tie_from}:${pitch.midi}`);
    let note=prior;
    if (note) {note.duration=Math.max(note.duration,at+event.duration-note.at);
      if(!score.short_attacks&&event.kind!=='onset'&&note.duration>=2)note.duration_required=true;}
    else {
      note={pitch:pitch.midi,name:pitch.name,at,duration:event.duration,bar:event.bar,voices:[event.voice],
        accent:(event.decorations||[]).includes('accent'),
        reference_velocity:Math.min(127,(dynamics.get(event.voice)||75)+((event.decorations||[]).includes('accent')?20:0)),
        staccato:(event.decorations||[]).some(d=>d==='staccato'||d==='.'),
        duration_required:!score.short_attacks&&event.kind!=='onset'&&
          (event.duration>=2||(event.decorations||[]).some(d=>['tenuto','staccato','.'].includes(d)))};
      notes.push(note);
    }
    ties.set(`${event.id}:${pitch.midi}`,note);
    }
  }
  // Two written voices in unison are one physical key, not two required strikes.
  const unique=new Map();
  for (const note of notes) {
    const key=`${note.pitch}:${note.at}`,old=unique.get(key);
    if (old) {old.duration=Math.max(old.duration,note.duration);old.accent ||= note.accent;
      old.reference_velocity=Math.max(old.reference_velocity,note.reference_velocity);
      old.duration_required ||= note.duration_required;old.voices.push(...note.voices);}
    else unique.set(key,{...note});
  }
  return [...unique.values()].sort((a,b)=>a.at-b.at||a.pitch-b.pitch);
}

export function makeContract(score, conditions, options={}) {
  const expected=expectedNotes(score), beats=score?.beats_per_bar||4;
  const text=[conditions.rhythm,conditions.instructions,conditions.exercise?.rhythm].filter(Boolean).join(' ');
  const reason=!score||!expected.length?'No fixed score':score.allowed_pitches?.length||score.bars.some(b=>
    ['left','right'].some(h=>(b[h]||[]).some(e=>e.kind==='improv')))?'Improvisation needs direct confirmation':
    /\b(swing|rubato)\b/i.test(text)?'Swing or rubato needs a dedicated timing model':
    options.manual?'Direct goal confirmation requested':null;
  const bpm=options.bpm||conditions.bpm, beatMs=60000/bpm;
  const onsets=[...new Set(expected.map(n=>n.at))].sort((a,b)=>a-b);
  const minGap=Math.min(1,...onsets.slice(1).map((n,i)=>n-onsets[i]));
  return {version:POLICY_VERSION,mode:reason?'manual':'exact',manual_reason:reason,requested_manual:Boolean(options.manual),
    target_bpm:conditions.bpm,bpm,bars:conditions.bars,beats_per_bar:beats,
    duration_ms:conditions.bars*beats*beatMs,latency_ms:options.latency_ms||0,
    tolerance_ms:Math.max(20,Math.min(120,beatMs*.18,beatMs*minGap*.4)),
    duration_policy:'Long/tenuto notes require 65% sounding duration; staccato requires release within 80%. Other durations are descriptive.',
    expected};
}

export function decodeNotes(messages, {end_ms=Infinity, initial_state={}}={}) {
  const held=new Map(),sustained=new Map(),pedals=new Set((initial_state.pedals||[]).map(p=>`${p.port}:${p.channel}`)),notes=[];
  const close=(note,at,channel)=>{
    note.key_end=at;
    if(pedals.has(channel)) {const list=sustained.get(channel)||[];list.push(note);sustained.set(channel,list);}
    else note.sound_end=at;
  };
  const releasePedal=(channel,at)=>{for(const note of sustained.get(channel)||[])note.sound_end=at;sustained.delete(channel);pedals.delete(channel);};
  for (const message of [...messages].sort((a,b)=>a.at_ms-b.at_ms)) {
    if(message.at_ms>end_ms)continue;
    const data=message.data;if(!data||data.length<3)continue;
    const type=data[0]&0xf0,channel=`${message.port}:${data[0]&15}`,key=`${channel}:${data[1]}`;
    if(type===0x90&&data[2]>0) {
      const note={pitch:data[1],velocity:data[2],at_ms:message.at_ms,port:message.port,channel:data[0]&15,key_end:null,sound_end:null};
      notes.push(note);const list=held.get(key)||[];list.push(note);held.set(key,list);
    } else if(type===0x80||(type===0x90&&data[2]===0)) {
      const list=held.get(key)||[],note=list.shift();if(note)close(note,message.at_ms,channel);
      if(list.length)held.set(key,list);else held.delete(key);
    } else if(type===0xb0) {
      if(data[1]===64) {if(data[2]>=64)pedals.add(channel);else releasePedal(channel,message.at_ms);}
      if([120,123].includes(data[1])) {
        if(data[1]===120)releasePedal(channel,message.at_ms);
        for(const [k,list] of held)if(k.startsWith(channel+':')) {for(const n of list)close(n,message.at_ms,channel);held.delete(k);}
      }
      if(data[1]===121)releasePedal(channel,message.at_ms);
    }
  }
  return notes;
}

// Ordered minimum-cost matching per pitch. Missing/extra notes do not shift the
// remainder of the performance; timing is never stretched to hide tempo errors.
function match(expected, actual, tolerance) {
  const n=expected.length,m=actual.length,cols=m+1,dp=new Float64Array((n+1)*cols),step=new Uint8Array(dp.length);
  for(let i=1;i<=n;i++){dp[i*cols]=i*1.5;step[i*cols]=1;}
  for(let j=1;j<=m;j++){dp[j]=j*1.5;step[j]=2;}
  for(let i=1;i<=n;i++)for(let j=1;j<=m;j++) {
    const k=i*cols+j,pair=dp[k-cols-1]+Math.abs(expected[i-1].time-actual[j-1].time)/tolerance;
    const missing=dp[k-cols]+1.5,extra=dp[k-1]+1.5;
    if(pair<=missing&&pair<=extra){dp[k]=pair;step[k]=3;}
    else if(missing<=extra){dp[k]=missing;step[k]=1;}
    else{dp[k]=extra;step[k]=2;}
  }
  const pairs=[];let i=n,j=m;
  while(i||j){const s=step[i*cols+j];if(s===3){pairs.push([expected[--i],actual[--j]]);}else if(s===1)i--;else j--;}
  return pairs;
}

export function analyze(contract, messages, {origin_ms=0,end_ms=Infinity,final=false,interrupted=false,initial_state={}}={}) {
  const beatMs=60000/contract.bpm, limit=Number.isFinite(end_ms)?end_ms:contract.duration_ms+origin_ms+beatMs;
  const decoded=decodeNotes(messages,{end_ms:limit,initial_state});
  const actual=decoded.filter(n=>n.at_ms>=origin_ms-contract.tolerance_ms&&n.at_ms<=origin_ms+contract.duration_ms+contract.tolerance_ms)
    .map((n,index)=>({...n,index,time:n.at_ms-origin_ms-contract.latency_ms}));
  const expected=contract.expected.map((n,index)=>({...n,index,time:n.at*beatMs}));
  const pitches=new Set(expected.map(n=>n.pitch));
  const unavailable=actual.length>10000||expected.length>5000||[...pitches].some(pitch=>
    (expected.filter(n=>n.pitch===pitch).length+1)*(actual.filter(n=>n.pitch===pitch).length+1)>2000000);
  if(unavailable)return {version:ANALYSIS_VERSION,result:'unknown',qualified_pass:false,reason:'Analysis input limit exceeded; recording preserved.',bars:[],counts:{},matches:[]};
  const pairs=[];
  for(const pitch of pitches)pairs.push(...match(expected.filter(n=>n.pitch===pitch),actual.filter(n=>n.pitch===pitch),contract.tolerance_ms));
  const matchedE=new Set(pairs.map(([e])=>e.index)),matchedA=new Set(pairs.map(([,a])=>a.index));
  const missing=expected.filter(n=>!matchedE.has(n.index)),extra=actual.filter(n=>!matchedA.has(n.index));
  const matches=pairs.map(([e,a])=>{
    const keyMs=a.key_end===null?null:Math.max(0,a.key_end-a.at_ms);
    const soundingMs=a.sound_end===null?null:Math.max(0,a.sound_end-a.at_ms);
    const ratio=soundingMs===null?null:soundingMs/(e.duration*beatMs);
    const length=e.duration_required?(ratio===null?'unknown':e.staccato?(ratio<=.8?'correct':'incorrect'):(ratio>=.65?'correct':'incorrect')):'descriptive';
    return {expected_index:e.index,actual_index:a.index,pitch:e.pitch,name:e.name,bar:e.bar,at:e.at,voice:e.voices.join('/'),
      timing_ms:a.time-e.time,timing_ok:Math.abs(a.time-e.time)<=contract.tolerance_ms,
      key_ms:keyMs,sounding_ms:soundingMs,expected_ms:e.duration*beatMs,duration_result:length,
      velocity:a.velocity,accent_expected:e.accent};
  });
  const through=(limit-origin_ms-contract.tolerance_ms)/beatMs;
  const bars=Array.from({length:contract.bars},(_,bar)=>{
    const m=missing.filter(n=>n.bar===bar),x=extra.filter(n=>Math.min(contract.bars-1,Math.floor(Math.max(0,n.time)/beatMs/contract.beats_per_bar))===bar);
    const hits=matches.filter(n=>n.bar===bar),timing=hits.filter(n=>!n.timing_ok);
    return {bar,missing:m.map(n=>({pitch:n.pitch,name:n.name,beat:n.at%contract.beats_per_bar})),
      extra:x.map(n=>({pitch:n.pitch,at_ms:n.time})),timing_errors:timing.map(n=>({pitch:n.pitch,timing_ms:n.timing_ms})),
      state:contract.mode==='manual'?'unknown':!final&&through<(bar+1)*contract.beats_per_bar?'waiting':m.length||x.length||timing.length?'incorrect':'correct'};
  });
  const lengths=matches.filter(n=>n.duration_result==='incorrect'),unknownLengths=matches.filter(n=>n.duration_result==='unknown');
  const timing=matches.filter(n=>!n.timing_ok), velocities=matches.map(n=>n.velocity),accent=matches.filter(n=>n.accent_expected).map(n=>n.velocity);
  const plain=matches.filter(n=>!n.accent_expected).map(n=>n.velocity);
  const groups=[...new Set(matches.map(n=>n.voice))].map(voice=>{
    const notes=matches.filter(n=>n.voice===voice),marked=notes.filter(n=>n.accent_expected).map(n=>n.velocity),other=notes.filter(n=>!n.accent_expected).map(n=>n.velocity);
    const delta=marked.length&&other.length?median(marked)-median(other):null;
    return {voice,marked:marked.length,other:other.length,delta,
      status:!marked.length?'not_marked':marked.length<2||other.length<2||
        Math.max(...notes.map(n=>n.velocity))-Math.min(...notes.map(n=>n.velocity))<5?'unknown':delta>=8?'distinguished':'not_distinguished'};
  });
  const incomplete=interrupted||Boolean(initial_state.held?.length)||actual.some(n=>n.sound_end===null);
  const success=!missing.length&&!extra.length&&!timing.length&&!lengths.length;
  const result=contract.mode==='manual'||!final||incomplete||unknownLengths.length?'unknown':success?'passed':'needs_work';
  return {version:ANALYSIS_VERSION,policy:contract.version,result,qualified_pass:result==='passed'&&contract.bpm>=contract.target_bpm,
    bpm:contract.bpm,target_bpm:contract.target_bpm,tolerance_ms:contract.tolerance_ms,interrupted:incomplete,
    manual_reason:contract.manual_reason,
    counts:{expected:expected.length,matched:matches.length,missing:missing.length,extra:extra.length,timing_errors:timing.length,duration_errors:lengths.length,unknown_durations:unknownLengths.length},
    timing:{median_ms:median(matches.map(n=>n.timing_ms)),max_abs_ms:Math.max(0,...matches.map(n=>Math.abs(n.timing_ms)))},
    expression:{status:velocities.length<2||Math.max(...velocities)-Math.min(...velocities)<5?'unknown':'observed',
      accented_median:median(accent),other_median:median(plain),velocity_range:velocities.length?[Math.min(...velocities),Math.max(...velocities)]:null,groups,
      interpretation:'Relative MIDI attack velocity; not measured acoustic loudness or a verified musical-expression grade.'},
    bars,matches:matches.slice(0,1000),omitted_matches:Math.max(0,matches.length-1000)};
}
