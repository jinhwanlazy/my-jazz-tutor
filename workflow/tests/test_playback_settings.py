"""Workspace preferences are atomic and independent of tasks and user evidence."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest

import review as r
from recommendation import context_for
from webapp import Application, PlaybackSettings


class PlaybackSettingsTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        self.root=Path(directory.name);(self.root/'profile.json').write_text('{"daily_minutes":30}')
        self.data=r.curriculum();self.app=Application(self.root,self.data)

    def save(self, changes, app=None):
        return (app or self.app).post('/api/playback-settings',{'changes':changes})

    def test_shared_preferences_survive_task_changes_other_clients_and_restart(self):
        initial=self.app.state()['playback_settings']
        self.assertFalse((self.root/'playback-settings.json').exists())
        saved=self.save({'metronome_enabled':True,'pad_enabled':True,'drums_enabled':True,'drum_feel':'swing','pad_volume':.09})
        other=Application(self.root,self.data)
        self.assertEqual(other.state()['playback_settings'],saved)
        self.save({'click_volume':.17},other)
        for exercise in ('E01','E02'):r.assign(self.root,self.data,exercise)
        current=Application(self.root,self.data).state()['playback_settings']
        self.assertEqual(current['values']['drum_feel'],'swing');self.assertTrue(current['values']['pad_enabled'])
        self.assertEqual(current['values']['click_volume'],.17);self.assertEqual(current['values']['pad_volume'],.09)
        self.assertGreater(current['revision'],initial['revision'])
        before=(self.root/'practice.csv').read_bytes();profile=(self.root/'profile.json').read_bytes()
        self.assertEqual(self.save({'click_volume':.17}),current)
        self.assertEqual((self.root/'practice.csv').read_bytes(),before)
        self.assertEqual((self.root/'profile.json').read_bytes(),profile)
        self.assertNotIn('pad_enabled',json.dumps(context_for(self.root,self.data)))

    def test_partial_updates_from_two_clients_do_not_overwrite_other_controls(self):
        other=Application(self.root,self.data)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(self.save,{'pad_enabled':True,'pad_volume':.11})
            second=pool.submit(self.save,{'drums_enabled':True,'drum_feel':'swing'},other)
            first.result();second.result()
        values=self.app.playback_settings.read()['values']
        self.assertTrue(values['pad_enabled']);self.assertTrue(values['drums_enabled'])
        self.assertEqual(values['pad_volume'],.11);self.assertEqual(values['drum_feel'],'swing')

    def test_invalid_or_corrupt_settings_never_reset_the_saved_file(self):
        self.save({'pad_enabled':True});path=self.root/'playback-settings.json';before=path.read_bytes()
        for changes in ({'bpm':60},{'pad_enabled':1},{'click_volume':True},{'drum_volume':.7},
                        {'click_volume':float('nan')},{'drum_feel':'shuffle'},{'pad_volume':-1}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.save(changes)
            self.assertEqual(path.read_bytes(),before)
        path.write_text('{ invalid synthetic settings')
        broken=path.read_bytes()
        with self.assertRaises(ValueError):self.app.playback_settings.read()
        with self.assertRaises(ValueError):self.save({'pad_enabled':False})
        self.assertEqual(path.read_bytes(),broken)
