# Trinet NAS Transfer

A small Tkinter utility for Linux that copies files under a mounted removable drive's `Trinet/recording/` folder to `Ego/DDMMYYYY/<title>/` on an SMB share named `Ego`. It shows byte progress, verifies each destination file with SHA-256, then removes only the files in the source snapshot. It refuses to overwrite a destination folder.

## Install and run

Python 3.10 or newer is required. Install the app in a virtual environment:

```bash
cd /home/sarthak/nas_transfer
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/trinet-nas-transfer
```

The app has no third-party Python runtime dependencies. Pip installs the app
and its command, but cannot install Tkinter, `mount.cifs`, or `pkexec`.
On Debian/Ubuntu, install those system dependencies and venv support first:

```bash
sudo apt install cifs-utils python3-tk pkexec python3-venv
```

You can also run directly with `python3 nas_transfer.py`.

The app automatically attempts to mount `smb://sxd/Ego` on launch using the embedded NAS credentials. The NAS host field also accepts a hostname, IP address, or SMB URL. The optional Find NAS button scans the local IPv4 `/24` for TCP port 445. It stores the mount under `~/.local/share/nas-transfer/Ego`. The account password is embedded in the script for this internal tool; keep this folder private and do not publish or share it. The mount operation may show a system authorization dialog because creating a CIFS mount requires elevated system privileges.

The source is cleared only after SHA-256 verification. If the copy or verification fails, the source remains. The source recording folder itself is retained.

## Terminal version

Run the separate CLI file (no Tkinter required):

```bash
python3 nas_transfer_cli.py
```

It defaults to `smb://sxd/Ego`, uses the shared embedded credentials without
prompting for a NAS password, detects mounted removable drives with
`Trinet/recording`, and asks for the data title. If several drives match, it asks
you to select one. Stop recording before transferring and leave the card connected
until completion. Linux may prompt for your local sudo password to mount CIFS.

If the NAS connection fails, the CLI asks for another NAS address, such as
`smb://sxd/Ego` or `192.168.1.50`, and retries using the saved credentials.
Press Enter without an address to cancel. The destination share remains `Ego`.

After reinstalling with `pip install --upgrade .`, you can also use:

```bash
trinet-nas-transfer-cli --title kitchen-session
trinet-nas-transfer-cli --source /media/user/SDCARD --title kitchen-session --keep-source
trinet-nas-transfer-cli --nas smb://sxd --title kitchen-session
```

Progress covers copying, reading back the NAS copy, and rechecking the source.
By default, verified source files are deleted after all files pass verification.
`--keep-source` disables deletion. Existing destination folders are never
reused or overwritten. Failed or interrupted copies remain on the NAS for manual
inspection; use a new title for a retry. If cleanup is interrupted, some verified
files may already have been removed from the source. Only empty subdirectories
are removed; newly added files are never recursively erased.

CLI system requirements: Python 3.10+, `cifs-utils`, `sudo`, and util-linux
(`lsblk` and `findmnt`). Shared credentials are in `nas_config.py`.
