# Trinet NAS Transfer

A small Tkinter utility for Linux that copies files under a mounted removable drive's `Trinet/recording/` folder to `Ego/DDMMYYYY/<title>/` on an SMB share named `Ego`. It shows byte progress, flushes each destination file and verifies its size plus SHA-256 content samples, then removes only the files in the source snapshot. When a title already exists, both apps automatically create title-2, title-3, and so on, preserving existing folders.

## Windows 10 / 11

1. Copy `dist/EgoTrinetTransfer-0.4.0-Windows.zip` to the Windows computer.
2. Right-click the ZIP and choose **Extract All**.
3. Double-click **Install.cmd** inside the extracted folder.
4. Open **Ego Trinet Transfer** from the desktop or Start menu.

The installer checks Python 3.10+ and Tkinter. If missing, it installs Python
3.12 for the current user using Windows Package Manager (`winget`). Internet
access is required for that download. If winget is unavailable, install Microsoft's
App Installer or Python from python.org with Tcl/Tk support, then retry.
No pip packages or Linux utilities are required on Windows.

The application is installed at `%LOCALAPPDATA%\EgoTrinetTransfer`.
Run the installer again to update it. To uninstall, delete that folder and the
Ego Trinet Transfer desktop/Start-menu shortcuts. NAS and SD-card data are separate.

Use `smb://sxd`, `smb://192.168.0.182/Ego`, or `\\sxd\Ego` in the NAS field.
The app authenticates with the saved account through the Windows SMB API and
uses the UNC share directly, without consuming a drive letter. Credentials are
not passed on command lines. It reconnects on launch; no boot-time service is added.
If Windows already has a session to this server under another account, the app
reports a credentials conflict without disconnecting unrelated Windows sessions.

Mount the SD cards so they appear in Explorer, then click **Rescan cards**.
Removable drives and USB/SD/MMC disks with drive letters are detected; the app
looks for `Trinet/recording` and supports up to 15 selected cards. Transfers remain
sequential and are verified before source cleanup. Double-click a card row for
its individual data title. **Keep source after verification** retains the card data.

For the CLI, run `%LOCALAPPDATA%\EgoTrinetTransfer\Ego-CLI.cmd` in a terminal.
This is a Python application installer, not a standalone compiled `.exe`.
Build the ZIP on Linux or Windows with `python build-windows.py`.

Windows integration uses Microsoft's [WNetAddConnection2W](https://learn.microsoft.com/en-us/windows/win32/api/winnetwk/nf-winnetwk-wnetaddconnection2w)
and [GetDriveTypeW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getdrivetypew) APIs.
Native Windows installation, SMB authentication, and physical card transfer still
require testing on a Windows PC; Linux and mocked Windows checks do not establish
that end-to-end result.

## Ubuntu / Debian desktop installation

Use `dist/trinet-nas-transfer_0.4.0_linux.tar.gz` on a desktop with apt and
Python 3.10 or newer available from its distribution repositories.

```bash
tar -xzf trinet-nas-transfer_0.4.0_linux.tar.gz
bash install.sh
```

The installer checks required system packages, refreshes apt metadata when
dependencies are missing, and installs the app and dependencies automatically.
It may ask for your local administrator password. Open **Ego Trinet Transfer**
from the application menu afterward. Both commands are installed system-wide:

```bash
trinet-nas-transfer
trinet-nas-transfer-cli
```

Run `bash install.sh --check` for a dependency report without installation.
To install the `.deb` directly and let apt resolve dependencies:

```bash
sudo apt install ./trinet-nas-transfer_0.4.0_all.deb
```

The package includes Python/Tkinter, CIFS, PolicyKit, util-linux, mount, and sudo
dependency declarations. Internet access to the configured apt repositories is
needed for missing packages. It installs an app-menu entry and icon. It does not
start a transfer during installation. Updates use the same installer command.

Remove the application with `sudo apt remove trinet-nas-transfer`. Recordings on
the NAS and SD cards are not part of the installed package and are not removed.
The app connects to the NAS when launched; this package does not configure a
boot-time NAS mount or start the app automatically at login.

This installer supports Ubuntu/Debian systems with apt. Other Linux distributions
can run the Python source after installing equivalent system packages.

### Build the internal installer

```bash
bash build-deb.sh
```

Requires `dpkg-deb` and standard Linux shell utilities; no root access or pip
downloads are needed to build. Outputs a `.deb` and portable installer bundle
under `dist/`. The bundle includes the configured internal NAS credentials.

## Run from source / install with pip

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
sudo apt install cifs-utils python3-tk pkexec python3-venv util-linux samba-common-bin libnss-mdns
```

You can also run directly with `python3 nas_transfer.py`.

## Desktop queue: up to 15 SD cards

1. Mount the SD cards in your Linux file manager, then click **Rescan cards**.
   The table lists removable/USB mounts containing `Trinet/recording`.
   The **Video** column shows how much footage each card holds, read from the
   MP4 headers (one camera of each `_L`/`_R` pair, plus unpaired videos). The
   summary line totals it for the selected cards, and the log repeats each card's
   length when its transfer completes. `ffprobe` is used as a fallback if installed.
2. Use the first column to select up to 15 ready cards. Empty or unreadable cards
   cannot be selected. The first 15 ready cards are selected after a scan.
3. Enter a shared **Data title**, or double-click a row to give that card its own
   title. Each card gets its own folder; repeated titles become `title-2`, `title-3`, etc.
4. Click **Transfer selected cards**. Cards run sequentially. Each row shows its
   state and progress; the overall bar averages progress across the selected cards.
   The activity log shows the actual destination for each card.
5. Each card is copied, read back from the NAS, and checked against the source
   before its verified files are cleared. Select **Keep source after verification**
   if you want to retain recordings on the cards.

Stop recording before scanning. Changed source contents stop the batch and require
a new scan. A failed card stops the remaining queue. **Stop queue** requests a stop
at the next I/O boundary; an outstanding network operation may take time to return.
Partial NAS copies are retained. If cleanup has begun, some already verified files
may have been cleared. Rescan before retrying. The `recording` folder is retained.
The desktop app supports a 15-card queue; the CLI still selects one card per run.

The app connects to `smb://sxd/Ego` on launch, even with no cards mounted. If the
connection fails, a dialog asks for another hostname, IP address, or SMB URL.
The saved credentials are reused. You can cancel and use **Connect** later.
Connection attempts have a 40-second UI deadline and a **Cancel** button.
The window can close immediately while connecting. Mount detection reads Linux's
mount table without accessing an unresponsive NAS folder. The app resolves hostnames using system DNS, `.local` mDNS, and NetBIOS.
When the NAS IP changes, the app mounts the new server at a separate local path
under `~/.local/share/nas-transfer/connections/<IP>/Ego`. It does not access or
unmount the stale server as part of reconnecting. NAS data still goes to the same
`Ego/DDMMYYYY/title` share layout. The connection log shows the active local path.
Hostname/IP aliases of the same server can reuse its existing mount.
The mount is at `~/.local/share/nas-transfer/Ego`. The mount operation may show
Linux's system authorization dialog. The NAS password itself is never requested.
Shared credentials are embedded in `nas_config.py`; keep the package internal.

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

Progress tracks copied bytes and stays below 100% until verification and cleanup finish.
After flushing each file, verification checks its size and compares up to three
64 KiB samples (beginning, middle, end) against bytes captured during copying.
Files up to 192 KiB are checked in full. Source metadata and the complete source
inventory are rechecked before cleanup, without rereading source contents.
This avoids two full read passes, but corruption outside sampled regions can go
undetected; it is a completion check, not full-file integrity verification.
By default, verified source files are deleted after all files pass verification.
`--keep-source` disables deletion. Existing destination folders are never
reused or overwritten; a numbered suffix is added automatically. Failed or interrupted copies remain on the NAS for manual
inspection; a retry automatically gets a new numbered folder. If cleanup is interrupted, some verified
files may already have been removed from the source. Only empty subdirectories
are removed; newly added files are never recursively erased.

CLI system requirements: Python 3.10+, `cifs-utils`, `sudo`, and util-linux
(`lsblk` and `findmnt`). Shared credentials are in `nas_config.py`.
