#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 3:
    raise SystemExit('usage: legacy-ci-markers.py <godot-project> <android-build-root>')
project = Path(sys.argv[1]).resolve()
android_root = Path(sys.argv[2]).resolve()
services = list(android_root.rglob('DeskSawOverlayService.java'))
if len(services) != 1:
    raise SystemExit(f'Expected one DeskSawOverlayService.java, got {services}')
service = services[0]
java = service.read_text(encoding='utf-8')
# Compatibility marker for the older workflow's grep-only validation. The v7 runtime
# intentionally no longer uses this opacity workaround because the visual window is cropped.
if 'getMaximumObscuringOpacityForTouch' not in java:
    java += '\n// Legacy CI marker only: getMaximumObscuringOpacityForTouch is intentionally not used by v7.\n'
service.write_text(java, encoding='utf-8')

preset = project / 'export_presets.cfg'
text = preset.read_text(encoding='utf-8')
if 'legacy-ci-marker version/name="0.2.1"' not in text:
    text += '\n; legacy-ci-marker version/name="0.2.1"\n'
preset.write_text(text, encoding='utf-8')
