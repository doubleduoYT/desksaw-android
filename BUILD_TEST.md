# Build test

This branch exists to trigger a pull-request build so the Android CI logs can be inspected and fixed before relying on main-branch builds.

Synchronization trigger: Android build diagnostic.

Toolchain hardening trigger: Godot 4.x settings + launcher fix.

Overlay v2 trigger: foreground desktop-pet service + Gradle build.

UID cache trigger: import before Gradle template install.

Fast template trigger: resolve main scene UID as res://scenes/loading.tscn.

Direct template trigger: unzip android_source.zip without editor installer.

Concurrency trigger: cancel stale headless builds and run the direct-template build.

Overlay v3 trigger: patch the real src/main AndroidManifest.xml.

ZIP CRC trigger: validate archive contents instead of byte-identical metadata.

V4 chunk trigger: rebuild exact overlay payload from six connector-safe chunks.

Per-chunk diagnostic trigger: verify exact length and SHA for all six v4 chunks.
