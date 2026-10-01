"""Destination folder allocation shared by the desktop and terminal apps."""
from pathlib import Path


def create_destination(requested: Path) -> Path:
    """Atomically reserve the first available title, title-2, title-3, ..."""
    requested.parent.mkdir(parents=True, exist_ok=True)
    candidate = requested
    suffix = 2
    while True:
        try:
            candidate.mkdir(exist_ok=False)
            return candidate
        except FileExistsError:
            candidate = requested.with_name(f"{requested.name}-{suffix}")
            suffix += 1
