// Pinned abcjs engraving adapter. Internal library objects do not escape here.
// Timing comes from our audio clock; this adapter maps quarter beats to the score.
const GRID_PADDING = 4, NOTE_CENTER = 4;

function prepareTimeGrid(tune, width) {
  const lines = tune.lines.filter(line => line.staffGroup).map(line =>
    line.staffGroup.voices.map(voice => {
      const first = voice.children.findIndex(item => item.duration > 0);
      const notes = voice.children.filter(item => item.duration > 0);
      if (first < 0) throw new Error('A score voice has no timed events.');
      // Secondary voices can omit the clef/key prefix. An invisible engraving
      // spacer gives them the same start as the other voices; it is not music.
      if (first === 0) {
        const spacer = new notes[0].constructor({el_type: 'staff-extra'}, 0, 0, 'staff-extra', 0);
        spacer.invisible = true; voice.children.unshift(spacer);
      }
      const prefix = voice.children.slice(0, Math.max(1, first));
      return {prefix, notes, prefixWidth: prefix.reduce((n, item) => n + item.w + item.minspacing, 0),
        duration: notes.reduce((n, item) => n + item.duration, 0)};
    }));
  const voices = lines.flat(), notes = voices.flatMap(voice => voice.notes);
  const accidentalSpace = Math.max(0, ...notes.map(note => -note.extraw));
  const header = Math.max(...voices.map(voice => voice.prefixWidth)) + accidentalSpace + GRID_PADDING;
  const duration = Math.max(...voices.map(voice => voice.duration));
  const unit = Math.max((width - header) / duration,
    ...notes.map(note => (note.w + accidentalSpace + GRID_PADDING) / note.duration));
  for (const line of lines) {
    const lineDuration = Math.max(...line.map(voice => voice.duration));
    for (const voice of line) {
      voice.prefix.at(-1).minspacing += header - voice.prefixWidth;
      for (const note of voice.notes) {
        // abcjs normally shifts noteheads to make room for accidentals. Reserve
        // that room in every time slot instead, keeping all onsets aligned.
        // Its grid subtracts the fixed header from the supplied width; account
        // for that here so every line, including a partial last line, has the
        // same points per beat. Glyphs, beams and ties are then drawn normally.
        note.extraw = 0;
        note.w = note.duration * (unit + header / lineDuration) - GRID_PADDING;
      }
    }
  }
  return unit / 4; // abcjs durations are whole notes; our clock uses quarters.
}

function engrave(root, score, options) {
  const api = globalThis.ABCJS;
  if (!api?.test?.EngraverController) throw new Error('The score library could not be loaded. Reload the page.');
  const tune = api.parseOnly(score.abc, options)[0];
  if (tune.warnings?.length) throw new Error('The score could not be rendered without warnings.');
  tune.metaText = {};
  root.replaceChildren();
  // Keep the pinned engraving hook inside this adapter. Adjust spacing before
  // layout draws stems/beams/ties, rather than moving finished SVG glyphs.
  const controller = new api.test.EngraverController(root, options);
  const construct = controller.constructTuneElements.bind(controller);
  let pointsPerBeat;
  controller.constructTuneElements = value => {
    construct(value); pointsPerBeat = prepareTimeGrid(value, controller.width);
  };
  controller.engraveABC(tune);
  return {groups: controller.staffgroups, pointsPerBeat};
}

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
    const breaks = Array.from({length: Math.floor((score.bars.length - 1) / barsPerLine)},
      (_, i) => (i + 1) * barsPerLine - 1);
    const {groups, pointsPerBeat} = engrave(root, score, {
      add_classes: true, lineBreaks: [breaks],
      staffwidth: Math.max(250, (root.clientWidth || 900) / 1.2 - 40),
      timeBasedLayout: {minPadding: GRID_PADDING, align: 'left'},
      paddingtop: 15, paddingbottom: 30, paddingleft: 20, paddingright: 20,
      foregroundColor: '#364b40'
    });
    // Our viewport sizes the SVG using attributes, compatible with the app's CSP.
    for (const property of ['overflow', 'width', 'height']) root.style.removeProperty(property);
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
      const origin = group.gridStart + GRID_PADDING / 2 + NOTE_CENTER;
      const anchors = [[start, origin], [end, origin + (end - start) * pointsPerBeat]];
      for (const voice of group.voices) for (const item of voice.children) {
        const event = byChar.get(item.abcelem?.startChar);
        if (item.abcelem?.el_type !== 'note' || !event) continue;
        const beat = event.bar * score.beats_per_bar + event.beat;
        if (Math.abs(item.x + NOTE_CENTER - interpolate(anchors, beat)) > 1e-6) {
          throw new Error('The score could not be aligned to the playback clock.');
        }
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
