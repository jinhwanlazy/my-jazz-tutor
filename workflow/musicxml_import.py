"""Conservative MusicXML/MXL bridge into jazz-abc-1, not a general engraver.

Only an explicitly selected, complete piano excerpt is converted. Unsupported
musical semantics fail closed. XML is an import intermediate; ABC is the saved
score. Structural equivalence does not certify an OMR result against its image.
"""
from fractions import Fraction as F
from io import BytesIO
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile, BadZipFile

from abc_score import parse_score, DECORATIONS

LIMIT = 8_000_000
VERSION = 'musicxml-subset-2'
MAJOR = ['Cb', 'Gb', 'Db', 'Ab', 'Eb', 'Bb', 'F', 'C', 'G', 'D', 'A', 'E', 'B', 'F#', 'C#']
MINOR = ['Abm', 'Ebm', 'Bbm', 'Fm', 'Cm', 'Gm', 'Dm', 'Am', 'Em', 'Bm', 'F#m', 'C#m', 'G#m', 'D#m', 'A#m']
LENGTHS = {'whole': F(4), 'half': F(2), 'quarter': F(1), 'eighth': F(1, 2), '16th': F(1, 4)}
KINDS = {'major': '', 'minor': 'm', 'dominant': '7', 'major-seventh': 'maj7', 'minor-seventh': 'm7',
         'diminished': 'dim', 'diminished-seventh': 'dim7', 'half-diminished': 'm7b5', 'augmented': '+',
         'major-sixth': '6', 'minor-sixth': 'm6', 'suspended-fourth': 'sus4', 'suspended-second': 'sus2'}
WRITTEN_ACCIDENTALS = {'natural': 0, 'sharp': 1, 'flat': -1, 'double-sharp': 2, 'sharp-sharp': 2, 'flat-flat': -2}
PITCH_ALTERATIONS = {None: 0, 'b': -1, 'bb': -2, '#': 1, '##': 2}


def need(condition, message):
    if not condition:
        raise ValueError('MusicXML: ' + message)


def xml(data):
    need(0 < len(data) <= LIMIT, 'input exceeds 8 MB')
    # ElementTree never fetches external DTDs; forbid internal entities/subsets.
    # UTF-8 only also prevents encoded declarations from evading this check.
    text = data.decode('utf-8-sig')
    need('<!ENTITY' not in text.upper() and not re.search(r'<!DOCTYPE[^>]*\[', text, re.I), 'entities/internal DTDs are unsupported')
    try:
        return ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError('MusicXML: malformed XML') from exc


def read_xml(data):
    if not data.startswith(b'PK'):
        return xml(data)
    try:
        with ZipFile(BytesIO(data)) as archive:
            need(len(archive.infolist()) <= 100 and sum(i.file_size for i in archive.infolist()) <= LIMIT, 'MXL expands beyond 8 MB')
            container = xml(archive.read('META-INF/container.xml'))
            roots = [n for n in container.iter() if n.tag.split('}')[-1] == 'rootfile']
            need(bool(roots), 'MXL has no rootfile')
            name = roots[0].get('full-path', '')
            need(name and not name.startswith('/') and '..' not in name.split('/'), 'invalid MXL root path')
            return xml(archive.read(name))
    except (BadZipFile, KeyError) as exc:
        raise ValueError('MusicXML: invalid MXL container') from exc


def children(node, allowed, where):
    unknown = {n.tag for n in node} - set(allowed.split())
    need(not unknown, f'unsupported {where}: {", ".join(sorted(unknown))}')


def integer(node, path, default=None):
    value = node.findtext(path, default)
    need(value is not None and re.fullmatch(r'-?\d+', str(value)) is not None, f'integer {path} required')
    return int(value)


def pitch(node):
    letter = node.findtext('step')
    alteration = integer(node, 'alter', '0')
    octave = integer(node, 'octave')
    need(letter in ('C', 'D', 'E', 'F', 'G', 'A', 'B') and alteration in range(-2, 3) and 0 <= octave <= 8, 'unsupported pitch')
    return letter + {0: '', -1: 'b', 1: '#', -2: 'bb', 2: '##'}[alteration] + str(octave)


def written_accidental(node, notes):
    """MusicXML pitch/alter is sounding spelling; accidental is a printed sign."""
    sign = node.find('accidental')
    if sign is None:
        return None
    need(len(notes) == 1 and sign.text in WRITTEN_ACCIDENTALS, 'unsupported written accidental')
    need(not any(sign.get(k) == 'yes' for k in ('parentheses', 'bracket')) and not sign.get('smufl'),
         'enclosed/custom accidentals require source review; their display cannot be silently removed')
    alteration = PITCH_ALTERATIONS[re.fullmatch(r'([A-G])(bb|##|b|#)?([0-8])', notes[0])[2]]
    need(WRITTEN_ACCIDENTALS[sign.text] == alteration, 'written accidental disagrees with pitch alteration')
    return sign.text


class ABCPitches:
    """Keep source signs, otherwise emit only a necessary change of pitch state.

    ABC scopes accidentals by voice and octave; a bar resets to the key signature.
    An incoming tie carries its pitch but does not set the new bar's accidental.
    This mirrors the parser's semantics and avoids an accidental on every note.
    """
    def __init__(self, key):
        fifths = (MINOR if key in MINOR else MAJOR).index(key) - 7
        letters = 'FCGDAEB' if fifths > 0 else 'BEADGCF'
        self.signature = {letter: 1 if fifths > 0 else -1 for letter in letters[:abs(fifths)]}
        self.reset_bar()

    def reset_bar(self):
        self.state = {}

    def write(self, name, explicit, tied):
        letter, accidental, octave = re.fullmatch(r'([A-G])(bb|##|b|#)?([0-8])', name).groups()
        octave = int(octave)
        alteration = PITCH_ALTERATIONS[accidental]
        current = self.state.get((letter, octave), self.signature.get(letter, 0))
        shown = explicit is not None or (not tied and alteration != current)
        prefix = {0: '=', -1: '_', -2: '__', 1: '^', 2: '^^'}[alteration] if shown else ''
        if shown:
            self.state[letter, octave] = alteration
        return prefix + (letter + ',' * (4 - octave) if octave <= 4 else letter.lower() + "'" * (octave - 5))


def length(value):
    return '' if value == 1 else str(value.numerator) if value.denominator == 1 else f'{value.numerator}/{value.denominator}'


def convert(data, *, first=1, last=None, missing_key=None, missing_meter=None):
    root = read_xml(data)
    need(root.tag == 'score-partwise', 'only score-partwise is supported')
    parts = root.findall('part')
    need(len(parts) == 1, 'select a single piano part before importing')
    measures = parts[0].findall('measure')
    last = len(measures) if last is None else last
    need(type(first) is int and type(last) is int and 1 <= first <= last <= len(measures) and last - first < 16, 'select 1–16 complete measures by position')
    need(missing_key is None or missing_key in MAJOR + MINOR, 'invalid missing-key override')
    need(missing_meter in (None, '3/4', '4/4'), 'invalid missing-meter override')
    key, meter, divisions, staves, clefs = None, None, None, 1, {}
    header = None
    events, harmonies, dynamics, labels, normalizations = [], {}, {}, [], []
    voice_ids = {1: set(), 2: set()}
    for index, measure in enumerate(measures[:last]):
        selected = index >= first - 1
        bar = index - first + 1
        cursor, previous = F(0), None
        if selected:
            labels.append(measure.get('number', str(index + 1)))
            need(measure.get('implicit', 'no') != 'yes', 'pickup/implicit measures require an explicit complete excerpt')
        for node in measure:
            tag = node.tag
            if tag == 'attributes':
                children(node, 'divisions key time staves clef staff-details', 'attributes')
                if node.find('divisions') is not None:
                    divisions = integer(node, 'divisions'); need(divisions > 0, 'divisions must be positive')
                if node.find('staves') is not None:
                    staves = integer(node, 'staves'); need(staves == 2, 'this importer requires two piano staves')
                for k in node.findall('key'):
                    children(k, 'fifths mode', 'key')
                    fifths = integer(k, 'fifths'); mode = k.findtext('mode', 'major')
                    need(-7 <= fifths <= 7 and mode in ('major', 'minor') and k.get('number') is None, 'unsupported key signature')
                    key = (MAJOR if mode == 'major' else MINOR)[fifths + 7]
                for t in node.findall('time'):
                    children(t, 'beats beat-type', 'time signature')
                    need(len(t.findall('beats')) == 1, 'compound/alternating meters are unsupported')
                    meter = t.findtext('beats', '') + '/' + t.findtext('beat-type', '')
                    need(meter in ('3/4', '4/4'), 'only fixed 3/4 or 4/4 is supported')
                for c in node.findall('clef'):
                    children(c, 'sign line', 'clef')
                    clefs[int(c.get('number', '1'))] = (c.findtext('sign'), c.findtext('line'))
                for s in node.findall('staff-details'):
                    need(len(s) == 0, 'nonstandard staff details are unsupported')
                continue
            if not selected:
                continue
            if tag == 'print':
                continue  # Page layout is deliberately regenerated by abcjs.
            resolved = (key or missing_key, meter or missing_meter)
            need(all(resolved), 'missing key/meter; supply explicit missing_key/missing_meter after source inspection')
            need(staves == 2 and clefs == {1: ('G', '2'), 2: ('F', '4')}, 'fixed treble/bass piano staves required')
            need(divisions is not None, 'divisions required')
            header = header or resolved
            need(resolved == header, 'key/meter changes within the excerpt are unsupported')
            beats = int(header[1][0])
            if tag == 'barline':
                children(node, 'bar-style', 'barline (repeat/endings need manual expansion)')
                continue
            if tag in ('backup', 'forward'):
                need(divisions is not None, 'divisions required')
                delta = F(node.findtext('duration', '0')) / divisions
                need(delta > 0, 'positive backup/forward duration required')
                cursor += delta * (-1 if tag == 'backup' else 1)
                need(0 <= cursor <= beats, 'backup/forward outside measure')
                previous = None
                continue
            if tag == 'harmony':
                children(node, 'root kind bass staff offset', 'harmony')
                kind = node.findtext('kind')
                need(kind in KINDS, 'unsupported harmony kind/extension')
                def root_name(prefix):
                    step = node.findtext(prefix + '/' + prefix + '-step')
                    alt = integer(node, prefix + '/' + prefix + '-alter', '0')
                    need(step in ('A', 'B', 'C', 'D', 'E', 'F', 'G') and alt in (-1, 0, 1), 'unsupported chord root')
                    return step + {-1: 'b', 0: '', 1: '#'}[alt]
                name = root_name('root') + KINDS[kind]
                if node.find('bass') is not None: name += '/' + root_name('bass')
                at = cursor + F(node.findtext('offset', '0')) / divisions
                need((bar, at) not in harmonies, 'overlapping harmony symbols')
                harmonies[bar, at] = name
                continue
            if tag == 'direction':
                children(node, 'direction-type staff voice offset', 'direction')
                need(node.findtext('offset', '0') == '0', 'offset directions require manual review')
                types = node.findall('direction-type')
                need(len(types) == 1 and len(types[0]) == 1 and types[0][0].tag == 'dynamics', 'only simple dynamics directions are supported')
                marks = [n.tag for n in types[0][0]]
                need(len(marks) == 1 and marks[0] in DECORATIONS, 'unsupported dynamics: ' + ', '.join(marks))
                staff = integer(node, 'staff', '1')
                need((bar, cursor, staff) not in dynamics, 'conflicting dynamics')
                dynamics[bar, cursor, staff] = marks[0]
                continue
            need(tag == 'note', 'unsupported measure element: ' + tag)
            children(node, 'pitch rest duration voice type dot accidental stem staff beam chord tie notations time-modification', 'note')
            need(node.get('print-object', 'yes') == 'yes' and not {'attack', 'release'}.intersection(node.attrib), 'hidden/performance-offset notes are unsupported')
            need(divisions is not None, 'divisions required')
            duration = F(node.findtext('duration', '0')) / divisions
            staff = integer(node, 'staff', '1'); voice = node.findtext('voice', '1')
            need(staff in (1, 2), 'unsupported staff')
            voice_ids[staff].add(voice)
            triplet = node.find('time-modification') is not None
            if triplet:
                tm = node.find('time-modification')
                children(tm, 'actual-notes normal-notes normal-type', 'tuplet')
                need(tm.findtext('actual-notes') == '3' and tm.findtext('normal-notes') == '2', 'only ordinary triplets are supported')
            written = LENGTHS.get(node.findtext('type'))
            if node.find('rest') is not None and node.find('rest').get('measure') == 'yes': written = F(beats)
            need(written is not None, 'unsupported/missing written note length')
            dots = len(node.findall('dot')); need(dots <= 1, 'at most one dot is supported')
            written *= F(3, 2) if dots else 1
            need(duration == written * (F(2, 3) if triplet else 1), 'written and numeric durations disagree')
            notes = [pitch(node.find('pitch'))] if node.find('pitch') is not None else []
            need(bool(notes) != (node.find('rest') is not None), 'note needs a pitch or rest')
            accidental = written_accidental(node, notes)
            tie_types = {t.get('type') for t in node.findall('tie')}
            need(tie_types <= {'start', 'stop'}, 'unsupported tie')
            decorations = []
            for ns in node.findall('notations'):
                children(ns, 'tied articulations tuplet', 'notations (slurs/ornaments need manual review)')
                for art in ns.findall('articulations'):
                    decorations.extend(a.tag for a in art)
                need(set(decorations) <= {'accent', 'tenuto', 'staccato'}, 'unsupported articulation')
                need({t.get('type') for t in ns.findall('tied')} <= tie_types, 'tie notation and playback disagree')
            chord = node.find('chord') is not None
            if chord:
                need(previous and previous['staff'] == staff and previous['xml_voice'] == voice and previous['duration'] == duration and notes and previous['notes'] and previous['triplet'] == triplet, 'invalid chord/cross-staff voice')
                previous['notes'].extend(notes); previous['ties'].append(tie_types)
                previous['accidentals'].append(accidental)
                previous['decorations'] = sorted(set(previous['decorations'] + decorations))
            else:
                previous = {'bar': bar, 'beat': cursor, 'duration': duration, 'written': written, 'staff': staff, 'xml_voice': voice,
                            'notes': notes, 'ties': [tie_types] if notes else [], 'accidentals': [accidental] if notes else [],
                            'triplet': triplet, 'decorations': decorations}
                events.append(previous); cursor += duration
            need(0 <= cursor <= beats, 'measure overflow')
    need(header is not None, 'no notes in selected excerpt')
    mapping = {}
    for staff, prefix in ((1, 'RH'), (2, 'LH')):
        need(1 <= len(voice_ids[staff]) <= 2, 'one or two explicit voices per staff required')
        for n, identity in enumerate(sorted(voice_ids[staff])): mapping[staff, identity] = prefix + ('2' if n else '')
    if key is None: normalizations.append('Missing key supplied explicitly: ' + missing_key)
    if meter is None: normalizations.append('Missing meter supplied explicitly: ' + missing_meter)
    normalizations.append('Page layout/beaming regenerated. Source accidentals are retained; other signs are emitted only when required by the key, bar, octave and ABC voice scope.')
    groups = ['(' + ' '.join(v for v in mapping.values() if v.startswith(p)) + ')' if len(voice_ids[s]) == 2 else p for s, p in ((1, 'RH'), (2, 'LH'))]
    lines = ['X:1', 'T:Imported excerpt', 'M:' + header[1], 'L:1/4', '%%score { ' + ' '.join(groups) + ' }']
    lines += [f'V:{v} clef={"treble" if v.startswith("RH") else "bass"}' for v in mapping.values()]
    lines += ['K:' + header[0]]
    used_harmonies, used_dynamics = set(), set()
    for (staff, xml_voice), identity in mapping.items():
        tokens, tied = [], set()
        pitches = ABCPitches(header[0])
        for bar in range(last - first + 1):
            pitches.reset_bar()
            row = [e for e in events if (e['staff'], e['xml_voice'], e['bar']) == (staff, xml_voice, bar)]
            row.sort(key=lambda e: e['beat']); cursor, triplets = F(0), 0
            for e in row:
                need(e['beat'] == cursor, f'{identity} measure {bar + 1} has a gap/overlap; no rests are invented')
                starts = {n for n, ts in zip(e['notes'], e['ties']) if 'start' in ts}
                stops = {n for n, ts in zip(e['notes'], e['ties']) if 'stop' in ts}
                need(stops == tied, 'tie crosses excerpt boundary or changes pitch')
                tied = starts
                symbol = ''.join(pitches.write(n, accidental, n in stops) + ('-' if n in starts else '')
                                 for n, accidental in zip(e['notes'], e['accidentals']))
                symbol = '[' + symbol + ']' if len(e['notes']) > 1 else symbol or 'z'
                prefix = ''
                if identity == 'RH' and (bar, cursor) in harmonies:
                    prefix += '"' + harmonies[bar, cursor] + '"'; used_harmonies.add((bar, cursor))
                dynamic = (bar, cursor, staff)
                if dynamic in dynamics and not identity.endswith('2'):
                    prefix += '!' + dynamics[dynamic] + '!'; used_dynamics.add(dynamic)
                prefix += ''.join('!' + d + '!' for d in e['decorations'])
                if e['triplet']:
                    if triplets == 0: prefix += '(3'
                    triplets = (triplets + 1) % 3
                else: need(triplets == 0, 'unfinished triplet group')
                # A single-note tie follows its length; chord-internal ties stay inside [].
                if len(e['notes']) == 1 and starts:
                    tokens.append(prefix + symbol[:-1] + length(e['written']) + '-')
                else:
                    tokens.append(prefix + symbol + length(e['written']))
                cursor += e['duration']
            need(cursor == int(header[1][0]) and triplets == 0, f'{identity} measure {bar + 1} is incomplete')
            tokens.append('|')
        need(not tied, 'tie ends outside excerpt')
        lines.append('[V:' + identity + '] ' + ' '.join(tokens))
    need(used_harmonies == set(harmonies) and used_dynamics == set(dynamics), 'harmony/dynamics do not align with a supported voice onset')
    notation = {'format': 'abc', 'profile': 'jazz-abc-1', 'abc': '\n'.join(lines) + '\n'}
    parsed = parse_score(notation)
    # Independent MusicXML timeline vs parsed ABC: spelling, pitches, time, voices.
    expected = sorted((mapping[e['staff'], e['xml_voice']], e['bar'], e['beat'], e['duration'], tuple(sorted(e['notes']))) for e in events)
    actual = sorted((e['voice'], e['bar'], F(*e['beat_fraction']), F(*e['duration_fraction']), tuple(sorted(e['notes']))) for e in parsed['events'])
    need(expected == actual, 'ABC round-trip changed the musical timeline')
    return {'notation': notation, 'converter': VERSION, 'source_measures': labels, 'normalizations': normalizations,
            'checks': ['pitch spelling', 'written accidentals and key/bar scope', 'rational duration', 'voice/staff', 'full bars', 'ties', 'ABC round-trip'],
            'source_fidelity': 'unreviewed'}
