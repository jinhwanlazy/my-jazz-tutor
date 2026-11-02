// Conservative chord-symbol backing. Unsupported symbols stay explicitly silent.
const ROOTS={C:0,D:2,E:4,F:5,G:7,A:9,B:11};
export function chordNotes(symbol) {
  const match=String(symbol||'').trim().match(/^([A-G])([b#]?)(maj7|M7|m7|m7b5|dim7|dim|aug|sus4|7|6|m|m6|maj|add9|9|m9|maj9)?(?:\/([A-G])([b#]?))?$/);
  if(!match)return null;
  const pc=(ROOTS[match[1]]+({'#':1,b:-1}[match[2]]||0)+12)%12;
  const intervals={maj7:[0,4,7,11],M7:[0,4,7,11],m7:[0,3,7,10],m7b5:[0,3,6,10],dim7:[0,3,6,9],
    dim:[0,3,6],aug:[0,4,8],sus4:[0,5,7],'7':[0,4,7,10],'6':[0,4,7,9],m:[0,3,7],m6:[0,3,7,9],
    maj:[0,4,7],add9:[0,4,7,14],'9':[0,4,7,10,14],m9:[0,3,7,10,14],maj9:[0,4,7,11,14]}[match[3]||'maj'];
  const notes=intervals.map(i=>48+pc+i);
  if(match[4])notes.unshift(36+(ROOTS[match[4]]+({'#':1,b:-1}[match[5]]||0)+12)%12);
  return notes;
}

export function backingFor(target) {
  if(target.playback)return {playback:target.playback,source:'assigned',unavailable:[]};
  const score=target.notation,beats=score?.beats_per_bar||4;
  const bars=score?.bars||Array.from({length:target.bars},(_,i)=>({chord:target.material?.chords.split('|')[i]?.trim()||''}));
  const events=[],unavailable=[];
  for(const [index,bar] of bars.entries()) {
    const changes=bar.harmony?.length?bar.harmony:[{beat:0,chord:bar.chord}];
    for(const [i,change] of changes.entries()) {
      const notes=chordNotes(change.chord);
      if(!notes){unavailable.push(change.chord||'No chord symbol');continue;}
      const duration=(changes[i+1]?.beat??beats)-change.beat;
      for(const pitch of notes)events.push({start:index*beats+change.beat,pitch,duration});
    }
  }
  return {playback:{beats_per_bar:beats,bars:bars.map(b=>({chord:b.chord||'',notes:[]})),events},
    source:events.length?'chord_symbols':'unavailable',unavailable:[...new Set(unavailable)]};
}

export function drumPattern(beats,feel='straight') {
  const events=[];
  for(let beat=0;beat<beats;beat++) {
    events.push({beat,kind:'ride',level:beat===0?.6:.45});
    if(beat%2===1)events.push({beat:beat+(feel==='swing'?2/3:.5),kind:'ride',level:.3});
    if(beat===1||beat===3)events.push({beat,kind:'hat',level:.3});
    if(beat===0)events.push({beat,kind:'kick',level:.25});
  }
  return events;
}
