import {tr} from './i18n.mjs';

const NS = 'http://www.w3.org/2000/svg';
const HEIGHT = 320, START = 144, BAR = 208, TOP = {right: 90, left: 205};
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
// One time scale for targets, the cursor and live input, including bar boundaries.
export function scoreX(beat) { return START + 20 + beat * BAR / 4; }
function noteX(bar, beat) { return scoreX(bar * 4 + beat); }

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
  constructor({root, status, follow, help}) {
    Object.assign(this, {root, status, follow, help});
    this.pass = 0; this.playing = false;
  }
  setScore(score) {
    const identity = JSON.stringify(score);
    if (identity !== this.identity) {
      this.identity = identity; this.score = score; this.pass = 0;
      this.input = score ? new LiveInput(score) : null; this.position = null;
      this.root.scrollLeft = 0;
    }
    this.render(); // Language refresh keeps the live buffer and play position.
  }
  begin() {
    this.input = this.score ? new LiveInput(this.score) : null;
    this.position = null; this.pass = 0; this.playing = true;
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
    const passChanged = position.pass !== this.pass;
    if (passChanged) { this.pass = position.pass; this.input.prune(this.pass); this.caption(); }
    this.cursor.setAttribute('visibility', this.playing ? 'visible' : 'hidden');
    const x = noteX(position.bar, position.beat);
    this.cursor.setAttribute('transform', `translate(${x} 0)`);
    // Follow every frame, without threshold jumps or animation lag behind audio.
    // Clamping keeps a fitting score still; only a loop resets to the beginning.
    if (this.playing && this.follow.checked && this.root.clientWidth > 0) {
      const pixel = x * this.svg.getBoundingClientRect().width / this.width;
      const limit = Math.max(0, this.root.scrollWidth - this.root.clientWidth);
      this.root.scrollLeft = Math.min(limit, Math.max(0, pixel - this.root.clientWidth * .55));
    }
    if (passChanged || (this.input.held.size && (!this.lastDraw || performance.now() - this.lastDraw > 50))) this.drawNotes();
  }
  caption() {
    const count = this.score?.bars.length || 0;
    this.status.textContent = count ? tr`Pass ${this.pass + 1}` : '';
  }
  render() {
    const scroll = this.root.scrollLeft;
    this.root.replaceChildren(); this.help?.replaceChildren(); this.caption();
    this.svg = this.cursor = this.liveLayer = null;
    if (!this.score) {
      const note = document.createElement('p'); note.className = 'field-note';
      note.textContent = tr('A score is not available for these conditions. Follow the written instructions.');
      this.root.append(note); return;
    }
    const score = this.score;
    this.width = scoreX(score.bars.length * 4) + 24;
    const scale = this.width / (scoreX(16) + 24);
    this.svg = svg('svg', {viewBox: `0 0 ${this.width} ${HEIGHT}`, role: 'img', class: 'practice-score',
      style: `width: ${Math.max(1, scale) * 100}%; min-width: ${scale * 760}px`,
      'aria-label': tr`Practice score in ${score.key}, ${score.bars.length} bars`});
    const canvas = this.svg;
    const bars = score.bars;
    for (const staff of ['right', 'left']) {
      const top = TOP[staff];
      for (let row = 0; row < 5; row++) line(canvas, 33, top + row * 10, this.width - 24, top + row * 10, 'score-staff-line');
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
    for (const [at, bar] of bars.entries()) {
      const x = noteX(at, 0);
      canvas.append(svg('text', {x, y: 49, class: 'score-chord'}, bar.chord));
      for (let beat = 0; beat < 4; beat++) {
        const bx = noteX(at, beat);
        line(canvas, bx, 275, bx, 280, 'score-beat-tick');
        canvas.append(svg('text', {x: bx, y: 298, class: 'score-beat-label'}, String(beat + 1)));
      }
      for (const staff of ['right', 'left']) for (const event of bar[staff]) this.drawEvent(canvas, event, staff, at);
      const end = x + BAR - (at === bars.length - 1 ? 0 : 20);
      line(canvas, end, TOP.right, end, TOP.left + 40, 'score-bar-line');
    }
    this.liveLayer = svg('g', {class: 'score-live-layer', 'aria-hidden': 'true'}); canvas.append(this.liveLayer);
    this.cursor = svg('g', {class: 'score-cursor', visibility: 'hidden', 'aria-hidden': 'true'});
    line(this.cursor, 0, 60, 0, 270, 'score-cursor-line');
    this.cursor.append(svg('path', {d: 'M-5 56 L5 56 L0 63 Z'})); canvas.append(this.cursor);
    this.root.append(canvas);
    if (score.allowed_pitches.length) {
      const note = document.createElement('p'); note.className = 'score-improv-help';
      note.textContent = tr`Use ${score.allowed_pitches.map(p => p.name).join(' · ')}. Improvise with quarter notes and rests, then rest for two bars. Bass diamonds mark beat 1; hold length is not specified.`;
      (this.help || this.root).append(note);
    }
    if (score.short_attacks) {
      const note = document.createElement('p'); note.className = 'score-improv-help';
      note.textContent = tr('Charleston: play short attacks on 1 and 2&. Eighth notes illustrate short playing; exact hold length is not an additional requirement.');
      (this.help || this.root).append(note);
    }
    this.drawNotes();
    this.root.scrollLeft = scroll;
    if (this.position) this.frame(this.position);
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
    const passEnd = passStart + total;
    for (const note of this.input.notes) {
      const end = Math.max(note.start, note.end ?? this.position?.absolute ?? note.start);
      if (note.start >= passEnd || end < passStart || (end === passStart && note.start < passStart)) continue;
      const bar = Math.floor(note.start / 4) % this.score.bars.length;
      const candidates = this.score.bars[bar][note.staff].flatMap(e => e.pitches).concat(this.score.allowed_pitches);
      const pitch = candidates.find(p => p.midi === note.midi) || spell(note.midi, this.score.key);
      const rawY = noteY(pitch, note.staff), min = TOP[note.staff] - 35, max = TOP[note.staff] + 85;
      const y = Math.max(min, Math.min(max, rawY));
      const group = svg('g', {class: 'score-live-note', 'data-midi': note.midi, 'data-start': note.start,
        'data-end': note.end ?? '', 'data-hand': note.staff});
      group.append(svg('title', {}, pitch.name));
      const from = Math.max(note.start, passStart), to = Math.min(end, passEnd);
      if (to > from) {
        line(group, scoreX(from - passStart), y, scoreX(to - passStart), y,
          note.interrupted ? 'score-hold interrupted' : 'score-hold');
      }
      if (note.start >= passStart) {
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
