import unittest
from unittest.mock import patch
import nas_windows as win
import nas_transfer_cli as core


class WindowsTests(unittest.TestCase):
    def test_addresses(self):
        for address in ('smb://sxd', 'smb://sxd/Ego', 'sxd', r'\\sxd\Ego'):
            self.assertEqual(win.unc_share(address), r'\\sxd\Ego')
        self.assertEqual(win.unc_share('smb://192.168.0.182'), r'\\192.168.0.182\Ego')

    def test_reject_other_shares_and_embedded_credentials(self):
        for address in ('smb://sxd/Other', 'smb://user:pass@sxd/Ego', 'https://sxd', 'smb://sxd:1445'):
            with self.assertRaises(ValueError):
                win.unc_share(address)

    def test_share_root_only(self):
        self.assertTrue(win.is_share_root(r'\\sxd\Ego'))
        self.assertFalse(win.is_share_root(r'C:\data'))
        self.assertFalse(win.is_share_root(r'\\sxd\Ego\subfolder'))

    def test_mount_uses_bounded_helper_without_password_arguments(self):
        with patch.object(core, 'IS_WINDOWS', True), patch.object(core, 'connection_command') as command:
            result = core.mount_nas('smb://sxd')
            self.assertEqual(str(result), r'\\sxd\Ego')
            argv = command.call_args.args[0]
            self.assertTrue(argv[0].endswith('python.exe'))
            self.assertNotIn(core.NAS_PASSWORD, ' '.join(argv))
            self.assertEqual(command.call_args.kwargs['timeout'], 30)

    def test_windows_mount_metadata_avoids_linux_files(self):
        with patch.object(core, 'IS_WINDOWS', True):
            self.assertEqual(core.mounted_nas(r'\\sxd\Ego'), (r'\\sxd\Ego', 'smb'))

    def test_windows_drive_dispatch(self):
        with patch.object(core, 'IS_WINDOWS', True), patch.object(win, 'removable_roots', return_value=['E:\\']):
            self.assertEqual(core.removable_roots(), ['E:\\'])


if __name__ == '__main__':
    unittest.main()
