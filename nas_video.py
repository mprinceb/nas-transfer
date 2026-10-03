"""Video length of a card's recordings, read from file headers only.

Adapted from nas_video_analyzer's nas_video_core: the duration comes from the
MP4/MOV 'mvhd' box, falling back to ffprobe when it is installed.
"""
import os
import re
import shutil
import struct
import subprocess
import sys

VIDEO_EXTS = ('.mp4', '.mov', '.mkv', '.avi', '.m4v')

# take0001_L.mp4, take0001_L (copy).mp4, take0002_R (another copy).mp4
SIDE_RE = re.compile(r'_([LR])(?: \([^)]*\))?\.[^./]+$', re.IGNORECASE)


def _mvhd_in(buf):
    """Duration from the last plausible 'mvhd' box inside buf, or None."""
    i = buf.rfind(b'mvhd')
    while i >= 4:
        box_size = struct.unpack('>I', buf[i - 4:i])[0]
        version = buf[i + 4] if i + 4 < len(buf) else None
        if version == 0 and box_size >= 108 and i + 24 <= len(buf):
            timescale, duration = struct.unpack('>II', buf[i + 16:i + 24])
        elif version == 1 and box_size >= 120 and i + 36 <= len(buf):
            timescale, duration = struct.unpack('>IQ', buf[i + 24:i + 36])
        else:
            timescale = duration = 0
        if timescale and duration:
            return duration / timescale
        i = buf.rfind(b'mvhd', 0, i)
    return None


def mp4_duration(path, max_tail=32 << 20):
    """Read the start (moov-first files), then a growing window from the end,
    where the cameras put the moov index."""
    with open(path, 'rb') as f:
        size = os.fstat(f.fileno()).st_size
        head = f.read(min(size, 1 << 20))
        if b'moov' in head:
            secs = _mvhd_in(head)
            if secs is not None:
                return secs
        tail = 1 << 20
        while True:
            start = max(0, size - tail)
            f.seek(start)
            secs = _mvhd_in(f.read(size - start))
            if secs is not None or start == 0 or tail >= max_tail:
                return secs
            tail *= 2


def ffprobe_duration(path):
    if not shutil.which('ffprobe'):
        return None
    try:
        res = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                              '-of', 'csv=p=0', str(path)], capture_output=True, text=True,
                             timeout=120, creationflags=0x08000000 if sys.platform == 'win32' else 0)
        return float(res.stdout.strip())
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def duration(path):
    try:
        secs = mp4_duration(path)
    except (OSError, struct.error, IndexError):
        secs = None
    return secs if secs is not None else ffprobe_duration(path)


def side_of(path):
    m = SIDE_RE.search(str(path))
    return m.group(1).upper() if m else '?'


def card_video(source, files):
    """files: inventory() mapping of relative path -> signature.

    Returns dict(count, unreadable, L, R, other, recorded). recorded is the
    footage length: one camera of each L/R pair plus unpaired 'other' videos.
    """
    secs = {'L': 0.0, 'R': 0.0, '?': 0.0}
    count = unreadable = 0
    for rel, sig in files.items():
        if not str(rel).lower().endswith(VIDEO_EXTS):
            continue
        count += 1
        value = duration(source / rel) if sig[2] else None
        if value is None:
            unreadable += 1
        else:
            secs[side_of(rel)] += value
    return dict(count=count, unreadable=unreadable, L=secs['L'], R=secs['R'], other=secs['?'],
                recorded=max(secs['L'], secs['R']) + secs['?'])


def hm(secs):
    minutes = int(round(secs / 60))
    return f'{minutes // 60}h {minutes % 60:02d}m'


def describe(video):
    """'1h 23m of video (L+R 2h 46m)' style one-liner for logs."""
    if not video or not video['count']:
        return 'no videos'
    text = f'{hm(video["recorded"])} of video in {video["count"]} files'
    if video['L'] and video['R']:
        text += f' (L {hm(video["L"])} · R {hm(video["R"])})'
    if video['unreadable']:
        text += f', {video["unreadable"]} unreadable'
    return text
