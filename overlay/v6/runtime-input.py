#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 3:
    raise SystemExit("usage: runtime-input.py <godot-project> <android-build-root>")

project = Path(sys.argv[1]).resolve()
android_root = Path(sys.argv[2]).resolve()

service_candidates = list(android_root.rglob("DeskSawOverlayService.java"))
if len(service_candidates) != 1:
    raise SystemExit(f"Expected exactly one DeskSawOverlayService.java, got {service_candidates}")
service = service_candidates[0]
java = service.read_text(encoding="utf-8")

# Android 12+ blocks touches that pass through a TYPE_APPLICATION_OVERLAY when
# the obscuring opacity is too high. Use the device-reported limit with real
# headroom instead of sitting right on the default 0.8 threshold.
java = java.replace(
    "import android.graphics.Rect;\n",
    "import android.graphics.Rect;\nimport android.hardware.input.InputManager;\n",
)
java = java.replace(
    "    private static final float VISUAL_OVERLAY_ALPHA = 0.79f;\n",
    "    private static final float LEGACY_VISUAL_OVERLAY_ALPHA = 0.70f;\n"
    "    private static final float MAX_VISUAL_OVERLAY_ALPHA = 0.70f;\n"
    "    private static final float OBSCURING_ALPHA_HEADROOM = 0.10f;\n",
)
java = java.replace(
    "        visualParams.alpha = VISUAL_OVERLAY_ALPHA;\n",
    "        visualParams.alpha = getSafeVisualOverlayAlpha();\n"
    "        Log.i(TAG, \"Visual overlay alpha=\" + visualParams.alpha);\n",
)
needle = "    public void setTouchRegion(String id, float x, float y, float width, float height) {\n"
helper = '''    private float getSafeVisualOverlayAlpha() {\n        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {\n            InputManager inputManager = (InputManager) getSystemService(Context.INPUT_SERVICE);\n            if (inputManager != null) {\n                float maximum = inputManager.getMaximumObscuringOpacityForTouch();\n                float safe = Math.max(0.20f, maximum - OBSCURING_ALPHA_HEADROOM);\n                return Math.min(MAX_VISUAL_OVERLAY_ALPHA, safe);\n            }\n        }\n        return LEGACY_VISUAL_OVERLAY_ALPHA;\n    }\n\n'''
if needle not in java:
    raise SystemExit("Could not locate touch-region insertion point")
java = java.replace(needle, helper + needle, 1)

# A transparent proxy is only a hit-test window. Keep its own window opacity
# tiny so it cannot contribute meaningful obscuring opacity on Samsung/Android.
java = java.replace("            params.alpha = 1.0f;\n", "            params.alpha = 0.01f;\n")

# Do not move/resize the WindowManager hit window while a gesture that began in
# it is active. Android keeps dispatching the pointer stream to the original
# window, and changing its local coordinate frame mid-drag causes jumps/stalls.
old_update = '''        if (proxy.spec.nearlyEquals(spec)) {\n            return;\n        }\n        proxy.spec = spec;\n        proxy.params.x = spec.x;\n        proxy.params.y = spec.y;\n        proxy.params.width = spec.width;\n        proxy.params.height = spec.height;\n        try {\n            windowManager.updateViewLayout(proxy.view, proxy.params);\n        } catch (RuntimeException error) {\n            Log.w(TAG, \"Failed to update touch region \" + id, error);\n        }\n'''
new_update = '''        if (proxy.gestureActive) {\n            proxy.pendingSpec = spec;\n            return;\n        }\n        applyProxySpec(id, proxy, spec);\n'''
if old_update not in java:
    raise SystemExit("Could not locate proxy update block")
java = java.replace(old_update, new_update, 1)

needle = "    private boolean forwardTouch(TouchProxy proxy, MotionEvent event) {\n"
helper = '''    private void applyProxySpec(String id, TouchProxy proxy, RegionSpec spec) {\n        if (proxy.spec.nearlyEquals(spec)) {\n            proxy.pendingSpec = null;\n            return;\n        }\n        proxy.spec = spec;\n        proxy.pendingSpec = null;\n        proxy.params.x = spec.x;\n        proxy.params.y = spec.y;\n        proxy.params.width = spec.width;\n        proxy.params.height = spec.height;\n        try {\n            windowManager.updateViewLayout(proxy.view, proxy.params);\n        } catch (RuntimeException error) {\n            Log.w(TAG, \"Failed to update touch region \" + id, error);\n        }\n    }\n\n    private void finishProxyGesture(TouchProxy proxy) {\n        proxy.gestureActive = false;\n        if (proxy.removeAfterGesture) {\n            proxy.removeAfterGesture = false;\n            touchProxies.values().remove(proxy);\n            safeRemoveView(proxy.view);\n            return;\n        }\n        if (proxy.pendingSpec != null) {\n            applyProxySpec(\"gesture\", proxy, proxy.pendingSpec);\n        }\n    }\n\n'''
if needle not in java:
    raise SystemExit("Could not locate forwardTouch")
java = java.replace(needle, helper + needle, 1)

# Defer removals too, otherwise hiding/deleting a limb while held tears down the
# view that owns the active MotionEvent stream.
old_remove = '''            TouchProxy proxy = touchProxies.remove(id);\n            if (proxy != null) {\n                safeRemoveView(proxy.view);\n            }\n'''
new_remove = '''            TouchProxy proxy = touchProxies.get(id);\n            if (proxy != null) {\n                if (proxy.gestureActive) {\n                    proxy.removeAfterGesture = true;\n                } else {\n                    touchProxies.remove(id);\n                    safeRemoveView(proxy.view);\n                }\n            }\n'''
if old_remove not in java:
    raise SystemExit("Could not locate removeTouchRegion block")
java = java.replace(old_remove, new_remove, 1)

old_touch = '''        @Override\n        public boolean onTouchEvent(MotionEvent event) {\n            return proxy != null && forwardTouch(proxy, event);\n        }\n'''
new_touch = '''        @Override\n        public boolean onTouchEvent(MotionEvent event) {\n            if (proxy == null) {\n                return false;\n            }\n            final int action = event.getActionMasked();\n            if (action == MotionEvent.ACTION_DOWN) {\n                proxy.gestureActive = true;\n                proxy.pendingSpec = null;\n                proxy.removeAfterGesture = false;\n            }\n            boolean handled = forwardTouch(proxy, event);\n            if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) {\n                mainHandler.post(() -> finishProxyGesture(proxy));\n            }\n            // Once DOWN lands on a pet hit window, own the full gesture until UP.\n            return action == MotionEvent.ACTION_DOWN || proxy.gestureActive || handled;\n        }\n'''
if old_touch not in java:
    raise SystemExit("Could not locate TouchProxyView.onTouchEvent")
java = java.replace(old_touch, new_touch, 1)

old_proxy_fields = '''        final TouchProxyView view;\n        final WindowManager.LayoutParams params;\n        RegionSpec spec;\n'''
new_proxy_fields = '''        final TouchProxyView view;\n        final WindowManager.LayoutParams params;\n        RegionSpec spec;\n        RegionSpec pendingSpec;\n        boolean gestureActive;\n        boolean removeAfterGesture;\n'''
if old_proxy_fields not in java:
    raise SystemExit("Could not locate TouchProxy fields")
java = java.replace(old_proxy_fields, new_proxy_fields, 1)
service.write_text(java, encoding="utf-8")

# Tighten mobile hit windows so a malformed/rotated collision AABB can never
# turn one limb into a giant dead rectangle over the launcher.
drag = project / "Scripts" / "impo" / "dragExp.gd"
gd = drag.read_text(encoding="utf-8")
gd = gd.replace(
    "const MOBILE_TOUCH_MARGIN := 12.0\n",
    "const MOBILE_TOUCH_MARGIN := 8.0\nconst MOBILE_TOUCH_MAX_SIDE := 220.0\n",
)
old = '''\t\trect = rect.grow(MOBILE_TOUCH_MARGIN)\n\t\t_android_overlay.setTouchRegion(\n'''
new = '''\t\trect = rect.grow(MOBILE_TOUCH_MARGIN)\n\t\t# Never let one rotated/far-away physics shape create a huge invisible\n\t\t# interception window. Keep the hit proxy centered on that limb.\n\t\tif rect.size.x > MOBILE_TOUCH_MAX_SIDE:\n\t\t\trect.position.x = body.global_position.x - MOBILE_TOUCH_MAX_SIDE * 0.5\n\t\t\trect.size.x = MOBILE_TOUCH_MAX_SIDE\n\t\tif rect.size.y > MOBILE_TOUCH_MAX_SIDE:\n\t\t\trect.position.y = body.global_position.y - MOBILE_TOUCH_MAX_SIDE * 0.5\n\t\t\trect.size.y = MOBILE_TOUCH_MAX_SIDE\n\t\t_android_overlay.setTouchRegion(\n'''
if old not in gd:
    raise SystemExit("Could not locate Android per-body touch rect block")
gd = gd.replace(old, new, 1)
drag.write_text(gd, encoding="utf-8")

print("Applied Android runtime input routing v6")
print(" dynamic safe visual overlay opacity")
print(" touch proxies frozen during active gestures")
print(" touch proxy opacity reduced to 0.01")
print(" oversized per-limb hit boxes capped")
