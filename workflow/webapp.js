import {tr, locale, setLocale, loadTranslations, translatePage} from './i18n.mjs';
import {AttemptTransport} from './attempt-audio.mjs';
import {backingFor} from './backing.mjs';
import {decodeNotes,expectedNotes} from './midi-analysis.mjs';
import {Capture, Outbox, uploadPending, randomHex, decodeMidiFrames} from './capture.mjs';
import {ScoreView} from './score.mjs';
import {MidiControls,CONTROL_ACTIONS,controlOnlyPort,portReference,resolvePort,midiPreferences,keyboardAction} from './midi-controls.mjs';

const $ = id => document.getElementById(id);
const sidebar = document.querySelector('.sidebar');
const toolbar = $('practice-toolbar');
function measureWorkspace() {
  const height = getComputedStyle(sidebar).position === 'sticky' ? sidebar.getBoundingClientRect().height : 0;
  document.documentElement.style.setProperty('--app-header-height', `${height}px`);
  document.documentElement.style.setProperty('--practice-toolbar-height', `${toolbar.getBoundingClientRect().height}px`);
}
const workspaceObserver = new ResizeObserver(measureWorkspace);
workspaceObserver.observe(sidebar);workspaceObserver.observe(toolbar);
const ui = {data: null, capture: null, busy: false, selected: null, recordTask: null, openedTaskId: null, view: 'list', reflectionSaving: false, ports: new Map(), phase:'idle', midiFrames:[], replayTrack:null};
ui.visit=0;ui.detailRequest=0;ui.replayRequest=0;ui.roomAudioActive=false;
ui.playbackRevision=-1;ui.playbackPending={};ui.playbackInFlight={};
const heldKeys=new Map(), heldPedals=new Map();
let analysisWorker,analysisSerial=0;
let outbox, midiAccess, midiSelection = 'all', timer, detailTask;
const labels = {success: 'Criteria met', unmet: 'Target not met', unknown: 'Assessment pending'};
const ratings = {impossible: 'Impossible', challenging: 'Challenging', good: 'Good practice', too_easy: 'Too easy to be useful'};
const discardChoices = {already_practiced: 'Already familiar', too_easy: 'Too easy'};
const ratingEmoji = {impossible: '😈', challenging: '💪', good: '🙂', too_easy: '🙄'};
const ratingText = rating => `${ratingEmoji[rating]} ${tr(ratings[rating])}`;
function el(tag, text, className) { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node; }
function icon(name) {
  const ns='http://www.w3.org/2000/svg',node=document.createElementNS(ns,'svg');
  for(const [key,value] of Object.entries({viewBox:'0 0 24 24',fill:'none',stroke:'currentColor','stroke-width':'1.7','stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true',focusable:'false'}))node.setAttribute(key,value);
  const paths={copy:['M9 8h10v13H9z','M15 4H5v13'],trash:['M4 7h16','M9 7V4h6v3','M6 7l1 14h10l1-14','M10 11v6','M14 11v6']};
  for(const d of paths[name]){const path=document.createElementNS(ns,'path');path.setAttribute('d',d);node.append(path);}
  return node;
}
function taskIdentity(id) {
  const box = el('div', undefined, 'task-identity'), value = el('code', id, 'task-id');
  const button = el('button', undefined, 'icon-button copy-task-id'); button.type = 'button';button.append(icon('copy'));button.title=tr('Copy ID');
  button.setAttribute('aria-label', tr`Copy practice ID ${id}`);
  const status = el('span', '', 'copy-status'); status.setAttribute('role', 'status');
  button.addEventListener('click', async () => {
    let copied = false;
    try { await navigator.clipboard.writeText(id); copied = true; } catch {
      // Plain LAN HTTP may not provide Clipboard API. Keep the ID selectable
      // even if the browser also refuses the user-initiated copy fallback.
      const selection = window.getSelection(), range = document.createRange();
      range.selectNodeContents(value); selection.removeAllRanges(); selection.addRange(range);
      try { copied = document.execCommand('copy'); } catch { /* Leave the ID selected. */ }
      if (copied) selection.removeAllRanges();
    }
    status.textContent = tr(copied ? 'ID copied.' : 'ID selected. Use your device’s copy command.');
  });
  box.append(el('span', tr('Practice ID')), value, button, status);
  return box;
}
function option(value, text, disabled = false) { const node = el('option', text); node.value = value; node.disabled = disabled; return node; }
function clock(ms) { const s = Math.max(0, Math.floor((ms || 0) / 1000)); return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`; }
function fail(error) { ui.error = error; $('error').textContent = tr(error.message || String(error)); $('error').hidden = false; }
function clearError() { ui.error = null; $('error').hidden = true; }
function pending() { return ui.data?.history.find(t => t.pending); }
function openedTask() { return ui.data?.history.find(t => t.id === ui.openedTaskId); }
function openSessions() { return ui.data?.sessions.filter(s => s.status === 'recording' && s.id !== ui.capture?.session.id) || []; }
function taskSessions(id) { return ui.data.sessions.filter(s => s.task_id === id); }
function focusPanel(node) {
  measureWorkspace();
  const style=getComputedStyle(document.documentElement);
  const inset=(parseFloat(style.getPropertyValue('--app-header-height'))||0)+(parseFloat(style.getPropertyValue('--practice-toolbar-height'))||0)+16;
  node.focus({preventScroll:true});
  window.scrollTo({top:Math.max(0,node.getBoundingClientRect().top+scrollY-inset),behavior:'instant'});
}

async function api(path, body) {
  let response;
  try {
    response = await fetch(path + (path.includes('?') ? '&' : '?') + 'lang=' + locale(), {method: body === undefined ? 'GET' : 'POST', cache: 'no-store',
      headers: body === undefined ? {} : {'Content-Type': 'application/json', 'X-Jazz-Token': ui.data.csrf_token},
      body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(12000)});
  } catch { throw new Error('Could not connect. Check that the practice server is running and try again.'); }
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Could not process the request.');
  return result;
}

let playbackSaveTimer;
function applyPlaybackSettings(saved) {
  if(!saved)return;
  if(saved.revision>=ui.playbackRevision){ui.playbackRevision=saved.revision;ui.playbackSaved=saved;}
  const previous=ui.playbackValues;
  const values={...ui.playbackSaved.values,...ui.playbackInFlight,...ui.playbackPending};ui.playbackValues=values;
  for(const [id,key] of [['click-toggle','metronome_enabled'],['pad-toggle','pad_enabled'],['drum-toggle','drums_enabled']])$(id).checked=values[key];
  for(const [id,key] of [['click-volume','click_volume'],['pad-volume','pad_volume'],['drum-volume','drum_volume'],['backing-feel','drum_feel']])$(id).value=values[key];
  transport.click=values.metronome_enabled;transport.setPad(values.pad_enabled);transport.setDrums(values.drums_enabled);
  transport.setVolumes(values.click_volume,values.pad_volume);transport.drumVolume=values.drum_volume;transport.feel=values.drum_feel;
  if(values.metronome_enabled&&ui.roomAudioActive&&!document.hidden)transport.setMetronome(true);
  if(previous&&ui.capture)for(const [key,type] of [['metronome_enabled','click'],['pad_enabled','pad'],['drums_enabled','drum']])
    if(previous[key]!==values[key])ui.capture.event(type,{enabled:values[key],source:'shared-settings'});
}
function queuePlaybackSettings(changes,delay=0) {
  Object.assign(ui.playbackPending,changes);applyPlaybackSettings(ui.playbackSaved);
  $('sound-settings-status').textContent=tr('Saving shared sound settings…');
  clearTimeout(playbackSaveTimer);playbackSaveTimer=setTimeout(savePlaybackSettings,delay);
}
async function savePlaybackSettings() {
  if(ui.playbackSaving||!ui.data||!Object.keys(ui.playbackPending).length)return;
  const changes=ui.playbackPending;ui.playbackPending={};ui.playbackInFlight=changes;ui.playbackSaving=true;
  let success=false;
  try {
    const saved=await api('/api/playback-settings',{changes});ui.playbackInFlight={};applyPlaybackSettings(saved);
    $('sound-settings-status').textContent=tr('Shared across all practices and browsers.');success=true;
  } catch {
    ui.playbackPending={...changes,...ui.playbackPending};ui.playbackInFlight={};
    $('sound-settings-status').textContent=tr('Sound settings could not be saved. Your changes will retry when connected.');
  } finally {ui.playbackSaving=false;}
  if(success&&Object.keys(ui.playbackPending).length)savePlaybackSettings();
}
async function activateRoomAudio() {
  ui.roomAudioActive=true;
  if(!ui.playbackValues?.metronome_enabled)return;
  try{await transport.unlock();if(ui.roomAudioActive)applyPlaybackSettings(ui.playbackSaved);}catch(error){fail(error);}
}
setInterval(async()=>{
  if(!ui.data||document.hidden||ui.playbackPolling)return;
  ui.playbackPolling=true;
  try{applyPlaybackSettings(await api('/api/playback-settings'));if(Object.keys(ui.playbackPending).length)savePlaybackSettings();}
  catch{ /* Keep the last settings; a read failure must not reset them. */ }
  finally{ui.playbackPolling=false;}
},3000);

const score = new ScoreView({root: $('score-viewport'), status: $('score-position'),
  follow: $('score-follow'), help: $('score-material-help'), finite:true});
const transport = new AttemptTransport({
  onStart: () => beginRecordedPass(),
  onFrame: position => {
    if (!position) return;
    beginRecordedPass(); score.frame(position);
    $('score-position').textContent=tr`Bar ${position.bar+1} / ${target().bars}`;
    if (ui.phase === 'playing') $('elapsed').textContent = clock(Math.max(0,performance.now()-ui.plannedStart));
    if (ui.capture && position.bar !== ui.analysisBar) {ui.analysisBar=position.bar;requestAnalysis();}
  },
  onCountIn: (beat,beats) => {ui.countInBeat=beat; $('transport-state').textContent=tr`Count-in ${beat} / ${beats}`; },
  onBeat: ({bar,beat,counting}) => {
    ui.beat={bar,beat};
    [...$('beats').children].forEach((node,i)=>node.classList.toggle('active',i===beat));
    if (ui.capture && !counting) $('bar-position').textContent=tr`Bar ${bar+1} · beat ${beat+1}`;
  },
  onAttemptEnd: at => {
    beginRecordedPass();ui.phase='tail';ui.capture?.event('attempt_end',{},at);ui.capture?.event('pause',{},at);
    requestAnalysis();updateTransport();
  },
  onAttemptFinished: () => {stopCapture().catch(fail);},
  onAbort: () => {ui.capture?.event('aborted');ui.capture?.event('pause');ui.phase='aborted';score.pause(score.position);},
  onInterrupt: message => {
    ui.roomAudioActive=false;
    ui.capture?.event('audio_interrupted',{message});
    if(ui.capture)stopCapture().catch(fail);
    fail(new Error(message));updateTransport();
  },
  onReplayFrame: (position,ms) => {score.frame(position);$('elapsed').textContent=clock(ms);$('score-position').textContent=tr`Bar ${position.bar+1} / ${target().bars}`;},
  onReplayStop: () => {score.pause(score.position);updateTransport();}
});

function beginRecordedPass() {
  if(!ui.capture||ui.phase==='playing'||ui.phase==='tail'||ui.capture.ended)return;
  const captured=new Set(ui.midiFrames.filter(f=>(f.data[0]&0xf0)===0x90&&f.data[2]>0).map(f=>`${f.port}:${f.data[0]&15}:${f.data[1]}`));
  const initial_state={held:[...heldKeys.values()].map(v=>({...v,port:ui.ports.get(v.port)})).filter(v=>v.port!==undefined&&!captured.has(`${v.port}:${v.channel}:${v.pitch}`)),
    pedals:[...heldPedals.values()].map(v=>({...v,port:ui.ports.get(v.port)})).filter(v=>v.port!==undefined)};
  ui.capture.event('play',{bpm:ui.lockedBpm,initial_state},ui.plannedStart);
  ui.initialMidi=initial_state;ui.phase='playing';score.begin();
  for(const frame of ui.midiFrames)score.midi(frame.data,String([...ui.ports].find(([,index])=>index===frame.port)?.[0]||frame.port),scorePositionAt(ui.capture.origin+frame.at_ms));
  updateTransport();
}
function scorePositionAt(at) {
  const beats=ui.attemptContract.beats_per_bar,total=ui.attemptContract.bars*beats;
  const absolute=Math.max(0,Math.min(total,(at-ui.plannedStart-ui.attemptContract.latency_ms)*ui.lockedBpm/60000));
  return {absolute,pass:0,bar:Math.min(ui.attemptContract.bars-1,Math.floor(absolute/beats)),beat:absolute>=total?beats:absolute%beats};
}
function requestAnalysis() {
  if(!ui.capture||!ui.attemptContract||!ui.plannedStart||ui.analysisLimited)return;
  try {
    analysisWorker ||= new Worker('/midi-analysis-worker.mjs',{type:'module'});
    analysisWorker.onmessage=event=>{
      if(!ui.capture||event.data.id!==analysisSerial||!event.data.analysis)return;
      renderBarResults(event.data.analysis.bars);
    };
    analysisWorker.postMessage({id:++analysisSerial,contract:ui.attemptContract,messages:ui.midiFrames,
      options:{origin_ms:ui.plannedStart-ui.capture.origin,end_ms:performance.now()-ui.capture.origin,
        initial_state:ui.initialMidi||{},final:false}});
  } catch { /* Saved input will still receive the server's final analysis. */ }
}
function renderBarResults(bars=[]) {
  $('bar-results').replaceChildren(...bars.map(bar=>{
    const icon={correct:'✓',incorrect:'!',waiting:'·',unknown:'?'}[bar.state];
    return el('span',tr`${bar.bar+1}: ${icon}`,`bar-result ${bar.state}`);
  }));
  score.setFeedback(bars);
}

function attemptLabel(attempt) {
  if(attempt.state==='aborted')return tr('Stopped');
  if(attempt.state==='interrupted')return tr('Interrupted');
  if(attempt.qualified_pass)return tr('Successful take');
  if(attempt.result==='passed')return tr('Accurate at this BPM · target BPM not reached');
  if(attempt.mode==='manual')return tr('Direct confirmation needed');
  if(attempt.result==='needs_work')return tr('Needs another try');
  return tr('Analysis incomplete');
}
function attemptNumber(attempt,task=openedTask()) {
  return Math.max(1,(task?.attempts||[]).findIndex(a=>a.id===attempt.id)+1);
}
function attemptCaption(attempt) { return tr`Attempt ${attemptNumber(attempt)} · ${attempt.bpm} BPM`; }
function renderAttempts(task) {
  const list=$('attempt-list');list.replaceChildren();
  const attempts=[...(task.attempts||[])].reverse(),shown=ui.showAllAttempts?attempts:attempts.slice(0,5);
  $('attempt-history-count').textContent=task.recording_coverage?.mode==='legacy'?'—':String(attempts.length);
  $('all-attempts').hidden=attempts.length<=5;
  $('all-attempts').textContent=ui.showAllAttempts?tr('Show recent attempts'):tr`Show all ${attempts.length} attempts`;
  if(!attempts.length)list.append(el('p',tr(task.recording_coverage?.mode==='legacy'?
    'This record uses the previous recording system. Individual attempt counts are unknown.':'Your recorded attempts will appear here.'),'field-note'));
  if(task.recording_coverage?.mode==='mixed')list.append(el('p',tr('Only saved individual attempts are counted here. Earlier records remain in practice details.'),'field-note'));
  for(const attempt of shown) {
    const selected=ui.selectedAttemptId===attempt.id,row=el('article',undefined,'attempt-row');
    row.dataset.attemptId=attempt.id;row.classList.toggle('is-selected',selected);
    const text=el('div',undefined,'attempt-row-content');
    text.append(el('strong',tr`Attempt ${attemptNumber(attempt,task)} · ${attemptLabel(attempt)}`),
      el('small',`${attempt.created_at.slice(0,16).replace('T',' ')} · ${attempt.bpm} BPM`));
    if(task.reopening&&attempt.cycle_id!==task.assessment.cycle_id)text.append(el('span',tr('Before resuming'),'cycle-label'));
    const buttons=el('div',undefined,'attempt-row-actions');
    const detail=el('button',tr('View feedback'),'text-button');detail.type='button';detail.disabled=Boolean(ui.capture)||attempt.state==='recording';
    detail.setAttribute('aria-pressed',String(selected));detail.setAttribute('aria-controls','attempt-review');
    detail.addEventListener('click',()=>loadAttempt(attempt.id,{focus:true}).catch(fail));
    const play=el('button',tr('Play my take'),'text-button');play.type='button';play.disabled=Boolean(ui.capture)||attempt.state==='recording';
    play.addEventListener('click',()=>playSession(attempt.session_id,task,attempt.id).catch(fail));
    buttons.append(detail,play);row.append(text,buttons);list.append(row);
  }
}
async function loadAttempt(id,{focus=false,forPlayback=false}={}) {
  if(!forPlayback)ui.replayRequest++;
  const taskId=openedTask()?.id,request=++ui.detailRequest;
  const value=await api('/api/attempts/'+id);
  if(request!==ui.detailRequest||openedTask()?.id!==taskId||value.task_id!==taskId||ui.capture)return null;
  transport.stopReplay();ui.replayTrack=null;ui.selectedAttemptId=id;ui.selectedAttempt=value;
  showAttemptFeedback(value);renderAttempts(openedTask());
  updateTransport();
  if(focus)focusPanel($('attempt-review'));
  return value;
}
function displayBars(attempt) {
  const bars=attempt.analysis?.bars||[];
  return ['aborted','interrupted'].includes(attempt.state)||attempt.result==='unknown'?
    bars.map(bar=>({...bar,state:'unknown'})):bars;
}
function showAttemptFeedback(attempt) {
  const task=openedTask();if(!task||attempt.task_id!==task.id)return;
  ui.selectedAttemptId=attempt.id;ui.selectedAttempt=attempt;
  const box=$('attempt-feedback'),analysis=attempt.analysis;
  const expanded=box.dataset.attemptId===attempt.id&&box.querySelector('details')?.open;
  box.replaceChildren();box.dataset.attemptId=attempt.id;box.hidden=false;
  const heading=el('div',undefined,'result-heading');
  heading.append(el('h3',attemptLabel(attempt)),el('p',`${attemptCaption(attempt)} · ${attempt.created_at.slice(0,16).replace('T',' ')}`,'field-note'));
  if(task.reopening&&attempt.cycle_id!==task.assessment.cycle_id)heading.append(el('span',tr('Before resuming'),'cycle-label'));
  box.append(heading);
  if(!analysis){box.append(el('p',tr('The recording is still being saved.')));return;}
  const c=analysis.counts||{},unassessed=attempt.mode==='manual'||analysis.result==='unknown';
  const countsAvailable=Number.isFinite(c.expected)&&attempt.mode!=='manual';
  if(analysis.reason)box.append(el('p',tr(analysis.reason)));
  if(attempt.mode==='manual')box.append(el('p',tr(attempt.manual_reason||'Direct confirmation needed')));
  else if(analysis.interrupted||['aborted','interrupted'].includes(attempt.state))box.append(el('p',tr('This attempt was interrupted. Its input is saved, but it has no complete assessment.')));
  else if(!c.matched)box.append(el('p',tr('No notes were matched. Timing, note length and accents could not be assessed.')));
  const metrics=el('div',undefined,'result-metrics');
  for(const [label,value] of [
    ['Notes matched',countsAvailable?`${c.matched||0} / ${c.expected||0}`:tr('Not assessed')],
    ['Missing / extra',countsAvailable?`${c.missing||0} / ${c.extra||0}`:tr('Not assessed')],
    ['Timing errors',!c.matched||unassessed?tr('Not assessed'):String(c.timing_errors||0)],
    ['Note-length issues',!c.matched||unassessed?tr('Not assessed'):String(c.duration_errors||0)],
  ]){const metric=el('div');metric.append(el('span',tr(label)),el('strong',value));metrics.append(metric);}
  box.append(metrics);
  const details=el('details',undefined,'analysis-detail');details.open=Boolean(expanded);
  details.append(el('summary',tr('Bar details, note lengths and accents')));
  if(analysis.timing?.median_ms!=null)details.append(el('p',tr`Median onset offset: ${Math.round(analysis.timing.median_ms)} ms`));
  details.append(el('p',tr`${c.unknown_durations||0} unknown note lengths`));
  const expression=analysis.expression;
  details.append(el('p',tr('Velocity describes MIDI attack strength; it does not measure acoustic loudness or musical expression.'),'field-note'));
  if(expression)details.append(el('p',expression.status==='unknown'?tr('Accent analysis unavailable: not enough velocity variation.'):
    tr`Attack velocity: ${expression.velocity_range[0]}–${expression.velocity_range[1]} · accented median ${expression.accented_median??'—'} · other median ${expression.other_median??'—'}`));
  const accents={not_marked:'No written accents',unknown:'Not enough comparable notes',distinguished:'Written accents had stronger attacks',not_distinguished:'Written accents were not clearly stronger'};
  for(const group of expression?.groups||[])details.append(el('p',`${group.voice} · ${tr(accents[group.status])}${group.delta===null?'':tr` · velocity difference ${group.delta}`}`));
  for(const bar of analysis.bars||[])if(bar.missing.length||bar.extra.length||bar.timing_errors.length){
    const pitch=n=>`${['C','C♯','D','E♭','E','F','F♯','G','A♭','A','B♭','B'][n%12]}${Math.floor(n/12)-1}`;
    details.append(el('p',tr`Bar ${bar.bar+1}: missing ${bar.missing.map(n=>n.name).join(', ')||'—'} · extra ${bar.extra.map(n=>pitch(n.pitch)).join(', ')||'—'} · timing ${bar.timing_errors.map(n=>`${pitch(n.pitch)} ${Math.round(n.timing_ms)} ms`).join(', ')||'—'}`));
  }
  if(analysis.matches?.length){
    const table=el('table',undefined,'note-analysis'),head=el('tr');
    for(const label of ['Bar','Note','Onset offset','Key hold','Sounding','Written'])head.append(el('th',tr(label)));
    const thead=el('thead');thead.append(head);table.append(thead);const body=el('tbody');
    for(const note of analysis.matches.slice(0,100)){
      const row=el('tr');for(const value of [note.bar+1,note.name,...[note.timing_ms,note.key_ms,note.sounding_ms,note.expected_ms].map(ms=>ms==null?'—':`${Math.round(ms)} ms`)])row.append(el('td',String(value)));
      body.append(row);
    }
    table.append(body);const wrap=el('div',undefined,'table-scroll');wrap.append(table);details.append(wrap);
    if(analysis.matches.length>100)details.append(el('p',tr('Showing the first 100 matched notes.'),'field-note'));
  }
  const source=el('a',tr('View saved analysis'));source.href='/api/attempts/'+attempt.id;source.target='_blank';source.rel='noopener';details.append(source);
  box.append(details);
  if(!transport.replay)$('replay-title').textContent=attemptCaption(attempt);
  $('selected-play').hidden=false;$('selected-play').disabled=Boolean(ui.capture)||attempt.state==='recording';
  renderBarResults(displayBars(attempt));
}
async function playSession(sessionId,task=openedTask(),attemptId=null,{focus=true}={}) {
  if(ui.capture)throw Error(tr('Finish the current attempt before replaying.'));
  const request=++ui.replayRequest,taskId=task?.id;
  ui.roomAudioActive=true;await transport.unlock();
  attemptId ||= task.attempts?.find(a=>a.session_id===sessionId)?.id;
  const attempt=attemptId?await loadAttempt(attemptId,{forPlayback:true}):null;
  if(openedTask()?.id!==taskId||request!==ui.replayRequest||attemptId&&!attempt)return;
  const [response,metadata]=await Promise.all([fetch(`/api/recordings/${sessionId}/midi`),api(`/api/recordings/${sessionId}/metadata`)]);
  if(!response.ok)throw Error('Recording not found.');
  const frames=decodeMidiFrames(await response.arrayBuffer()),play=metadata.events.find(e=>e.type==='play');
  if(openedTask()?.id!==taskId||request!==ui.replayRequest||ui.capture)return;
  const origin=attempt?.analysis?.origin_ms??play?.at_ms??0;
  const duration=Math.max(0,(metadata.summary?.elapsed_ms||0)-origin),initial=play?.initial_state||{};
  const notes=decodeNotes(frames,{initial_state:initial}).filter(n=>n.at_ms>=origin-120).map(n=>({...n,
    at_ms:Math.max(0,n.at_ms-origin),key_end:n.key_end==null?null:n.key_end-origin,
    sound_end:n.sound_end==null?duration:n.sound_end-origin}));
  ui.replayTrack={notes,bpm:attempt?.bpm||play?.bpm||task.target.bpm,beats:task.target.notation?.beats_per_bar||4,bars:task.target.bars,duration,
    kind:'recording',attemptId:attempt?.id,recordedAt:metadata.created_at};
  startReplay(0);if(attempt?.analysis)score.setFeedback(displayBars(attempt));
  if(focus)focusPanel($('attempt-review'));
}
function replayCaption() {
  const track=ui.replayTrack;if(!track)return tr('Choose a recording below to hear your performance.');
  const attempt=ui.selectedAttempt?.id===track.attemptId?ui.selectedAttempt:null;
  return track.kind==='score'?tr('Written score · assigned note timing'):attempt?tr`${attemptCaption(attempt)} · My recorded performance`:
    tr`My recorded performance · ${track.bpm} BPM · ${(track.recordedAt||'').slice(0,16).replace('T',' ')}`;
}
function startReplay(from=0,{paused=false}={}) {
  const track=ui.replayTrack;if(!track||ui.capture)return;
  ui.replayRequest++;
  score.begin();const total=track.bars*track.beats;
  for(const note of score.input&&track.kind==='recording'?track.notes:[]){
    const at=ms=>{const absolute=Math.max(0,ms*track.bpm/60000);return {absolute,pass:0,bar:Math.min(track.bars-1,Math.floor(absolute/track.beats)),beat:absolute%track.beats};};
    if(note.at_ms*track.bpm/60000>=total)continue;
    score.input.midi([0x90,note.pitch,note.velocity],String(note.port||0),at(note.at_ms));
    score.input.midi([0x80,note.pitch,0],String(note.port||0),at(note.key_end??track.duration));
  }
  score.drawNotes();transport.playRecording(track.notes,{...track,from,rate:Number($('replay-rate').value)});
  score.frame(transport.position());
  if(paused)transport.pauseReplay();
  if(track.kind==='recording'&&ui.selectedAttempt)score.setFeedback(displayBars(ui.selectedAttempt));
  $('replay-title').textContent=replayCaption();updateTransport();
}

async function refresh(keep = false, skipUnchanged = false) {
  const previous = openedTask()?.id;
  const data = await api('/api/state');
  if (data.language !== locale()) return; // A newer language selection superseded this response.
  if (skipUnchanged && JSON.stringify(data) === JSON.stringify(ui.data)) return;
  ui.data = data;
  initializeMidiPreferences();
  applyPlaybackSettings(data.playback_settings);
  outbox ||= new Outbox(ui.data.workspace_id);
  const current = pending();
  if (ui.openedTaskId && !openedTask()) { ui.openedTaskId = null; if (ui.view === 'practice') switchView('list'); }
  $('connection').textContent = tr('Connected locally');
  $('preview-badge').hidden = !ui.data.preview;
  $('version').textContent = tr`VERSION ${ui.data.status.version}`;
  $('today-date').textContent = tr`${ui.data.status.today.date.replaceAll('-', '. ')} / DAILY PRACTICE`;
  const daily = ui.data.status.today;
  $('daily-time').replaceChildren(document.createTextNode(Number(daily.known_minutes.toFixed(1)).toString()), el('span', tr` / ${daily.budget_minutes} min`));
  $('daily-count').textContent = tr`${daily.reported_attempts} completed${daily.minutes_unknown ? tr` · duration unknown: ${daily.minutes_unknown}` : daily.budget_reached ? tr(' · good work today') : ''}`;
  renderGeneration();
  renderChoices();
  renderLesson(!keep || previous !== openedTask()?.id);
  renderHistory();
  renderRecordText();
  if ($('history-dialog').open && detailTask) {
    const task = ui.data.history.find(t => t.id === detailTask.id);
    if (task) showDetail(task);else {$('history-dialog').close();detailTask=null;}
  }
  $('recovery').hidden = openSessions().length === 0;
  updateTransport();
  scheduleTranslations();
}

let translationTimer, translationPosting = false;
const translationRetries = new Set();
function scheduleTranslations() {
  clearTimeout(translationTimer);
  if (translationPosting || !ui.data || ui.data.language !== locale()) return;
  const translating = ui.data.history.some(t => t.target.translation?.state === 'running');
  const next = ui.data.history.find(t => t.target.translation?.state === 'missing' || translationRetries.has(t.target.translation?.id));
  if (!translating && !next) return;
  translationTimer = setTimeout(async () => {
    translationPosting = true;
    try {
      if (!translating && next) {
        const identity = next.target.translation.id;
        const job = await api('/api/translate', {task_id: next.id, retry: translationRetries.has(identity)});
        if (['running', 'completed', 'original'].includes(job.state)) translationRetries.delete(identity);
      }
      await refresh(true, true);
    } catch (error) { fail(error); }
    finally { translationPosting = false; scheduleTranslations(); }
  }, 1500);
}
function translationNotice(task) {
  const state = task.target.translation;
  const box = el('div', undefined, 'translation-notice');
  if (!state || ['original', 'completed'].includes(state.state)) return box;
  box.setAttribute('role', 'status');
  const retrying = translationRetries.has(state.id);
  box.append(el('span', state.state === 'failed' && !retrying ? state.error : tr('Translating this practice… Showing the original while you wait.')));
  if (state.state === 'failed' && !retrying) {
    const retry = el('button', tr('Retry translation'), 'text-button');
    retry.addEventListener('click', () => {
      translationRetries.add(state.id); retry.disabled = true; scheduleTranslations();
    });
    box.append(retry);
  }
  return box;
}

let generationTimer;
async function pollGeneration() {
  try { await refresh(true); }
  catch (error) { fail(error); generationTimer = setTimeout(pollGeneration, 3000); }
}
function renderGeneration() {
  const job = ui.creating ? {state: 'running', has_request: Boolean(ui.submittedFocus?.trim())} : ui.data.recommendation;
  $('generation-panel').hidden = !job || (job.state === 'completed' && !ui.data.history.some(t => t.id === job.task_id && t.pending));
  if (job) {
    $('generation-panel').setAttribute('aria-busy', String(job.state === 'running'));
    $('generation-title').textContent = tr(job.state === 'running' ? 'Creating your practice…' : job.state === 'completed' ? 'Your new practice is in the list.' : 'Could not create a practice');
    $('generation-message').textContent = job.state === 'running' ? tr(job.has_request ? 'Your focus is included. Codex is reviewing it with your profile and practice records. This may take a few minutes.' : 'Codex is reviewing your profile, practice records, feedback, and notes. You can stay on this page; this may take a few minutes.') : job.state === 'failed' ? job.error : tr('Open the item when you are ready to practice.');
    const stages = {materials: 'Finding teaching material for your practice goal…', generating: 'Writing the exercise and score…', checking: 'Checking the music and correcting a notation issue…'};
    if (job.state === 'running' && stages[job.stage]) {
      $('generation-message').textContent = (job.has_request ? tr('Your requested focus is included.') + ' ' : '') + tr(stages[job.stage]);
    }
    if (job.state === 'completed' && job.id === ui.submittedRequestId) {
      if ($('recommendation-request').value === ui.submittedFocus) $('recommendation-request').value = '';
      ui.submittedRequestId = null;
    }
    $('retry-recommendation').hidden = job.state !== 'failed';
    if (job.state !== 'running') ui.newRequestId = null;
  }
  clearTimeout(generationTimer);
  if (job?.state === 'running') generationTimer = setTimeout(pollGeneration, 1500);
}
function renderChoices() {
  const generating = ui.creating || ui.data.recommendation?.state === 'running';
  const lock = ui.busy || generating;
  for (const id of ['tempo', 'tempo-range']) { $(id).min = ui.data.minimum_bpm; $(id).max = ui.data.maximum_bpm; }
  $('new-practice').disabled = lock || Boolean(ui.capture) || openSessions().length > 0;
  $('retry-recommendation').disabled = $('new-practice').disabled;
  $('recommendation-request').disabled = generating || ui.busy;
  $('recommendation-focus').hidden = Boolean(generating);
  const active=ui.data.history.filter(t=>t.pending).length;
  $('pending-hint').textContent=active?tr`${active} active practices · choose one or add another.`:'';
  const exerciseFilter = $('filter-exercise').value, keyFilter = $('filter-key').value;
  const exercises = new Map(ui.data.history.map(t => [t.exercise_id, t.target.title]));
  const keys = [...new Set(ui.data.history.map(t => t.target.key))];
  $('filter-exercise').replaceChildren(option('', tr('All exercises')), ...[...exercises].map(([id, title]) => option(id, title)));
  $('filter-key').replaceChildren(option('', tr('All keys')), ...keys.map(k => option(k, k)));
  $('filter-exercise').value = exercises.has(exerciseFilter) ? exerciseFilter : '';
  $('filter-key').value = keys.includes(keyFilter) ? keyFilter : '';
}
function appendAnalysis(parent, t, open = false) {
  if (!t.analysis) return;
  const analysis = el('details', undefined, 'recommendation-analysis');
  analysis.open = open;
  analysis.append(el('summary', tr('Why this practice?')));
  analysis.append(el('p', t.exercise.selection_reason));
  if (t.exercise.development) analysis.append(el('p', t.exercise.development.difference_from_recent));
  analysis.append(el('h4', tr('Coach interpretation · not measured performance')));
  for (const evidence of t.analysis.evidence) {
    const materials = new Set((t.source_references || []).flatMap(r => [r.source_id, r.excerpt_id]));
    if (evidence.source_ids.some(id => materials.has(id))) analysis.append(el('small', tr('Teaching material · not player performance')));
    analysis.append(el('p', evidence.interpretation));
    analysis.append(el('small', `${tr('Confidence')}: ${tr(evidence.confidence)} · ${tr('Sources')}: ${evidence.source_ids.join(', ')}`));
  }
  analysis.append(el('h4', tr('Still unknown')));
  for (const unknown of t.analysis.unknowns) analysis.append(el('p', unknown));
  if (t.generation?.request_id) {
    const link = el('a', tr('View the original recommendation context'));
    link.href = `/api/recommendations/${t.generation.request_id}`;
    link.target = '_blank'; link.rel = 'noopener'; analysis.append(link);
  }
  parent.append(analysis);
}

function appendDevelopment(parent, t) {
  if (!t.exercise?.development) return;
  const details = el('dl', undefined, 'task-parts development-details');
  for (const [key, label] of [['musical_structure', 'Musical phrase'], ['expression', 'Listen for'], ['application', 'Apply it']]) {
    details.append(el('dt', tr(label)), el('dd', t.exercise.development[key]));
  }
  parent.append(details);
}

function appendReferences(parent, t) {
  if (!t.source_references?.length) return;
  const section = el('section', undefined, 'practice-references');
  section.append(el('h4', tr('Practice references')));
  for (const [i, ref] of t.source_references.entries()) {
    const item = el('div', undefined, 'practice-reference');
    const kind = ref.role === 'teaching_reference' ? 'Teaching concept reference' : ref.mode === 'source_original' ? 'Original source example' : 'Adapted source example';
    item.append(el('span', tr(kind), 'reference-kind'));
    const link = el('a', ref.source.title);
    try { if (new URL(ref.source.url).protocol === 'https:') link.href = ref.source.url; } catch {}
    link.target = '_blank'; link.rel = 'noopener noreferrer';
    item.append(link, el('small', `${ref.source.author} · ${ref.locator.kind === 'pdf_page' ? tr`PDF page ${ref.locator.page}` : ref.locator.label}`));
    if (ref.source_excerpt) item.append(el('small', t.references?.[i]?.source_excerpt || ref.source_excerpt));
    for (const change of t.references?.[i]?.changes || ref.changes) item.append(el('p', change));
    section.append(item);
  }
  parent.append(section);
}

const burdenLabels = {unknown: 'Not enough evidence', underload: 'May be too easy', workable: 'Likely manageable', challenging: 'Likely challenging', overload: 'May be overwhelming'};
function appendTaskOverview(parent, t, compact = false, open = false) {
  const overview = el('section', undefined, 'task-overview');
  overview.setAttribute('aria-label', tr('Task characteristics and personal burden'));
  overview.append(el('h4', tr('Task characteristics')));
  const traits = t.task_characteristics;
  const chips = el('div', undefined, 'characteristic-chips');
  for (const tag of traits?.tags || []) chips.append(el('span', tr(tag), 'characteristic-chip'));
  if (chips.childElementCount) overview.append(chips);
  else overview.append(el('p', t.exercise?.rhythm || t.instructions, 'task-description'));
  const prediction = t.difficulty?.prediction;
  const burden = el('p', undefined, 'burden-prediction');
  burden.append(el('span', tr('Personal burden · when assigned'), 'burden-label'),
    el('strong', tr(prediction ? burdenLabels[prediction.burden] : 'No prediction was saved for this task.'), 'burden-value'));
  overview.append(burden);
  parent.append(overview);
  if (compact) return;
  const details = el('details', undefined, 'task-context-detail'); details.open = open;
  details.append(el('summary', tr('Written conditions and prediction evidence')),
    el('p', tr('These characteristics describe the assigned task, not measured performance.'), 'subtle'));
  if (!traits?.notation_available) details.append(el('p', tr('No fixed score is available. Follow the written conditions.')));
  if (t.exercise) {
    const parts = el('dl', undefined, 'task-parts');
    for (const [label, text] of [['Rhythm', t.exercise.rhythm], ['Left hand', t.exercise.left_hand], ['Right hand', t.exercise.right_hand]]) {
      parts.append(el('dt', tr(label)), el('dd', text));
    }
    details.append(parts);
  }
  if (prediction) {
    details.append(el('h4', tr('Why this personal prediction?')), el('p', prediction.reason),
      el('p', prediction.uncertainty, 'subtle'));
    if (prediction.source_ids.length) details.append(el('small', `${tr('Sources')}: ${prediction.source_ids.join(', ')}`));
  }
  overview.append(details);
}

function target() { return openedTask()?.target; }
function renderLesson(resetTempo = false) {
  const current = openedTask(), t = target();
  if (!current) return;
  score.setScore(t.notation,ui.scoreContext||current.id);
  if ($('view-practice').dataset.taskId !== current.id) {
    $('task-context').open = false;
    $('lesson-guide').open = false;
    $('lesson-material').open = !t.notation;
    $('view-practice').dataset.taskId = current.id;
  }
  $('lesson-kind').textContent = tr(current.completed?'Completed practice':'Current task');
  $('lesson-title').textContent = t.title;
  $('lesson-id').replaceChildren(taskIdentity(current.id));
  $('lesson-translation').replaceChildren(translationNotice(current));
  $('lesson-phase').textContent = t.kind === 'generated' ? tr('Personal practice') : tr('Practice');
  $('lesson-purpose').textContent = t.exercise?.objective || t.material.title;
  $('lesson-section').textContent = t.exercise?.section || '';
  $('lesson-notes').textContent = t.exercise ? [t.exercise.notes, !t.notation ? t.exercise.notation_reason : ''].filter(Boolean).join('\n') : '';
  $('bar-position').textContent = ui.capture && ui.beat ? tr`Bar ${ui.beat.bar + 1} · beat ${ui.beat.beat + 1}` : tr('Chord changes by bar');
  const beats = t.notation?.beats_per_bar || t.playback?.beats_per_bar || 4;
  $('target-meta').replaceChildren(...[tr`Key ${t.key}`, tr`Target ${t.bpm} BPM`, tr`${t.bars} bars`, `${beats}/4`].map(s => el('span', s)));
  $('beats').replaceChildren(...Array.from({length: beats}, (_, i) => el('span', String(i + 1))));
  let chords = t.notation?.format === 'abc' ? t.notation.bars.map(b =>
    [b.chord, ...(b.harmony || []).filter(h => h.beat > 0).map(h => h.chord)].filter(Boolean).join(' → ')) : t.playback?.bars.map(b => b.chord);
  if (!chords) chords = t.material.chords.split('|').map(s => s.trim());
  $('chords').replaceChildren(...chords.map((chord, index) => { const box = el('div', undefined, 'chord-box'); box.append(el('small', `${String(index + 1).padStart(2, '0')}`), el('strong', chord)); return box; }));
  $('hand-notes').replaceChildren();
  const rows = [];
  if (t.bass !== 'none' && t.material.roots) rows.push([tr('Left hand'), t.material.roots]);
  if (t.melody !== 'none' && t.material.melody) rows.push([tr('Right hand'), t.material.melody]);
  if (t.voicing !== 'none' && t.material.guide_tones) rows.push([tr('Right hand'), t.material.guide_tones]);
  if (t.arrangement === 'left-bass-only') rows.push([tr('Right hand'), tr('Rest comfortably')]);
  if (t.arrangement === 'right-melody-only') rows.push([tr('Left hand'), tr('Rest comfortably')]);
  for (const [label, text] of rows) { const row = el('div', undefined, 'hand-row'); row.append(el('span', label), el('strong', text)); $('hand-notes').append(row); }
  $('lesson-instructions').textContent = t.instructions;
  $('criterion-text').textContent = t.exercise?.rhythm || tr`Play ${t.criteria.min_clean_runs} consecutive runs with correct notes, a steady pulse, and no stops under the assigned conditions.`;
  $('lesson-steps').replaceChildren(...(t.exercise?.steps || []).map(step => el('li', step)));
  $('lesson-development').replaceChildren();
  appendDevelopment($('lesson-development'), t);
  $('lesson-references').replaceChildren();
  appendReferences($('lesson-references'), t);
  const contextOpen = $('lesson-overview').querySelector('.task-context-detail')?.open;
  const coachOpen = $('lesson-analysis').querySelector('.recommendation-analysis')?.open;
  $('lesson-analysis').replaceChildren();
  $('lesson-overview').replaceChildren();
  appendTaskOverview($('lesson-overview'), t, false, contextOpen);
  appendAnalysis($('lesson-analysis'), t, coachOpen);
  if(t.notation)$('lesson-resources').append($('lesson-material'));else $('written-material').append($('lesson-material'));
  $('discard-btn').hidden = !current.pending;
  const backing=backingFor(t);ui.backing=backing;
  const available=backing.source!=='unavailable';$('pad-toggle').disabled=!available;
  $('backing-status').textContent=tr(backing.source==='assigned'?'Assigned accompaniment':available?'Backing from written chord symbols':'No supported chord progression for a pad.')+
    (backing.unavailable.length?' · '+backing.unavailable.join(', '):'');
  if(!ui.capture)transport.configure(backing.playback,Number($('tempo').value)||t.bpm);
  $('reference-play').disabled=!t.notation||Boolean(ui.capture);
  const replayBar=$('replay-bar').value;
  $('replay-bar').replaceChildren(...Array.from({length:t.bars},(_,i)=>option(String(i),String(i+1))));
  if(Number(replayBar)<t.bars)$('replay-bar').value=replayBar||'0';
  if(!ui.capture&&!ui.manualTouched)$('manual-mode').checked=false;
  renderAttempts(current);
  if(ui.selectedAttempt&&!ui.capture&&(!transport.replay||ui.replayTrack?.kind==='recording'))showAttemptFeedback(ui.selectedAttempt);
  if (resetTempo && !ui.capture) setTempo(t.bpm);
}
function setTempo(value) {
  if(transport.replay){updateTransport();return;}
  if (ui.lockedBpm != null) {
    $('tempo').value = $('tempo-range').value = ui.lockedBpm;
    return;
  }
  const numeric = Math.min(ui.data.maximum_bpm, Math.max(ui.data.minimum_bpm, Math.round(Number(value) || ui.data.minimum_bpm)));
  $('tempo').value = $('tempo-range').value = numeric;
  transport.setTempo(numeric);
}
function updateTransport() {
  if(!ui.data)return;
  const recording=ui.capture,recovery=openSessions().length>0,task=openedTask(),eligible=Boolean(task?.pending),replaying=Boolean(transport.replay);
  const locked=Boolean(recording)||ui.busy||recovery;
  for(const id of ['tempo','tempo-range','tempo-down','tempo-up'])$(id).disabled=locked||replaying;
  for(const id of ['manual-mode','latency-ms'])$(id).disabled=locked;
  const playbackBpm=replaying?Number((transport.replay.bpm*transport.replay.rate).toFixed(2)):null;
  $('tempo').value=$('tempo-range').value=playbackBpm??ui.lockedBpm??transport.requestedBpm;
  toolbar.dataset.phase=ui.phase;toolbar.dataset.replay=String(replaying);
  $('tempo-hint').textContent=replaying?tr('Change playback tempo with Playback speed.'):tr(recording?'BPM is fixed for this attempt.':'Choose BPM before an attempt.');
  $('practice-actions').hidden=replaying;$('replay-actions').hidden=!replaying;
  $('practice-btn').hidden=!eligible||Boolean(recording);
  $('practice-btn').disabled=locked||!eligible||replaying||selectedPorts().length===0;
  $('practice-btn').textContent=tr(ui.phase==='starting'?'Starting attempt…':'Start attempt');
  $('practice-btn').setAttribute('aria-busy',String(ui.phase==='starting'));
  $('abort-attempt').hidden=!recording;
  $('abort-attempt').textContent=tr(ui.finishing?'Saving and analyzing':recording?.ended?'Retry save':ui.phase==='countin'?'Cancel attempt':'Stop attempt');
  $('abort-attempt').disabled=Boolean(ui.finishing);
  $('resume-practice').hidden=!task?.completed;$('resume-practice').disabled=locked;
  $('finish-btn').hidden=!eligible;$('discard-btn').hidden=!eligible;
  $('finish-btn').disabled=locked||!eligible||!(task?.assessment?.eligible||task?.assessment?.manual_available);
  $('discard-btn').disabled=locked||!eligible;
  document.querySelector('.attempt-preferences').hidden=!eligible;
  $('back-list').disabled=ui.busy||Boolean(ui.finishing);
  $('reference-play').disabled=!task?.target.notation||Boolean(recording)||ui.busy;
  $('selected-play').disabled=Boolean(recording)||ui.busy;
  $('replay-pause').disabled=!replaying;$('replay-stop').disabled=!replaying;
  $('replay-rate').disabled=Boolean(recording);$('replay-bar').disabled=Boolean(recording);
  $('replay-pause').textContent=tr(transport.replay?.paused?'Resume playback':'Pause playback');
  $('manual-confirm-label').hidden=Boolean(task?.assessment?.eligible);
  const phases={starting:'Starting attempt…',idle:'Ready for an attempt',countin:'Count-in',playing:'Recording one pass',tail:'Release the final keys',saving:'Saving and analyzing',aborted:'Stopped'};
  if(replaying){$('transport-state').textContent=transport.replay.paused?tr('Playback paused'):ui.replayTrack?.kind==='score'?tr('Written score playback'):
    ui.selectedAttempt?tr`Playing attempt ${attemptNumber(ui.selectedAttempt)}`:tr('Recorded take playback');$('replay-title').textContent=replayCaption();}
  else if(task?.completed)$('transport-state').textContent=tr('Completed practice');
  else if(ui.phase!=='countin')$('transport-state').textContent=tr(phases[ui.phase]||'Ready');
  else if(!ui.countInBeat)$('transport-state').textContent=tr('Count-in');
  if(!recording&&!replaying)$('score-position').textContent=ui.selectedAttempt?tr`Viewing attempt ${attemptNumber(ui.selectedAttempt)}`:'';
  let hint='';
  if(recovery)hint=tr('Recover the unfinished recording before starting.');
  else if(replaying)hint=tr`Playback ${playbackBpm} BPM · speed ${transport.replay.rate}×`;
  else if(recording)hint=tr(recording.ended&&!ui.finishing?'The take is saved in this browser. Retry the upload.':ui.attemptContract?.mode==='manual'?'Unscored take · confirm the goal after one full pass.':'BPM is fixed for this attempt.');
  else if(task?.completed)hint=tr('Resume this practice to record another attempt.');
  else if(eligible){
    if(task.assessment.eligible)hint=tr`Ready to complete · ${task.assessment.successes} successful take(s) this round.`;
    else if(task.assessment.manual_available)hint=tr('Ready to complete · confirm the goal yourself.');
    else if(!selectedPorts().length)hint=tr('Connect MIDI to start an attempt. Listening and the metronome remain available.');
    else if($('manual-mode').checked||!task.target.notation)hint=tr`Finish one full take at ${task.target.bpm} BPM or above, then confirm the goal.`;
    else if(task.reopening)hint=tr('A new successful take is required after resuming.');
    else hint=tr`Complete after one successful take at ${task.target.bpm} BPM or above.`;
  }
  $('completion-hint').textContent=hint;
  $('attempt-mode-note').textContent=tr(recording&&ui.attemptContract?.manual_reason?ui.attemptContract.manual_reason:
    $('manual-mode').checked?'MIDI is recorded; confirm the goal yourself after a full take.':'MIDI input is recorded only during the take.');
  $('save-status').hidden=!ui.saveStatus||ui.saveStatus==='Autosaved';
  if(ui.saveStatus)$('save-status').textContent=tr(ui.saveStatus);
  renderControllerBindings();
}

function registerPort(port) {
  if (!ui.capture || ui.ports.has(port.id)) return;
  const index = ui.ports.size;
  ui.ports.set(port.id, index);
  ui.capture.event('device', {index, name: port.name || 'Unnamed input', manufacturer: port.manufacturer || '', id: port.id});
}
function controlActionLabel(action) {return tr({record:'Start attempt / retry',stop:'Stop',play:'Play / pause'}[action]);}
function saveMidiPreferences() {
  try{localStorage.setItem(ui.midiPrefsKey,JSON.stringify(ui.midiPrefs));}
  catch{$('controller-status').textContent=tr('MIDI preferences are available in this tab only.');}
}
function initializeMidiPreferences() {
  const key='my-jazz-tutor.midi:'+ui.data.workspace_id;if(ui.midiPrefsKey===key)return;
  ui.midiPrefsKey=key;let saved;
  try{saved=JSON.parse(localStorage.getItem(key)||'null');}catch{}
  ui.midiPrefs=midiPreferences(saved);ui.midiControls=new MidiControls(ui.midiPrefs.bindings);
  $('midi-reconnect').checked=ui.midiPrefs.remember;$('keyboard-shortcuts').checked=ui.midiPrefs.keyboard;
  renderControllerBindings();restoreMidiAccess();
}
function restoreSelectedInput() {
  if(!ui.midiPrefs||!midiAccess)return;
  const choice=ui.midiPrefs.selection;
  if(choice.mode==='device')midiSelection=resolvePort(choice,[...midiAccess.inputs.values()].filter(p=>!controlOnlyPort(p)))?.id||choice.id;
  else midiSelection=choice.mode;
}
async function restoreMidiAccess() {
  if(!ui.midiPrefs.remember||!navigator.requestMIDIAccess||window.isSecureContext===false)return;
  let permitted=ui.midiPrefs.connectedBefore;
  try {
    const permission=await navigator.permissions.query({name:'midi',sysex:false});
    if(permission.state!=='granted'){
      if(ui.midiPrefs.connectedBefore){ui.midiNotice='Allow MIDI access again to reconnect.';$('midi-status').textContent=tr(ui.midiNotice);}
      return;
    }
    permitted=true;
  } catch { /* Browsers without MIDI permission querying can retry prior consent. */ }
  if(permitted&&ui.midiPrefs.remember&&!midiAccess)await connectMidi(true);
}
async function connectMidi(automatic=false) {
  if(!ui.data||ui.midiConnecting)return;
  if(!automatic)clearError();
  if(window.isSecureContext===false){ui.midiNotice='MIDI input requires HTTPS or localhost. You can still practice with the metronome.';$('midi-status').textContent=tr(ui.midiNotice);return;}
  if(!navigator.requestMIDIAccess){ui.midiNotice='This browser does not support Web MIDI. Practice without MIDI or connect using a supported browser.';$('midi-status').textContent=tr(ui.midiNotice);return;}
  ui.midiConnecting=true;$('midi-connect').disabled=true;
  try {
    const access=await navigator.requestMIDIAccess({sysex:false});
    if(midiAccess&&midiAccess!==access){for(const port of midiAccess.inputs.values())port.onmidimessage=null;midiAccess.onstatechange=null;}
    midiAccess=access;ui.midiPrefs.connectedBefore=true;saveMidiPreferences();
    midiAccess.onstatechange=event=>{
      if(event.port.type==='input'&&event.port.state==='disconnected'){
        ui.midiControls.disconnect(event.port);score.disconnect(event.port.id,transport.position());
        if(midiSelection==='all'||midiSelection===event.port.id)ui.capture?.event('disconnect',{id:event.port.id});
      }
      midiBindings();
    };
    midiBindings();
  } catch {ui.midiNotice='MIDI access was denied. Check browser permissions. Other practice features are still available.';$('midi-status').textContent=tr(ui.midiNotice);}
  finally{ui.midiConnecting=false;$('midi-connect').disabled=false;updateTransport();}
}
function renderControllerBindings() {
  if(!ui.midiControls)return;
  for(const [id,key] of [['practice-btn','R'],['abort-attempt','S'],['replay-pause','Space'],['replay-stop','S']])
    if(ui.midiPrefs.keyboard)$(id).setAttribute('aria-keyshortcuts',key);else $(id).removeAttribute('aria-keyshortcuts');
  const locked=Boolean(ui.capture)||ui.busy||Boolean(transport.replay);
  for(const action of CONTROL_ACTIONS){
    const binding=ui.midiControls.bindings[action];
    const text=binding?`${binding.port.name||tr('MIDI input')} · ${binding.kind==='note'?'Note':'CC'} ${binding.number}${binding.kind==='cc'?' = '+binding.value:''} · Ch ${binding.channel+1}`:tr('Not assigned');
    document.querySelector(`[data-midi-binding="${action}"]`).textContent=text;
    document.querySelector(`[data-learn-action="${action}"]`).disabled=locked||!midiAccess||![...midiAccess.inputs.values()].some(p=>p.state==='connected');
    document.querySelector(`[data-clear-action="${action}"]`).disabled=locked||!binding;
  }
}
async function runTransportControl(action) {
  if(ui.view!=='practice'||!openedTask()||document.hidden||document.querySelector('dialog[open]')||ui.midiControls?.learning)return;
  if(action==='stop'){
    ui.replayRequest++;
    if(ui.capture&&!ui.finishing&&!ui.busy)await stopCapture();
    else if(transport.replay){transport.stopReplay();updateTransport();}
    return;
  }
  if(ui.busy||ui.finishing||ui.controlLoading||ui.capture)return;
  if(action==='record'){
    if(!openedTask().pending||!selectedPorts().length)return;
    ui.replayRequest++;transport.stopReplay();await startOrPause();return;
  }
  if(action==='play'){
    if(transport.replay){if(transport.replay.paused)startReplay(transport.replay.from);else transport.pauseReplay();updateTransport();return;}
    ui.controlLoading=true;
    try {
      const attempt=ui.selectedAttempt;
      if(attempt?.session_id)await playSession(attempt.session_id,openedTask(),attempt.id,{focus:false});
      else await playWrittenScore();
    } finally {ui.controlLoading=false;}
  }
}
function selectedPorts() { return midiAccess ? [...midiAccess.inputs.values()].filter(p => p.state === 'connected'&&!controlOnlyPort(p)&&(midiSelection === 'all' || midiSelection === p.id)) : []; }
function midiBindings() {
  if (!midiAccess) return;
  restoreSelectedInput();
  const available = [...midiAccess.inputs.values()].filter(p => p.state === 'connected'&&!controlOnlyPort(p));
  $('midi-input').hidden = false;
  $('midi-input').replaceChildren(option('all', tr('Record all connected inputs')), option('none', tr('Turn MIDI recording off')), ...available.map(p => option(p.id, p.name || tr('MIDI input'))));
  if (![...$('midi-input').options].some(o => o.value === midiSelection)) $('midi-input').append(option(midiSelection, tr('Selected device · disconnected')));
  $('midi-input').value = midiSelection;
  for (const port of midiAccess.inputs.values()) {
    if (selectedPorts().includes(port)) registerPort(port);
    port.onmidimessage = message => {
      if(port.state!=='connected')return;
      const routed=ui.midiControls.process(port,message.data,[...midiAccess.inputs.values()]);
      if(routed.learned){ui.midiPrefs.bindings=structuredClone(ui.midiControls.bindings);saveMidiPreferences();$('midi-learn-dialog').close();renderControllerBindings();}
      if(routed.conflict){$('midi-learn-status').textContent=tr`This pad is already assigned to ${controlActionLabel(routed.conflict)}.`;}
      if(routed.action)runTransportControl(routed.action).catch(fail);
      if(routed.consume||controlOnlyPort(port))return;
      if (midiSelection !== 'all' && midiSelection !== port.id) return;
      $('midi-light').classList.add('received');
      clearTimeout(port.indicatorTimer);
      port.indicatorTimer = setTimeout(() => $('midi-light').classList.remove('received'), 110);
      const position=transport.inputPosition(message.timeStamp),data=message.data,type=data[0]&0xf0,channel=data[0]&15;
      if(ui.capture&&!ui.capture.ended&&message.timeStamp>=ui.plannedStart-ui.attemptContract.tolerance_ms&&
          ['countin','playing','tail'].includes(ui.phase)) {
        if(position)beginRecordedPass();
        registerPort(port);const index=ui.ports.get(port.id);
        ui.capture.midi(data,index,message.timeStamp);
        if([0x80,0x90].includes(type)||type===0xb0&&[64,120,121,123].includes(data[1])){
          if(ui.midiFrames.length<30000)ui.midiFrames.push({at_ms:Math.max(0,Math.min(message.timeStamp,performance.now())-ui.capture.origin),port:index,data:[...data]});
          else ui.analysisLimited=true;
        }
        if(ui.phase!=='countin')score.midi(data,port.id,scorePositionAt(message.timeStamp));
        $('midi-status').textContent=tr`Recording input · ${ui.capture.noteCount} note-ons`;
      }
      const key=`${port.id}:${channel}:${data[1]}`,pedalKey=`${port.id}:${channel}`;
      if(type===0x90&&data[2]>0)heldKeys.set(key,{port:port.id,channel,pitch:data[1]});
      if(type===0x80||type===0x90&&data[2]===0)heldKeys.delete(key);
      if(type===0xb0&&data[1]===64){if(data[2]>=64)heldPedals.set(pedalKey,{port:port.id,channel});else heldPedals.delete(pedalKey);}
      if(type===0xb0&&[120,123].includes(data[1]))for(const [id,note] of heldKeys)if(note.port===port.id&&note.channel===channel)heldKeys.delete(id);
      if(type===0xb0&&[120,121].includes(data[1]))heldPedals.delete(pedalKey);

    };
  }
  ui.midiNotice = null;
  $('midi-light').classList.toggle('connected', selectedPorts().length > 0);
  $('midi-status').textContent = midiSelection === 'none' ? tr('MIDI recording is off.') : selectedPorts().length ? tr`${selectedPorts().length} input(s) ready · MIDI is recorded only during an attempt.` : tr('No inputs connected. The metronome is still available.');
  $('midi-connect').textContent = tr('Refresh');
  if(!ui.capture&&!ui.manualTouched)$('manual-mode').checked=false;
  updateTransport();
}

async function startOrPause() {
  if(ui.busy||ui.capture||transport.replay||!openedTask()?.pending)return;
  if(!selectedPorts().length){fail(new Error(tr('Connect MIDI before starting an attempt.')));return;}
  clearError();ui.busy=true;ui.phase='starting';updateTransport();
  try {
    ui.roomAudioActive=true;await transport.unlock();await outbox.database();
    if(!selectedPorts().length)throw Error(tr('Connect MIDI before starting an attempt.'));
    ui.nextAttemptId ||= 'A-'+randomHex();
    const bpm=Number($('tempo').value),manual=$('manual-mode').checked;
    const result=await api('/api/attempts/start',{task_id:openedTask().id,attempt_id:ui.nextAttemptId,bpm,manual,
      latency_ms:Number($('latency-ms').value)||0});
    ui.nextAttemptId=null;ui.currentAttempt=result.attempt;ui.attemptContract=result.attempt.contract;
    ui.detailRequest++;ui.replayRequest++;analysisSerial++;ui.selectedAttempt=null;ui.selectedAttemptId=null;ui.replayTrack=null;ui.countInBeat=null;ui.saveStatus=null;
    $('selected-play').hidden=true;$('playback-settings').open=false;
    ui.capture=new Capture(result.session,outbox,api,(text,warning)=>{
      ui.saveStatus=text;$('save-status').textContent=tr(text);$('save-status').classList.toggle('save-warning',warning);
    });
    ui.ports.clear();ui.midiFrames=[];ui.analysisLimited=false;ui.analysisBar=null;ui.initialMidi={};ui.phase='countin';
    await ui.capture.begin();selectedPorts().forEach(registerPort);ui.lockedBpm=bpm;
    ui.capture.event('countin');ui.capture.event('pad',{enabled:$('pad-toggle').checked});
    ui.capture.event('click',{enabled:$('click-toggle').checked});ui.capture.event('drum',{enabled:$('drum-toggle').checked});
    $('attempt-feedback').hidden=true;renderBarResults([]);
    score.begin();score.frame({absolute:0,pass:0,bar:0,beat:0});
    transport.click=$('click-toggle').checked;transport.padEnabled=$('pad-toggle').checked;transport.drums=$('drum-toggle').checked;
    const planned=transport.startAttempt(ui.backing.playback,bpm);ui.plannedStart=planned.performanceTime;
    clearInterval(timer);timer=setInterval(()=>{if(ui.capture&&['playing','tail'].includes(ui.phase))requestAnalysis();},250);
    $('save-status').textContent=tr('One count-in bar, then one recorded pass.');
  } catch(error){fail(error);if(ui.capture){ui.capture.event('aborted');try{await stopCapture();}catch{}}}
  finally{ui.busy=false;if(!ui.capture){ui.lockedBpm=null;ui.phase='idle';}updateTransport();}
}
async function stopCapture() {
  if(ui.finishing)return ui.finishing;
  if(!ui.capture)return;
  if(transport.attempt)transport.abortAttempt();
  const capture=ui.capture;ui.phase='saving';clearInterval(timer);
  ui.finishing=(async()=>{
    try {
      const saved=await capture.stop();ui.capture=null;ui.lockedBpm=null;ui.phase='idle';
      score.pause(score.position);
      ui.latestAttempt=saved.attempt||null;ui.currentAttempt=null;ui.plannedStart=null;
      await refresh(true);
      if(saved.attempt&&openedTask()?.id===saved.attempt.task_id){showAttemptFeedback(saved.attempt);renderAttempts(openedTask());}
      midiBindings();return saved;
    } finally {ui.finishing=null;updateTransport();}
  })();
  updateTransport();return ui.finishing;
}
async function finish() {
  const task=openedTask();if(!task?.pending||ui.busy||ui.capture)return;
  $('complete-summary').textContent=task.assessment.eligible?tr`${task.assessment.successes} successful take(s) at the target BPM. Confirm to complete.`:
    tr('This is an unscored practice. Confirm the goal yourself to complete it.');
  $('manual-confirm').checked=false;$('manual-confirm-label').hidden=task.assessment.eligible;
  $('complete-error').hidden=true;$('complete-dialog').showModal();
  ui.completeSnapshot={task_id:task.id,expected_event_id:task.lifecycle_event_id};
}

$('complete-cancel').addEventListener('click',()=>$('complete-dialog').close());
$('complete-confirm').addEventListener('click',async()=>{
  const task=openedTask();if(!task||ui.busy)return;
  if(!task.assessment.eligible&&!$('manual-confirm').checked){$('complete-error').textContent=tr('Confirm that you achieved the practice goal.');$('complete-error').hidden=false;return;}
  ui.busy=true;$('complete-confirm').disabled=true;
  try {
    await api('/api/complete',{...ui.completeSnapshot,manual_confirmed:$('manual-confirm').checked});
    $('complete-dialog').close();stopRoomAudio();ui.openedTaskId=null;
    await refresh();switchView('list');clearFilters();renderHistory();
    showRecord(ui.data.history.find(t=>t.id===task.id));
  }catch(error){$('complete-error').textContent=tr(error.message||String(error));$('complete-error').hidden=false;}
  finally{ui.busy=false;$('complete-confirm').disabled=false;updateTransport();}
});
$('abort-attempt').addEventListener('click',()=>stopCapture().catch(fail));
$('manual-mode').addEventListener('change',()=>{ui.manualTouched=true;updateTransport();});
$('drum-toggle').addEventListener('change',event=>queuePlaybackSettings({drums_enabled:event.target.checked}));
$('drum-volume').addEventListener('input',event=>queuePlaybackSettings({drum_volume:Number(event.target.value)},150));
$('backing-feel').addEventListener('change',event=>queuePlaybackSettings({drum_feel:event.target.value}));
async function playWrittenScore() {
  if(ui.capture||!target()?.notation)return;
  const request=++ui.replayRequest,taskId=openedTask()?.id,bpm=transport.requestedBpm,source=target().notation;
  try{
    ui.roomAudioActive=true;await transport.unlock();
    if(request!==ui.replayRequest||taskId!==openedTask()?.id||ui.capture)return;
    ui.detailRequest++;ui.selectedAttempt=null;ui.selectedAttemptId=null;
    $('attempt-feedback').hidden=true;$('selected-play').hidden=true;renderAttempts(openedTask());
    ui.replayTrack={notes:expectedNotes(source).map(n=>({pitch:n.pitch,velocity:n.reference_velocity,
      at_ms:n.at*60000/bpm,key_end:(n.at+n.duration*(n.staccato?.45:1))*60000/bpm,
      sound_end:(n.at+n.duration*(n.staccato?.45:1))*60000/bpm})),
      bpm,beats:source.beats_per_bar||4,bars:source.bars.length,duration:source.bars.length*(source.beats_per_bar||4)*60000/bpm,
      kind:'score'};
    renderBarResults([]);
    startReplay(0);
  }catch(error){fail(error);}
}
$('reference-play').addEventListener('click',playWrittenScore);
$('replay-pause').addEventListener('click',()=>{
  if(!transport.replay)return;
  if(transport.replay.paused)startReplay(transport.replay.from);else transport.pauseReplay();
  updateTransport();
});
$('replay-stop').addEventListener('click',()=>transport.stopReplay());
$('replay-rate').addEventListener('change',()=>{if(transport.replay)startReplay(transport.replayPosition(),{paused:transport.replay.paused});});
$('replay-bar').addEventListener('change',()=>{
  if(ui.replayTrack)startReplay(Number($('replay-bar').value)*ui.replayTrack.beats*60000/ui.replayTrack.bpm,{paused:Boolean(transport.replay?.paused)});
});
async function reopenPractice(task) {
  if(ui.busy||ui.capture||!task?.completed)return;
  ui.busy=true;
  try{await api('/api/reopen',{task_id:task.id,expected_event_id:task.lifecycle_event_id});$('history-dialog').close();await refresh(true);}
  catch(error){fail(error);}finally{ui.busy=false;updateTransport();renderChoices();}
}
$('reopen-btn').addEventListener('click',()=>reopenPractice(detailTask));
$('resume-practice').addEventListener('click',()=>reopenPractice(openedTask()));
$('view-score-btn').addEventListener('click',()=>{$('history-dialog').close();openPractice(detailTask);});
$('latency-ms').addEventListener('change',()=>{try{localStorage.setItem('jazz-midi-latency-ms',$('latency-ms').value);}catch{}});
try{$('latency-ms').value=localStorage.getItem('jazz-midi-latency-ms')||'0';}catch{}

function stopRoomAudio() {
  ui.midiControls?.cancel();if($('midi-learn-dialog').open)$('midi-learn-dialog').close();
  ui.roomAudioActive=false;transport.pause();
}
async function goToList() {
  if (ui.busy) return;
  ui.detailRequest++;ui.replayRequest++;
  clearError(); ui.busy = true; updateTransport();
  try {
    await stopCapture();
    stopRoomAudio();
    ui.openedTaskId = null;
    await refresh(true); switchView('list');window.scrollTo({top:ui.listScrollY||0,behavior:'instant'});
  } catch (error) { fail(error); }
  finally { ui.busy = false; updateTransport(); renderChoices(); }
}
function openPractice(task) {
  if (!task || ui.busy || ui.capture) return;
  ui.midiControls?.cancel();
  if(ui.view==='list')ui.listScrollY=window.scrollY;
  transport.stopReplay();
  ui.detailRequest++;ui.replayRequest++;analysisSerial++;
  Object.assign(ui,{replayTrack:null,selectedAttemptId:null,selectedAttempt:null,latestAttempt:null,
    openedTaskId:task.id,scoreContext:task.id+':'+(++ui.visit),manualTouched:false,showAllAttempts:false,
    phase:'idle',midiFrames:[],attemptContract:null,plannedStart:null,initialMidi:{},saveStatus:null,countInBeat:null,nextAttemptId:null});
  $('elapsed').textContent='00:00';$('score-position').textContent='';$('bar-results').replaceChildren();
  $('attempt-feedback').hidden=true;$('attempt-feedback').replaceChildren();
  $('selected-play').hidden=true;$('replay-title').textContent=tr('Choose a recording below to hear your performance.');
  $('playback-settings').open=false;$('attempt-history').open=true;
  renderLesson(true);switchView('practice');updateTransport();
  activateRoomAudio();
  window.scrollTo({top:0,behavior:'instant'});
  const recent=[...(task.attempts||[])].reverse().find(a=>a.cycle_id===task.assessment.cycle_id&&a.state!=='recording');
  if(recent)loadAttempt(recent.id).catch(fail);
}

async function recover() {
  clearError(); ui.busy = true; updateTransport(); $('recover-btn').disabled = true;
  try {
    const drafts = await outbox.drafts();
    for (const session of openSessions()) {
      await uploadPending(outbox, session.id, api);
      const fresh = await api('/api/state');
      const remote = fresh.sessions.find(s => s.id === session.id);
      const draft = drafts.find(d => d.id === session.id);
      await api('/api/sessions/finish', {session_id: session.id, expected_chunks: draft?.finished ? draft.expected_chunks : remote.next_sequence, interrupted: !draft?.finished});
      await outbox.removeDraft(session.id);
    }
    await refresh(true);
    switchView('list');
  } catch (error) { fail(error); }
  finally { ui.busy = false; $('recover-btn').disabled = false; updateTransport(); renderChoices(); }
}

function renderRecordText() {
  if (!ui.recordTask) return;
  const task = ui.data.history.find(t => t.id === ui.recordTask.id);
  if(!task||!task.completed){$('record-panel').hidden=true;if(!task)ui.recordTask=null;return;}
  ui.recordTask = task;
  const rating = task.report?.difficulty;
  $('record-title').textContent = tr('How did your practice go?');
  document.querySelectorAll('[data-rating]').forEach(button => {
    button.setAttribute('aria-pressed', String(button.dataset.rating === rating));
    button.disabled = Boolean(ui.reflectionSaving);
  });
  $('reflection-status').textContent = tr(ui.reflectionSaving ? 'Saving…' : ratings[rating] ? 'Practice saved' : '');
  $('save-note').disabled = Boolean(ui.reflectionSaving) || !ratings[rating];
  $('raw-note').disabled = Boolean(ui.reflectionSaving);
  $('close-record').disabled = Boolean(ui.reflectionSaving);
  $('measurements').replaceChildren();
  const measured = task.observations;
  if (measured) {
    $('measurements').append(el('span', measured.date_source === 'session' ? measured.practice_date : tr`Recorded ${measured.practice_date}`));
    if (measured.minutes !== null) $('measurements').append(el('span', tr`Practice time ${clock(measured.minutes * 60000)}`));
    else $('measurements').append(el('span', tr('Practice time unknown')));
    if (measured.metronome_bpm !== null) $('measurements').append(el('span', tr`Metronome ${measured.metronome_bpm} BPM`));
  }
}

function showRecord(task) {
  if (!task?.completed || ui.capture || openSessions().length) return;
  if (ui.recordTask?.id !== task.id) {
    $('record-form').reset();
    $('raw-note').value = task.report?.raw_note || '';
    $('memo-details').open = Boolean(task.report?.raw_note);
    ui.reflectionEventId = task.report?.event_id || null;
  }
  ui.recordTask = task;
  $('record-panel').hidden = false;
  renderHistory(); renderRecordText();
  $('record-panel').scrollIntoView({behavior: 'smooth', block: 'start'});
}
async function saveReflection(rating) {
  if (ui.reflectionSaving || !ui.recordTask || !ratings[rating]) return false;
  clearError(); ui.reflectionSaving = true; renderRecordText();
  try {
    const saved = await api('/api/reflection', {task_id: ui.recordTask.id, rating,
      note: $('raw-note').value, expected_event_id: ui.reflectionEventId});
    // Keep the revision token even if the subsequent refresh loses its response.
    ui.reflectionEventId = saved.event_id;
    ui.recordTask.report = {...ui.recordTask.report, event_id: saved.event_id, difficulty: rating, raw_note: $('raw-note').value};
    await refresh(true);
    return true;
  } catch (error) { fail(error); return false; }
  finally { ui.reflectionSaving = false; renderRecordText(); }
}

function switchView(name) {
  ui.view = name;document.body.dataset.view=name;
  document.querySelectorAll('.view').forEach(view => view.hidden = view.id !== `view-${name}`);
  const section = name === 'practice' ? 'list' : name;
  document.querySelectorAll('[data-view]').forEach(button => { button.classList.toggle('active', button.dataset.view === section); button.setAttribute('aria-current', button.dataset.view === section ? 'page' : 'false'); });
}
function clearFilters() {
  for (const id of ['filter-exercise', 'filter-key', 'filter-status', 'filter-from', 'filter-to']) $(id).value = '';
}
function renderHistory() {
  const exercise=$('filter-exercise').value,key=$('filter-key').value,from=$('filter-from').value,to=$('filter-to').value,status=$('filter-status').value;
  const dayOf=task=>(task.report||task.completion)?task.observations?.practice_date||task.report?.practice_date||task.completion.practice_date:task.assigned_at.slice(0,10);
  const expanded=new Map([...$('history-list').querySelectorAll('.practice-card-details')].map(d=>[d.closest('.practice-item').dataset.taskId,{open:d.open,context:d.querySelector('.task-context-detail')?.open}]));
  const tasks=ui.data.history.filter(task=>{
    const actualKey=task.report?JSON.parse(task.report.actual_json).key||task.target.key:task.target.key,day=dayOf(task);
    return (!status||status==='active'&&task.pending||status==='completed'&&task.completed||status==='closed'&&task.cancelled)&&
      (!exercise||task.exercise_id===exercise)&&(!key||actualKey===key)&&(!from||day>=from)&&(!to||day<=to);
  }).sort((a,b)=>dayOf(b).localeCompare(dayOf(a))||b.assigned_at.localeCompare(a.assigned_at));
  for(const button of document.querySelectorAll('[data-status-filter]')){
    const value=button.dataset.statusFilter,count=ui.data.history.filter(t=>!value||value==='active'&&t.pending||value==='completed'&&t.completed||value==='closed'&&t.cancelled).length;
    const text={'':'All practices',active:'Active practices',completed:'Completed practices',closed:'Skipped or retired'}[value];
    button.replaceChildren(document.createTextNode(tr(text)),el('span',String(count),'filter-count'));
    button.setAttribute('aria-pressed',String(value===status));
  }
  $('view-list').append($('record-panel'));$('history-list').replaceChildren();
  if(!tasks.length){const empty=el('div',undefined,'empty-state');empty.append(el('h3',tr('No practices match this filter.')),el('p',tr('Add an exercise to begin. Completed and skipped practices will stay in this list.')));$('history-list').append(empty);}
  let day;
  for(const task of tasks){
    if(dayOf(task)!==day){day=dayOf(task);$('history-list').append(el('h2',day,'practice-day'));}
    const card=el('article',undefined,'practice-item');card.dataset.taskId=task.id;
    const button=el('button',undefined,'history-item'),left=el('div');
    const record=task.completion&&(!task.report||task.completion.recorded_at>task.report.recorded_at)?task.completion:task.report;
    const minutes=record?.actual_minutes!==''&&record?.actual_minutes!=null?tr` · ${Number(Number(record.actual_minutes).toFixed(2))} min`:'';
    left.append(el('h3',task.target.title),el('p',tr`${task.target.key} · Target ${task.target.bpm} BPM${minutes}`));
    const state=task.retired?tr('Retired on update'):task.discarded?tr('Discarded'):task.cancelled?tr('Skipped'):task.completed?tr('Completed'):task.started||ui.capture?.session.task_id===task.id?tr('In progress'):tr('Ready to practice');
    button.append(left,el('span',state,`tag ${task.completed?'success':'unknown'}`));
    button.addEventListener('click',()=>task.pending?openPractice(task):showDetail(task));card.append(button);
    card.append(el('p',task.target.exercise?.objective||task.target.instructions,'practice-content'));
    const summary=el('div',undefined,'practice-summary'),count=task.attempts?.length||0;
    const counted=count?tr`Recorded attempts: ${count}`:tr(task.recording_coverage?.mode==='legacy'?'Legacy practice record':'No recorded attempts yet');
    summary.append(el('p',counted+(task.recording_coverage?.mode==='mixed'?tr(' · earlier record format also present'):'')+(task.assessment?.successes?tr` · ${task.assessment.successes} successful this round`:''),'attempt-count'));
    const result=ratings[task.report?.difficulty]?ratingText(task.report.difficulty):task.report?tr(labels[task.outcome]):task.completed?tr('Feedback not added yet'):'';
    if(result)summary.append(el('p',result,'practice-result'));
    if(task.discard_choice)summary.append(el('p',tr(discardChoices[task.discard_choice]),'practice-result'));
    card.append(summary);
    const note=task.report?.raw_note||(task.cancelled?task.reason:'');if(note)card.append(el('p',note,'practice-note'));
    card.append(translationNotice(task));
    const footer=el('div',undefined,'practice-card-footer'),actions=el('div',undefined,'row-actions');
    footer.append(taskIdentity(task.id));
    if(task.completed){const edit=el('button',tr(task.report?'Edit feedback':'Add feedback'),'text-button');edit.disabled=Boolean(ui.capture)||openSessions().length>0;edit.addEventListener('click',()=>showRecord(task));actions.append(edit);}
    footer.append(actions);card.append(footer);
    const details=el('details',undefined,'practice-card-details');details.open=Boolean(expanded.get(task.id)?.open);
    details.append(el('summary',tr('Task details')));appendTaskOverview(details,task.target,false,Boolean(expanded.get(task.id)?.context));
    details.append(el('p',task.target.instructions,'practice-content'));
    const recordDetails=el('button',tr('Practice record details'),'text-button');recordDetails.addEventListener('click',()=>showDetail(task));details.append(recordDetails);card.append(details);
    if(ui.recordTask?.id===task.id)card.append($('record-panel'));
    $('history-list').append(card);
  }
}
function showDetail(task) {
  const analysisOpen = detailTask?.id === task.id && $('history-detail').querySelector('.recommendation-analysis')?.open;
  const contextOpen = detailTask?.id === task.id && $('history-detail').querySelector('.task-context-detail')?.open;
  const overviewOpen = detailTask?.id === task.id && $('history-detail').querySelector('.detail-context')?.open;
  detailTask = task;
  const box = $('history-detail');const detailScroll=box.scrollTop;box.replaceChildren(el('h2', task.target.title), taskIdentity(task.id),
    el('p', (task.report || task.completion)?.practice_date || task.assigned_at.slice(0, 10), 'subtle'));
  box.append(translationNotice(task));
  if(['legacy','mixed'].includes(task.recording_coverage?.mode))box.append(el('p',tr('Individual attempts were not tracked by the previous recording system. Missing attempts do not mean no practice.'),'field-note'));
  const context=el('details',undefined,'task-context detail-context');context.open=Boolean(overviewOpen);context.append(el('summary',tr('Task characteristics and personal burden')));appendTaskOverview(context,task.target,false,contextOpen);box.append(context);
  const grid = el('div', undefined, 'detail-grid');
  const intended = el('div'); intended.append(el('h3', tr('Assigned conditions')), el('div', tr`${task.target.key} · ${task.target.bpm} BPM · ${task.target.bars} bars`), el('div', ui.data.arrangements[task.target.arrangement] || task.target.arrangement));
  const actualBox = el('div'); actualBox.append(el('h3', tr('Reported performance')));
  if (task.report && ratings[task.report.difficulty]) {
    actualBox.append(el('div', ratingText(task.report.difficulty)));
    const observed = task.observations;
    if (observed?.metronome_bpm) actualBox.append(el('div', tr`Metronome ${observed.metronome_bpm} BPM`));
    if (task.report.actual_minutes) actualBox.append(el('div', tr`Practice time ${clock(Number(task.report.actual_minutes) * 60000)}`));
  } else if (task.report) {
    const a = JSON.parse(task.report.actual_json);
    actualBox.append(el('div', tr`${a.key || tr('Key unknown')} · ${a.bpm ?? tr('Unknown')} BPM · ${a.bars ?? tr('Unknown')} bars`), el('div', ui.data.arrangements[a.arrangement] || tr('Hand arrangement unknown')), el('div', tr`${tr(labels[task.outcome])} · Consecutive successful runs: ${task.report.clean_runs || tr('Unknown')}`));
  } else if (task.completed) actualBox.append(el('div', tr('Completed')), el('div', tr('Feedback not added yet')));
  else actualBox.append(el('div', task.retired ? tr('Closed by an update. No practice result was inferred.') : task.discarded ? tr('Task closed. Saved recordings are kept below.') : task.cancelled ? tr('Cancelled before practice') : tr('No result reported yet')));
  grid.append(intended, actualBox); box.append(grid);
  box.append(el('p', task.target.instructions));
  if (task.target.exercise) {
    const e = task.target.exercise;
    box.append(el('p', e.section), el('p', e.notes), el('p', e.rhythm));
    const steps = el('ol'); steps.append(...e.steps.map(step => el('li', step))); box.append(steps);
    appendDevelopment(box, task.target);
  }
  appendReferences(box, task.target);
  appendAnalysis(box, task.target, analysisOpen);
  if (task.discard_choice) box.append(el('p', tr(discardChoices[task.discard_choice]), 'discard-choice'));
  const note = task.report ? task.report.raw_note : task.reason;
  if (note) box.append(el('p', note, 'raw-note'));
  if(task.completions?.length){
    const timeline=el('details',undefined,'revision');timeline.append(el('summary',tr`Completion history: ${task.completions.length}`));
    for(const event of task.completions){
      const basis=JSON.parse(event.reason).attempt_completion?.basis;
      timeline.append(el('p',`${event.recorded_at.slice(0,16).replace('T',' ')} · ${tr(basis==='midi-analysis'?'Successful take':basis==='user-confirmation'?'User-confirmed goal':'Completed')}`));
    }
    box.append(timeline);
  }
  for (const session of taskSessions(task.id)) {
    const row = el('div', undefined, 'session-row');
    row.append(el('div', tr`Practice ${session.created_at.slice(0, 16).replace('T', ' ')} · ${session.status === 'recording' ? tr('Saving') : session.status === 'interrupted' ? tr('Interrupted') : tr('Saved')}`));
    if (session.summary) {
      const s = session.summary;
      row.append(el('div', tr`Session ${clock(s.elapsed_ms)} · MIDI span ${s.input_span_ms === null ? tr('Unknown') : clock(s.input_span_ms)} · Last setting ${s.last_note_bpm ?? s.last_setting_bpm ?? tr('Unknown')} BPM`));
    }
    for (const [suffix, text] of [['midi', tr('Download raw MIDI (.jpm)')], ['metadata', tr('Download session info (.json)')]]) { const a = el('a', text); a.href = `/api/recordings/${session.id}/${suffix}`; a.download = ''; row.append(a); }
    const play=el('button',tr('Play this recording'),'text-button');play.type='button';
    play.addEventListener('click',()=>{ $('history-dialog').close();openPractice(task);playSession(session.id,task).catch(fail); });row.append(play);
    box.append(row);
  }
  if (task.revisions.length > 1) {
    const details = el('details', undefined, 'revision'); details.append(el('summary', tr`Original and corrections: ${task.revisions.length} reports`));
    for (const revision of task.revisions) { details.append(el('small', `${revision.recorded_at.slice(0, 16).replace('T', ' ')} · ${revision.event_type === 'reported' ? tr('Original report') : tr('Correction')}`), el('p', [ratings[revision.difficulty] ? ratingText(revision.difficulty) : '', revision.raw_note].filter(Boolean).join('\n'))); }
    box.append(details);
  }
  $('correct-btn').hidden = !task.completed;
  $('reopen-btn').hidden=!task.completed;
  $('reopen-btn').disabled=Boolean(ui.capture);
  $('repeat-btn').hidden = task.pending;
  $('repeat-btn').disabled = Boolean(ui.capture) || openSessions().length > 0 || ui.data.recommendation?.state === 'running';
  $('correct-btn').disabled = Boolean(ui.capture) || openSessions().length > 0;
  $('delete-practice').disabled=ui.busy||Boolean(ui.capture)||openSessions().length>0;
  if (!$('history-dialog').open){$('history-dialog').showModal();box.scrollTop=0;}else box.scrollTop=detailScroll;
}

$('delete-practice').append(icon('trash'));
$('delete-practice').addEventListener('click',()=>{
  if(!detailTask||ui.busy||ui.capture||openSessions().length)return;
  ui.deleteTarget={id:detailTask.id,title:detailTask.target.title,revision:detailTask.revision_event_id};
  $('delete-task-title').textContent=ui.deleteTarget.title;$('delete-error').hidden=true;$('delete-dialog').showModal();
});
$('delete-cancel').addEventListener('click',()=>$('delete-dialog').close());
$('delete-form').addEventListener('submit',async event=>{
  event.preventDefault();if(ui.busy||!ui.deleteTarget||ui.capture)return;
  ui.busy=true;$('delete-confirm').disabled=true;$('delete-cancel').disabled=true;
  try {
    await api('/api/delete',{task_id:ui.deleteTarget.id,expected_event_id:ui.deleteTarget.revision});
    if(ui.openedTaskId===ui.deleteTarget.id){stopRoomAudio();ui.openedTaskId=null;ui.detailRequest++;ui.replayRequest++;}
    if(ui.recordTask?.id===ui.deleteTarget.id){ui.recordTask=null;$('record-panel').hidden=true;}
    await refresh(true);$('delete-dialog').close();$('history-dialog').close();detailTask=null;ui.deleteTarget=null;
    switchView('list');
  } catch(error){$('delete-error').textContent=tr(error.message);$('delete-error').hidden=false;}
  finally{ui.busy=false;$('delete-confirm').disabled=false;$('delete-cancel').disabled=false;updateTransport();renderChoices();}
});
$('delete-dialog').addEventListener('cancel',event=>{if(ui.busy)event.preventDefault();});

$('practice-btn').addEventListener('click', startOrPause);
$('go-score').addEventListener('click',event=>{event.preventDefault();focusPanel($('score-viewport'));});
$('all-attempts').addEventListener('click',()=>{ui.showAllAttempts=!ui.showAllAttempts;renderAttempts(openedTask());});
$('selected-play').addEventListener('click',()=>{
  const attempt=ui.selectedAttempt;if(attempt)playSession(attempt.session_id,openedTask(),attempt.id).catch(fail);
});
document.querySelectorAll('[data-status-filter]').forEach(button=>button.addEventListener('click',()=>{
  $('filter-status').value=button.dataset.statusFilter;renderHistory();
}));
document.addEventListener('click',event=>{
  if($('playback-settings').open&&!$('playback-settings').contains(event.target))$('playback-settings').open=false;
  if($('midi-options').open&&!$('midi-options').contains(event.target))$('midi-options').open=false;
});
document.addEventListener('keydown',event=>{if(event.key==='Escape'){$('playback-settings').open=false;$('midi-options').open=false;}});
document.addEventListener('keydown',event=>{
  if(!ui.midiPrefs?.keyboard||ui.view!=='practice'||document.querySelector('dialog[open]'))return;
  const action=keyboardAction(event);if(!action)return;
  event.preventDefault();runTransportControl(action).catch(fail);
});
$('keyboard-shortcuts').addEventListener('change',event=>{ui.midiPrefs.keyboard=event.target.checked;saveMidiPreferences();renderControllerBindings();});
$('midi-reconnect').addEventListener('change',event=>{ui.midiPrefs.remember=event.target.checked;saveMidiPreferences();});
document.querySelectorAll('[data-learn-action]').forEach(button=>button.addEventListener('click',()=>{
  if(!ui.midiControls||ui.capture||ui.busy||transport.replay)return;
  const action=button.dataset.learnAction;ui.midiControls.learn(action);
  $('midi-learn-action').textContent=controlActionLabel(action);$('midi-learn-status').textContent='';$('midi-learn-dialog').showModal();
}));
document.querySelectorAll('[data-clear-action]').forEach(button=>button.addEventListener('click',()=>{
  if(ui.capture||ui.busy||transport.replay)return;
  ui.midiControls.clear(button.dataset.clearAction);ui.midiPrefs.bindings=structuredClone(ui.midiControls.bindings);saveMidiPreferences();renderControllerBindings();
}));
$('midi-learn-cancel').addEventListener('click',()=>$('midi-learn-dialog').close());
$('midi-learn-dialog').addEventListener('close',()=>ui.midiControls?.cancel());
$('finish-btn').addEventListener('click', () => finish());
$('recover-btn').addEventListener('click', recover);
document.querySelectorAll('[data-rating]').forEach(button => button.addEventListener('click', () => saveReflection(button.dataset.rating)));
$('record-form').addEventListener('submit', event => { event.preventDefault(); saveReflection(ui.recordTask?.report?.difficulty); });
$('close-record').addEventListener('click', () => { $('record-panel').hidden = true; ui.recordTask = null; });
$('tempo').addEventListener('change', event => setTempo(event.target.value));
$('tempo-range').addEventListener('input', event => setTempo(event.target.value));
$('tempo-down').addEventListener('click', () => setTempo(Number($('tempo').value) - 5));
$('tempo-up').addEventListener('click', () => setTempo(Number($('tempo').value) + 5));
$('click-toggle').addEventListener('change',async event=>{queuePlaybackSettings({metronome_enabled:event.target.checked});if(event.target.checked)await activateRoomAudio();});
$('pad-toggle').addEventListener('change',event=>queuePlaybackSettings({pad_enabled:event.target.checked}));
for(const [id,key] of [['click-volume','click_volume'],['pad-volume','pad_volume']])$(id).addEventListener('input',event=>queuePlaybackSettings({[key]:Number(event.target.value)},150));
async function newPractice() {
  if (ui.busy || ui.capture || openSessions().length || ui.data.recommendation?.state === 'running') return;
  clearError(); ui.busy = true; ui.creating = true;
  ui.newRequestId ||= 'R-' + randomHex();
  ui.submittedRequestId = ui.newRequestId;
  ui.submittedFocus = $('recommendation-request').value;
  renderChoices(); renderGeneration();
  try {
    await api('/api/recommend', {request_id: ui.newRequestId, request: ui.submittedFocus});
    clearFilters(); await refresh(true);
  } catch (error) {
    fail(error);
    // If only the response was lost, pick up the durable job instead of creating another.
    try { await refresh(true); } catch {}
  } finally { ui.busy = false; ui.creating = false; renderGeneration(); renderChoices(); }
}
$('new-practice').addEventListener('click', newPractice);
$('retry-recommendation').addEventListener('click', newPractice);
$('back-list').addEventListener('click', goToList);
$('repeat-btn').addEventListener('click', async () => {
  if (ui.busy || ui.capture || ui.data.recommendation?.state === 'running') return;
  ui.busy = true; $('repeat-btn').disabled = true;
  ui.repeatTaskId ||= 'T-' + randomHex(5);
  try {
    await api('/api/repeat', {source_task_id: detailTask.id, task_id: ui.repeatTaskId});
    ui.repeatTaskId = null; $('history-dialog').close(); clearFilters();
    await refresh(true); switchView('list');
  } catch (error) { fail(error); }
  finally { ui.busy = false; renderChoices(); $('repeat-btn').disabled = Boolean(ui.capture); }
});
$('midi-connect').addEventListener('click',()=>connectMidi(false));
$('midi-input').addEventListener('change', event => {
  heldKeys.clear();heldPedals.clear();
  if (midiSelection !== event.target.value) score.disconnect(undefined, transport.position());
  if (ui.capture && midiSelection !== event.target.value) ui.capture.event('disconnect', {reason: 'Recording input changed'});
  midiSelection=event.target.value;
  const port=midiAccess?.inputs.get(midiSelection);
  if(port)ui.midiPrefs.selection={mode:'device',...portReference(port)};
  else if(['all','none'].includes(midiSelection))ui.midiPrefs.selection={mode:midiSelection};
  saveMidiPreferences();midiBindings();
});
$('discard-btn').addEventListener('click', () => {
  ui.discardTaskId = openedTask()?.id || null;
  ui.discardChoice = '';
  $('discard-reason').value = ui.recordTask?.id === ui.discardTaskId ? $('raw-note').value : '';
  $('discard-error').hidden = true;
  document.querySelectorAll('[data-discard-choice]').forEach(button => button.setAttribute('aria-pressed', 'false'));
  $('discard-dialog').showModal();
});
document.querySelectorAll('[data-discard-choice]').forEach(button => button.addEventListener('click', () => {
  ui.discardChoice = ui.discardChoice === button.dataset.discardChoice ? '' : button.dataset.discardChoice;
  document.querySelectorAll('[data-discard-choice]').forEach(choice => choice.setAttribute('aria-pressed', String(choice.dataset.discardChoice === ui.discardChoice)));
}));
$('discard-close').addEventListener('click', () => $('discard-dialog').close());
$('discard-dialog').addEventListener('cancel', event => { if (ui.discarding) event.preventDefault(); });
$('discard-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (ui.discarding) return;
  if(!$('discard-reason').value.trim()){$('discard-error').textContent=tr('Enter a reason before moving on from this task.');$('discard-error').hidden=false;return;}
  clearError(); $('discard-error').hidden = true;
  ui.discarding = true; ui.busy = true; updateTransport();
  const reason = $('discard-reason').value, choice = ui.discardChoice;
  $('discard-form').querySelectorAll('button, textarea').forEach(control => control.disabled = true);
  try {
    // Finish the local capture before closing the task; failed uploads remain retryable.
    await stopCapture();
    ui.busy = true; updateTransport();
    await api('/api/discard', {task_id: ui.discardTaskId, reason, choice});
    stopRoomAudio();
    $('discard-dialog').close(); $('record-panel').hidden = true; ui.recordTask = null; ui.openedTaskId = null;
    await refresh(); switchView('list');
  } catch (error) {
    fail(error);
    $('discard-error').textContent = tr(error.message || String(error));
    $('discard-error').hidden = false;
  } finally {
    ui.discarding = false; ui.busy = false;
    $('discard-form').querySelectorAll('button, textarea').forEach(control => control.disabled = false);
    updateTransport(); renderChoices();
  }
});
$('dialog-close').addEventListener('click', () => $('history-dialog').close());
$('correct-btn').addEventListener('click', () => { $('history-dialog').close(); switchView('list'); clearFilters(); showRecord(detailTask); });
for (const id of ['filter-exercise', 'filter-key', 'filter-status', 'filter-from', 'filter-to']) $(id).addEventListener('change', renderHistory);
document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', async () => {
  if (button.dataset.view === 'list') return goToList();
  switchView(button.dataset.view);
  if (!ui.capture) { try { await refresh(true); } catch (error) { fail(error); } }
}));
document.querySelector('.brand').addEventListener('click', event => { event.preventDefault(); goToList(); });
document.addEventListener('visibilitychange', () => {
  if(document.hidden&&$('midi-learn-dialog').open){ui.midiControls?.cancel();$('midi-learn-dialog').close();}
  ui.capture?.event('visibility', {hidden: document.hidden});
  if(document.hidden&&transport.playing){stopRoomAudio();if(ui.capture)stopCapture().catch(fail);updateTransport();}
  if (document.hidden && ui.capture && !ui.capture.ended) ui.capture.checkpoint().then(() => ui.capture.upload()).catch(() => {});
});
window.addEventListener('beforeunload', event => { if (ui.capture) { event.preventDefault(); event.returnValue = ''; } });
window.addEventListener('pagehide', () => { if (ui.capture && !ui.capture.ended) ui.capture.checkpoint().catch(() => {}); transport.pause(); });
async function changeLanguage() {
  const saved = setLocale($('language-select').value);
  translatePage();
  // Static journal/attempt labels do not need a translated task response.
  // Keep them in the selected language even when navigation precedes that GET.
  if(ui.data){renderHistory();renderRecordText();if(openedTask())renderAttempts(openedTask());}
  $('language-note').textContent = tr(saved ? 'Saved in this browser. Your notes stay in their original language.' : 'This tab only: browser storage is unavailable.');
  updateTransport();
  if (ui.error) fail(ui.error);
  if (ui.saveStatus) $('save-status').textContent = tr(ui.saveStatus);
  if (midiAccess) midiBindings();
  else if (ui.midiNotice) $('midi-status').textContent = tr(ui.midiNotice);
  try {
    await refresh(true);
    if ($('history-dialog').open && detailTask) showDetail(ui.data.history.find(t => t.id === detailTask.id));
  } catch (error) { fail(error); }
}
$('language-select').value = locale();
$('settings-back').addEventListener('click', () => switchView(openedTask() ? 'practice' : 'list'));
$('language-select').addEventListener('change', changeLanguage);
loadTranslations().then(() => { translatePage(); return refresh(); }).catch(error => {
  $('connection').textContent = tr('Check connection'); fail(error);
});
