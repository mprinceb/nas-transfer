"""Windows removable storage and SMB integration; no third-party Python modules."""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path, PureWindowsPath
import subprocess
import sys
from urllib.parse import urlsplit


def unc_share(address):
    value = address.strip().replace('\\', '/')
    if value.startswith('//'):
        value = 'smb:' + value
    parsed = urlsplit(value if '://' in value else 'smb://' + value)
    if (parsed.scheme != 'smb' or not parsed.hostname or parsed.username or parsed.port
            or parsed.query or parsed.fragment or parsed.path.strip('/').lower() not in ('', 'ego')
            or ':' in parsed.hostname or any(c.isspace() for c in parsed.hostname)):
        raise ValueError('Use smb://sxd, smb://192.168.0.182/Ego, or \\\\sxd\\Ego.')
    return '\\\\' + parsed.hostname + '\\Ego'


def is_share_root(path):
    value = PureWindowsPath(str(path))
    return value.is_absolute() and value.drive.startswith('\\\\') and value == PureWindowsPath(value.anchor)


def removable_roots():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetLogicalDrives.restype = wintypes.DWORD
    kernel.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    kernel.GetDriveTypeW.restype = wintypes.UINT
    mask = kernel.GetLogicalDrives()
    roots = {f'{chr(65+i)}:\\' for i in range(26) if mask & (1 << i) and kernel.GetDriveTypeW(f'{chr(65+i)}:\\') == 2}
    # Some USB readers report fixed media rather than DRIVE_REMOVABLE.
    script = "@(Get-Disk | Where-Object {$_.BusType -in @('USB','SD','MMC')} | Get-Partition | Where-Object DriveLetter | ForEach-Object { [string]$_.DriveLetter + ':\\' }) | ConvertTo-Json -Compress"
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                                capture_output=True, text=True, timeout=15, creationflags=0x08000000)
        if result.returncode == 0 and result.stdout.strip():
            values = json.loads(result.stdout)
            if isinstance(values, str):
                values = [values]
            roots.update(p for p in (values or []) if len(p) == 3 and p[1:] == ':\\')
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass  # Native removable-drive enumeration still works.
    return sorted(Path(p) for p in roots)


def authenticate(remote):
    from nas_config import NAS_USER, NAS_PASSWORD
    class NETRESOURCE(ctypes.Structure):
        _fields_ = [('dwScope', wintypes.DWORD), ('dwType', wintypes.DWORD),
                    ('dwDisplayType', wintypes.DWORD), ('dwUsage', wintypes.DWORD),
                    ('lpLocalName', wintypes.LPWSTR), ('lpRemoteName', wintypes.LPWSTR),
                    ('lpComment', wintypes.LPWSTR), ('lpProvider', wintypes.LPWSTR)]
    api = ctypes.WinDLL('mpr', use_last_error=True).WNetAddConnection2W
    api.argtypes = [ctypes.POINTER(NETRESOURCE), wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    api.restype = wintypes.DWORD
    resource = NETRESOURCE()
    resource.dwType = 1  # RESOURCETYPE_DISK; connect without consuming a drive letter.
    resource.lpRemoteName = remote
    status = api(ctypes.byref(resource), NAS_PASSWORD, NAS_USER, 4)  # CONNECT_TEMPORARY
    if status == 1219:
        raise RuntimeError('Windows already has a connection to this NAS with different credentials. Disconnect that NAS in Windows or use its IP address, then retry.')
    if status:
        raise RuntimeError(f'Windows SMB error {status}: {ctypes.FormatError(status).strip()}')
    # Run in the helper process so an unresponsive share cannot freeze the UI.
    with __import__('os').scandir(remote) as entries:
        next(entries, None)


if __name__ == '__main__':
    try:
        authenticate(unc_share(sys.argv[1]))
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
