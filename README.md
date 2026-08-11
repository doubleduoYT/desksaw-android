# deskSaw Android build

Android port/build harness for [dee-dee-catorce/desksaw](https://github.com/dee-dee-catorce/desksaw).

The repository intentionally stores only the Android patch and CI configuration. GitHub Actions clones the upstream `master` branch, applies `patches/android-port.patch`, installs Godot 4.7 export templates, and exports an arm64 Android APK.

Build output is uploaded as the `desksaw-android-apk` Actions artifact.
