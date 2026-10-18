#!/usr/bin/env python3
"""Create a clean source ZIP for BRO."""
from pathlib import Path
import os
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = os.environ.get("BRO_VERSION", "1.0.0")
OUTPUT = ROOT / f"BRO-Command-Center-v{VERSION}.zip"
EXCLUDED_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", "target", "node_modules", "data", "dist", "build"}
EXCLUDED_NAMES = {".env", ".DS_Store"}

def include(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    if any(part in EXCLUDED_DIRS for part in rel.parts[:-1]):
        return False
    if path.name in EXCLUDED_NAMES or path.suffix in {".pyc", ".db", ".zip"}:
        return False
    if path.name.startswith(".env.") and path.name != ".env.example":
        return False
    return path.is_file()

with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    for path in sorted(ROOT.rglob("*")):
        if path == OUTPUT or not include(path):
            continue
        archive.write(path, Path("BRO-Command-Center") / path.relative_to(ROOT))

print(f"Created {OUTPUT} ({OUTPUT.stat().st_size:,} bytes)")
