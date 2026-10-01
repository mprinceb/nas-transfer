#!/usr/bin/env python3
"""Terminal transfer utility. Run with --help for options."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
from urllib.parse import urlsplit

from nas_config import NAS_USER, NAS_PASSWORD, SHARE_NAME, MOUNT_ROOT

CHUNK = 4 * 1024 * 1024


def removable_roots():
    result = subprocess.run(
        ['lsblk', '--json', '--output', 'PATH,RM,TRAN,MOUNTPOINTS'],
        check=True, capture_output=True, text=True,
    )
    roots = set()
    def walk(nodes, removable=False):
        for node in nodes:
            removable_here = removable or bool(node.get('rm')) or node.get('tran') == 'usb'
            if removable_here:
                roots.update(Path(p) for p in node.get('mountpoints', []) if p)
            walk(node.get('children', []), removable_here)
    walk(json.loads(result.stdout)['blockdevices'])
    return sorted(roots)


def mount_nas(address):
    parsed = urlsplit(address if '://' in address else 'smb://' + address)
    if (parsed.scheme != 'smb' or not parsed.hostname or parsed.username
            or parsed.path.strip('/') not in ('', SHARE_NAME)):
        raise ValueError('Use smb://sxd, smb://sxd/Ego, or a NAS IP address.')
    remote = f'//{parsed.hostname}/{SHARE_NAME}'
    if os.path.ismount(MOUNT_ROOT):
        result = subprocess.run(['findmnt', '-rn', '-M', str(MOUNT_ROOT), '-o', 'SOURCE,FSTYPE'],
                                check=True, capture_output=True, text=True)
        parts = result.stdout.split()
        if len(parts) != 2 or parts[0].casefold() != remote.casefold() or parts[1] != 'cifs':
            raise RuntimeError(f'{MOUNT_ROOT} is mounted from a different source: {result.stdout.strip()}')
        return
    if not shutil.which('mount.cifs'):
        raise RuntimeError('Install cifs-utils first: sudo apt install cifs-utils')
    MOUNT_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', prefix='nas-credentials-') as credentials:
        credentials.write(f'username={NAS_USER}\npassword={NAS_PASSWORD}\n')
        credentials.flush()
        command = ['mount', '-t', 'cifs', remote, str(MOUNT_ROOT), '-o',
                   f'credentials={credentials.name},uid={os.getuid()},gid={os.getgid()},cache=none,iocharset=utf8']
        if os.geteuid() != 0:
            command.insert(0, 'sudo')
        subprocess.run(command, check=True)
    if not os.path.ismount(MOUNT_ROOT):
        raise RuntimeError('NAS mount did not appear.')


def signature(path):
    s = path.lstat()
    if not stat.S_ISREG(s.st_mode):
        raise RuntimeError(f'Not a regular file: {path}')
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def connect_nas(address):
    """Retry failed mounts with an operator-supplied SMB address."""
    while True:
        print(f'Connecting to {address} (share {SHARE_NAME}) as {NAS_USER}…', flush=True)
        try:
            mount_nas(address)
            return
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
            print(f'Could not connect to the NAS: {str(error).replace(NAS_PASSWORD, "[redacted]")}', flush=True)
        try:
            address = input(
                'Enter NAS address (e.g. smb://sxd/Ego or 192.168.1.50; blank to cancel): '
            ).strip()
        except EOFError:
            raise RuntimeError('No NAS address supplied. Retry with --nas smb://HOST/Ego.') from None
        if not address:
            raise RuntimeError('NAS connection cancelled.')


def inventory(root):
    files, dirs = {}, []
    for current, names, filenames in os.walk(root, followlinks=False):
        for name in names + filenames:
            p = Path(current) / name
            if p.is_symlink():
                raise RuntimeError(f'Symlinks are not supported: {p}')
        dirs.extend((Path(current) / n).relative_to(root) for n in names)
        for name in filenames:
            p = Path(current) / name
            files[p.relative_to(root)] = signature(p)
    return files, dirs


def digest(path, on_chunk=lambda n: None):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(CHUNK):
            h.update(chunk)
            on_chunk(len(chunk))
    return h.hexdigest()


def transfer(source, destination, keep_source=False):
    files, dirs = inventory(source)
    if not files:
        raise RuntimeError('No recording files found.')
    source_device = source.stat().st_dev
    nas_device = MOUNT_ROOT.stat().st_dev
    def check_mounts():
        if (not os.path.ismount(MOUNT_ROOT) or MOUNT_ROOT.stat().st_dev != nas_device
                or source.stat().st_dev != source_device):
            raise RuntimeError('A source or NAS mount changed. Cleanup stopped.')
    total = sum(s[2] for s in files.values())
    print(f'{len(files)} files, {total / 1024**3:.2f} GiB\nDestination: {destination}', flush=True)
    check_mounts()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir(exist_ok=False)
    for rel in dirs:
        (destination / rel).mkdir(parents=True, exist_ok=True)
    completed = 0
    def progress(n):
        nonlocal completed
        completed += n
        print(f'\rProgress: {completed / max(total * 3, 1):.1%} ({completed / 1024**2:.1f} MiB processed)', end='', flush=True)
    hashes = {}
    for rel, original in files.items():
        check_mounts()
        if signature(source / rel) != original:
            raise RuntimeError(f'Source changed: {rel}')
        h = hashlib.sha256()
        with (source / rel).open('rb') as reader, (destination / rel).open('xb') as writer:
            while chunk := reader.read(CHUNK):
                writer.write(chunk)
                h.update(chunk)
                progress(len(chunk))
            writer.flush()
            os.fsync(writer.fileno())
        if signature(source / rel) != original:
            raise RuntimeError(f'Source changed during copy: {rel}')
        hashes[rel] = h.hexdigest()
    print('\nVerifying NAS and rechecking source…', flush=True)
    for rel, original in files.items():
        check_mounts()
        if (signature(destination / rel)[2] != original[2]
                or digest(destination / rel, progress) != hashes[rel]
                or digest(source / rel, progress) != hashes[rel]
                or signature(source / rel) != original):
            raise RuntimeError(f'Verification failed: {rel}')
    current, current_dirs = inventory(source)
    if current != files or set(current_dirs) != set(dirs):
        raise RuntimeError('Source contents changed. Source cleanup skipped.')
    print('\nAll files verified.', flush=True)
    if keep_source:
        print('Source retained (--keep-source).')
        return
    print('Clearing verified source files…', flush=True)
    for rel, original in files.items():
        check_mounts()
        if signature(source / rel) != original:
            raise RuntimeError(f'Source changed during cleanup: {rel}')
        (source / rel).unlink()
    for rel in sorted(dirs, key=lambda p: len(p.parts), reverse=True):
        try:
            (source / rel).rmdir()
        except OSError:
            pass
    print(f'Complete. Recording files cleared; recording folder retained.\n{destination}')


def main():
    parser = argparse.ArgumentParser(description='Copy Trinet recordings to the NAS, verify, then clear copied source files.')
    parser.add_argument('--nas', default='smb://sxd', help='NAS hostname or SMB URL (default: smb://sxd)')
    parser.add_argument('--source', type=Path, help='Mounted removable drive root or its Trinet/recording folder')
    parser.add_argument('--title', help='Data title; prompted when omitted')
    parser.add_argument('--keep-source', action='store_true', help='Copy and verify without clearing the source')
    args = parser.parse_args()
    transfer_started = False
    try:
        connect_nas(args.nas)
        roots = removable_roots()
        if args.source:
            source = args.source.expanduser().absolute()
            if source.name != 'recording' or source.parent.name != 'Trinet':
                source = source / 'Trinet' / 'recording'
        else:
            choices = [p / 'Trinet' / 'recording' for p in roots if (p / 'Trinet' / 'recording').is_dir()]
            if not choices:
                raise RuntimeError('No mounted removable drive with Trinet/recording found. Mount the SD card and rerun; use --source /media/USER/CARD if needed.')
            if len(choices) == 1:
                source = choices[0]
            else:
                for i, path in enumerate(choices, 1):
                    print(f'{i}: {path}')
                selection = int(input('Select drive number: '))
                if not 1 <= selection <= len(choices):
                    raise ValueError('Invalid drive selection.')
                source = choices[selection - 1]
        if not source.is_dir() or source.resolve() != source or not any(source.is_relative_to(p) for p in roots):
            raise RuntimeError('Source must be a real Trinet/recording folder on a mounted removable drive.')
        title = (args.title if args.title is not None else input('Data title: ')).strip()
        if not title or title in ('.', '..') or any(c in title for c in '/\\\x00'):
            raise ValueError('Enter a nonempty data title without slashes.')
        destination = MOUNT_ROOT / datetime.datetime.now().strftime('%d%m%Y') / title
        transfer_started = True
        transfer(source, destination, args.keep_source)
    except (Exception, KeyboardInterrupt) as error:
        print(f'\nStopped: {str(error).replace(NAS_PASSWORD, "[redacted]") or "Interrupted"}')
        if transfer_started:
            print('Any partial NAS copy is retained. If cleanup had started, already verified files may have been removed from the source.')
        else:
            print('No recording files were copied or deleted.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
