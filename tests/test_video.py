"""Video-length reading from synthetic MP4 headers; never touches real media."""
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import nas_transfer as gui
import nas_transfer_cli as core
import nas_video


def fake_mp4(path, seconds, moov_first=False, padding=4096):
    """Minimal file with a version-0 mvhd box (timescale 1000)."""
    mvhd = struct.pack('>I4sB3xIIII', 108, b'mvhd', 0, 0, 0, 1000, int(seconds * 1000)) + bytes(80)
    moov = struct.pack('>I4s', 8 + len(mvhd), b'moov') + mvhd
    mdat = struct.pack('>I4s', 8 + padding, b'mdat') + bytes(padding)
    path.write_bytes(moov + mdat if moov_first else mdat + moov)


class VideoTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_moov_at_end_and_start(self):
        fake_mp4(self.root / 'a.mp4', 61.5)
        fake_mp4(self.root / 'b.mp4', 7, moov_first=True)
        self.assertAlmostEqual(nas_video.mp4_duration(self.root / 'a.mp4'), 61.5)
        self.assertAlmostEqual(nas_video.mp4_duration(self.root / 'b.mp4'), 7)

    def test_card_totals_count_one_camera_of_each_pair(self):
        source = self.root / 'card' / 'Trinet' / 'recording'
        (source / 'take1').mkdir(parents=True)
        fake_mp4(source / 'take1' / 'take0001_L.mp4', 3600)
        fake_mp4(source / 'take1' / 'take0001_R.mp4', 3601)
        fake_mp4(source / 'extra.mp4', 60)
        (source / 'broken_L.mp4').write_bytes(b'')
        (source / 'notes.txt').write_text('not a video')
        with patch.object(nas_video, 'ffprobe_duration', return_value=None):
            video = nas_video.card_video(source, core.inventory(source)[0])
        self.assertEqual((video['count'], video['unreadable']), (4, 1))
        self.assertAlmostEqual(video['recorded'], 3661)
        self.assertEqual(nas_video.hm(video['recorded']), '1h 01m')
        self.assertIn('1h 01m of video in 4 files', nas_video.describe(video))

    def test_scan_reports_card_video(self):
        source = self.root / 'card' / 'Trinet' / 'recording'
        source.mkdir(parents=True)
        fake_mp4(source / 'take_L.mp4', 90)
        with patch.object(gui, 'removable_roots', return_value=[self.root / 'card']):
            [card] = gui.scan_cards()
        self.assertEqual(card['phase'], 'Ready')
        self.assertAlmostEqual(card['video']['recorded'], 90)


if __name__ == '__main__':
    unittest.main()
