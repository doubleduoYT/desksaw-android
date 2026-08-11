#!/usr/bin/env python3
from pathlib import Path
import re
import sys

if len(sys.argv) != 3:
    raise SystemExit("usage: compat-install.py <godot-project> <android-build-root>")

project = Path(sys.argv[1]).resolve()
android_root = Path(sys.argv[2]).resolve()

# Use a fresh package id so this APK can install even when an older deskSaw build,
# signed with one of the previous ephemeral CI debug keys, is still installed.
preset = project / "export_presets.cfg"
text = preset.read_text(encoding="utf-8")
text = re.sub(r'package/unique_name="[^"]+"', 'package/unique_name="org.deedee14.desksaw.pet"', text)
text = re.sub(r'gradle_build/target_sdk="[^"]+"', 'gradle_build/target_sdk="33"', text)
text = re.sub(r'version/code=\d+', 'version/code=201', text)
text = re.sub(r'version/name="[^"]+"', 'version/name="0.2.1-android-touchfix"', text)
preset.write_text(text, encoding="utf-8")

# Target 33 deliberately: Android 14+ only requires an FGS type for apps targeting
# API 34+. This lets the same APK avoid API-34-only specialUse manifest metadata while
# remaining able to run a user-started foreground overlay service on newer Android.
service_candidates = list(android_root.rglob("DeskSawOverlayService.java"))
if len(service_candidates) != 1:
    raise SystemExit(f"Expected exactly one DeskSawOverlayService.java, got {service_candidates}")
service = service_candidates[0]
java = service.read_text(encoding="utf-8")
java = re.sub(
    r'\n\s*if \(Build\.VERSION\.SDK_INT >= Build\.VERSION_CODES\.UPSIDE_DOWN_CAKE\) \{\s*\n\s*startForeground\(NOTIFICATION_ID, notification, ServiceInfo\.FOREGROUND_SERVICE_TYPE_SPECIAL_USE\);\s*\n\s*\} else \{\s*\n\s*startForeground\(NOTIFICATION_ID, notification\);\s*\n\s*\}',
    '\n        startForeground(NOTIFICATION_ID, notification);',
    java,
    flags=re.MULTILINE,
)
service.write_text(java, encoding="utf-8")

manifest = android_root / "src" / "main" / "AndroidManifest.xml"
xml = manifest.read_text(encoding="utf-8")
xml = re.sub(r'\s*<uses-permission android:name="android\.permission\.FOREGROUND_SERVICE_SPECIAL_USE"\s*/>\s*', '\n', xml)
xml = re.sub(r'\s*android:foregroundServiceType="specialUse"', '', xml)
xml = re.sub(
    r'\s*<property\s+android:name="android\.app\.PROPERTY_SPECIAL_USE_FGS_SUBTYPE"\s+android:value="[^"]*"\s*/>\s*',
    '\n',
    xml,
    flags=re.MULTILINE,
)
# deskSaw is an app-overlay toggle, not a replacement launcher/home app.
xml = re.sub(r'\s*<category android:name="android\.intent\.category\.HOME"\s*/>\s*', '\n', xml)
manifest.write_text(xml, encoding="utf-8")

print("Applied install-compatibility patch")
print(" package: org.deedee14.desksaw.pet")
print(" targetSdk: 33")
print(" removed API-34 specialUse manifest requirements")
print(" persistent signing is configured by CI")
