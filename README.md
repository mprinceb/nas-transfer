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

The app scans the local IPv4 `/24` for TCP port 445. It stores the mount under `~/.local/share/nas-transfer/Ego`. The account password is currently embedded in the script for this internal tool; keep this folder private and do not publish or share it. The mount operation may show a system authorization dialog because creating a CIFS mount requires elevated system privileges.

The source is cleared only after SHA-256 verification. If the copy or verification fails, the source remains. The source recording folder itself is retained.
