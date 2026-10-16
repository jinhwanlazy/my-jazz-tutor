"""Synthetic input in temporary workspaces, never production practice evidence."""
import base64
import unittest

from sessions import FRAME, measurements, midi_messages


def raw(*messages):
    return b''.join(FRAME.pack(at, port, len(data)) + bytes(data) for at, port, data in messages)


def chunk(blob=b'', events=None, elapsed=10000, seq=0):
    return {'sequence': seq, 'midi': base64.b64encode(blob).decode(),
            'events': events or [], 'elapsed_ms': elapsed}


def measure(blob=b'', events=None, interrupted=False):
    return measurements([{'midi': blob, 'events': events or [], 'elapsed_ms': 10000}], interrupted)


class MeasurementTests(unittest.TestCase):
    def test_trim_ignores_clock_controls_and_preserves_tempo_at_last_note(self):
        blob = raw((100, 0, [0xf8]), (2000, 0, [0x90, 60, 100]),
                   (3000, 0, [0x80, 60, 0]), (5000, 0, [0x91, 64, 90]),
                   (7000, 0, [0x91, 64, 0]), (9000, 0, [0xb0, 1, 127]))
        result = measure(blob, [{'type': 'play', 'at_ms': 0, 'bpm': 60},
                                {'type': 'tempo', 'at_ms': 4000, 'bpm': 80},
                                {'type': 'tempo', 'at_ms': 8000, 'bpm': 100}])
        self.assertEqual(result['input_span_ms'], 5000)
        self.assertEqual(result['note_ons'], 2)
        self.assertEqual(result['midi_messages'], 6)
        self.assertEqual(result['last_note_bpm'], 80)
        self.assertEqual(result['last_setting_bpm'], 100)
        self.assertNotIn('notes_correct', result)

    def test_sustain_tracks_each_input_and_channel(self):
        blob = raw((1000, 0, [0x90, 60, 100]), (1500, 0, [0xb0, 64, 127]),
                   (2000, 0, [0x80, 60, 0]), (3000, 1, [0xb0, 64, 0]),
                   (4000, 0, [0xb1, 64, 0]), (6000, 0, [0xb0, 64, 0]))
        self.assertEqual(measure(blob)['input_span_ms'], 5000)
        self.assertIsNone(measure(blob[:-15])['input_span_ms'])

    def test_missing_note_off_or_disconnect_is_not_exact_time(self):
        held = raw((1000, 0, [0x90, 60, 90]))
        self.assertIsNone(measure(held)['input_span_ms'])
        self.assertIn('held_notes', measure(held)['capture_warnings'])
        complete = held + raw((2000, 0, [0x80, 60, 0]))
        self.assertIsNone(measure(complete, [{'type': 'disconnect', 'at_ms': 3000}])['input_span_ms'])
        self.assertIsNone(measure(complete, interrupted=True)['input_span_ms'])

    def test_all_notes_off_respects_sustain_and_controller_reset_releases_it(self):
        prefix = raw((1000, 0, [0x90, 60, 100]), (1500, 0, [0xb0, 64, 127]),
                     (2000, 0, [0xb0, 123, 0]))
        self.assertIsNone(measure(prefix)['input_span_ms'])
        self.assertEqual(measure(prefix + raw((4000, 0, [0xb0, 121, 0])))['input_span_ms'], 3000)
        self.assertEqual(measure(prefix + raw((3000, 0, [0xb0, 120, 0])))['input_span_ms'], 2000)

    def test_no_midi_remains_unknown_and_active_time_excludes_pause(self):
        result = measure(events=[{'type': 'play', 'at_ms': 500, 'bpm': 60},
                                 {'type': 'pause', 'at_ms': 3000},
                                 {'type': 'play', 'at_ms': 6000, 'bpm': 72},
                                 {'type': 'pause', 'at_ms': 8000}])
        self.assertEqual(result['active_ms'], 4500)
        self.assertIsNone(result['input_span_ms'])
        self.assertIsNone(result['last_note_bpm'])
        self.assertEqual(result['last_setting_bpm'], 72)

    def test_truncated_or_nonfinite_binary_is_rejected(self):
        for blob in [b'bad', FRAME.pack(1, 0, 3) + b'\x90', FRAME.pack(float('nan'), 0, 1) + b'\xf8']:
            with self.subTest(blob=blob), self.assertRaises(ValueError):
                list(midi_messages(blob))
