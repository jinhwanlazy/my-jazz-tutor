// A bounded history of scheduled audio beats, including tempo changes and loops.
export class BeatTimeline {
  constructor(beatsPerBar, barCount) {
    this.beatsPerBar = beatsPerBar;
    this.barCount = barCount;
    this.beats = [];
  }
  add(time, index, bpm) {
    this.beats.push({time, index, bpm});
    if (this.beats.length > 256) this.beats.shift();
  }
  position(time) {
    if (!Number.isFinite(time)) return null;
    const beat = this.beats.findLast(item => item.time <= time);
    if (!beat) return null; // Includes the lead-in before the first click.
    // Do not extrapolate indefinitely after an audio interruption.
    const fraction = (time - beat.time) * beat.bpm / 60;
    if (fraction > 1.25) return null;
    const absolute = beat.index + fraction;
    const total = this.beatsPerBar * this.barCount;
    return {absolute, pass: Math.floor(absolute / total),
      bar: Math.floor(absolute / this.beatsPerBar) % this.barCount,
      beat: absolute % this.beatsPerBar};
  }
}

// MIDI event.timeStamp and getOutputTimestamp().performanceTime share the same
// origin. Prefer the output-device clock, with a currentTime fallback.
export function audioTimeAt(context, at, now = performance.now()) {
  const stamp = context.getOutputTimestamp?.();
  if (stamp && stamp.contextTime > 0 && stamp.performanceTime > 0) {
    return stamp.contextTime + (at - stamp.performanceTime) / 1000;
  }
  return context.currentTime + (at - now) / 1000;
}
