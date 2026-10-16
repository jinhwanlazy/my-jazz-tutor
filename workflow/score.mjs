import {tr} from './i18n.mjs';

const NS = 'http://www.w3.org/2000/svg';
const WIDTH = 1000, HEIGHT = 320, START = 144, BAR = 208, TOP = {right: 90, left: 205};
const LETTERS = 'CDEFGAB', SEMITONES = [0, 2, 4, 5, 7, 9, 11];
const FLATS = {C: [], F: ['B'], Bb: ['B', 'E']};
const glyphs = {treble: '\uE050', bass: '\uE062', flat: '\uE260', natural: '\uE261', sharp: '\uE262',
  quarterRest: '\uE4E5', eighthRest: '\uE4E6', eighthFlag: '\uE240'};

function svg(tag, attributes = {}, text) {
  const node = document.createElementNS(NS, tag);
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
  if (text !== undefined) node.textContent = text;
  return node;
}
function line(parent, x1, y1, x2, y2, cls) { parent.append(svg('line', {x1, y1, x2, y2, class: cls})); }
function symbol(parent, name, x, y) { parent.append(svg('text', {x, y, class: 'score-glyph'}, glyphs[name])); }
function noteX(bar, beat) { return START + (bar % 4) * BAR + 20 + beat / 4 * (BAR - 40); }

export function spell(midi, key = 'C') {
  const pc = midi % 12, octave = Math.floor(midi / 12) - 1;
  const names = key === 'C' ? ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'] :
    ['C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B'];
  const name = names[pc], letter = name[0], alter = pc - SEMITONES[LETTERS.indexOf(letter)];
  return {midi, name: name + octave, letter, alter, octave};
}
export function noteY(pitch, staff) {
  const bottom = staff === 'right' ? 4 * 7 + 2 : 2 * 7 + 4; // E4 / G2
  return TOP[staff] + 40 - (pitch.octave * 7 + LETTERS.indexOf(pitch.letter) - bottom) * 5;
}
function staffFor(score, midi, bar) {
  const material = score.bars[bar];
  const has = hand => material[hand].some(event => event.pitches.some(pitch => pitch.midi === midi));
  const left = has('left'), right = has('right') || score.allowed_pitches.some(pitch => pitch.midi === midi);
  return left !== right ? left ? 'left' : 'right' : midi < 60 ? 'left' : 'right';
}

// This is a live display buffer, separate from the unmodified MIDI recorder.
// Tails represent physical key holds. Pedal sustain is intentionally not inferred.
export class LiveInput {
  constructor(score) { this.score = score; this.notes = []; this.held = new Map(); }
  midi(data, port, position) {
    if (!position || data.length < 3) return false;
    const type = data[0] & 0xf0, channel = data[0] & 0x0f, pitch = data[1];
    const key = `${port}:${channel}:${pitch}`;
    if (type === 0x90 && data[2] > 0 && pitch < 128) {
      const previous = this.held.get(key);
      if (previous) { previous.end = Math.max(previous.start, position.absolute); previous.interrupted = true; }
      const note = {midi: pitch, port, channel, start: position.absolute, end: null,
        staff: staffFor(this.score, pitch, position.bar)};
      this.notes.push(note); this.held.set(key, note);
      // A busy controller cannot grow the live DOM or memory without bound.
      if (this.notes.length > 512) {
        const removed = this.notes.shift();
        const oldKey = `${removed.port}:${removed.channel}:${removed.midi}`;
        if (this.held.get(oldKey) === removed) this.held.delete(oldKey);
      }
      return true;
    } else if (type === 0x80 || (type === 0x90 && data[2] === 0)) {
      const note = this.held.get(key);
      if (note) { note.end = Math.max(note.start, position.absolute); this.held.delete(key); return true; }
    } else if (type === 0xb0 && (pitch === 120 || pitch === 123)) {
      this.release(position, note => note.port === port && note.channel === channel, false);
      return true;
    }
    return false;
  }
  release(position, matches = () => true, interrupted = true) {
    for (const [key, note] of this.held) if (matches(note)) {
      note.end = Math.max(note.start, position?.absolute ?? note.start);
      note.interrupted = interrupted; this.held.delete(key);
    }
  }
  prune(pass) {
    const first = pass * this.score.bars.length * 4;
    this.notes = this.notes.filter(note => note.end === null || note.end >= first);
  }
}

function ledger(parent, x, y, staff) {
  const top = TOP[staff], bottom = top + 40;
  for (let at = top - 10; at >= y; at -= 10) line(parent, x - 11, at, x + 11, at, 'score-ledger');
  for (let at = bottom + 10; at <= y; at += 10) line(parent, x - 11, at, x + 11, at, 'score-ledger');
}
function accidental(parent, pitch, x, y, key, live = false) {
  const signature = FLATS[key].includes(pitch.letter) ? -1 : 0;
  if (pitch.alter !== signature || (live && pitch.alter !== 0)) {
    symbol(parent, pitch.alter === -1 ? 'flat' : pitch.alter === 1 ? 'sharp' : 'natural', x - 24, y);
  }
}

export class ScoreView {
  constructor({root, status, previous, next, follow}) {
    Object.assign(this, {root, status, previous, next, follow});
    this.page = 0; this.pass = 0; this.playing = false;
    previous.addEventListener('click', () => this.turn(-1));
    next.addEventListener('click', () => this.turn(1));
  }
  setScore(score) {
    const identity = JSON.stringify(score);
    if (identity !== this.identity) {
      this.identity = identity; this.score = score; this.page = this.pass = 0;
      this.input = score ? new LiveInput(score) : null; this.position = null;
    }
    this.render(); // Language refresh keeps the live buffer and play position.
  }
  turn(direction) {
    if (!this.score) return;
    this.page = Math.max(0, Math.min(Math.ceil(this.score.bars.length / 4) - 1, this.page + direction));
    if (this.playing) this.follow.checked = false;
    this.render(); this.root.scrollLeft = 0;
  }
  begin() {
    this.input = this.score ? new LiveInput(this.score) : null;
    this.position = null; this.page = this.pass = 0; this.playing = true;
    this.render(); this.root.scrollLeft = 0;
  }
  pause(position) {
    this.input?.release(position || this.position);
    this.playing = false;
    this.frame(position || this.position);
    this.drawNotes(); // No later animation frame runs after a pause.
    if (this.cursor) this.cursor.setAttribute('visibility', 'hidden');
  }
  disconnect(port, position) {
    this.input?.release(position || this.position, note => port === undefined || note.port === port);
    this.drawNotes();
  }
  midi(data, port, position) {
    if (this.input?.midi(data, port, position)) this.drawNotes();
  }
  frame(position) {
    if (!this.score || !position) return;
    this.position = position;
    const page = Math.floor(position.bar / 4), passChanged = position.pass !== this.pass;
    if (passChanged) { this.pass = position.pass; this.input.prune(this.pass); }
    if (this.follow.checked && page !== this.page) { this.page = page; this.render(); }
    else if (passChanged) this.caption();
    const visible = this.playing && page === this.page;
    this.cursor.setAttribute('visibility', visible ? 'visible' : 'hidden');
    const x = noteX(position.bar, position.beat);
    this.cursor.setAttribute('transform', `translate(${x} 0)`);
    for (const node of this.root.querySelectorAll('.score-bar-highlight')) {
      node.setAttribute('visibility', visible && Number(node.dataset.bar) === position.bar ? 'visible' : 'hidden');
    }
    // Follow within the score's own scroll area, never scroll the whole page.
    if (visible && this.follow.checked && this.root.clientWidth > 0) {
      const pixel = x * this.svg.getBoundingClientRect().width / WIDTH;
      if (pixel < this.root.scrollLeft + 50 || pixel > this.root.scrollLeft + this.root.clientWidth - 50)
        this.root.scrollLeft = Math.max(0, pixel - this.root.clientWidth * .35);
    }
    if (passChanged || (this.input.held.size && (!this.lastDraw || performance.now() - this.lastDraw > 50))) this.drawNotes();
  }
  caption() {
    const count = this.score?.bars.length || 0;
    this.status.textContent = count ? tr`Pass ${this.pass + 1} · bars ${this.page * 4 + 1}–${Math.min(count, this.page * 4 + 4)}` : '';
    this.previous.disabled = !count || this.page === 0;
    this.next.disabled = !count || (this.page + 1) * 4 >= count;
    this.previous.hidden = this.next.hidden = count <= 4;
  }
  render() {
    this.root.replaceChildren(); this.caption();
    if (!this.score) {
      const note = document.createElement('p'); note.className = 'field-note';
      note.textContent = tr('A score is not available for these conditions. Follow the written instructions.');
      this.root.append(note); return;
    }
    const score = this.score;
    this.svg = svg('svg', {viewBox: `0 0 ${WIDTH} ${HEIGHT}`, role: 'img', class: 'practice-score',
      'aria-label': tr`Practice score in ${score.key}, bars ${this.page * 4 + 1}–${Math.min(score.bars.length, this.page * 4 + 4)}`});
    const canvas = this.svg;
    const first = this.page * 4, bars = score.bars.slice(first, first + 4);
    for (const [index] of bars.entries()) canvas.append(svg('rect', {x: START + index * BAR, y: 54,
      width: BAR, height: 221, rx: 6, class: 'score-bar-highlight', 'data-bar': first + index, visibility: 'hidden'}));
    for (const staff of ['right', 'left']) {
      const top = TOP[staff];
      canvas.append(svg('text', {x: 14, y: top - 28, class: 'score-hand'}, tr(staff === 'right' ? 'Right hand' : 'Left hand')));
      for (let row = 0; row < 5; row++) line(canvas, 33, top + row * 10, WIDTH - 20, top + row * 10, 'score-staff-line');
      symbol(canvas, staff === 'right' ? 'treble' : 'bass', 39, top + (staff === 'right' ? 30 : 10));
      for (const [i, letter] of FLATS[score.key].entries()) {
        const pitch = {letter, octave: staff === 'right' ? 4 : 2};
        if (letter === 'E') pitch.octave++;
        symbol(canvas, 'flat', 78 + i * 12, noteY(pitch, staff));
      }
      canvas.append(svg('text', {x: 116, y: top + 18, class: 'score-meter'}, '4'),
                    svg('text', {x: 116, y: top + 39, class: 'score-meter'}, '4'));
    }
    // Brace and barlines join the treble and bass staves into one grand staff.
    canvas.append(svg('path', {d: 'M26 89 C12 89 21 150 12 167 C21 184 12 245 26 245', class: 'score-brace'}));
    line(canvas, 33, TOP.right, 33, TOP.left + 40, 'score-bar-line');
    for (const [index, bar] of bars.entries()) {
      const at = first + index, x = START + index * BAR;
      canvas.append(svg('text', {x: x + 20, y: 25, class: 'score-bar-number'}, String(at + 1)),
                    svg('text', {x: x + 20, y: 49, class: 'score-chord'}, bar.chord));
      for (let beat = 0; beat < 4; beat++) {
        const bx = noteX(at, beat);
        line(canvas, bx, 275, bx, 280, 'score-beat-tick');
        canvas.append(svg('text', {x: bx, y: 298, class: 'score-beat-label'}, String(beat + 1)));
      }
      for (const staff of ['right', 'left']) for (const event of bar[staff]) this.drawEvent(canvas, event, staff, at);
      line(canvas, x + BAR, TOP.right, x + BAR, TOP.left + 40, 'score-bar-line');
    }
    this.liveLayer = svg('g', {class: 'score-live-layer', 'aria-hidden': 'true'}); canvas.append(this.liveLayer);
    this.cursor = svg('g', {class: 'score-cursor', visibility: 'hidden', 'aria-hidden': 'true'});
    line(this.cursor, 0, 60, 0, 270, 'score-cursor-line');
    this.cursor.append(svg('path', {d: 'M-5 56 L5 56 L0 63 Z'})); canvas.append(this.cursor);
    this.root.append(canvas);
    if (score.allowed_pitches.length) {
      const note = document.createElement('p'); note.className = 'score-improv-help';
      note.textContent = tr`Use ${score.allowed_pitches.map(p => p.name).join(' · ')}. Improvise with quarter notes and rests, then rest for two bars. Bass diamonds mark beat 1; hold length is not specified.`;
      this.root.append(note);
    }
    if (score.short_attacks) {
      const note = document.createElement('p'); note.className = 'score-improv-help';
      note.textContent = tr('Charleston: play short attacks on 1 and 2&. Eighth notes illustrate short playing; exact hold length is not an additional requirement.');
      this.root.append(note);
    }
    this.drawNotes();
  }
  drawEvent(canvas, event, staff, bar) {
    const x = noteX(bar, event.beat), top = TOP[staff];
    const group = svg('g', {class: 'score-target', 'data-hand': staff, 'data-bar': bar, 'data-beat': event.beat,
      'data-kind': event.kind, 'data-duration': event.duration ?? ''});
    canvas.append(group);
    if (event.kind === 'improv') {
      group.append(svg('text', {x: x + 32, y: top + 61, class: 'score-improv'}, tr('Improvise'))); return;
    }
    if (event.kind === 'rest') {
      if (event.duration === 4) group.append(svg('rect', {x: x + 53, y: top + 10, width: 14, height: 5, class: 'score-rest'}));
      else symbol(group, event.duration === .5 ? 'eighthRest' : 'quarterRest', x - 4, top + 20);
      return;
    }
    const ys = [];
    for (const pitch of event.pitches) {
      const y = noteY(pitch, staff); ys.push(y);
      const note = svg('g', {'data-midi': pitch.midi, class: 'score-target-note'});
      note.append(svg('title', {}, pitch.name));
      ledger(note, x, y, staff); accidental(note, pitch, x, y, this.score.key);
      if (event.kind === 'onset') note.append(svg('path', {d: `M${x} ${y - 5} l7 5 -7 5 -7 -5 Z`, class: 'score-onset'}));
      else note.append(svg('ellipse', {cx: x, cy: y, rx: event.duration === 4 ? 8 : 6, ry: 4.3,
        transform: `rotate(-18 ${x} ${y})`, class: event.duration === 4 ? 'score-whole' : 'score-notehead'}));
      group.append(note);
    }
    if (event.kind !== 'onset' && event.duration < 4) {
      const tip = Math.min(...ys) - 30;
      line(group, x + 5, Math.max(...ys), x + 5, tip, 'score-stem');
      if (event.duration === .5) symbol(group, 'eighthFlag', x + 5, tip);
    }
  }
  drawNotes() {
    if (!this.liveLayer || !this.input || !this.score) return;
    this.lastDraw = performance.now(); this.liveLayer.replaceChildren();
    const total = this.score.bars.length * 4, passStart = this.pass * total;
    const firstBar = this.page * 4, pageStart = passStart + firstBar * 4, pageEnd = Math.min(pageStart + 16, passStart + total);
    for (const note of this.input.notes) {
      const end = Math.max(note.start, note.end ?? this.position?.absolute ?? note.start);
      if (note.start >= pageEnd || end < pageStart || (end === pageStart && note.start < pageStart)) continue;
      const bar = Math.floor(note.start / 4) % this.score.bars.length;
      const candidates = this.score.bars[bar][note.staff].flatMap(e => e.pitches).concat(this.score.allowed_pitches);
      const pitch = candidates.find(p => p.midi === note.midi) || spell(note.midi, this.score.key);
      const rawY = noteY(pitch, note.staff), min = TOP[note.staff] - 35, max = TOP[note.staff] + 85;
      const y = Math.max(min, Math.min(max, rawY));
      const group = svg('g', {class: 'score-live-note', 'data-midi': note.midi, 'data-start': note.start,
        'data-end': note.end ?? '', 'data-hand': note.staff});
      group.append(svg('title', {}, pitch.name));
      for (let at = firstBar; at < Math.min(firstBar + 4, this.score.bars.length); at++) {
        const start = passStart + at * 4, from = Math.max(note.start, start), to = Math.min(end, start + 4);
        if (to <= from) continue;
        line(group, noteX(at, from - start), y, noteX(at, to - start), y,
          note.interrupted ? 'score-hold interrupted' : 'score-hold');
      }
      if (note.start >= pageStart) {
        const x = noteX(bar, note.start % 4);
        if (y !== rawY) {
          group.append(svg('text', {x, y, class: 'score-edge-note'}, `${rawY < min ? '↑' : '↓'}${pitch.name}`));
        } else {
          ledger(group, x, y, note.staff); accidental(group, pitch, x, y, this.score.key, true);
          group.append(svg('ellipse', {cx: x, cy: y, rx: 5, ry: 3.7, class: 'score-input-head'}));
        }
      }
      this.liveLayer.append(group);
    }
  }
}
