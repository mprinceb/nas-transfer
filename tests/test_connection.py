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

    def test_changed_ip_unmounts_then_mounts(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(core, 'MOUNT_ROOT', Path(tmp)/'Ego'), \
             patch.object(core, 'mounted_nas', side_effect=[('//192.168.0.222/Ego','cifs'), None, ('//sxd/Ego','cifs')]), \
             patch.object(core, 'mounted_nas_ip', return_value='192.168.0.222'), \
             patch.object(core, 'reachable_nas_ip', return_value='192.168.0.182'), \
             patch.object(core.shutil, 'which', return_value='/usr/sbin/mount.cifs'), \
             patch.object(core, 'connection_command', return_value='') as command:
            core.mount_nas('smb://sxd')
            calls=[c.args[0] for c in command.call_args_list]
            self.assertIn('umount', calls[0])
            self.assertNotIn('-l', calls[0])
            self.assertNotIn('-f', calls[0])
            self.assertIn('mount', calls[1])
            self.assertIn('ip=192.168.0.182', calls[1][-1])

    def test_alias_of_current_ip_reuses_mount(self):
        with patch.object(core, 'mounted_nas', return_value=('//192.168.0.182/Ego','cifs')), \
             patch.object(core, 'mounted_nas_ip', return_value='192.168.0.182'), \
             patch.object(core, 'reachable_nas_ip', return_value='192.168.0.182'), \
             patch.object(core, 'connection_command') as command:
            core.mount_nas('smb://sxd')
            command.assert_not_called()

    def test_busy_old_mount_never_mounts_over_it(self):
        with patch.object(core, 'mounted_nas', return_value=('//192.168.0.222/Ego','cifs')), \
             patch.object(core, 'mounted_nas_ip', return_value='192.168.0.222'), \
             patch.object(core, 'reachable_nas_ip', return_value='192.168.0.182'), \
             patch.object(core.shutil, 'which', return_value='/usr/sbin/mount.cifs'), \
             patch.object(core, 'connection_command', side_effect=RuntimeError('target is busy')) as command:
            with self.assertRaisesRegex(RuntimeError, 'Close files or transfers'):
                core.mount_nas('smb://sxd')
            self.assertEqual(command.call_count, 1)
            self.assertIn('umount', command.call_args.args[0])

    def test_netbios_fallback(self):
        with patch.object(core.shutil, 'which', return_value='/usr/bin/nmblookup'), \
             patch.object(core, 'connection_command', side_effect=[RuntimeError('dns'), RuntimeError('mdns'), '192.168.0.182 sxd<00>\n', '192.168.0.182\n']) as command:
            self.assertEqual(core.reachable_nas_ip('sxd'), '192.168.0.182')
            self.assertEqual(command.call_args_list[2].args[0], ['nmblookup', '--', 'sxd'])

    def test_unreachable_new_nas_preserves_existing_mount(self):
        with patch.object(core, 'mounted_nas', return_value=('//192.168.0.222/Ego','cifs')), \
             patch.object(core, 'reachable_nas_ip', side_effect=RuntimeError('unreachable')), \
             patch.object(core, 'connection_command') as command:
            with self.assertRaisesRegex(RuntimeError, 'unreachable'):
                core.mount_nas('smb://sxd')
            command.assert_not_called()


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
