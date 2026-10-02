#!/usr/bin/env python3
"""Terminal transfer utility. Run with --help for options."""
import argparse
import datetime
import hashlib
import ipaddress
import json
import os
import re
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

from nas_config import NAS_USER, NAS_PASSWORD, SHARE_NAME, MOUNT_ROOT
from nas_paths import create_destination

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


def mounted_nas():
    """Read kernel mount metadata without touching a possibly stalled CIFS path."""
    def unescape(value):
        return re.sub(r'\\([0-7]{3})', lambda match: chr(int(match[1], 8)), value)
    result = None
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        left, right = line.split(' - ', 1)
        fields = left.split()
        if unescape(fields[4]) == str(MOUNT_ROOT):
            filesystem, source, *_ = right.split()
            result = (unescape(source), filesystem)
    return result


def connection_command(command, cancel=None, timeout=35):
    """Bound waits, including pipe reads, and permit a desktop cancellation."""
    if cancel and cancel.is_set():
        raise RuntimeError('NAS connection cancelled.')
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    deadline = time.monotonic() + timeout
    try:
        while True:
            if cancel and cancel.is_set():
                raise RuntimeError('NAS connection cancelled.')
            if time.monotonic() >= deadline:
                raise RuntimeError('NAS connection timed out. Check the NAS address and network, then retry.')
            try:
                output, error = process.communicate(timeout=.2)
                if process.returncode:
                    raise RuntimeError((error or output or 'Connection command failed').strip())
                return output
            except subprocess.TimeoutExpired:
                continue
    finally:
        if process.poll() is None:
            try:
                process.kill()
                process.wait(timeout=.5)
            except (PermissionError, ProcessLookupError, subprocess.TimeoutExpired):
                # A privileged mount is bounded by its own root-owned timeout.
                pass
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()


def mounted_nas_ip():
    """The address used by an existing CIFS session, even after DNS changes."""
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        left, right = line.split(' - ', 1)
        mountpoint = re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), left.split()[4])
        if mountpoint == str(MOUNT_ROOT):
            for option in right.split()[2].split(','):
                if option.startswith('addr='):
                    return option[5:]
    return None


def reachable_nas_ip(host, cancel=None):
    """Try system DNS/mDNS, then Samba's LAN NetBIOS name service."""
    probe = ('import socket,sys; '
             's=socket.create_connection((sys.argv[1],445),timeout=3); '
             'print(s.getpeername()[0]); s.close()')
    names = [host]
    if '.' not in host and ':' not in host:
        names.append(host + '.local')
    def try_address(name):
        output = connection_command([sys.executable, '-c', probe, name], cancel=cancel, timeout=4)
        return str(ipaddress.ip_address(output.strip()))
    for name in names:
        try:
            return try_address(name)
        except (RuntimeError, ValueError):
            if cancel and cancel.is_set():
                raise RuntimeError('NAS connection cancelled.')
    if len(names) > 1 and shutil.which('nmblookup'):
        try:
            output = connection_command(['nmblookup', '--', host], cancel=cancel, timeout=4)
            for line in output.splitlines():
                fields = line.split()
                if not fields:
                    continue
                try:
                    address = str(ipaddress.ip_address(fields[0]))
                except ValueError:
                    continue
                return try_address(address)
        except (RuntimeError, ValueError):
            if cancel and cancel.is_set():
                raise RuntimeError('NAS connection cancelled.')
    raise RuntimeError(f'Cannot reach NAS {host} on SMB port 445. Check the network or enter its IP address.')


def mount_nas(address, authorization='sudo', cancel=None):
    parsed = urlsplit(address if '://' in address else 'smb://' + address)
    if (parsed.scheme != 'smb' or not parsed.hostname or parsed.username
            or parsed.path.strip('/') not in ('', SHARE_NAME)):
        raise ValueError('Use smb://sxd, smb://sxd/Ego, or a NAS IP address.')
    remote = f'//{parsed.hostname}/{SHARE_NAME}'
    existing = mounted_nas()
    if existing and (existing[1] != 'cifs' or existing[0].rsplit('/', 1)[-1].casefold() != SHARE_NAME.casefold()):
        raise RuntimeError('The application mount folder is used by a different filesystem or share. Unmount it manually first.')
    # Confirm the new server is reachable before changing the existing mount.
    resolved_ip = reachable_nas_ip(parsed.hostname, cancel)
    if existing:
        old_ip = mounted_nas_ip()
        if old_ip is None:
            try:
                old_ip = str(ipaddress.ip_address(urlsplit('smb:' + existing[0]).hostname))
            except ValueError:
                pass
        if old_ip == resolved_ip:
            return
    if not shutil.which('mount.cifs'):
        raise RuntimeError('Install cifs-utils first: sudo apt install cifs-utils')
    def privileged(command):
        if os.geteuid() != 0:
            command.insert(0, authorization)
        return connection_command(command, cancel=cancel)
    if existing:
        try:
            privileged(['timeout', '--kill-after=2s', '12s', 'umount', '--', str(MOUNT_ROOT)])
        except RuntimeError as error:
            raise RuntimeError(f'Could not disconnect the old NAS {existing[0]}. Close files or transfers using it, then retry. {error}') from error
        if mounted_nas():
            raise RuntimeError('The old NAS is still mounted. Reconnect stopped.')
    if cancel and cancel.is_set():
        raise RuntimeError('NAS connection cancelled.')
    MOUNT_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', prefix='nas-credentials-') as credentials:
        credentials.write(f'username={NAS_USER}\npassword={NAS_PASSWORD}\n')
        credentials.flush()
        privileged(['timeout', '--kill-after=2s', '25s', 'mount', '-t', 'cifs', remote, str(MOUNT_ROOT), '-o',
                    f'credentials={credentials.name},uid={os.getuid()},gid={os.getgid()},ip={resolved_ip},cache=none,iocharset=utf8'])
    if mounted_nas() != (remote, 'cifs'):
        raise RuntimeError('Expected NAS mount did not appear.')


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
    def on_error(error):
        raise error
    for current, names, filenames in os.walk(root, followlinks=False, onerror=on_error):
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


class TransferCancelled(RuntimeError):
    pass


def transfer(source, destination, keep_source=False, notify=None, cancel=None, expected=None):
    """Optional callbacks allow the desktop app to share the verified CLI transfer."""
    phase = 'Preparing'
    def emit(**event):
        if notify:
            notify(event)
    def say(message):
        if notify:
            emit(message=message)
        else:
            print(message, flush=True)
    def check_cancel():
        if cancel and cancel.is_set():
            raise TransferCancelled('Stopped by user. Any partial NAS copy is retained.')
    check_cancel()
    files, dirs = inventory(source)
    if expected is not None and files != expected:
        raise RuntimeError('Card contents changed since scanning. Rescan the cards before transferring.')
    if not files:
        raise RuntimeError('No recording files found.')
    source_device = source.stat().st_dev
    nas_device = MOUNT_ROOT.stat().st_dev
    def check_mounts():
        check_cancel()
        if (not os.path.ismount(MOUNT_ROOT) or MOUNT_ROOT.stat().st_dev != nas_device
                or source.stat().st_dev != source_device):
            raise RuntimeError('A source or NAS mount changed. Cleanup stopped.')
    total = sum(s[2] for s in files.values())
    check_mounts()
    destination = create_destination(destination)
    emit(destination=str(destination))
    say(f'{len(files)} files, {total / 1024**3:.2f} GiB\nDestination: {destination}')
    for rel in dirs:
        (destination / rel).mkdir(parents=True, exist_ok=True)
    completed = 0
    last_report = 0.0
    def progress(n):
        nonlocal completed, last_report
        check_cancel()
        completed += n
        now = time.monotonic()
        if now - last_report >= .1:
            last_report = now
            fraction = min(completed / max(total * 3, 1), .99)
            if notify:
                emit(phase=phase, progress=fraction)
            else:
                print(f'\rProgress: {fraction:.1%} ({completed / 1024**2:.1f} MiB processed)', end='', flush=True)
    hashes = {}
    phase = 'Copying'
    emit(phase=phase, progress=0.0)
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
    phase = 'Verifying'
    emit(phase=phase)
    say('\nVerifying NAS and rechecking source…')
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
    check_mounts()
    say('\nAll files verified.')
    if keep_source:
        say('Source retained (--keep-source).')
        emit(phase='Complete · source kept', progress=1.0)
        return destination
    emit(phase='Clearing verified files')
    say('Clearing verified source files…')
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
    say(f'Complete. Recording files cleared; recording folder retained.\n{destination}')
    emit(phase='Complete', progress=1.0)
    return destination


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
