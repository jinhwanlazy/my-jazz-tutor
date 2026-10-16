// One audio clock drives the click, chord pad, and beat display.
export class Transport {
  constructor({onBeat = () => {}, onEvent = () => {}, onInterrupt = () => {}} = {}) {
    Object.assign(this, {onBeat, onEvent, onInterrupt});
    this.bpm = this.requestedBpm = 60;
    this.click = true;
    this.padEnabled = false;
    this.clickVolume = 0.35;
    this.padVolume = 0.18;
    this.playing = false;
    this.voices = new Set();
    this.padVoices = [];
    this.queue = [];
  }
  async unlock() {
    if (!this.context) {
      const Audio = globalThis.AudioContext || globalThis.webkitAudioContext;
      if (!Audio) throw new Error('Web Audio is not available in this browser.');
      this.context = new Audio({latencyHint: 'interactive'});
      this.clickBus = this.context.createGain();
      this.padBus = this.context.createGain();
      this.clickBus.connect(this.context.destination);
      this.padBus.connect(this.context.destination);
      this.context.onstatechange = () => {
        if (this.playing && this.context.state !== 'running') {
          this.pause();
          this.onInterrupt('Playback paused because the browser interrupted audio.');
        }
      };
    }
    await this.context.resume();
    if (this.context.state !== 'running') throw new Error('Could not start audio. Try starting again.');
  }
  start(playback, bpm) {
    if (this.playing) return;
    this.playback = playback || {beats_per_bar: 4, bars: []};
    this.bpm = this.requestedBpm = bpm;
    this.beatIndex = 0;
    this.nextTime = this.context.currentTime + 0.08;
    this.queue = [];
    this.playing = true;
    this.refreshPad = true;
    this.schedule();
    this.interval = setInterval(() => this.schedule(), 25);
    const draw = () => {
      this.flush();
      if (this.playing) this.animation = requestAnimationFrame(draw);
    };
    draw();
  }
  schedule() {
    if (!this.playing) return;
    // A long background stall is a recorded interruption, never a burst of late clicks.
    if (this.nextTime < this.context.currentTime - 0.15) {
      this.pause();
      this.onInterrupt('Playback paused after a timing delay. Try starting again.');
      return;
    }
    while (this.nextTime < this.context.currentTime + 0.1) {
      const changed = this.bpm !== this.requestedBpm;
      this.bpm = this.requestedBpm;
      const beats = this.playback.beats_per_bar;
      const bar = Math.floor(this.beatIndex / beats) % Math.max(1, this.playback.bars.length);
      const beat = this.beatIndex % beats;
      if (this.click) this.tick(this.nextTime, beat === 0);
      if (this.padEnabled && (beat === 0 || changed || this.refreshPad)) {
        this.chord(this.nextTime, this.playback.bars[bar]?.notes || []);
        this.refreshPad = false;
      }
      this.queue.push({time: this.nextTime, bar, beat, bpm: this.bpm, changed,
        chord: this.playback.bars[bar]?.chord || ''});
      this.nextTime += 60 / this.bpm;
      this.beatIndex += 1;
    }
  }
  flush() {
    if (!this.context) return;
    while (this.queue.length && this.queue[0].time <= this.context.currentTime) {
      const item = this.queue.shift();
      const at = performance.now() + (item.time - this.context.currentTime) * 1000;
      if (item.changed) this.onEvent('tempo', {bpm: item.bpm}, at);
      this.onBeat(item);
    }
  }
  voice(oscillator, gain, time) {
    oscillator.connect(gain);
    this.voices.add(oscillator);
    oscillator.onended = () => { this.voices.delete(oscillator); oscillator.disconnect(); gain.disconnect(); };
    oscillator.start(time);
  }
  tick(time, accent) {
    const osc = this.context.createOscillator(), gain = this.context.createGain();
    osc.frequency.value = accent ? 1320 : 880;
    gain.gain.setValueAtTime(0, time);
    gain.gain.linearRampToValueAtTime(0.35, time + 0.002);
    gain.gain.exponentialRampToValueAtTime(0.0001, time + 0.045);
    this.clickBus.gain.value = this.clickVolume;
    gain.connect(this.clickBus);
    this.voice(osc, gain, time);
    osc.stop(time + 0.05);
  }
  releasePad(time) {
    for (const {osc, gain} of this.padVoices) {
      gain.gain.cancelAndHoldAtTime(time);
      gain.gain.linearRampToValueAtTime(0, time + 0.25);
      try { osc.stop(time + 0.26); } catch {}
    }
    this.padVoices = [];
  }
  chord(time, notes) {
    this.releasePad(time);
    this.padBus.gain.value = this.padVolume;
    for (const note of notes) {
      for (const detune of [-3, 3]) {
        const osc = this.context.createOscillator(), gain = this.context.createGain();
        osc.type = 'sine';
        osc.frequency.value = 440 * 2 ** ((note - 69) / 12);
        osc.detune.value = detune;
        gain.gain.setValueAtTime(0, time);
        gain.gain.linearRampToValueAtTime(0.32 / Math.max(notes.length, 1), time + 0.3);
        gain.connect(this.padBus);
        this.voice(osc, gain, time);
        this.padVoices.push({osc, gain});
      }
    }
  }
  setTempo(bpm) { this.requestedBpm = bpm; }
  setPad(enabled) {
    this.padEnabled = enabled;
    this.refreshPad = true;
    if (!enabled && this.context) this.releasePad(this.context.currentTime);
  }
  setVolumes(click, pad) {
    this.clickVolume = click;
    this.padVolume = pad;
    if (this.context) {
      this.clickBus.gain.setTargetAtTime(click, this.context.currentTime, 0.03);
      this.padBus.gain.setTargetAtTime(pad, this.context.currentTime, 0.05);
    }
  }
  pause() {
    if (!this.playing) return;
    this.flush();
    this.playing = false;
    clearInterval(this.interval);
    cancelAnimationFrame(this.animation);
    this.queue = [];
    this.padVoices = [];
    for (const osc of this.voices) { try { osc.stop(this.context.currentTime); } catch {} }
    this.voices.clear();
  }
}
