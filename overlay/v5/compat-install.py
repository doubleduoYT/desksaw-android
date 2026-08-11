#!/usr/bin/env python3
from pathlib import Path
import re
import sys

if len(sys.argv) != 3:
    raise SystemExit("usage: compat-install.py <godot-project> <android-build-root>")

project = Path(sys.argv[1]).resolve()
android_root = Path(sys.argv[2]).resolve()

# Keep the stable package id/signing identity used by the Android port, but target
# the current Android platform instead of intentionally falling back to an old SDK.
preset = project / "export_presets.cfg"
text = preset.read_text(encoding="utf-8")
text = re.sub(r'package/unique_name="[^"]+"', 'package/unique_name="org.deedee14.desksaw.pet"', text)
text = re.sub(r'gradle_build/target_sdk="[^"]+"', 'gradle_build/target_sdk="36"', text)
text = re.sub(r'version/code=\d+', 'version/code=202', text)
text = re.sub(r'version/name="[^"]+"', 'version/name="0.2.1"', text)
preset.write_text(text, encoding="utf-8")

manifest = android_root / "src" / "main" / "AndroidManifest.xml"
xml = manifest.read_text(encoding="utf-8")
# deskSaw is an app-overlay toggle, not a replacement launcher/home app.
xml = re.sub(r'\s*<category android:name="android\.intent\.category\.HOME"\s*/>\s*', '\n', xml)
manifest.write_text(xml, encoding="utf-8")

print("Applied Android install compatibility settings")
print(" package: org.deedee14.desksaw.pet")
print(" targetSdk: 36")
print(" version: 0.2.1")
print(" kept foreground-service specialUse declarations required by modern Android")
print(" persistent signing is configured by CI")
