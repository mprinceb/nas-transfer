#!/usr/bin/env python3
"""Transfer Trinet recordings to a NAS SMB share with progress and verification."""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import threading
import time
import tkinter as tk
from urllib.parse import urlsplit
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

from nas_config import NAS_USER, NAS_PASSWORD, SHARE_NAME, MOUNT_ROOT
from nas_paths import create_destination


def mounted_devices() -> list[Path]:
    """Find removable mounts, prioritizing the requested Trinet/recording path."""
    candidates: list[Path] = []
    for root in (Path("/media") / os.environ.get("USER", ""), Path("/run/media") / os.environ.get("USER", ""), Path("/mnt")):
        if root.is_dir():
            candidates.extend(p for p in root.iterdir() if p.is_dir())
    return candidates


def discover_nas(timeout: float = 1.4) -> list[str]:
    """Find SMB hosts on the local IPv4 /24 by probing TCP/445 concurrently."""
    try:
        local_ip = socket.gethostbyname(socket.gethostname())
        octets = local_ip.split(".")
        if len(octets) != 4:
            return []
        prefix = ".".join(octets[:3]) + "."
    except OSError:
        return []
    found: list[str] = []
    lock = threading.Lock()
    def probe(host: str) -> None:
        try:
            with socket.create_connection((host, 445), timeout=timeout):
                with lock:
                    found.append(host)
        except OSError:
            pass
    threads = [
        threading.Thread(target=probe, args=(prefix + str(i),), daemon=True)
        for i in range(1, 255)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout + .2)
    return sorted(found, key=lambda x: tuple(map(int, x.split('.'))))


def run(cmd: list[str], timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, check=False)


class TransferApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Trinet NAS Transfer")
        root.geometry("650x480")
        root.minsize(560, 420)
        self.status = tk.StringVar(value="Connect the removable drive, then find the NAS.")
        self.source = tk.StringVar(value="Not detected")
        self.target = tk.StringVar(value="Not mounted")
        self.title_var = tk.StringVar()
        self.progress = tk.DoubleVar(value=0)
        self.busy = False
        self.hosts: list[str] = []

        frame = ttk.Frame(root, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Trinet recording transfer", font=("TkDefaultFont", 16, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Copy Trinet/recording to the NAS and verify it before clearing the card.", wraplength=590).pack(anchor="w", pady=(4, 14))

        ttk.Label(frame, text="Removable drive").pack(anchor="w")
        row = ttk.Frame(frame); row.pack(fill="x", pady=(2, 8))
        ttk.Label(row, textvariable=self.source).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Rescan drives", command=self.refresh_drives).pack(side="right")

        ttk.Label(frame, text="NAS host").pack(anchor="w")
        row = ttk.Frame(frame); row.pack(fill="x", pady=(2, 8))
        self.host_combo = ttk.Combobox(row, values=["smb://sxd"])
        self.host_combo.set("smb://sxd")
        self.host_combo.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Find NAS", command=self.find_nas).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="Mount", command=self.mount_nas).pack(side="left", padx=(8, 0))

        ttk.Label(frame, text="Data title").pack(anchor="w")
        ttk.Entry(frame, textvariable=self.title_var).pack(fill="x", pady=(2, 8))
        ttk.Label(frame, textvariable=self.target).pack(anchor="w", pady=(0, 8))
        self.start_btn = ttk.Button(frame, text="Copy, verify, and clear SD card", command=self.start_transfer)
        self.start_btn.pack(anchor="w", pady=(0, 12))
        self.bar = ttk.Progressbar(frame, variable=self.progress, maximum=100)
        self.bar.pack(fill="x")
        ttk.Label(frame, textvariable=self.status, wraplength=600).pack(anchor="w", pady=(10, 0))
        self.log = tk.Text(frame, height=9, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True, pady=(10, 0))
        self.refresh_drives()
        self.root.after(300, self.mount_nas)

    def append(self, msg: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")
        self.status.set(msg)

    def ui(self, fn, *args) -> None:
        self.root.after(0, fn, *args)

    def refresh_drives(self) -> None:
        matches = []
        for mount in mounted_devices():
            expected = mount / "Trinet" / "recording"
            if expected.is_dir():
                matches.append(expected)
        if matches:
            self.source.set(str(matches[0]))
            self.append(f"Found recording folder: {matches[0]}")
        else:
            self.source.set("No mounted removable drive with Trinet/recording found")

    def find_nas(self) -> None:
        if self.busy: return
        self.busy = True
        self.append("Scanning local network for SMB servers…")
        def worker():
            hosts = discover_nas()
            self.hosts = hosts
            def done():
                self.busy = False
                self.host_combo["values"] = hosts
                if hosts:
                    self.host_combo.current(0)
                    self.append(f"Found {len(hosts)} SMB host(s). Select the NAS and mount it.")
                else:
                    self.ask_nas_address("No SMB hosts were found on the network.")
            self.ui(done)
        threading.Thread(target=worker, daemon=True).start()

    def ask_nas_address(self, reason: str) -> None:
        """Called on the UI thread after discovery or mounting fails."""
        self.busy = False
        reason = reason.replace(NAS_PASSWORD, "[redacted]")
        self.append(reason)
        address = simpledialog.askstring(
            "Connect to NAS",
            f"{reason}\n\nEnter the NAS address, for example:\n"
            "smb://sxd/Ego or 192.168.1.50\n\n"
            "The saved NAS username and password will be used.",
            initialvalue=self.host_combo.get(),
            parent=self.root,
        )
        if address and address.strip():
            self.host_combo.set(address.strip())
            self.mount_nas()
        else:
            self.append("NAS connection cancelled. Enter an address and click Mount to retry.")

    def mount_nas(self) -> None:
        if self.busy: return
        address = self.host_combo.get().strip()
        try:
            parsed = urlsplit(address if "://" in address else "smb://" + address)
            host = parsed.hostname
            if not host or parsed.scheme != "smb" or parsed.username or parsed.path.strip("/") not in ("", SHARE_NAME):
                raise ValueError("Use smb://sxd, smb://sxd/Ego, or a NAS IP address.")
        except ValueError as error:
            self.root.after(0, self.ask_nas_address, f"Invalid NAS address: {error}")
            return
        if shutil.which("mount.cifs") is None:
            messagebox.showerror("Missing CIFS tools", "Install cifs-utils (for example: sudo apt install cifs-utils), then retry."); return
        self.busy = True
        self.append(f"Mounting //{host}/{SHARE_NAME}…")
        def worker():
            try:
                MOUNT_ROOT.parent.mkdir(parents=True, exist_ok=True)
                if not os.path.ismount(MOUNT_ROOT):
                    MOUNT_ROOT.mkdir(parents=True, exist_ok=True)
                    # Pass credentials through a private file, never command arguments.
                    cred = MOUNT_ROOT.parent / ".credentials"
                    fd = os.open(cred, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                    with os.fdopen(fd, "w") as f:
                        f.write(f"username={NAS_USER}\npassword={NAS_PASSWORD}\n")
                    try:
                        result = run(["pkexec", "mount", "-t", "cifs", f"//{host}/{SHARE_NAME}", str(MOUNT_ROOT), "-o", f"credentials={cred},uid={os.getuid()},gid={os.getgid()},iocharset=utf8"], timeout=45)
                    finally:
                        cred.unlink(missing_ok=True)
                    if result.returncode != 0:
                        raise RuntimeError((result.stderr or result.stdout or "Mount failed").strip())
                self.ui(self.target.set, f"NAS destination: {MOUNT_ROOT}/ddmmyyyy/datatitle/")
                self.ui(self.append, f"Mounted {host}:{SHARE_NAME} at {MOUNT_ROOT}")
            except Exception as e:
                self.ui(self.ask_nas_address, f"Mount failed: {e}")
            else:
                self.ui(setattr, self, "busy", False)
        threading.Thread(target=worker, daemon=True).start()

    def start_transfer(self) -> None:
        if self.busy: return
        src = Path(self.source.get())
        title = self.title_var.get().strip()
        if not src.is_dir():
            messagebox.showerror("Source missing", "Mount the removable drive containing Trinet/recording, then rescan."); return
        if not title or title in {".", ".."} or "/" in title or "\\" in title:
            messagebox.showerror("Invalid title", "Enter a folder name without slashes."); return
        if not os.path.ismount(MOUNT_ROOT):
            messagebox.showerror("NAS not mounted", "Find and mount the NAS before transferring."); return
        date_dir = time.strftime("%d%m%Y")
        dest = MOUNT_ROOT / date_dir / title
        files = [p for p in src.rglob("*") if p.is_file() and not p.is_symlink()]
        total = sum(p.stat().st_size for p in files)
        if not files:
            messagebox.showerror("No data", f"No files found under {src}."); return
        if not messagebox.askyesno("Confirm transfer and erase", f"Copy {len(files)} files ({total / (1024**3):.2f} GiB) to:\n{dest}\n\nAn existing destination gets a numbered suffix automatically.\n\nAfter size and SHA-256 verification, all contents of {src} will be deleted. Continue?"):
            return
        self.busy = True
        self.start_btn.state(["disabled"])
        self.progress.set(0)
        self.append(f"Copying {len(files)} files ({total} bytes)…")
        threading.Thread(target=self._transfer_worker, args=(src, dest, files, total), daemon=True).start()

    def _transfer_worker(self, src: Path, dest: Path, files: list[Path], total: int) -> None:
        import hashlib
        copied = 0
        try:
            dest = create_destination(dest)
            self.ui(self.target.set, f"NAS destination: {dest}")
            self.ui(self.append, f"Copying to {dest}")
            hashes: list[tuple[Path, str, int]] = []
            for index, source in enumerate(files, 1):
                rel = source.relative_to(src)
                target = dest / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                h = hashlib.sha256(); size = 0
                with source.open("rb") as rf, target.open("xb") as wf:
                    while True:
                        chunk = rf.read(4 * 1024 * 1024)
                        if not chunk: break
                        wf.write(chunk); h.update(chunk); size += len(chunk); copied += len(chunk)
                        pct = 100 * copied / total if total else 100
                        self.ui(self.progress.set, pct)
                        self.ui(self.status.set, f"Copying {index}/{len(files)}: {rel} ({pct:.1f}%)")
                    wf.flush(); os.fsync(wf.fileno())
                hashes.append((rel, h.hexdigest(), size))
            self.ui(self.append, "Copy finished. Verifying NAS files by size and SHA-256…")
            for idx, (rel, expected, expected_size) in enumerate(hashes, 1):
                target = dest / rel
                h = hashlib.sha256(); size = 0
                with target.open("rb") as f:
                    for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
                        h.update(chunk); size += len(chunk)
                if size != expected_size or h.hexdigest() != expected:
                    raise RuntimeError(f"Verification failed for {rel}; source was kept.")
                self.ui(self.progress.set, 100 * idx / len(hashes))
                self.ui(self.status.set, f"Verifying {idx}/{len(hashes)}: {rel}")
            # Remove only the contents captured by the source snapshot; retain source folder.
            for source in files:
                source.unlink()
            for directory in sorted(
                (p for p in src.rglob("*") if p.is_dir() and not p.is_symlink()),
                key=lambda p: len(p.parts),
                reverse=True,
            ):
                try:
                    directory.rmdir()
                except OSError:
                    pass
            self.ui(self.append, f"Verified {len(files)} files. Cleared SD data. Destination: {dest}")
            self.ui(messagebox.showinfo, "Transfer complete", f"Copied and verified {len(files)} files.\nSD recording contents cleared.\n\n{dest}")
        except Exception as e:
            self.ui(self.append, f"Transfer stopped: {e}")
            self.ui(messagebox.showerror, "Transfer failed", f"The source data was kept.\n\n{e}")
        finally:
            self.ui(setattr, self, "busy", False)
            self.ui(self.start_btn.state, ["!disabled"])


def main() -> None:
    root = tk.Tk()
    TransferApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
