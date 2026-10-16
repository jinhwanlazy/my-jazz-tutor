"""Display-only notation from an assignment's own material, never pad voicings.

Only the existing curriculum's explicit note/rhythm forms are supported. Unknown
forms return None rather than silently inventing a score or changing evidence.
"""
import re

PITCH = re.compile(r"([A-G])([b#]?)(-?\d+)")
SEMITONES = dict(zip("CDEFGAB", (0, 2, 4, 5, 7, 9, 11)))


def pitches(text):
    result = []
    for letter, accidental, octave in PITCH.findall(text):
        octave = int(octave)
        alter = {"": 0, "b": -1, "#": 1}[accidental]
        midi = 12 * (octave + 1) + SEMITONES[letter] + alter
        if not 0 <= midi <= 127:
            raise ValueError("Pitch outside MIDI range")
        result.append({"name": f"{letter}{accidental}{octave}", "midi": midi,
                       "letter": letter, "alter": alter, "octave": octave})
    return result


def event(beat=0, duration=4, notes=None, kind=None):
    return {"beat": beat, "duration": duration, "pitches": notes or [],
            "kind": kind or ("notes" if notes else "rest")}


def score_for(target):
    try:
        return _score(target)
    except (KeyError, TypeError, ValueError, IndexError):
        return None


def _score(t):
    material, count = t["material"], t["bars"]
    if t["key"] not in ("C", "F", "Bb") or count not in (4, 8):
        return None
    whole = t["rhythm"] == "whole-notes"
    charleston = t["rhythm"] == "charleston-1-and-2and"
    improv = t["rhythm"] == "quarter-notes-and-rests" and t["melody"] == "three-note-call-and-rest"
    supported = {
        ("left-bass-only", "root-on-beat-1", "none", "none"),
        ("right-melody-only", "none", "none", "written-notes"),
        ("melody-and-bass", "root-on-beat-1", "none", "written-notes"),
        ("left-root-right-guides", "root-on-beat-1", "third-and-seventh", "none"),
        ("left-root-right-improv", "root-on-beat-1", "none", "three-note-call-and-rest"),
    }
    if tuple(t[k] for k in ("arrangement", "bass", "voicing", "melody")) not in supported:
        return None
    if not (whole or charleston or improv):
        return None
    if charleston and t["arrangement"] != "left-root-right-guides":
        return None
    if improv != (t["arrangement"] == "left-root-right-improv"):
        return None
    if count != (8 if improv else 4):
        return None
    chords = [s.strip() for s in material["chords"].split("|")]
    if improv:
        # Both canonical and English presentation use the multiplication sign.
        chord, repeats = material["chords"].split("×")
        if not re.fullmatch(r"\s*8(?:마디|\s+bars)\s*", repeats):
            return None
        chords = [chord.strip()] * count
    if len(chords) != count:
        return None
    left = [pitches(s) for s in material.get("roots", "").split("|")]
    right = [pitches(s) for s in material.get("guide_tones" if t["voicing"] != "none" else "melody", "").split("|")]
    if t["bass"] != "none":
        if improv:
            left *= count
        if len(left) != count or any(len(notes) != 1 for notes in left):
            return None
    if t["melody"] != "none" or t["voicing"] != "none":
        expected = 3 if improv else 2 if t["voicing"] != "none" else 1
        if len(right) != (1 if improv else count) or any(len(notes) != expected for notes in right):
            return None
    bars = []
    for index, chord in enumerate(chords):
        # The vamp specifies a bass attack on beat 1, but no exact hold length.
        lh = [event(notes=left[index], duration=None, kind="onset")] if improv else [event(notes=left[index])] if t["bass"] != "none" else [event()]
        if improv:
            rh = [event(notes=right[0], kind="improv")] if index % 4 < 2 else [event()]
        elif charleston:
            rh = [event(0, .5, right[index]), event(.5, .5), event(1, .5),
                  event(1.5, .5, right[index]), event(2, 1), event(3, 1)]
        else:
            rh = [event(notes=right[index])] if t["melody"] != "none" or t["voicing"] != "none" else [event()]
        bars.append({"chord": chord, "left": lh, "right": rh})
    return {"key": t["key"], "beats_per_bar": 4, "bars": bars,
            "allowed_pitches": right[0] if improv else [], "bass_onset_only": improv,
            "short_attacks": charleston}
