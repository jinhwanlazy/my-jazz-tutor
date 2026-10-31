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
  constructor(root, score) {
    if (!globalThis.ABCJS) throw new Error('The score library could not be loaded. Reload the page.');
    const tune = globalThis.ABCJS.renderAbc(root, score.abc, {
      add_classes: true, lineBreaks: [[]], staffwidth: Math.max(550, score.bars.length * 180),
      paddingtop: 15, paddingbottom: 30, paddingleft: 20, paddingright: 20,
      foregroundColor: '#364b40',
      afterParsing: tune => { tune.metaText = {}; tune.formatting.stretchlast = true; }
    })[0];
    // abcjs sizes its wrapper for a static engraving. Our viewport owns scrolling
    // and the SVG is scaled with width/height attributes below.
    for (const property of ['overflow', 'width', 'height']) root.style.removeProperty(property);
    if (tune.warnings?.length) throw new Error('The score could not be rendered without warnings.');
    const groups = tune.engraver.staffgroups;
    if (groups.length !== 1 || groups[0].staffs.length !== 2) throw new Error('The score must use one continuous grand staff.');
    const group = groups[0];
    this.staffs = {right: group.staffs[0], left: group.staffs[1]};
    this.svg = root.querySelector('svg');
    this.width = Number(this.svg.getAttribute('width'));
    this.height = Number(this.svg.getAttribute('height'));
    this.svg.setAttribute('viewBox', `0 0 ${this.width} ${this.height}`);
    this.svg.setAttribute('class', 'practice-score abc-score');
    this.svg.setAttribute('role', 'img');
    const byChar = new Map(score.events.map(e => [e.start_char, e]));
    const positions = new Map();
    let end = 0;
    for (const voice of group.voices) for (const item of voice.children) {
      if (item.type === 'bar') end = Math.max(end, item.x);
      const event = byChar.get(item.abcelem?.startChar);
      if (item.abcelem?.el_type !== 'note' || !event) continue;
      const beat = event.bar * score.beats_per_bar + event.beat;
      positions.set(beat, Math.min(positions.get(beat) ?? Infinity, item.x + 4));
    }
    positions.set(score.bars.length * score.beats_per_bar, end);
    this.anchors = [...positions].sort((a, b) => a[0] - b[0]);
    if (this.anchors[0]?.[0] !== 0 || this.anchors.some((p, i) => i && p[1] <= this.anchors[i - 1][1])) {
      throw new Error('The rendered score does not have a continuous time axis.');
    }
  }
  x(beat) { return interpolate(this.anchors, beat); }
  y(pitch, hand) {
    const bottom = hand === 'right' ? 30 : 18; // E4 / G2, in diatonic steps.
    const step = (this.staffs[hand].bottomLine - this.staffs[hand].topLine) / 8;
    return this.staffs[hand].bottomLine - (pitch.octave * 7 + 'CDEFGAB'.indexOf(pitch.letter) - bottom) * step;
  }
  bounds(hand) { const staff = this.staffs[hand]; return {top: staff.topLine, bottom: staff.bottomLine}; }
}
