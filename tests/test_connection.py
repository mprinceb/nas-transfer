import os
import sys
import threading
import time
import unittest
from unittest.mock import patch
from pathlib import Path

import nas_transfer_cli as core


class ConnectionTests(unittest.TestCase):
    def test_mount_metadata_does_not_stat_nas(self):
        record = f'49 33 0:110 / {core.MOUNT_ROOT} rw - cifs //10.0.0.1/Ego rw\n'
        with patch.object(Path, 'read_text', return_value=record), patch.object(os.path, 'ismount', side_effect=AssertionError('Network stat forbidden')):
            self.assertEqual(core.mounted_nas(), ('//10.0.0.1/Ego', 'cifs'))

    def test_command_timeout(self):
        start = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, 'timed out'):
            core.connection_command([sys.executable, '-c', 'import time; time.sleep(20)'], timeout=.3)
        self.assertLess(time.monotonic() - start, 2)

    def test_command_cancel(self):
        cancel = threading.Event()
        timer = threading.Timer(.1, cancel.set)
        timer.start()
        try:
            with self.assertRaisesRegex(RuntimeError, 'cancelled'):
                core.connection_command([sys.executable, '-c', 'import time; time.sleep(20)'], cancel=cancel)
        finally:
            timer.join()

    def test_existing_mismatched_mount_is_reported_without_stat(self):
        with patch.object(core, 'mounted_nas', return_value=('//10.0.0.1/Ego', 'cifs')), patch.object(os.path, 'ismount', side_effect=AssertionError('Network stat forbidden')):
            with self.assertRaisesRegex(RuntimeError, 'already mounted from //10.0.0.1/Ego'):
                core.mount_nas('smb://sxd')


@unittest.skipUnless(os.environ.get('DISPLAY'), 'Needs Xvfb or a desktop')
class WindowTests(unittest.TestCase):
    def test_cancel_close_timeout_and_late_result(self):
        import tkinter as tk
        import nas_transfer as gui
        root = tk.Tk()
        with patch.object(gui.TransferApp, 'refresh_drives'), patch.object(gui.TransferApp, 'connect'):
            app = gui.TransferApp(root)
            root.update()
        app.connecting = True
        app.connection_id = 4
        app.connected = False
        app.cancel_connection()
        self.assertFalse(app.connecting)
        self.assertTrue(app.connection_cancel.is_set())
        app.events.put(('connected', (4, 'stale-host')))
        app.pump()
        self.assertFalse(app.connected)
        app.connecting = True
        with patch.object(app, 'prompt_nas_address') as prompt:
            app.connection_timed_out(app.connection_id)
            prompt.assert_called_once()
        self.assertFalse(app.connecting)
        app.connecting = True
        app.close()
        self.assertTrue(app.closing)
        self.assertTrue(app.connection_cancel.is_set())


if __name__ == '__main__':
    unittest.main()
