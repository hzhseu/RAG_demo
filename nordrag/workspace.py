"""Only call cleanup after acquiring the application's lifetime lock."""
import re
import shutil
from pathlib import Path


def clean_abandoned_work(parent: Path):
    if not parent.exists():
        return
    for child in parent.iterdir():
        if not re.fullmatch(r"[a-f0-9]{20}-[a-z0-9_]+", child.name):
            continue
        if child.is_dir() and not child.is_symlink() and child.resolve().is_relative_to(parent.resolve()):
            shutil.rmtree(child)
