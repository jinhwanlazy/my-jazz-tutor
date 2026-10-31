import {tr, locale, setLocale, loadTranslations, translatePage} from './i18n.mjs';
import {Transport} from './audio.mjs';
import {Capture, Outbox, uploadPending, randomHex} from './capture.mjs';
import {ScoreView} from './score.mjs';

const $ = id => document.getElementById(id);
// Keep in-page navigation clear of the mobile header, including connected MIDI controls.
const sidebar = document.querySelector('.sidebar');
new ResizeObserver(() => {
  const height = getComputedStyle(sidebar).position === 'sticky' ? sidebar.getBoundingClientRect().height : 0;
  document.documentElement.style.setProperty('--app-header-height', `${height}px`);
}).observe(sidebar);
const ui = {data: null, capture: null, busy: false, selected: null, recordTask: null, openedTaskId: null, view: 'list', reflectionSaving: false, ports: new Map()};
let outbox, midiAccess, midiSelection = 'all', timer, detailTask;
const labels = {success: 'Criteria met', unmet: 'Target not met', unknown: 'Assessment pending'};
const ratings = {impossible: 'Impossible', challenging: 'Challenging', good: 'Good practice', too_easy: 'Too easy to be useful'};
const discardChoices = {already_practiced: 'Already familiar', too_easy: 'Too easy'};
const ratingEmoji = {impossible: '😈', challenging: '💪', good: '🙂', too_easy: '🙄'};
const ratingText = rating => `${ratingEmoji[rating]} ${tr(ratings[rating])}`;
function el(tag, text, className) { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node; }
function option(value, text, disabled = false) { const node = el('option', text); node.value = value; node.disabled = disabled; return node; }
function clock(ms) { const s = Math.max(0, Math.floor((ms || 0) / 1000)); return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`; }
function fail(error) { ui.error = error; $('error').textContent = tr(error.message || String(error)); $('error').hidden = false; }
function clearError() { ui.error = null; $('error').hidden = true; }
function pending() { return ui.data?.history.find(t => t.pending); }
function openedTask() { return ui.data?.history.find(t => t.id === ui.openedTaskId && t.pending); }
function openSessions() { return ui.data?.sessions.filter(s => s.status === 'recording' && s.id !== ui.capture?.session.id) || []; }
function taskSessions(id) { return ui.data.sessions.filter(s => s.task_id === id); }

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

const score = new ScoreView({root: $('score-viewport'), status: $('score-position'),
  follow: $('score-follow'), help: $('score-material-help')});
const transport = new Transport({
  onStart: () => score.begin(),
  onPause: position => score.pause(position),
  onFrame: position => score.frame(position),
  onBeat: ({bar, beat}) => {
    ui.beat = {bar, beat};
    [...$('beats').children].forEach((node, i) => node.classList.toggle('active', i === beat));
    [...$('chords').children].forEach((node, i) => node.classList.toggle('current', i === bar));
    $('bar-position').textContent = tr`Bar ${bar + 1} · beat ${beat + 1}`;
  },
  onEvent: (type, values, at) => ui.capture?.event(type, values, at),
  onInterrupt: message => {
    ui.capture?.event('audio_interrupted', {message});
    ui.capture?.event('pause');
    fail(new Error(message));
    updateTransport();
  }
});

async function refresh(keep = false, skipUnchanged = false) {
  const previous = openedTask()?.id;
  const data = await api('/api/state');
  if (data.language !== locale()) return; // A newer language selection superseded this response.
  if (skipUnchanged && JSON.stringify(data) === JSON.stringify(ui.data)) return;
  ui.data = data;
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
    if (task) showDetail(task);
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
  const lock = Boolean(pending()) || ui.busy || generating;
  for (const id of ['tempo', 'tempo-range']) { $(id).min = ui.data.minimum_bpm; $(id).max = ui.data.maximum_bpm; }
  $('new-practice').disabled = lock || Boolean(ui.capture) || openSessions().length > 0;
  $('retry-recommendation').disabled = $('new-practice').disabled;
  $('recommendation-request').disabled = generating || ui.busy;
  $('recommendation-focus').hidden = Boolean(generating);
  $('pending-hint').textContent = pending() ? tr('Open your unfinished practice below to continue or skip it.') : '';
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
  score.setScore(t.notation);
  if ($('view-practice').dataset.taskId !== current.id) {
    $('lesson-guide').open = false;
    $('lesson-material').open = !t.notation;
    $('view-practice').dataset.taskId = current.id;
  }
  $('lesson-kind').textContent = tr('Current task');
  $('lesson-title').textContent = t.title;
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
  $('discard-btn').hidden = false;
  $('pad-toggle').disabled = !t.playback;
  if (!t.playback) { $('pad-toggle').checked = false; transport.setPad(false); }
  if (resetTempo && !ui.capture) setTempo(t.bpm);
}
function setTempo(value) {
  if (ui.lockedBpm != null) {
    $('tempo').value = $('tempo-range').value = ui.lockedBpm;
    return;
  }
  const numeric = Math.min(ui.data.maximum_bpm, Math.max(ui.data.minimum_bpm, Math.round(Number(value) || ui.data.minimum_bpm)));
  $('tempo').value = $('tempo-range').value = numeric;
  transport.setTempo(numeric);
}
function updateTransport() {
  if (!ui.data) return;
  const recording = ui.capture, recovery = openSessions().length > 0;
  const eligible = Boolean(openedTask());
  const tempoLocked = Boolean(recording) || ui.busy || recovery;
  for (const id of ['tempo', 'tempo-range', 'tempo-down', 'tempo-up']) $(id).disabled = tempoLocked;
  if (ui.lockedBpm != null) $('tempo').value = $('tempo-range').value = ui.lockedBpm;
  $('tempo-hint').textContent = tr(recording ? 'BPM is fixed for this recording, including pauses.' : 'Choose BPM before starting. It stays fixed until this recording ends.');
  $('practice-btn').disabled = ui.busy || recovery || !eligible || Boolean(recording?.ended);
  $('practice-btn').textContent = recording ? transport.playing ? tr('Pause') : recording.ended ? tr('Waiting to save') : tr('Resume') : tr('Start practice');
  $('finish-btn').disabled = ui.busy || recovery || !eligible || (!recording && !openedTask()?.started);
  $('finish-btn').textContent = recording?.ended ? tr('Retry save') : tr('Complete practice');
  $('transport-state').textContent = recording ? transport.playing ? tr('Practicing') : recording.ended ? tr('Waiting to save') : tr('Paused') : tr('Ready');
  $('discard-btn').disabled = recovery || ui.busy || ui.reflectionSaving || !eligible;
  $('back-list').disabled = ui.busy;
}

function registerPort(port) {
  if (!ui.capture || ui.ports.has(port.id)) return;
  const index = ui.ports.size;
  ui.ports.set(port.id, index);
  ui.capture.event('device', {index, name: port.name || 'Unnamed input', manufacturer: port.manufacturer || '', id: port.id});
}
function selectedPorts() { return midiAccess ? [...midiAccess.inputs.values()].filter(p => p.state === 'connected' && (midiSelection === 'all' || midiSelection === p.id)) : []; }
function midiBindings() {
  if (!midiAccess) return;
  const available = [...midiAccess.inputs.values()].filter(p => p.state === 'connected');
  $('midi-input').hidden = false;
  $('midi-input').replaceChildren(option('all', tr('Record all connected inputs')), option('none', tr('Turn MIDI recording off')), ...available.map(p => option(p.id, p.name || tr('MIDI input'))));
  if (![...$('midi-input').options].some(o => o.value === midiSelection)) $('midi-input').append(option(midiSelection, tr('Selected device · disconnected')));
  $('midi-input').value = midiSelection;
  for (const port of midiAccess.inputs.values()) {
    if (selectedPorts().includes(port)) registerPort(port);
    port.onmidimessage = message => {
      if (midiSelection !== 'all' && midiSelection !== port.id) return;
      $('midi-light').classList.add('received');
      clearTimeout(port.indicatorTimer);
      port.indicatorTimer = setTimeout(() => $('midi-light').classList.remove('received'), 110);
      if (ui.capture && !ui.capture.ended) {
        registerPort(port);
        ui.capture.midi(message.data, ui.ports.get(port.id), message.timeStamp);
        score.midi(message.data, port.id, transport.position(message.timeStamp));
        $('midi-status').textContent = tr`Recording input · ${ui.capture.noteCount} note-ons`;
      }
    };
  }
  ui.midiNotice = null;
  $('midi-light').classList.toggle('connected', selectedPorts().length > 0);
  $('midi-status').textContent = midiSelection === 'none' ? tr('MIDI recording is off.') : selectedPorts().length ? tr`${selectedPorts().length} input(s) ready · raw input is recorded during practice.` : tr('No inputs connected. The metronome is still available.');
  $('midi-connect').textContent = tr('Refresh');
}

async function startOrPause() {
  if (!openedTask() || ui.busy) return;
  clearError();
  if (ui.capture && transport.playing) {
    transport.pause(); ui.capture.event('pause'); updateTransport(); return;
  }
  setTempo($('tempo').value);
  ui.lockedBpm ??= Number($('tempo').value);
  ui.busy = true; updateTransport();
  try {
    await transport.unlock(); // User gesture, before a network round trip.
    if (!ui.capture) {
      await outbox.database();
      const session = await api('/api/sessions/start', {task_id: openedTask().id, session_id: 'S-' + randomHex()});
      const capture = new Capture(session, outbox, api, (text, warning) => {
        ui.saveStatus = text; $('save-status').textContent = tr(text);
        $('save-status').classList.toggle('save-warning', warning);
      });
      ui.ports.clear();
      await capture.begin();
      ui.capture = capture;
      selectedPorts().forEach(registerPort);
      ui.capture.event('pad', {enabled: $('pad-toggle').checked});
      ui.capture.event('click', {enabled: $('click-toggle').checked});
      clearInterval(timer);
      timer = setInterval(() => { if (ui.capture) $('elapsed').textContent = clock((ui.capture.endAt || performance.now()) - ui.capture.origin); }, 250);
    }
    $('record-panel').hidden = true;
    transport.click = $('click-toggle').checked;
    transport.setPad($('pad-toggle').checked);
    ui.capture.event('play', {bpm: ui.lockedBpm});
    const t = target();
    const playback = t.playback || {beats_per_bar: t.notation?.beats_per_bar || 4,
      bars: Array.from({length: t.bars}, (_, i) => ({chord: t.notation?.bars[i]?.chord || '', notes: []}))};
    transport.start(playback, ui.lockedBpm);
    openedTask().started = true;
    ui.saveStatus = 'Recording · autosaving every 3 seconds';
    $('save-status').textContent = tr(ui.saveStatus);
  } catch (error) {
    fail(error);
    if (!ui.capture) { try { await refresh(true); } catch {} }
  }
  finally { if (!ui.capture) ui.lockedBpm = null; ui.busy = false; updateTransport(); }
}
async function stopCapture() {
  if (!ui.capture) return;
  if (transport.playing) { transport.pause(); ui.capture.event('pause'); }
  const saved = await ui.capture.stop();
  const index = ui.data.sessions.findIndex(session => session.id === saved.id);
  if (index < 0) ui.data.sessions.push(saved);
  else ui.data.sessions[index] = saved;
  ui.capture = null; ui.lockedBpm = null; clearInterval(timer);
  midiBindings();
  ui.saveStatus = 'Practice saved'; $('save-status').textContent = tr(ui.saveStatus);
}
async function finish() {
  const task = openedTask();
  if (!task || ui.busy) return;
  clearError(); ui.busy = true; updateTransport();
  try {
    await stopCapture();
    await api('/api/complete', {task_id: task.id});
    ui.openedTaskId = null;
    await refresh();
    switchView('list');
    clearFilters(); renderHistory();
    showRecord(ui.data.history.find(t => t.id === task.id));
  } catch (error) { fail(error); }
  finally { ui.busy = false; updateTransport(); renderChoices(); }
}
async function goToList() {
  if (ui.busy) return;
  clearError(); ui.busy = true; updateTransport();
  try {
    await stopCapture();
    ui.openedTaskId = null;
    await refresh(true); switchView('list');
  } catch (error) { fail(error); }
  finally { ui.busy = false; updateTransport(); renderChoices(); }
}
function openPractice(task) {
  if (!task?.pending || ui.busy || (ui.capture && ui.capture.session.task_id !== task.id)) return;
  ui.openedTaskId = task.id;
  renderLesson(true); switchView('practice'); updateTransport();
  window.scrollTo({top: 0, behavior: 'instant'});
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
  const task = ui.data.history.find(t => t.id === ui.recordTask.id) || ui.recordTask;
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
  ui.view = name;
  document.querySelectorAll('.view').forEach(view => view.hidden = view.id !== `view-${name}`);
  const section = name === 'practice' ? 'list' : name;
  document.querySelectorAll('[data-view]').forEach(button => { button.classList.toggle('active', button.dataset.view === section); button.setAttribute('aria-current', button.dataset.view === section ? 'page' : 'false'); });
}
function clearFilters() {
  for (const id of ['filter-exercise', 'filter-key', 'filter-from', 'filter-to']) $(id).value = '';
}
function renderHistory() {
  const exercise = $('filter-exercise').value, key = $('filter-key').value, from = $('filter-from').value, to = $('filter-to').value;
  const dayOf = task => (task.report || task.completion)?.practice_date || task.assigned_at.slice(0, 10);
  const tasks = ui.data.history.filter(task => {
    const day = dayOf(task);
    const actualKey = task.report ? JSON.parse(task.report.actual_json).key || task.target.key : task.target.key;
    return (!exercise || task.exercise_id === exercise) && (!key || actualKey === key) && (!from || day >= from) && (!to || day <= to);
  }).sort((a,b) => dayOf(b).localeCompare(dayOf(a)) || b.assigned_at.localeCompare(a.assigned_at));
  // Reuse the editor node so refresh and language changes keep unsaved text intact.
  $('view-list').append($('record-panel'));
  $('history-list').replaceChildren();
  if (!tasks.length) {
    const empty = el('div', undefined, 'empty-state');
    empty.append(el('h3', tr('Your practice starts here.')), el('p', tr('Add an exercise to begin. Completed and skipped practices will stay in this list.')));
    $('history-list').append(empty);
  }
  let day;
  for (const task of tasks) {
    if (dayOf(task) !== day) { day = dayOf(task); $('history-list').append(el('h2', day, 'practice-day')); }
    const card = el('article', undefined, 'practice-item'); card.dataset.taskId = task.id;
    const button = el('button', undefined, 'history-item'), left = el('div');
    const record = task.report || task.completion;
    const minutes = record?.actual_minutes !== '' && record?.actual_minutes != null ? tr` · ${Number(Number(record.actual_minutes).toFixed(2))} min` : '';
    left.append(el('small', task.assigned_at.slice(11,16)), el('h3', task.target.title), el('p', tr`${task.target.key} · Target ${task.target.bpm} BPM${minutes}`));
    const status = task.retired ? tr('Retired on update') : task.discarded ? tr('Discarded') : task.cancelled ? tr('Skipped') : task.completed ? tr('Completed') : task.started || ui.capture?.session.task_id === task.id ? tr('In progress') : tr('Ready to practice');
    button.append(left, el('span', status, `tag ${task.completed ? 'success' : 'unknown'}`));
    button.addEventListener('click', () => task.pending ? openPractice(task) : showDetail(task));
    card.append(button);
    appendTaskOverview(card, task.target, true);
    card.append(el('p', task.target.instructions, 'practice-content'), translationNotice(task));
    const result = ratings[task.report?.difficulty] ? ratingText(task.report.difficulty) : task.report ? tr(labels[task.outcome]) : task.completed ? tr('Feedback not added yet') : '';
    if (result) card.append(el('p', result, 'practice-result'));
    if (task.discard_choice) card.append(el('p', tr(discardChoices[task.discard_choice]), 'practice-result'));
    const note = task.report?.raw_note || (task.cancelled ? task.reason : '');
    if (note) card.append(el('p', note, 'practice-note'));
    const actions = el('div', undefined, 'row-actions');
    if (task.pending) {
      const open = el('button', tr(task.started ? 'Continue practice' : 'Open practice room'), 'text-button');
      open.disabled = ui.busy;
      open.addEventListener('click', () => openPractice(task)); actions.append(open);
    }
    if (task.completed) {
      const edit = el('button', tr(task.report ? 'Edit feedback' : 'Add feedback'), 'text-button');
      edit.disabled = Boolean(ui.capture) || openSessions().length > 0;
      edit.addEventListener('click', () => showRecord(task)); actions.append(edit);
    }
    card.append(actions);
    if (ui.recordTask?.id === task.id) card.append($('record-panel'));
    $('history-list').append(card);
  }
}
function showDetail(task) {
  const analysisOpen = detailTask?.id === task.id && $('history-detail').querySelector('.recommendation-analysis')?.open;
  const contextOpen = detailTask?.id === task.id && $('history-detail').querySelector('.task-context-detail')?.open;
  detailTask = task;
  const box = $('history-detail'); box.replaceChildren(el('h2', task.target.title), el('p', `${task.exercise_id} · ${(task.report || task.completion)?.practice_date || task.assigned_at.slice(0, 10)}`, 'subtle'));
  box.append(translationNotice(task));
  appendTaskOverview(box, task.target, false, contextOpen);
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
  for (const session of taskSessions(task.id)) {
    const row = el('div', undefined, 'session-row');
    row.append(el('div', tr`Practice ${session.created_at.slice(0, 16).replace('T', ' ')} · ${session.status === 'recording' ? tr('Saving') : session.status === 'interrupted' ? tr('Interrupted') : tr('Saved')}`));
    if (session.summary) {
      const s = session.summary;
      row.append(el('div', tr`Session ${clock(s.elapsed_ms)} · MIDI span ${s.input_span_ms === null ? tr('Unknown') : clock(s.input_span_ms)} · Last setting ${s.last_note_bpm ?? s.last_setting_bpm ?? tr('Unknown')} BPM`));
    }
    for (const [suffix, text] of [['midi', tr('Download raw MIDI (.jpm)')], ['metadata', tr('Download session info (.json)')]]) { const a = el('a', text); a.href = `/api/recordings/${session.id}/${suffix}`; a.download = ''; row.append(a); }
    box.append(row);
  }
  if (task.revisions.length > 1) {
    const details = el('details', undefined, 'revision'); details.append(el('summary', tr`Original and corrections: ${task.revisions.length} reports`));
    for (const revision of task.revisions) { details.append(el('small', `${revision.recorded_at.slice(0, 16).replace('T', ' ')} · ${revision.event_type === 'reported' ? tr('Original report') : tr('Correction')}`), el('p', [ratings[revision.difficulty] ? ratingText(revision.difficulty) : '', revision.raw_note].filter(Boolean).join('\n'))); }
    box.append(details);
  }
  $('correct-btn').hidden = !task.completed;
  $('repeat-btn').hidden = task.pending;
  $('repeat-btn').disabled = Boolean(pending()) || Boolean(ui.capture) || openSessions().length > 0 || ui.data.recommendation?.state === 'running';
  $('correct-btn').disabled = Boolean(ui.capture) || openSessions().length > 0;
  if (!$('history-dialog').open) $('history-dialog').showModal();
}

$('practice-btn').addEventListener('click', startOrPause);
$('finish-btn').addEventListener('click', () => finish());
$('recover-btn').addEventListener('click', recover);
document.querySelectorAll('[data-rating]').forEach(button => button.addEventListener('click', () => saveReflection(button.dataset.rating)));
$('record-form').addEventListener('submit', event => { event.preventDefault(); saveReflection(ui.recordTask?.report?.difficulty); });
$('close-record').addEventListener('click', () => { $('record-panel').hidden = true; ui.recordTask = null; });
$('tempo').addEventListener('change', event => setTempo(event.target.value));
$('tempo-range').addEventListener('input', event => setTempo(event.target.value));
$('tempo-down').addEventListener('click', () => setTempo(Number($('tempo').value) - 5));
$('tempo-up').addEventListener('click', () => setTempo(Number($('tempo').value) + 5));
$('click-toggle').addEventListener('change', event => { transport.click = event.target.checked; ui.capture?.event('click', {enabled: event.target.checked}); });
$('pad-toggle').addEventListener('change', event => { transport.setPad(event.target.checked); ui.capture?.event('pad', {enabled: event.target.checked}); });
for (const id of ['click-volume', 'pad-volume']) $(id).addEventListener('input', () => transport.setVolumes(Number($('click-volume').value), Number($('pad-volume').value)));
async function newPractice() {
  if (pending() || ui.busy || ui.capture || openSessions().length || ui.data.recommendation?.state === 'running') return;
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
  if (pending() || ui.busy || ui.capture || ui.data.recommendation?.state === 'running') return;
  ui.busy = true; $('repeat-btn').disabled = true;
  ui.repeatTaskId ||= 'T-' + randomHex(5);
  try {
    await api('/api/repeat', {source_task_id: detailTask.id, task_id: ui.repeatTaskId});
    ui.repeatTaskId = null; $('history-dialog').close(); clearFilters();
    await refresh(true); switchView('list');
  } catch (error) { fail(error); }
  finally { ui.busy = false; renderChoices(); $('repeat-btn').disabled = Boolean(pending()); }
});
$('midi-connect').addEventListener('click', async () => {
  clearError();
  if (window.isSecureContext === false) { ui.midiNotice = 'MIDI input requires HTTPS or localhost. You can still practice with the metronome.'; $('midi-status').textContent = tr(ui.midiNotice); return; }
  if (!navigator.requestMIDIAccess) { ui.midiNotice = 'This browser does not support Web MIDI. Practice without MIDI or connect using a supported browser.'; $('midi-status').textContent = tr(ui.midiNotice); return; }
  try {
    const first = !midiAccess;
    midiAccess ||= await navigator.requestMIDIAccess({sysex: false});
    if (first && ui.capture) ui.capture.event('disconnect', {reason: 'MIDI connected during practice; earlier input was not captured'});
    midiAccess.onstatechange = event => {
      if (event.port.type === 'input' && event.port.state === 'disconnected') score.disconnect(event.port.id, transport.position());
      if (event.port.type === 'input' && event.port.state === 'disconnected' && (midiSelection === 'all' || midiSelection === event.port.id)) ui.capture?.event('disconnect', {id: event.port.id});
      midiBindings();
    };
    midiBindings();
  } catch { ui.midiNotice = 'MIDI access was denied. Check browser permissions. Other practice features are still available.'; $('midi-status').textContent = tr(ui.midiNotice); }
});
$('midi-input').addEventListener('change', event => {
  if (midiSelection !== event.target.value) score.disconnect(undefined, transport.position());
  if (ui.capture && midiSelection !== event.target.value) ui.capture.event('disconnect', {reason: 'Recording input changed'});
  midiSelection = event.target.value; midiBindings();
});
$('discard-btn').addEventListener('click', () => {
  if (transport.playing) { transport.pause(); ui.capture?.event('pause'); updateTransport(); }
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
  clearError(); $('discard-error').hidden = true;
  ui.discarding = true; ui.busy = true; updateTransport();
  const reason = $('discard-reason').value, choice = ui.discardChoice;
  $('discard-form').querySelectorAll('button, textarea').forEach(control => control.disabled = true);
  try {
    // Finish the local capture before closing the task; failed uploads remain retryable.
    await stopCapture();
    ui.busy = true; updateTransport();
    await api('/api/discard', {task_id: ui.discardTaskId, reason, choice});
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
for (const id of ['filter-exercise', 'filter-key', 'filter-from', 'filter-to']) $(id).addEventListener('change', renderHistory);
document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', async () => {
  if (button.dataset.view === 'list') return goToList();
  switchView(button.dataset.view);
  if (!ui.capture) { try { await refresh(true); } catch (error) { fail(error); } }
}));
document.querySelector('.brand').addEventListener('click', event => { event.preventDefault(); goToList(); });
document.addEventListener('visibilitychange', () => {
  ui.capture?.event('visibility', {hidden: document.hidden});
  if (document.hidden && transport.playing) { transport.pause(); ui.capture?.event('pause'); updateTransport(); }
  if (document.hidden && ui.capture && !ui.capture.ended) ui.capture.checkpoint().then(() => ui.capture.upload()).catch(() => {});
});
window.addEventListener('beforeunload', event => { if (ui.capture) { event.preventDefault(); event.returnValue = ''; } });
window.addEventListener('pagehide', () => { if (ui.capture && !ui.capture.ended) ui.capture.checkpoint().catch(() => {}); transport.pause(); });
async function changeLanguage() {
  const saved = setLocale($('language-select').value);
  translatePage();
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
