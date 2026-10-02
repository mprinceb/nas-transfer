"""Isolated transfer and queue regression checks; never touch mounted media."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import nas_transfer as gui
import nas_transfer_cli as core


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.nas = self.root / 'nas'
        self.nas.mkdir()
        for module in (core, gui):
            patcher = patch.object(module, 'MOUNT_ROOT', self.nas)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(core.os.path, 'ismount', return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def card(self, number):
        source = self.root / f'card{number}' / 'Trinet' / 'recording'
        source.mkdir(parents=True)
        (source / 'recording.bin').write_bytes(f'card {number}'.encode() * 100)
        (source / 'empty').mkdir()
        return dict(source=source, title='', files=core.inventory(source)[0])

    def test_fifteen_cards_numbered_and_verified(self):
        jobs = [(str(n), self.card(n)) for n in range(15)]
        snapshots = [(c['source'] / 'recording.bin').read_bytes() for _, c in jobs]
        events = []
        result = gui.run_batch(jobs, 'walking', False, threading.Event(), lambda key, event: events.append((key, event)))
        self.assertEqual(result, (15, 'Complete'))
        destinations = [Path(e['destination']) for _, e in events if 'destination' in e]
        self.assertEqual([p.name for p in destinations], ['walking'] + [f'walking-{i}' for i in range(2, 16)])
        for (_, card), destination, content in zip(jobs, destinations, snapshots):
            self.assertEqual((destination / 'recording.bin').read_bytes(), content)
            self.assertEqual(list(card['source'].iterdir()), [])
            self.assertTrue((destination / 'empty').is_dir())

    def test_changed_queued_card_stops_rest(self):
        jobs = [(str(n), self.card(n)) for n in range(3)]
        (jobs[1][1]['source'] / 'recording.bin').write_bytes(b'changed')
        result = gui.run_batch(jobs, 'walking', False, threading.Event(), lambda *args: None)
        self.assertEqual(result, (1, 'Failed'))
        for _, card in jobs[1:]:
            self.assertTrue((card['source'] / 'recording.bin').exists())

    def test_corruption_never_clears_source(self):
        card = self.card(0)
        def event(event):
            if event.get('phase') == 'Verifying':
                (self.nas / 'test' / 'recording.bin').write_bytes(b'bad data')
        with self.assertRaisesRegex(RuntimeError, 'Verification failed'):
            core.transfer(card['source'], self.nas / 'test', notify=event)
        self.assertTrue((card['source'] / 'recording.bin').exists())

    def test_keep_source(self):
        card = self.card(0)
        core.transfer(card['source'], self.nas / 'test', keep_source=True, notify=lambda event: None)
        self.assertTrue((card['source'] / 'recording.bin').exists())

    def test_cancel_before_cleanup_keeps_source(self):
        card = self.card(0)
        cancel = threading.Event()
        def event(event):
            if event.get('phase') == 'Clearing verified files':
                cancel.set()
        with self.assertRaises(core.TransferCancelled):
            core.transfer(card['source'], self.nas / 'test', notify=event, cancel=cancel)
        self.assertTrue((card['source'] / 'recording.bin').exists())

    def test_card_titles(self):
        jobs = [('a', self.card(0)), ('b', self.card(1))]
        jobs[1][1]['title'] = 'other'
        paths = []
        result = gui.run_batch(jobs, 'default', True, threading.Event(), lambda key, event: paths.append(event.get('destination')))
        self.assertEqual(result, (2, 'Complete'))
        self.assertEqual([Path(p).name for p in paths if p], ['default', 'other'])


if __name__ == '__main__':
    unittest.main()
