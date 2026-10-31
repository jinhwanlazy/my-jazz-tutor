"""Validated ABC originals and disposable derived music, never performance evidence.

abcjs owns the grammar. This module constrains the supported profile and validates
its parsed meaning using rational quarter-note durations. No regex note parser.
"""
from __future__ import annotations

import copy
from fractions import Fraction
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

PROFILE = 'jazz-abc-1'
ENGINE = 'abcjs-6.7.2'
HERE = Path(__file__).resolve().parent
LETTERS = 'CDEFGAB'
SEMITONES = (0, 2, 4, 5, 7, 9, 11)
ACCIDENTALS = {'natural': 0, 'sharp': 1, 'flat': -1, 'dblsharp': 2, 'dblflat': -2}
DECORATIONS = {'ppp', 'pp', 'p', 'mp', 'mf', 'f', 'ff', 'fff', 'accent', 'tenuto',
               'staccato', 'crescendo(', 'crescendo)', 'diminuendo(', 'diminuendo)'}


def require(condition, message):
    if not condition:
        raise ValueError('ABC: ' + message)


def chord_name(value):
    # abcjs substitutes engraving glyphs in chord labels; preserve their meaning
    # in the derived data and compare them with plain-text degree claims.
    return value.replace('♯', '#').replace('♭', 'b').replace('♮', '')


def header(source):
    require(isinstance(source, str) and 20 <= len(source) <= 24000, 'invalid source size')
    require('\x00' not in source and '\r' not in source, 'use LF text without control characters')
    fields, declarations, layout = {}, [], None
    body = False
    for line in source.splitlines():
        line = line.strip()
        if line.startswith('%%'):
            require(not body and line.startswith('%%score '), 'unsupported directive; only header %%score is allowed')
            require(layout is None, 'duplicate staff layout')
            layout = line[8:].strip()
        elif not line or line.startswith('%'):
            continue
        elif re.match(r'^[A-Za-z]:', line):
            field, value = line[0], line[2:].strip()
            require(not body, 'put voice switches in [V:ID] form; no inline condition changes')
            if field == 'V':
                match = re.fullmatch(r'(RH2?|LH2?)\s+clef=(treble|bass)', value)
                require(match is not None, 'declare V:RH/RH2 clef=treble or V:LH/LH2 clef=bass')
                identity, clef = match.groups()
                require(clef == ('treble' if identity.startswith('RH') else 'bass'), 'voice clef does not match its assigned staff')
                require(identity not in declarations, 'duplicate voice')
                declarations.append(identity)
            else:
                require(field in ('X', 'T', 'M', 'L', 'Q', 'K', 'C', 'O', 'S', 'Z', 'N'), 'unsupported header ' + field)
                require(field not in fields or field == 'N', 'duplicate header ' + field)
                fields[field] = value
                if field == 'K':
                    body = True
        else:
            require(body, 'music must follow K:')
            for inline in re.findall(r'\[([A-Za-z]):([^\]]*)\]', line):
                require(inline[0] == 'V' and inline[1].strip() in declarations, 'unknown voice or inline condition change')
    require(fields.get('X') == '1', 'supply exactly one tune with X:1')
    require(fields.get('M') in ('3/4', '4/4'), 'profile 1 supports fixed 3/4 or 4/4')
    require(fields.get('L') in ('1/4', '1/8', '1/16'), 'specify L:1/4, L:1/8 or L:1/16')
    require(re.fullmatch(r'[A-G][b#]?(?:maj|major|m|min|minor|dor|dorian|mix|mixolydian|lyd|lydian|phr|phrygian|loc|locrian)?', fields.get('K', ''), re.I), 'unsupported key header')
    require('RH' in declarations and 'LH' in declarations, 'declare both staves; use explicit rests for a silent hand')
    groups = [('RH', 'RH2') if 'RH2' in declarations else ('RH',),
              ('LH', 'LH2') if 'LH2' in declarations else ('LH',)]
    require(layout is not None, 'explicit %%score staff layout is required')
    tokens = re.findall(r'\([^()]+\)|RH2?|LH2?|[{}]|\S+', layout)
    require(tokens[0:1] == ['{'] and tokens[-1:] == ['}'] and len(tokens) == 4,
            'layout must group right and left voices into two braced staves')
    require([tuple(t.strip('()').split()) for t in tokens[1:-1]] == groups,
            'layout must list the right staff then the left staff, with RH/LH before RH2/LH2')
    require(declarations == [v for group in groups for v in group], 'declare voices in staff order')
    tempo = fields.get('Q')
    require(tempo is None or re.fullmatch(r'1/4\s*=\s*\d+', tempo), 'tempo must use quarter-note BPM')
    return fields, groups


@lru_cache(maxsize=256)
def _parsed(source):
    fields, groups = header(source)
    node = os.environ.get('JAZZ_NODE_BIN') or shutil.which('node')
    require(bool(node), 'Node.js is required to validate ABC. Install Node.js and restart the server.')
    try:
        process = subprocess.run([node, str(HERE / 'abc-parse.cjs')],
            input=json.dumps({'abc': source}), capture_output=True, text=True, timeout=5, cwd=HERE)
        require(process.returncode == 0 and len(process.stdout) <= 2_000_000, 'parser could not read this score')
        parsed = json.loads(process.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        raise ValueError('ABC: parser unavailable or timed out') from exc
    require(parsed.get('engine') == ENGINE, 'parser version mismatch')
    require(not parsed.get('warnings'), 'parser warning: ' + '; '.join(parsed.get('warnings', []))[:600])
    music_lines = [line for line in parsed['lines'] if 'staff' in line]
    require(bool(music_lines) and all(len(line['staff']) == 2 for line in music_lines), 'exactly two staves are required')
    beats = int(fields['M'][0])
    bars, voices, events, harmonies = [], [], [], {}
    first_key = music_lines[0]['staff'][0]['key']
    for staff_index, group in enumerate(groups):
        hand = 'right' if staff_index == 0 else 'left'
        for voice_index, identity in enumerate(group):
            voice_bars, current, offset, ties = [], [], Fraction(0), {}
            accidentals, triplet, slurs = {}, None, set()
            for music_line in music_lines:
                staff = music_line['staff'][staff_index]
                require(len(staff['voices']) == len(group), 'voice count changes inside the score')
                key = staff['key']
                require((key['root'], key['acc'], key['mode']) == (first_key['root'], first_key['acc'], first_key['mode']), 'key changes are not supported in profile 1')
                signature = {p['note'].upper(): ACCIDENTALS[p['acc']] for p in key['accidentals']}
                for element in staff['voices'][voice_index]:
                    kind = element['el_type']
                    if kind == 'stem':
                        continue
                    if kind == 'bar':
                        require(element['type'] in ('bar_thin', 'bar_thin_thin', 'bar_thin_thick') and not element.get('startEnding') and not element.get('endEnding'), 'write out repeats and endings')
                        if not current and not voice_bars:
                            continue
                        require(offset == beats, f'{identity} bar {len(voice_bars) + 1} has {offset} quarter beats, expected {beats}')
                        voice_bars.append(current)
                        current, offset, accidentals = [], Fraction(0), {}
                        continue
                    require(kind == 'note', 'unsupported musical element ' + kind)
                    require(not element.get('gracenotes'), 'grace notes are not supported in profile 1')
                    require(not element.get('style'), 'nonstandard notehead styles are not supported in profile 1')
                    require(not element.get('rest', {}).get('type') in ('spacer', 'invisible', 'multimeasure'), 'use explicit single-measure rests')
                    decorations = element.get('decoration', [])
                    require(set(decorations) <= DECORATIONS, 'unsupported decoration')
                    if 'startTriplet' in element:
                        require(triplet is None and element['startTriplet'] == 3 and element['tripletR'] == 3 and abs(element['tripletMultiplier'] - 2/3) < 1e-9, 'profile 1 supports ordinary three-in-two triplets')
                        triplet = 3
                    duration = Fraction(str(element['duration'])).limit_denominator(64) * 4
                    is_triplet = bool(triplet)
                    require(duration >= Fraction(1, 4) and duration <= 4, 'written duration outside sixteenth–whole range')
                    if triplet:
                        duration *= Fraction(2, 3)
                        triplet -= 1
                        if triplet == 0:
                            require(element.get('endTriplet'), 'unfinished triplet')
                            triplet = None
                    require(offset + duration <= beats, f'{identity} bar {len(voice_bars) + 1} overflows; use ties across bars')
                    eid = f'{identity}:{len(voice_bars)}:{len(current)}'
                    notes = []
                    next_ties = {}
                    slur_starts, slur_ends = [], []
                    for item in [element, *element.get('pitches', []), element.get('rest', {})]:
                        slur_starts.extend(s['label'] for s in item.get('startSlur', []))
                        slur_ends.extend(item.get('endSlur', []))
                    for label in slur_ends:
                        require(label in slurs, 'slur ends without a matching start')
                        slurs.remove(label)
                    for label in slur_starts:
                        require(label not in slurs, 'duplicate slur start')
                        slurs.add(label)
                    for pitch in element.get('pitches', []):
                        diatonic = pitch['pitch']
                        octave, step = divmod(diatonic, 7)
                        octave += 4
                        letter = LETTERS[step]
                        previous = ties.get(diatonic)
                        explicit = pitch.get('accidental')
                        require(explicit is None or explicit in ACCIDENTALS, 'unsupported accidental')
                        alter = ACCIDENTALS[explicit] if explicit else (previous['alter'] if previous else accidentals.get(diatonic, signature.get(letter, 0)))
                        if explicit:
                            accidentals[diatonic] = alter
                        midi = 12 * (octave + 1) + SEMITONES[step] + alter
                        require(21 <= midi <= 108, 'notes must be within piano range A0–C8')
                        require(bool(pitch.get('endTie')) == bool(previous), 'tie must connect adjacent notes of the same spelling')
                        require(not previous or previous['midi'] == midi, 'tied pitch changes')
                        spelling = letter + {0:'', 1:'#', -1:'b', 2:'##', -2:'bb'}[alter] + str(octave)
                        note = {'name': spelling, 'midi': midi, 'letter': letter, 'alter': alter, 'octave': octave,
                                'tie_from': previous['event'] if previous else None, 'tie_to': None}
                        if previous:
                            previous['note']['tie_to'] = eid
                        if 'startTie' in pitch:
                            next_ties[diatonic] = {'midi': midi, 'alter': alter, 'event': eid, 'note': note}
                        notes.append(note)
                    require(not (set(ties) - {p['pitch'] for p in element.get('pitches', [])}), 'a tied note is missing at the next position')
                    require(len(notes) <= 6 and len({n['midi'] for n in notes}) == len(notes), 'each voice chord must contain at most six distinct notes')
                    ties = next_ties
                    event = {'id': eid, 'voice': identity, 'hand': hand, 'bar': len(voice_bars),
                             'beat': float(offset), 'duration': float(duration),
                             'beat_fraction': [offset.numerator, offset.denominator],
                             'duration_fraction': [duration.numerator, duration.denominator],
                             'pitches': notes, 'notes': [n['name'] for n in notes],
                             'kind': 'notes' if notes else 'rest', 'decorations': decorations, 'triplet': is_triplet,
                             'slur_starts': slur_starts, 'slur_ends': slur_ends,
                             'start_char': element['startChar'], 'end_char': element['endChar']}
                    for chord in element.get('chord', []):
                        require(chord.get('position') == 'default', 'free-text score annotations are not supported; use exercise instructions')
                        position = len(voice_bars) * beats + offset
                        name = chord_name(chord['name'])
                        require(position not in harmonies or harmonies[position] == name, 'conflicting chord symbols')
                        harmonies[position] = name
                    current.append(event); events.append(event)
                    offset += duration
            if current:
                require(offset == beats, f'{identity} final bar is incomplete')
                voice_bars.append(current)
            require(not ties and triplet is None, 'unfinished tie or triplet')
            require(not slurs, 'unfinished slur')
            require(1 <= len(voice_bars) <= 16, 'score must contain 1–16 full bars')
            if not bars:
                bars = [{'chord': '', 'left': [], 'right': []} for _ in voice_bars]
            require(len(bars) == len(voice_bars), 'all voices must have the same bar count')
            for bar, items in zip(bars, voice_bars):
                bar[hand].extend(items)
            voices.append({'id': identity, 'hand': hand, 'staff': staff_index})
    require(any(e['pitches'] for e in events), 'score contains only rests')
    last_chord = ''
    for index, bar in enumerate(bars):
        chords = [(position - index * beats, name) for position, name in sorted(harmonies.items()) if index * beats <= position < (index + 1) * beats]
        bar['harmony'] = [{'beat': float(at), 'chord': name} for at, name in chords]
        bar['chord'] = chords[0][1] if chords and chords[0][0] == 0 else last_chord
        if chords:
            last_chord = chords[-1][1]
        for hand in ('left', 'right'):
            bar[hand].sort(key=lambda e: (e['beat'], e['voice']))
    return {'format': 'abc', 'profile': PROFILE, 'engine': ENGINE, 'abc': source,
            'sha256': hashlib.sha256(source.encode()).hexdigest(),
            'key': first_key['root'] + first_key['acc'] + first_key['mode'],
            'key_signature': {p['note'].upper(): ACCIDENTALS[p['acc']] for p in first_key['accidentals']},
            'beats_per_bar': beats, 'bars': bars, 'voices': voices, 'events': events,
            'allowed_pitches': [], 'bass_onset_only': False, 'short_attacks': False,
            'tempo': int(fields['Q'].split('=')[1]) if 'Q' in fields else None}


def parse_score(notation, *, key=None, bpm=None, bars=None):
    require(isinstance(notation, dict) and set(notation) == {'format', 'profile', 'abc'}, 'invalid notation envelope')
    require(notation['format'] == 'abc' and notation['profile'] == PROFILE, 'unsupported notation profile')
    score = _parsed(notation['abc'])
    if key is not None:
        normalized = key.replace(' major', '').replace(' minor', 'm')
        normalized = re.sub(r'(?:major|maj)$', '', normalized)
        normalized = re.sub(r'(?:minor|min)$', 'm', normalized)
        require(normalized == score['key'], 'key differs from assigned key')
    require(bpm is None or score['tempo'] is None or bpm == score['tempo'], 'tempo differs from assigned quarter-note BPM')
    require(bars is None or bars == len(score['bars']), 'bar count differs from assignment')
    return copy.deepcopy(score)


def playback_for(notation, **conditions):
    """Explicit accompaniment notes, with tied continuations merged for sounding."""
    score = parse_score(notation, **conditions)
    sounding, pending = [], {}
    for event in sorted(score['events'], key=lambda e: (e['bar'], e['beat'], e['voice'])):
        start = event['bar'] * score['beats_per_bar'] + event['beat']
        for note in event['pitches']:
            if note['tie_from']:
                played = pending.pop((note['tie_from'], note['midi']))
                played['duration'] += event['duration']
            else:
                played = {'start': start, 'duration': event['duration'], 'pitch': note['midi'], 'voice': event['voice']}
                sounding.append(played)
            if note['tie_to']:
                pending[(event['id'], note['midi'])] = played
    return {'beats_per_bar': score['beats_per_bar'], 'bars': [{'chord': b['chord'], 'harmony': b['harmony'], 'notes': []} for b in score['bars']],
            'events': sounding}


def validate_claims(claims, score):
    """Verify explicit pitch/degree claims, not every possible prose interpretation."""
    require(score is not None or not claims, 'music claims require explicit notation')
    for index, claim in enumerate(claims):
        bar = claim['bar'] - 1
        require(bar < len(score['bars']), 'music claim references a missing bar')
        events = [e for e in score['events'] if e['bar'] == bar and e['voice'] == claim['voice'] and abs(e['beat'] - claim['beat']) < 1e-8]
        notes = [n for e in events for n in e['pitches'] if n['name'] == claim['pitch']]
        require(bool(notes), 'music claim references a missing note')
        chord = score['bars'][bar]['chord']
        for change in score['bars'][bar]['harmony']:
            if change['beat'] <= claim['beat']:
                chord = change['chord']
        require(chord == chord_name(claim['chord']), 'music claim differs from the written chord')
        root = re.match(r'^([A-G])(#{1,2}|b{1,2})?(?![#b])', chord)
        require(root is not None, 'music claim requires a spelled chord root')
        letter, accidental = root.groups()
        root_step = LETTERS.index(letter)
        root_pc = (SEMITONES[root_step] + {None:0, '#':1, 'b':-1, '##':2, 'bb':-2}[accidental]) % 12
        degree = (claim['degree'] - 1) % 7
        require((LETTERS.index(notes[0]['letter']) - root_step) % 7 == degree,
                'claimed degree disagrees with the spelled pitch (third and fifth are distinct)')
        require((notes[0]['midi'] - root_pc) % 12 == (SEMITONES[degree] + claim['alteration']) % 12,
                f'claimed degree alteration disagrees with its chromatic interval: music_claims[{index}] '
                f'{claim["chord"]}/{claim["pitch"]}, degree={claim["degree"]}, alteration={claim["alteration"]}; '
                'alteration is relative to the major/perfect interval from the root, not the chord quality')
