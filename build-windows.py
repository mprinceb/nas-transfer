"""Build the Windows source installer bundle on any platform."""
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parent
out = root / 'dist' / 'EgoTrinetTransfer-0.3.0-Windows.zip'
out.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as archive:
    for name in ('nas_transfer.py', 'nas_transfer_cli.py', 'nas_windows.py', 'nas_paths.py', 'nas_config.py', 'README.md'):
        archive.write(root / name, name)
    for name in ('Install.cmd', 'Install.ps1'):
        archive.write(root / 'windows' / name, name)
print(out)
