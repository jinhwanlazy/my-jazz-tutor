// Pinned abcjs engraving adapter. Internal library objects do not escape here.
// Timing comes from our audio clock; this adapter maps quarter beats to the score.
export function interpolate(anchors, beat) {
  if (beat <= anchors[0][0]) return anchors[0][1];
  for (let i = 1; i < anchors.length; i++) {
    const [end, x2] = anchors[i], [start, x1] = anchors[i - 1];
    if (beat <= end) return x1 + (x2 - x1) * (beat - start) / (end - start);
  }
  return anchors.at(-1)[1];
}

export class ABCLayout {
  constructor(root, score, barsPerLine = 4) {
    if (!globalThis.ABCJS) throw new Error('The score library could not be loaded. Reload the page.');
    const breaks = Array.from({length: Math.floor((score.bars.length - 1) / barsPerLine)},
      (_, i) => (i + 1) * barsPerLine - 1);
    const tune = globalThis.ABCJS.renderAbc(root, score.abc, {
      add_classes: true, lineBreaks: [breaks],
      staffwidth: Math.max(250, (root.clientWidth || 900) / 1.2 - 40),
      paddingtop: 15, paddingbottom: 30, paddingleft: 20, paddingright: 20,
      foregroundColor: '#364b40',
      afterParsing: tune => { tune.metaText = {}; tune.formatting.stretchlast = true; }
    })[0];
    // Our viewport sizes the SVG using attributes, compatible with the app's CSP.
    for (const property of ['overflow', 'width', 'height']) root.style.removeProperty(property);
    if (tune.warnings?.length) throw new Error('The score could not be rendered without warnings.');
    const groups = tune.engraver.staffgroups;
    if (groups.length !== breaks.length + 1 || groups.some(group => group.staffs.length !== 2)) {
      throw new Error('The score must use two staves on each line.');
    }
    this.svg = root.querySelector('svg');
    this.width = Number(this.svg.getAttribute('width'));
    this.height = Number(this.svg.getAttribute('height'));
    this.svg.setAttribute('viewBox', `0 0 ${this.width} ${this.height}`);
    this.svg.setAttribute('class', 'practice-score abc-score');
    this.svg.setAttribute('role', 'img');
    const byChar = new Map(score.events.map(e => [e.start_char, e]));
    this.systems = groups.map((group, index) => {
      const start = index * barsPerLine * score.beats_per_bar;
      const end = Math.min(score.bars.length, (index + 1) * barsPerLine) * score.beats_per_bar;
      const positions = new Map();
      let endX = 0;
      for (const voice of group.voices) for (const item of voice.children) {
        if (item.type === 'bar') endX = Math.max(endX, item.x);
        const event = byChar.get(item.abcelem?.startChar);
        if (item.abcelem?.el_type !== 'note' || !event) continue;
        const beat = event.bar * score.beats_per_bar + event.beat;
        positions.set(beat, Math.min(positions.get(beat) ?? Infinity, item.x + 4));
      }
      positions.set(end, endX);
      const anchors = [...positions].sort((a, b) => a[0] - b[0]);
      if (anchors[0]?.[0] !== start || anchors.some((p, i) => i && p[1] <= anchors[i - 1][1])) {
        throw new Error('A score line does not have a continuous time axis.');
      }
      return {index, start, end, anchors, staffs: {right: group.staffs[0], left: group.staffs[1]}};
    });
  }
  system(beat) { return this.systems.find(system => beat < system.end) || this.systems.at(-1); }
  x(beat, system = this.system(beat)) { return interpolate(system.anchors, beat); }
  y(pitch, hand, system = this.systems[0]) {
    const bottom = hand === 'right' ? 30 : 18; // E4 / G2, in diatonic steps.
    const staff = system.staffs[hand];
    const step = (staff.bottomLine - staff.topLine) / 8;
    return staff.bottomLine - (pitch.octave * 7 + 'CDEFGAB'.indexOf(pitch.letter) - bottom) * step;
  }
  bounds(hand, system = this.systems[0]) {
    const staff = system.staffs[hand]; return {top: staff.topLine, bottom: staff.bottomLine};
  }
}
