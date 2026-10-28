import {tr, locale, setLocale, loadTranslations, translatePage} from './i18n.mjs';
import {Transport} from './audio.mjs';
import {Capture, Outbox, uploadPending} from './capture.mjs';
import {ScoreView} from './score.mjs';

const $ = id => document.getElementById(id);
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

async function refresh(keep = false) {
  const previous = openedTask()?.id;
  const data = await api('/api/state');
  if (data.language !== locale()) return; // A newer language selection superseded this response.
  ui.data = data;
  outbox ||= new Outbox(ui.data.workspace_id);
  const current = pending();
  if (ui.openedTaskId && !openedTask()) { ui.openedTaskId = null; if (ui.view === 'practice') switchView('list'); }
  const next = ui.data.status.next;
  if (!keep || !ui.selected) {
    const lesson = ui.data.exercises.find(x => x.id === (current?.exercise_id || next.exercise_id)) || ui.data.exercises[0];
    ui.selected = {exercise: lesson.id, key: current?.target.key || next.key || ui.data.keys[0], bpm: current?.target.bpm || next.bpm || lesson.targets[ui.data.keys[0]].bpm};
  }
  $('connection').textContent = tr('Connected locally');
  $('preview-badge').hidden = !ui.data.preview;
  $('version').textContent = tr`VERSION ${ui.data.status.version}`;
  $('today-date').textContent = tr`${ui.data.status.today.date.replaceAll('-', '. ')} / DAILY PRACTICE`;
  const daily = ui.data.status.today;
  $('daily-time').replaceChildren(document.createTextNode(Number(daily.known_minutes.toFixed(1)).toString()), el('span', tr` / ${daily.budget_minutes} min`));
  $('daily-count').textContent = tr`${daily.reported_attempts} completed${daily.minutes_unknown ? tr` · duration unknown: ${daily.minutes_unknown}` : daily.budget_reached ? tr(' · good work today') : ''}`;
  $('suggestion-note').textContent = daily.budget_reached ? tr('You have reached your daily time budget. You can finish here or keep practicing if you like.') : next.reason;
  renderChoices();
  renderLesson(!keep || previous !== openedTask()?.id);
  renderHistory();
  renderRecordText();
  $('recovery').hidden = openSessions().length === 0;
  updateTransport();
}

function renderChoices() {
  const lock = Boolean(pending()) || ui.busy;
  $('exercise-select').replaceChildren(...ui.data.exercises.map(x => option(x.id, `${x.id} · ${x.title}`)));
  $('exercise-select').value = ui.selected.exercise;
  $('key-select').replaceChildren(...ui.data.keys.map(key => option(key, key)));
  $('key-select').value = ui.selected.key;
  $('goal-bpm').value = ui.selected.bpm;
  for (const id of ['goal-bpm', 'tempo', 'tempo-range']) { $(id).min = ui.data.minimum_bpm; $(id).max = ui.data.maximum_bpm; }
  ['exercise-select', 'key-select', 'goal-bpm', 'add-practice'].forEach(id => $(id).disabled = lock);
  $('new-practice').disabled = lock || Boolean(ui.capture) || openSessions().length > 0;
  $('pending-hint').textContent = pending() ? tr('Open your unfinished practice below to continue or skip it.') : '';
  const lesson = ui.data.exercises.find(x => x.id === ui.selected.exercise);
  const eligible = lesson.eligible_keys.includes(ui.selected.key);
  $('eligibility').textContent = eligible ? tr('This adds an item to your list. Open it when you are ready.') : tr`First complete the prerequisites in this key: ${lesson.prerequisites.join(', ')}.`;
  $('add-practice').disabled = lock || !eligible;
  $('new-description').textContent = lesson.targets[ui.selected.key].instructions;
  const exerciseFilter = $('filter-exercise').value, keyFilter = $('filter-key').value;
  $('filter-exercise').replaceChildren(option('', tr('All exercises')), ...ui.data.exercises.map(x => option(x.id, `${x.id} · ${x.title}`)));
  $('filter-key').replaceChildren(option('', tr('All keys')), ...ui.data.keys.map(k => option(k, k)));
  $('filter-exercise').value = exerciseFilter;
  $('filter-key').value = keyFilter;
}

function target() { return openedTask()?.target; }
function renderLesson(resetTempo = false) {
  const current = openedTask(), t = target();
  if (!current) return;
  score.setScore(t.notation);
  if (!t.notation) $('lesson-material').open = true;
  const lesson = ui.data.exercises.find(x => x.id === (current?.exercise_id || ui.selected.exercise));
  $('lesson-kind').textContent = tr`${current ? tr('Current task') : tr('Next task')} / ${lesson.id}`;
  $('lesson-title').textContent = t.title;
  $('lesson-phase').textContent = lesson.phase;
  $('lesson-purpose').textContent = t.material.title;
  $('bar-position').textContent = ui.capture && ui.beat ? tr`Bar ${ui.beat.bar + 1} · beat ${ui.beat.beat + 1}` : tr('One chord per bar');
  $('target-meta').replaceChildren(...[tr`Key ${t.key}`, tr`Target ${t.bpm} BPM`, tr`${t.bars} bars`, '4/4'].map(s => el('span', s)));
  let chords = t.playback?.bars.map(b => b.chord);
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
  $('lesson-instructions').textContent = tr`${t.instructions} C4 is middle C.`;
  $('criterion-text').textContent = tr`Play ${t.criteria.min_clean_runs} consecutive runs with correct notes, a steady pulse, and no stops under the assigned conditions.`;
  $('discard-btn').hidden = !current && !lesson.eligible_keys.includes(ui.selected.key);
  $('pad-toggle').disabled = !t.playback;
  if (!t.playback) { $('pad-toggle').checked = false; transport.setPad(false); }
  if (resetTempo && !ui.capture) setTempo(t.bpm);
}
function setTempo(value) {
  const numeric = Math.min(ui.data.maximum_bpm, Math.max(ui.data.minimum_bpm, Math.round(Number(value) || ui.data.minimum_bpm)));
  $('tempo').value = $('tempo-range').value = numeric;
  transport.setTempo(numeric);
}
function updateTransport() {
  if (!ui.data) return;
  const recording = ui.capture, recovery = openSessions().length > 0;
  const eligible = Boolean(openedTask());
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
  $('midi-status').textContent = selectedPorts().length ? tr`${selectedPorts().length} input(s) ready · raw input is recorded during practice.` : tr('No inputs connected. The metronome is still available.');
  $('midi-connect').textContent = tr('Refresh');
}

async function startOrPause() {
  if (!openedTask() || ui.busy) return;
  clearError();
  if (ui.capture && transport.playing) {
    transport.pause(); ui.capture.event('pause'); updateTransport(); return;
  }
  ui.busy = true; updateTransport();
  const requestedTempo = Number($('tempo').value);
  try {
    await transport.unlock(); // User gesture, before a network round trip.
    if (!ui.capture) {
      await outbox.database();
      const session = await api('/api/sessions/start', {task_id: openedTask().id, session_id: 'S-' + crypto.randomUUID().replaceAll('-', '')});
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
    ui.capture.event('play', {bpm: Number($('tempo').value)});
    transport.start(target().playback, Number($('tempo').value));
    openedTask().started = true;
    ui.saveStatus = 'Recording · autosaving every 3 seconds';
    $('save-status').textContent = tr(ui.saveStatus);
  } catch (error) {
    fail(error);
    if (!ui.capture) { try { await refresh(true); } catch {} }
  }
  finally { ui.busy = false; updateTransport(); }
}
async function stopCapture() {
  if (!ui.capture) return;
  if (transport.playing) { transport.pause(); ui.capture.event('pause'); }
  const saved = await ui.capture.stop();
  const index = ui.data.sessions.findIndex(session => session.id === saved.id);
  if (index < 0) ui.data.sessions.push(saved);
  else ui.data.sessions[index] = saved;
  ui.capture = null; clearInterval(timer);
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
  document.querySelectorAll('[data-view]').forEach(button => { button.classList.toggle('active', button.dataset.view === name); button.setAttribute('aria-current', button.dataset.view === name ? 'page' : 'false'); });
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
    left.append(el('small', `${task.assigned_at.slice(11,16)} / ${task.exercise_id}`), el('h3', task.target.title), el('p', tr`${task.target.key} · Target ${task.target.bpm} BPM${minutes}`));
    const status = task.retired ? tr('Retired on update') : task.discarded ? tr('Discarded') : task.cancelled ? tr('Skipped') : task.completed ? tr('Completed') : task.started || ui.capture?.session.task_id === task.id ? tr('In progress') : tr('Ready to practice');
    button.append(left, el('span', status, `tag ${task.completed ? 'success' : 'unknown'}`));
    button.addEventListener('click', () => task.pending ? openPractice(task) : showDetail(task));
    card.append(button, el('p', task.target.instructions, 'practice-content'));
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
  detailTask = task;
  const box = $('history-detail'); box.replaceChildren(el('h2', task.target.title), el('p', `${task.exercise_id} · ${(task.report || task.completion)?.practice_date || task.assigned_at.slice(0, 10)}`, 'subtle'));
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
  $('repeat-btn').disabled = Boolean(pending()) || Boolean(ui.capture) || openSessions().length > 0;
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
for (const id of ['exercise-select', 'key-select', 'goal-bpm']) $(id).addEventListener('change', () => {
  ui.selected = {exercise: $('exercise-select').value, key: $('key-select').value, bpm: Math.min(ui.data.maximum_bpm, Math.max(ui.data.minimum_bpm, Number($('goal-bpm').value) || 60))};
  renderChoices();
});
function newPractice(source) {
  if (pending() || ui.busy || ui.capture || openSessions().length) return;
  const next = ui.data.status.next;
  ui.selected = source ? {exercise: source.exercise_id, key: source.target.key, bpm: source.target.bpm} :
    {exercise: next.exercise_id || ui.data.exercises[0].id, key: next.key || ui.data.keys[0], bpm: next.bpm || 60};
  ui.newTaskId = 'T-' + crypto.randomUUID().replaceAll('-', '').slice(0,10);
  $('new-error').hidden = true;
  renderChoices(); $('new-dialog').showModal();
}
$('new-practice').addEventListener('click', () => newPractice());
$('new-close').addEventListener('click', () => $('new-dialog').close());
$('new-dialog').addEventListener('cancel', event => { if (ui.busy) event.preventDefault(); });
$('new-form').addEventListener('submit', async event => {
  event.preventDefault(); if (ui.busy) return;
  ui.busy = true; renderChoices(); $('new-close').disabled = true;
  try {
    await api('/api/assign', {task_id: ui.newTaskId, exercise_id: ui.selected.exercise, key: ui.selected.key, bpm: ui.selected.bpm});
    await refresh(true); clearFilters(); renderHistory();
    $('new-dialog').close(); switchView('list');
    document.querySelector(`[data-task-id="${ui.newTaskId}"]`)?.scrollIntoView({behavior:'smooth', block:'center'});
  } catch (error) { $('new-error').textContent = tr(error.message); $('new-error').hidden = false; }
  finally { ui.busy = false; $('new-close').disabled = false; renderChoices(); updateTransport(); }
});
$('back-list').addEventListener('click', goToList);
$('repeat-btn').addEventListener('click', () => { $('history-dialog').close(); newPractice(detailTask); });
$('midi-connect').addEventListener('click', async () => {
  clearError();
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
