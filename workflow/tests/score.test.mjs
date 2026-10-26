import assert from 'node:assert/strict';
import test from 'node:test';
import {BeatTimeline, audioTimeAt} from '../timeline.mjs';
import {LiveInput, noteY, scoreX, spell} from '../score.mjs';

const event = pitches => ({pitches: pitches.map(midi => spell(midi))});
const score = {bars: Array.from({length: 4}, () => ({left: [event([38])], right: [event([53, 60])]})), allowed_pitches: []};
const at = absolute => ({absolute, bar: Math.floor(absolute / 4) % 4, pass: Math.floor(absolute / 16), beat: absolute % 4});

test('score spacing stays continuous at every bar, including the former page boundary', () => {
  const step = scoreX(.01) - scoreX(0);
  for (const boundary of [4, 8, 12, 16, 20, 24, 28, 32]) {
    assert.ok(Math.abs(scoreX(boundary) - scoreX(boundary - .01) - step) < 1e-9);
    assert.ok(Math.abs(scoreX(boundary + .01) - scoreX(boundary) - step) < 1e-9);
  }
  assert.ok(scoreX(32) > scoreX(16));
});

test('beat position uses applied tempo, including offbeats and loop boundaries', () => {
  const clock = new BeatTimeline(4, 4);
  clock.add(10, 0, 60); clock.add(11, 1, 120); clock.add(11.5, 2, 120);
  assert.equal(clock.position(9.99), null);
  assert.equal(clock.position(10.5).absolute, .5);
  assert.equal(clock.position(11.25).absolute, 1.5);
  assert.equal(clock.position(11.75).absolute, 2.5);
  clock.add(18, 16, 60);
  assert.deepEqual(clock.position(18.125), {absolute: 16.125, pass: 1, bar: 0, beat: .125});
  assert.equal(clock.position(22), null);
});

test('MIDI timestamps use output-device timing when available and a safe fallback', () => {
  const context = {currentTime: 10.2, getOutputTimestamp: () => ({contextTime: 10, performanceTime: 5000})};
  assert.equal(audioTimeAt(context, 5250, 5300), 10.25);
  assert.equal(audioTimeAt({currentTime: 10}, 5250, 5300), 9.95);
  assert.equal(audioTimeAt({currentTime: 10, getOutputTimestamp: () => ({contextTime: 0, performanceTime: 0})}, 5250, 5300), 9.95);
});

test('new playback has its own origin and beat history stays bounded', () => {
  const clock = new BeatTimeline(4, 8);
  for (let i = 0; i < 1000; i++) clock.add(i, i, 60);
  assert.equal(clock.beats.length, 256);
  assert.equal(clock.position(0), null);
  assert.equal(clock.position(999.5).absolute, 999.5);
  const restarted = new BeatTimeline(4, 8); restarted.add(1100, 0, 80);
  assert.equal(restarted.position(1100).absolute, 0);
});

test('key holds preserve fractional onsets, assigned low right-hand notes, and device identity', () => {
  const input = new LiveInput(score);
  input.midi([0x90, 53, 100], 'a', at(.12));
  input.midi([0x90, 53, 90], 'b', at(.15));
  input.midi([0x91, 53, 80], 'a', at(.2));
  input.midi([0x90, 38, 100], 'a', at(.22));
  input.midi([0x80, 53, 0], 'a', at(.9));
  assert.deepEqual(input.notes.map(n => n.staff), ['right', 'right', 'right', 'left']);
  assert.equal(input.notes[0].start, .12);
  assert.equal(input.notes[0].end, .9);
  assert.equal(input.notes[1].end, null);
  assert.equal(input.notes[2].end, null);
  input.midi([0x91, 53, 0], 'a', at(1.2));
  assert.equal(input.notes[2].end, 1.2);
});

test('pedal does not extend key-hold tails; pause/disconnect is explicitly incomplete', () => {
  const input = new LiveInput(score);
  input.midi([0x90, 60, 100], 'a', at(1));
  assert.equal(input.midi([0xb0, 64, 127], 'a', at(1.5)), false);
  assert.equal(input.midi([0xf8], 'a', at(1.6)), false);
  input.midi([0x80, 60, 0], 'a', at(2));
  assert.equal(input.notes[0].end, 2);
  input.midi([0x90, 38, 100], 'b', at(3));
  input.release(at(3.7), n => n.port === 'b');
  assert.equal(input.notes[1].end, 3.7);
  assert.equal(input.notes[1].interrupted, true);
  input.midi([0x90, 64, 100], 'a', null); // Paused input has no musical position.
  assert.equal(input.notes.length, 2);
});

test('held notes cross loops; ended notes and busy input do not accumulate forever', () => {
  const input = new LiveInput(score);
  input.midi([0x90, 60, 100], 'a', at(15.9));
  input.prune(1);
  assert.equal(input.notes.length, 1);
  input.midi([0x80, 60, 0], 'a', at(16.5));
  input.prune(2);
  assert.equal(input.notes.length, 0);
  for (let i = 0; i < 1000; i++) input.midi([0x90, 60, 100], 'a', at(i / 100));
  assert.equal(input.notes.length, 512);
  assert.equal(input.held.size, 1);
  input.midi([0xb0, 123, 0], 'a', at(12));
  assert.equal(input.held.size, 0);
});

test('staff positions use diatonic steps, preserve flats, and place middle C on its ledger line', () => {
  assert.equal(noteY(spell(60), 'right'), 140);
  assert.equal(noteY(spell(60), 'left'), 195);
  assert.equal(noteY(spell(70, 'F'), 'right'), noteY(spell(71, 'F'), 'right'));
  assert.equal(spell(70, 'F').name, 'Bb4');
  assert.equal(spell(63, 'Bb').name, 'Eb4');
  assert.equal(spell(61).name, 'C#4');
});
