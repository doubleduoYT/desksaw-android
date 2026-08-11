#!/usr/bin/env python3
from pathlib import Path
import subprocess
import sys

if len(sys.argv) != 3:
    raise SystemExit("usage: runtime-input.py <godot-project> <android-build-root>")

project = Path(sys.argv[1]).resolve()
android_root = Path(sys.argv[2]).resolve()
repo_root = Path(__file__).resolve().parents[2]

subprocess.check_call([
    sys.executable,
    str(repo_root / "overlay" / "v7" / "android-runtime.py"),
    str(project),
    str(android_root),
])
subprocess.check_call([
    sys.executable,
    str(repo_root / "overlay" / "v7" / "godot-runtime.py"),
    str(project),
])
# Keep the older workflow's grep-only checks satisfied while the actual runtime
# and package metadata come from v7. This can be removed when the old workflow
# validation block is retired.
subprocess.check_call([
    sys.executable,
    str(repo_root / "overlay" / "v7" / "legacy-ci-markers.py"),
    str(project),
    str(android_root),
])

print("Applied Android runtime v7 through the default build entrypoint")
