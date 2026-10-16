import {Transport} from './audio.mjs';
import {Capture, Outbox, uploadPending} from './capture.mjs';

const $ = id => document.getElementById(id);
const ui = {data: null, capture: null, busy: false, selected: null, recordTask: null, correcting: false, ports: new Map()};
let outbox, midiAccess, midiSelection = 'all', timer, detailTask;
const labels = {success: '조건 충족', unmet: '목표 미충족', unknown: '근거 부족'};
const states = {unknown: '미평가', attempted: '연습 기록', success: '당일 성공', retained: '후일 재현'};
function el(tag, text, className) { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node; }
function option(value, text, disabled = false) { const node = el('option', text); node.value = value; node.disabled = disabled; return node; }
function clock(ms) { const s = Math.max(0, Math.floor((ms || 0) / 1000)); return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`; }
function fail(error) { $('error').textContent = error.message || String(error); $('error').hidden = false; }
function clearError() { $('error').hidden = true; }
function numberOrNull(id) { return $(id).value === '' ? null : Number($(id).value); }
function pending() { return ui.data?.history.find(t => !t.report && !t.cancelled); }
function openSessions() { return ui.data?.sessions.filter(s => s.status === 'recording' && s.id !== ui.capture?.session.id) || []; }
function taskSessions(id) { return ui.data.sessions.filter(s => s.task_id === id); }

async function api(path, body) {
  let response;
  try {
    response = await fetch(path, {method: body === undefined ? 'GET' : 'POST', cache: 'no-store',
      headers: body === undefined ? {} : {'Content-Type': 'application/json', 'X-Jazz-Token': ui.data.csrf_token},
      body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(12000)});
  } catch { throw new Error('서버에 연결하지 못했습니다. 연습 서버가 실행 중인지 확인하고 다시 시도해 주세요.'); }
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '요청을 처리하지 못했습니다.');
  return result;
}

const transport = new Transport({
  onBeat: ({bar, beat}) => {
    [...$('beats').children].forEach((node, i) => node.classList.toggle('active', i === beat));
    [...$('chords').children].forEach((node, i) => node.classList.toggle('current', i === bar));
    $('bar-position').textContent = `${bar + 1}마디 · ${beat + 1}박`;
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
  const previous = pending()?.id;
  ui.data = await api('/api/state');
  outbox ||= new Outbox(ui.data.workspace_id);
  const current = pending();
  const next = ui.data.status.next;
  if (!keep || !ui.selected) {
    const lesson = ui.data.exercises.find(x => x.id === (current?.exercise_id || next.exercise_id)) || ui.data.exercises[0];
    ui.selected = {exercise: lesson.id, key: current?.target.key || next.key || ui.data.keys[0], bpm: current?.target.bpm || next.bpm || lesson.targets[ui.data.keys[0]].bpm};
  }
  $('connection').textContent = '로컬에 연결됨';
  $('preview-badge').hidden = !ui.data.preview;
  $('version').textContent = `VERSION ${ui.data.status.version}`;
  $('today-date').textContent = `${ui.data.status.today.date.replaceAll('-', '. ')} / DAILY PRACTICE`;
  const daily = ui.data.status.today;
  $('daily-time').replaceChildren(document.createTextNode(Number(daily.known_minutes.toFixed(1)).toString()), el('span', ` / ${daily.budget_minutes}분`));
  $('daily-count').textContent = `${daily.reported_attempts}개 기록${daily.minutes_unknown ? ` · 시간 미확인 ${daily.minutes_unknown}건` : daily.budget_reached ? ' · 오늘도 수고했어요' : ''}`;
  $('suggestion-note').textContent = daily.budget_reached ? '오늘의 시간 예산을 채웠어요. 마무리해도 좋고, 원하면 더 연습할 수 있습니다.' : next.reason;
  renderChoices();
  renderLesson(!keep || previous !== current?.id);
  renderHistory();
  renderGoals();
  $('recovery').hidden = openSessions().length === 0;
  updateTransport();
}

function renderChoices() {
  const lock = Boolean(pending());
  $('exercise-select').replaceChildren(...ui.data.exercises.map(x => option(x.id, `${x.id} · ${x.title}`)));
  $('exercise-select').value = ui.selected.exercise;
  $('key-select').replaceChildren(...ui.data.keys.map(key => option(key, key)));
  $('key-select').value = ui.selected.key;
  $('goal-bpm').value = ui.selected.bpm;
  for (const id of ['goal-bpm', 'tempo', 'tempo-range']) { $(id).min = ui.data.minimum_bpm; $(id).max = ui.data.maximum_bpm; }
  ['exercise-select', 'key-select', 'goal-bpm'].forEach(id => $(id).disabled = lock);
  const lesson = ui.data.exercises.find(x => x.id === ui.selected.exercise);
  $('eligibility').textContent = lock ? '진행 중인 과제의 목표는 보존됩니다. 다음 과제에서 조건을 바꿀 수 있어요.' : lesson.eligible_keys.includes(ui.selected.key) ? '시작 버튼을 누르면 이 조건으로 과제가 발급됩니다.' : `같은 키의 선행 과제 ${lesson.prerequisites.join(', ')}를 먼저 확인해 주세요.`;
  const actualKey = $('actual-key').value, actualArrangement = $('actual-arrangement').value;
  $('actual-key').replaceChildren(option('', '미확인'), ...ui.data.keys.map(key => option(key, key)));
  $('actual-arrangement').replaceChildren(option('', '미확인'), ...Object.entries(ui.data.arrangements).map(([value, title]) => option(value, title)));
  $('actual-key').value = actualKey;
  $('actual-arrangement').value = actualArrangement;
  const exerciseFilter = $('filter-exercise').value, keyFilter = $('filter-key').value;
  $('filter-exercise').replaceChildren(option('', '전체 과제'), ...ui.data.exercises.map(x => option(x.id, `${x.id} · ${x.title}`)));
  $('filter-key').replaceChildren(option('', '모든 키'), ...ui.data.keys.map(k => option(k, k)));
  $('filter-exercise').value = exerciseFilter;
  $('filter-key').value = keyFilter;
}

function target() {
  const current = pending();
  if (current) return current.target;
  const lesson = ui.data.exercises.find(x => x.id === ui.selected.exercise);
  return {...lesson.targets[ui.selected.key], bpm: ui.selected.bpm};
}
function renderLesson(resetTempo = false) {
  const current = pending(), t = target();
  const lesson = ui.data.exercises.find(x => x.id === (current?.exercise_id || ui.selected.exercise));
  $('lesson-kind').textContent = `${current ? '진행 중인 과제' : '다음 과제'} / ${lesson.id}`;
  $('lesson-title').textContent = t.title;
  $('lesson-phase').textContent = lesson.phase;
  $('lesson-purpose').textContent = t.material.title;
  $('target-meta').replaceChildren(...[`${t.key} 키`, `목표 ${t.bpm} BPM`, `${t.bars}마디`, '4/4'].map(s => el('span', s)));
  let chords = t.playback?.bars.map(b => b.chord);
  if (!chords) chords = t.material.chords.split('|').map(s => s.trim());
  $('chords').replaceChildren(...chords.map((chord, index) => { const box = el('div', undefined, 'chord-box'); box.append(el('small', `${String(index + 1).padStart(2, '0')}`), el('strong', chord)); return box; }));
  $('hand-notes').replaceChildren();
  const rows = [];
  if (t.bass !== 'none' && t.material.roots) rows.push(['왼손', t.material.roots]);
  if (t.melody !== 'none' && t.material.melody) rows.push(['오른손', t.material.melody]);
  if (t.voicing !== 'none' && t.material.guide_tones) rows.push(['오른손', t.material.guide_tones]);
  if (t.arrangement === 'left-bass-only') rows.push(['오른손', '편안하게 쉬어요']);
  if (t.arrangement === 'right-melody-only') rows.push(['왼손', '편안하게 쉬어요']);
  for (const [label, text] of rows) { const row = el('div', undefined, 'hand-row'); row.append(el('span', label), el('strong', text)); $('hand-notes').append(row); }
  $('lesson-instructions').textContent = `${t.instructions} C4는 가운데 도입니다.`;
  $('criterion-text').textContent = `지정 조건에서 음과 박을 지키며, 멈추지 않고 연속 ${t.criteria.min_clean_runs}회.`;
  $('skip-btn').hidden = current ? taskSessions(current.id).some(s => s.status === 'recording' || s.summary?.active_ms > 0 || s.summary?.note_ons > 0) : !lesson.eligible_keys.includes(ui.selected.key);
  $('manual-record-btn').hidden = !current;
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
  const eligible = pending() || ui.data.exercises.find(x => x.id === ui.selected.exercise).eligible_keys.includes(ui.selected.key);
  $('practice-btn').disabled = ui.busy || recovery || !eligible || Boolean(recording?.ended);
  $('practice-btn').textContent = recording ? transport.playing ? '일시정지' : recording.ended ? '저장 대기' : '이어하기' : '연습 시작';
  $('finish-btn').disabled = ui.busy || !recording;
  $('finish-btn').textContent = recording?.ended ? '저장 재시도' : '마치기';
  $('transport-state').textContent = recording ? transport.playing ? '연습 중' : recording.ended ? '저장 대기' : '잠시 쉬는 중' : '준비';
  $('manual-record-btn').disabled = Boolean(recording) || recovery || ui.busy;
  $('skip-btn').disabled = Boolean(recording) || recovery || ui.busy;
}

function registerPort(port) {
  if (!ui.capture || ui.ports.has(port.id)) return;
  const index = ui.ports.size;
  ui.ports.set(port.id, index);
  ui.capture.event('device', {index, name: port.name || '이름 없는 입력', manufacturer: port.manufacturer || '', id: port.id});
}
function selectedPorts() { return midiAccess ? [...midiAccess.inputs.values()].filter(p => p.state === 'connected' && (midiSelection === 'all' || midiSelection === p.id)) : []; }
function midiBindings() {
  if (!midiAccess) return;
  const available = [...midiAccess.inputs.values()].filter(p => p.state === 'connected');
  $('midi-input').hidden = false;
  $('midi-input').replaceChildren(option('all', '연결된 모든 입력 기록'), option('none', 'MIDI 기록 끄기'), ...available.map(p => option(p.id, p.name || 'MIDI 입력')));
  if (![...$('midi-input').options].some(o => o.value === midiSelection)) $('midi-input').append(option(midiSelection, '선택한 장치 · 연결 끊김'));
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
        $('midi-status').textContent = `입력 기록 중 · 건반 ${ui.capture.noteCount}회`;
      }
    };
  }
  $('midi-light').classList.toggle('connected', selectedPorts().length > 0);
  $('midi-status').textContent = selectedPorts().length ? `${selectedPorts().length}개 입력 준비 · 연습 중 원본을 기록합니다.` : '연결된 입력이 없습니다. 메트로놈은 계속 사용할 수 있어요.';
  $('midi-connect').textContent = '다시 검색';
}

async function startOrPause() {
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
      if (!pending()) {
        await api('/api/assign', {exercise_id: ui.selected.exercise, key: ui.selected.key, bpm: ui.selected.bpm});
        await refresh(true);
        setTempo(requestedTempo);
      }
      const session = await api('/api/sessions/start', {task_id: pending().id, session_id: 'S-' + crypto.randomUUID().replaceAll('-', '')});
      const capture = new Capture(session, outbox, api, (text, warning) => {
        $('save-status').textContent = text;
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
    $('record-panel').hidden = $('feedback-panel').hidden = true;
    transport.click = $('click-toggle').checked;
    transport.setPad($('pad-toggle').checked);
    ui.capture.event('play', {bpm: Number($('tempo').value)});
    transport.start(target().playback, Number($('tempo').value));
    $('save-status').textContent = '기록 중 · 3초마다 자동 저장';
  } catch (error) {
    fail(error);
    if (!ui.capture) { try { await refresh(true); } catch {} }
  }
  finally { ui.busy = false; updateTransport(); }
}
async function finish() {
  if (!ui.capture) return;
  clearError(); ui.busy = true; updateTransport();
  const id = ui.capture.session.task_id;
  try {
    if (transport.playing) { transport.pause(); ui.capture.event('pause'); }
    await ui.capture.stop();
    ui.capture = null; clearInterval(timer);
    $('save-status').textContent = '연습 저장 완료';
    await refresh(true);
    showRecord(ui.data.history.find(t => t.id === id));
  } catch (error) { fail(error); }
  finally { ui.busy = false; updateTransport(); }
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
    if (pending()) showRecord(pending());
  } catch (error) { fail(error); }
  finally { ui.busy = false; $('recover-btn').disabled = false; updateTransport(); }
}

function showRecord(task, correcting = false) {
  if (!task || ui.capture || openSessions().length) return;
  ui.recordTask = task; ui.correcting = correcting;
  $('record-form').reset();
  for (const id of ['actual-key', 'actual-arrangement', 'actual-bars']) $(id).disabled = false;
  $('record-title').textContent = correcting ? `${task.exercise_id} 기록을 정정합니다` : '오늘의 연주를 남겨볼까요?';
  $('save-report').textContent = correcting ? '정정 내용 저장' : '기록 저장 · 피드백 보기';
  $('record-panel').hidden = false;
  $('feedback-panel').hidden = true;
  $('measurements').replaceChildren();
  $('practice-date').max = ui.data.status.today.date;
  $('practice-date').value = ui.data.status.today.date;
  const sessions = taskSessions(task.id).filter(s => s.summary);
  const summaries = sessions.map(s => s.summary);
  if (summaries.length) {
    const elapsed = summaries.reduce((n, s) => n + s.elapsed_ms, 0);
    const completeSpans = summaries.filter(s => s.input_span_ms !== null);
    $('measurements').append(el('span', `세션 경과 ${clock(elapsed)}`), el('span', `저장된 연습 ${summaries.length}회`));
    if (completeSpans.length) $('measurements').append(el('span', `측정 가능한 MIDI 구간 ${clock(completeSpans.reduce((n, s) => n + s.input_span_ms, 0))}`));
    if (summaries.some(s => s.capture_warnings.length)) $('measurements').append(el('span', '입력 누락·중단 표시 있음'));
    const last = [...summaries].reverse().find(s => s.last_note_bpm !== null || s.last_setting_bpm !== null);
    if (last) $('actual-bpm').value = last.last_note_bpm ?? last.last_setting_bpm;
    if (sessions.every(s => s.status === 'finished')) {
      $('actual-minutes').value = (summaries.reduce((n, s) => n + (s.input_span_ms ?? s.active_ms), 0) / 60000).toFixed(3);
    }
    $('prefill-note').textContent = 'BPM은 마지막 연주 시점의 메트로놈 설정값입니다. 시간은 앞뒤를 뺀 MIDI 구간을 우선하며, 측정할 수 없으면 일시정지를 뺀 세션 시간을 제안합니다. 의도적인 쉼과 실제 수행 조건을 확인해 주세요. 수집이 중단된 세션의 시간은 직접 입력합니다.';
  } else $('prefill-note').textContent = '자동 측정된 연습이 없습니다. 기억나는 실제 조건만 입력하고, 모르는 항목은 미확인으로 두세요.';
  if (correcting) {
    const report = task.report, actual = JSON.parse(report.actual_json), checks = JSON.parse(report.checks_json);
    $('practice-date').value = report.practice_date;
    $('actual-bpm').value = actual.bpm ?? '';
    $('actual-minutes').value = report.actual_minutes;
    $('actual-key').value = actual.key || '';
    $('actual-arrangement').value = actual.arrangement || '';
    $('actual-bars').value = actual.bars ?? '';
    $('notes-correct').value = checks.notes_correct == null ? '' : String(checks.notes_correct);
    $('steady-pulse').value = checks.steady_pulse == null ? '' : String(checks.steady_pulse);
    $('no-stops').value = checks.no_stops == null ? '' : String(checks.no_stops);
    $('clean-runs').value = report.clean_runs;
    $('difficulty').value = report.difficulty || 'unknown';
    $('raw-note').value = report.raw_note;
    $('prefill-note').textContent = '이전 실제 조건과 원문을 불러왔습니다. 수정 전 기록도 보존됩니다.';
  }
  $('record-panel').scrollIntoView({behavior: 'smooth', block: 'start'});
}
async function saveReport(event) {
  event.preventDefault(); clearError(); $('save-report').disabled = true;
  try {
    const followedTarget = $('followed-target').checked;
    const actual = ui.correcting && !followedTarget ? {...JSON.parse(ui.recordTask.report.actual_json)} : {};
    actual.bpm = numberOrNull('actual-bpm');
    if (!followedTarget) {
      for (const [id, key] of [['actual-key', 'key'], ['actual-arrangement', 'arrangement']]) actual[key] = $(id).value || null;
      actual.bars = numberOrNull('actual-bars');
    }
    const checks = {};
    for (const [id, key] of [['notes-correct', 'notes_correct'], ['steady-pulse', 'steady_pulse'], ['no-stops', 'no_stops']]) checks[key] = $(id).value === '' ? null : $(id).value === 'true';
    const result = {practice_date: $('practice-date').value, followed_target: followedTarget,
      actual, checks, clean_runs: numberOrNull('clean-runs'), actual_minutes: numberOrNull('actual-minutes'),
      difficulty: $('difficulty').value, raw_note: $('raw-note').value};
    if (ui.correcting) result.hypothesis = ui.recordTask.report.hypothesis;
    const saved = await api('/api/report', {task_id: ui.recordTask.id, result, correction: ui.correcting});
    await refresh();
    $('record-panel').hidden = true;
    $('feedback-title').textContent = saved.feedback.title;
    $('feedback-details').replaceChildren(...saved.feedback.details.map(text => el('li', text)));
    $('feedback-next').textContent = ui.data.status.next.reason;
    $('feedback-panel').hidden = false;
    $('feedback-panel').focus();
    $('feedback-panel').scrollIntoView({behavior: 'smooth', block: 'center'});
    ui.recordTask = null;
  } catch (error) { fail(error); }
  finally { $('save-report').disabled = false; }
}

function switchView(name) {
  document.querySelectorAll('.view').forEach(view => view.hidden = view.id !== `view-${name}`);
  document.querySelectorAll('[data-view]').forEach(button => { button.classList.toggle('active', button.dataset.view === name); button.setAttribute('aria-current', button.dataset.view === name ? 'page' : 'false'); });
}
function renderHistory() {
  const exercise = $('filter-exercise').value, key = $('filter-key').value, from = $('filter-from').value, to = $('filter-to').value;
  const tasks = ui.data.history.filter(task => {
    const day = task.report?.practice_date || task.assigned_at.slice(0, 10);
    const actualKey = task.report ? JSON.parse(task.report.actual_json).key || task.target.key : task.target.key;
    return (!exercise || task.exercise_id === exercise) && (!key || actualKey === key) && (!from || day >= from) && (!to || day <= to);
  });
  $('history-list').replaceChildren();
  if (!tasks.length) { const empty = el('div', undefined, 'empty-state'); empty.append(el('h3', '아직 이곳은 빈 악보예요.'), el('p', '연습을 시작하면 조건과 메모가 차곡차곡 쌓입니다.')); $('history-list').append(empty); }
  for (const task of tasks) {
    const button = el('button', undefined, 'history-item'), left = el('div');
    const day = task.report?.practice_date || task.assigned_at.slice(0, 10);
    left.append(el('small', `${day} / ${task.exercise_id}`), el('h3', task.target.title), el('p', `${task.target.key} · 목표 ${task.target.bpm} BPM${task.report?.actual_minutes ? ` · ${Number(Number(task.report.actual_minutes).toFixed(2))}분` : ''}`));
    button.append(left, el('span', task.cancelled ? '건너뜀' : task.report ? labels[task.outcome] : '진행 중', `tag ${task.outcome}`));
    button.addEventListener('click', () => showDetail(task));
    $('history-list').append(button);
  }
}
function renderGoals() {
  $('goals').replaceChildren(...ui.data.status.goals.map(goal => {
    const lesson = ui.data.exercises.find(x => x.id === goal.exercise_id), card = el('div', undefined, 'card goal-card');
    const top = el('div', undefined, 'section-top'); top.append(el('span', goal.exercise_id, 'eyebrow'), el('span', states[goal.state], `tag ${['success','retained'].includes(goal.state) ? 'success' : 'unknown'}`));
    card.append(top, el('h3', lesson.title), el('p', `${goal.key} · ${goal.bpm} BPM · ${goal.attempts}회 기록${goal.last_success ? ` · 마지막 성공 ${goal.last_success}` : ''}`));
    return card;
  }));
}
function showDetail(task) {
  detailTask = task;
  const box = $('history-detail'); box.replaceChildren(el('h2', task.target.title), el('p', `${task.exercise_id} · ${task.report?.practice_date || task.assigned_at.slice(0, 10)}`, 'subtle'));
  const grid = el('div', undefined, 'detail-grid');
  const intended = el('div'); intended.append(el('h3', '발급 조건'), el('div', `${task.target.key} · ${task.target.bpm} BPM · ${task.target.bars}마디`), el('div', ui.data.arrangements[task.target.arrangement] || task.target.arrangement));
  const actualBox = el('div'); actualBox.append(el('h3', '실제 보고'));
  if (task.report) {
    const a = JSON.parse(task.report.actual_json);
    actualBox.append(el('div', `${a.key || '키 미확인'} · ${a.bpm ?? '미확인'} BPM · ${a.bars ?? '미확인'}마디`), el('div', ui.data.arrangements[a.arrangement] || '손 구성 미확인'), el('div', `${labels[task.outcome]} · 연속 성공 ${task.report.clean_runs || '미확인'}회`));
  } else actualBox.append(el('div', task.cancelled ? '연습 전 취소' : '아직 결과를 기록하지 않았어요'));
  grid.append(intended, actualBox); box.append(grid);
  box.append(el('p', task.report?.raw_note || task.reason, 'raw-note'));
  for (const session of taskSessions(task.id)) {
    const row = el('div', undefined, 'session-row');
    row.append(el('div', `연습 ${session.created_at.slice(0, 16).replace('T', ' ')} · ${session.status === 'recording' ? '저장 중' : session.status === 'interrupted' ? '중단됨' : '저장 완료'}`));
    if (session.summary) {
      const s = session.summary;
      row.append(el('div', `세션 ${clock(s.elapsed_ms)} · MIDI 구간 ${s.input_span_ms === null ? '미확인' : clock(s.input_span_ms)} · 마지막 설정 ${s.last_note_bpm ?? s.last_setting_bpm ?? '미확인'} BPM`));
    }
    for (const [suffix, text] of [['midi', 'MIDI 원본 받기 (.jpm)'], ['metadata', '세션 정보 받기 (.json)']]) { const a = el('a', text); a.href = `/api/recordings/${session.id}/${suffix}`; a.download = ''; row.append(a); }
    box.append(row);
  }
  if (task.revisions.length > 1) {
    const details = el('details', undefined, 'revision'); details.append(el('summary', `원본과 정정 이력 ${task.revisions.length}건`));
    for (const revision of task.revisions) { details.append(el('small', `${revision.recorded_at.slice(0, 16).replace('T', ' ')} · ${revision.event_type === 'reported' ? '최초 기록' : '정정'}`), el('p', revision.raw_note)); }
    box.append(details);
  }
  $('correct-btn').hidden = !task.report;
  $('correct-btn').disabled = Boolean(ui.capture) || openSessions().length > 0;
  $('history-dialog').showModal();
}

$('practice-btn').addEventListener('click', startOrPause);
$('finish-btn').addEventListener('click', finish);
$('recover-btn').addEventListener('click', recover);
$('manual-record-btn').addEventListener('click', () => showRecord(pending()));
$('record-form').addEventListener('submit', saveReport);
$('close-record').addEventListener('click', () => $('record-panel').hidden = true);
$('next-btn').addEventListener('click', () => { $('feedback-panel').hidden = true; window.scrollTo({top: 0, behavior: 'smooth'}); });
$('tempo').addEventListener('change', event => setTempo(event.target.value));
$('tempo-range').addEventListener('input', event => setTempo(event.target.value));
$('tempo-down').addEventListener('click', () => setTempo(Number($('tempo').value) - 5));
$('tempo-up').addEventListener('click', () => setTempo(Number($('tempo').value) + 5));
$('click-toggle').addEventListener('change', event => { transport.click = event.target.checked; ui.capture?.event('click', {enabled: event.target.checked}); });
$('pad-toggle').addEventListener('change', event => { transport.setPad(event.target.checked); ui.capture?.event('pad', {enabled: event.target.checked}); });
for (const id of ['click-volume', 'pad-volume']) $(id).addEventListener('input', () => transport.setVolumes(Number($('click-volume').value), Number($('pad-volume').value)));
for (const id of ['exercise-select', 'key-select', 'goal-bpm']) $(id).addEventListener('change', () => {
  if (pending()) return;
  ui.selected = {exercise: $('exercise-select').value, key: $('key-select').value, bpm: Math.min(ui.data.maximum_bpm, Math.max(ui.data.minimum_bpm, Number($('goal-bpm').value) || 60))};
  renderChoices(); renderLesson(true); updateTransport();
});
$('midi-connect').addEventListener('click', async () => {
  clearError();
  if (!navigator.requestMIDIAccess) { $('midi-status').textContent = 'Web MIDI를 지원하지 않는 브라우저입니다. MIDI 없이 연습하거나 지원 브라우저에서 연결해 주세요.'; return; }
  try {
    const first = !midiAccess;
    midiAccess ||= await navigator.requestMIDIAccess({sysex: false});
    if (first && ui.capture) ui.capture.event('disconnect', {reason: '연습 도중 MIDI 연결 · 이전 구간은 미수집'});
    midiAccess.onstatechange = event => {
      if (event.port.type === 'input' && event.port.state === 'disconnected' && (midiSelection === 'all' || midiSelection === event.port.id)) ui.capture?.event('disconnect', {id: event.port.id});
      midiBindings();
    };
    midiBindings();
  } catch { $('midi-status').textContent = 'MIDI 접근이 허용되지 않았습니다. 브라우저 권한을 확인해 주세요. 나머지 연습 기능은 사용할 수 있습니다.'; }
});
$('midi-input').addEventListener('change', event => {
  if (ui.capture && midiSelection !== event.target.value) ui.capture.event('disconnect', {reason: '기록 입력 변경'});
  midiSelection = event.target.value; midiBindings();
});
$('skip-btn').addEventListener('click', () => { $('skip-reason').value = ''; $('skip-dialog').showModal(); });
$('skip-close').addEventListener('click', () => $('skip-dialog').close());
$('skip-form').addEventListener('submit', async event => {
  event.preventDefault(); clearError();
  try {
    if (!pending()) {
      await api('/api/assign', {exercise_id: ui.selected.exercise, key: ui.selected.key, bpm: ui.selected.bpm});
      await refresh(true);
    }
    await api('/api/cancel', {task_id: pending().id, reason: $('skip-reason').value});
    $('skip-dialog').close(); $('record-panel').hidden = true; await refresh();
  }
  catch (error) { $('skip-dialog').close(); fail(error); }
});
$('dialog-close').addEventListener('click', () => $('history-dialog').close());
$('followed-target').addEventListener('change', event => {
  for (const id of ['actual-key', 'actual-arrangement', 'actual-bars']) $(id).disabled = event.target.checked;
});
$('correct-btn').addEventListener('click', () => { $('history-dialog').close(); switchView('practice'); showRecord(detailTask, true); });
for (const id of ['filter-exercise', 'filter-key', 'filter-from', 'filter-to']) $(id).addEventListener('change', renderHistory);
document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', async () => { switchView(button.dataset.view); if (!ui.capture) { try { await refresh(true); } catch (error) { fail(error); } } }));
document.querySelector('.brand').addEventListener('click', () => switchView('practice'));
document.addEventListener('visibilitychange', () => {
  ui.capture?.event('visibility', {hidden: document.hidden});
  if (document.hidden && transport.playing) { transport.pause(); ui.capture?.event('pause'); updateTransport(); }
  if (document.hidden && ui.capture && !ui.capture.ended) ui.capture.checkpoint().then(() => ui.capture.upload()).catch(() => {});
});
window.addEventListener('beforeunload', event => { if (ui.capture) { event.preventDefault(); event.returnValue = ''; } });
window.addEventListener('pagehide', () => { if (ui.capture && !ui.capture.ended) ui.capture.checkpoint().catch(() => {}); transport.pause(); });
refresh().catch(error => { $('connection').textContent = '연결 확인 필요'; fail(error); });
