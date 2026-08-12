#!/usr/bin/env python3
from pathlib import Path
import re
import sys

if len(sys.argv) != 3:
    raise SystemExit('usage: runtime-input.py <godot-project> <android-build-root>')

project = Path(sys.argv[1]).resolve()
android_root = Path(sys.argv[2]).resolve()

# ---------------------------------------------------------------------------
# Android native input: stop depending on separate touch proxy windows.
# The cropped Godot SurfaceView receives touch directly and hit-tests against
# the registered pet/console regions. Proxy windows stay only as geometry
# records for cropping and are completely transparent + NOT_TOUCHABLE.
# ---------------------------------------------------------------------------
service_candidates = list(android_root.rglob('DeskSawOverlayService.java'))
plugin_candidates = list(android_root.rglob('DeskSawOverlayPlugin.java'))
if len(service_candidates) != 1 or len(plugin_candidates) != 1:
    raise SystemExit(f'Expected one service/plugin, got {service_candidates} / {plugin_candidates}')
service = service_candidates[0]
plugin = plugin_candidates[0]
java = service.read_text(encoding='utf-8')

old = '''            addVisualOverlay();
            godot.onStart(this);'''
new = '''            addVisualOverlay();
            installDirectInput();
            godot.onStart(this);'''
if old not in java:
    raise SystemExit('Could not locate addVisualOverlay startup block')
java = java.replace(old, new, 1)

old = '''            WindowManager.LayoutParams params = new WindowManager.LayoutParams(
                    spec.width,
                    spec.height,
                    overlayWindowType(),
                    WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
                            | WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL
                            | WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN
                            | WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
                    PixelFormat.TRANSLUCENT);'''
new = '''            WindowManager.LayoutParams params = new WindowManager.LayoutParams(
                    spec.width,
                    spec.height,
                    overlayWindowType(),
                    WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
                            | WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL
                            | WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
                            | WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN
                            | WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
                    PixelFormat.TRANSLUCENT);'''
if old not in java:
    raise SystemExit('Could not locate touch proxy LayoutParams block')
java = java.replace(old, new, 1)
java = java.replace('            params.alpha = 0.01f;\n', '            params.alpha = 0.0f;\n', 1)

needle = '    private boolean forwardTouch(TouchProxy proxy, MotionEvent event) {\n'
helper = r'''    private void installDirectInput() {
        if (godot == null) return;
        GodotRenderView renderView = godot.getRenderView();
        if (renderView == null) return;
        SurfaceView surface = renderView.getView();
        if (surface == null) return;
        surface.setClickable(true);
        surface.setOnTouchListener((view, event) -> handleVisualTouch(event));
        Log.i(TAG, "Direct SurfaceView input installed");
    }

    private RegionSpec effectiveSpec(TouchProxy proxy) {
        if (proxy == null) return null;
        return proxy.pendingSpec != null ? proxy.pendingSpec : proxy.spec;
    }

    private String findOwnerAt(float screenX, float screenY) {
        TouchProxy console = touchProxies.get("__console");
        RegionSpec consoleSpec = effectiveSpec(console);
        if (consoleSpec != null && consoleSpec.contains(screenX, screenY)) {
            return "__console";
        }

        String bestId = "";
        long bestArea = Long.MAX_VALUE;
        for (Map.Entry<String, TouchProxy> entry : touchProxies.entrySet()) {
            if ("__console".equals(entry.getKey())) continue;
            RegionSpec spec = effectiveSpec(entry.getValue());
            if (spec == null || !spec.contains(screenX, screenY)) continue;
            long area = (long) spec.width * (long) spec.height;
            if (area < bestArea) {
                bestArea = area;
                bestId = entry.getKey();
            }
        }
        return bestId;
    }

    private boolean handleVisualTouch(MotionEvent event) {
        if (event == null) return false;
        final int action = event.getActionMasked();
        final float screenX = event.getX(0) + visualOriginX;
        final float screenY = event.getY(0) + visualOriginY;

        if (action == MotionEvent.ACTION_DOWN) {
            pointerSequence += 1;
            pointerOwner = findOwnerAt(screenX, screenY);
            pointerX = screenX;
            pointerY = screenY;
            pointerDown = true;
            Log.d(TAG, "DOWN owner=" + pointerOwner + " x=" + screenX + " y=" + screenY);
        } else if (pointerDown) {
            pointerX = screenX;
            pointerY = screenY;
        }

        boolean handled = false;
        if (godot != null) {
            GodotRenderView renderView = godot.getRenderView();
            if (renderView != null && renderView.getInputHandler() != null) {
                handled = renderView.getInputHandler().onTouchEvent(event);
            }
        }

        if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) {
            pointerX = screenX;
            pointerY = screenY;
            pointerDown = false;
        }

        // The cropped Godot window is intentionally interactive. Outside this
        // rectangle no DeskSaw window exists, so background apps still receive
        // their own touches normally.
        return true || handled;
    }

    public void setConsoleInteractive(boolean interactive) {
        mainHandler.post(() -> {
            if (visualParams == null || godotContainer == null || windowManager == null) return;
            int flags = visualParams.flags;
            int desired = interactive
                    ? (flags & ~WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE)
                    : (flags | WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE);
            if (desired == flags) return;
            visualParams.flags = desired;
            try {
                windowManager.updateViewLayout(godotContainer, visualParams);
                if (interactive) godotContainer.requestFocus();
            } catch (RuntimeException error) {
                Log.w(TAG, "Unable to change console focus mode", error);
            }
        });
    }

'''
if needle not in java:
    raise SystemExit('Could not locate forwardTouch insertion point')
java = java.replace(needle, helper + needle, 1)

needle = '        boolean nearlyEquals(RegionSpec other) {\n'
contains = '''        boolean contains(float px, float py) {\n            return px >= x && py >= y && px < x + width && py < y + height;\n        }\n'''
if needle not in java:
    raise SystemExit('Could not locate RegionSpec.nearlyEquals')
java = java.replace(needle, contains + needle, 1)
service.write_text(java, encoding='utf-8')

plugin_text = plugin.read_text(encoding='utf-8')
needle = '    @UsedByGodot public boolean isOverlayRunning() { return true; }\n'
insert = '    @UsedByGodot public void setConsoleInteractive(boolean interactive) { service.setConsoleInteractive(interactive); }\n'
if needle not in plugin_text:
    raise SystemExit('Could not locate plugin insertion point')
plugin_text = plugin_text.replace(needle, needle + insert, 1)
plugin.write_text(plugin_text, encoding='utf-8')

# ---------------------------------------------------------------------------
# Godot: make the native pointer path a fallback instead of the only input.
# Direct SurfaceView events now reach physics picking and Control nodes.
# ---------------------------------------------------------------------------
window_path = project / 'Scripts' / 'nimpo' / 'windowHandler.gd'
window = window_path.read_text(encoding='utf-8')
window = window.replace(
    '\tmouse_filter = Control.MOUSE_FILTER_IGNORE\n',
    '\tmouse_filter = Control.MOUSE_FILTER_PASS if OS.get_name() == "Android" else Control.MOUSE_FILTER_IGNORE\n',
    1,
)
old = '''func _downDrag() -> void:
\tif OS.get_name() == "Android": return
\toffset = get_global_mouse_position() - global_position
\tdragging = true
\tmove_to_front()
func _upDrag() -> void:
\tif OS.get_name() == "Android": return
\tdragging = false
'''
new = '''func _downDrag() -> void:
\tif OS.get_name() == "Android" and _android_overlay:
\t\tvar pointer := Vector2(float(_android_overlay.getPointerX()), float(_android_overlay.getPointerY()))
\t\t_android_drag_offset = pointer - position
\t\t_android_dragging = true
\t\tmove_to_front()
\t\treturn
\toffset = get_global_mouse_position() - global_position
\tdragging = true
\tmove_to_front()
func _upDrag() -> void:
\tif OS.get_name() == "Android":
\t\t_android_dragging = false
\t\treturn
\tdragging = false
'''
if old not in window:
    raise SystemExit('Could not locate Android console drag handlers')
window = window.replace(old, new, 1)
window_path.write_text(window, encoding='utf-8')

# Keep the visual window focusable only while the console is visible.
main_path = project / 'Scripts' / 'impo' / 'main.gd'
main = main_path.read_text(encoding='utf-8')
old = '''\tif console is Control and console.visible:
\t\tvar c := console as Control
'''
new = '''\tvar console_open := console is Control and console.visible
\t_android_overlay.setConsoleInteractive(console_open)
\tif console_open:
\t\tvar c := console as Control
'''
if old not in main:
    raise SystemExit('Could not locate console touch-region block in main.gd')
main = main.replace(old, new, 1)
main_path.write_text(main, encoding='utf-8')

# Restore Android body input as a second path. A direct Godot pick identifies the
# body even if native rectangular hit-testing is slightly off after rotation.
drag_path = project / 'Scripts' / 'impo' / 'dragExp.gd'
drag = drag_path.read_text(encoding='utf-8')
old = '''\tif OS.get_name() == "Android":
\t\treturn

'''
new = '''\tif OS.get_name() == "Android":
\t\tif event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT:
\t\t\tvar pointer_pos := Vector2(float(_android_overlay.getPointerX()), float(_android_overlay.getPointerY())) if _android_overlay else rigid_bodies_container.get_global_mouse_position()
\t\t\tif event.pressed and not _dragging:
\t\t\t\t_mobile_touch_pending = true
\t\t\t\t_mobile_pending_body = body
\t\t\t\t_mobile_touch_start_pos = pointer_pos
\t\t\telif not event.pressed and _mobile_touch_pending:
\t\t\t\t_finish_mobile_tap()
\t\treturn

'''
if old not in drag:
    raise SystemExit('Could not locate Android dragExp early return')
drag = drag.replace(old, new, 1)
drag_path.write_text(drag, encoding='utf-8')

# ---------------------------------------------------------------------------
# Gyro/gravity: default ON, use native gravity sample and directly apply force
# to RigidBody2D nodes. This avoids depending solely on Rapier2D's handling of
# the world's default gravity area.
# ---------------------------------------------------------------------------
global_path = project / 'Scripts' / 'preload' / 'globalVariable.gd'
global_gd = global_path.read_text(encoding='utf-8')
start = global_gd.find('func setGyroGravityEnabled(enabled: bool) -> bool:\n')
end = global_gd.find('func toggleGyroGravity() -> bool:\n')
if start < 0 or end < 0 or end <= start:
    raise SystemExit('Could not locate gyro enable function')
set_func = r'''func setGyroGravityEnabled(enabled: bool) -> bool:
\tgyroGravityEnabled = enabled and OS.get_name() == "Android"
\tif gyroGravityEnabled:
\t\t_lastGravityDirection = Vector2.DOWN
\telse:
\t\t_restore_body_gravity(get_tree().current_scene if get_tree() else null)
\t\t_lastGravityDirection = Vector2.DOWN
\t\t_applyGravityDirection(Vector2.DOWN, true)
\treturn gyroGravityEnabled

'''
global_gd = global_gd[:start] + set_func + global_gd[end:]

start = global_gd.find('func _physics_process(_delta: float) -> void:\n')
end = global_gd.find('func _applyGravityDirection(direction: Vector2, wake_bodies: bool = false) -> void:\n')
if start < 0 or end < 0 or end <= start:
    raise SystemExit('Could not locate gyro physics block')
physics = r'''func _physics_process(_delta: float) -> void:
\tif OS.get_name() != "Android" or not gyroGravityEnabled:
\t\treturn
\tvar screen_gravity := Vector2.DOWN
\tif _android_overlay and bool(_android_overlay.hasGravitySample()):
\t\tscreen_gravity = Vector2(float(_android_overlay.getGravityX()), float(_android_overlay.getGravityY()))
\telse:
\t\tvar sensor := Input.get_gravity()
\t\tif sensor.length() < SENSOR_GRAVITY_MIN:
\t\t\tsensor = Input.get_accelerometer()
\t\tif sensor.length() >= SENSOR_GRAVITY_MIN:
\t\t\tscreen_gravity = Vector2(sensor.x, -sensor.y)
\tif screen_gravity.length() < SENSOR_GRAVITY_MIN:
\t\tscreen_gravity = Vector2.DOWN
\tvar direction := screen_gravity.normalized()
\t_lastGravityDirection = direction
\t_applyGravityDirection(direction, false)
\t_apply_sensor_gravity_forces(direction)

func _apply_sensor_gravity_forces(direction: Vector2) -> void:
\tif get_tree() == null or get_tree().current_scene == null:
\t\treturn
\tvar strength := float(ProjectSettings.get_setting("physics/2d/default_gravity", 980.0))
\t_apply_sensor_gravity_recursive(get_tree().current_scene, direction.normalized(), strength)

func _apply_sensor_gravity_recursive(node: Node, direction: Vector2, strength: float) -> void:
\tfor child in node.get_children():
\t\tif child is RigidBody2D:
\t\t\tvar body := child as RigidBody2D
\t\t\tif not body.has_meta("_desksaw_original_gravity_scale"):
\t\t\t\tbody.set_meta("_desksaw_original_gravity_scale", body.gravity_scale)
\t\t\tbody.gravity_scale = 0.0
\t\t\tbody.sleeping = false
\t\t\tbody.apply_central_force(direction * strength * body.mass)
\t\t_apply_sensor_gravity_recursive(child, direction, strength)

func _restore_body_gravity(node: Node) -> void:
\tif node == null:
\t\treturn
\tfor child in node.get_children():
\t\tif child is RigidBody2D:
\t\t\tvar body := child as RigidBody2D
\t\t\tif body.has_meta("_desksaw_original_gravity_scale"):
\t\t\t\tbody.gravity_scale = float(body.get_meta("_desksaw_original_gravity_scale"))
\t\t\t\tbody.remove_meta("_desksaw_original_gravity_scale")
\t\t\tbody.sleeping = false
\t\t_restore_body_gravity(child)

'''
global_gd = global_gd[:start] + physics + global_gd[end:]
global_path.write_text(global_gd, encoding='utf-8')

# Real console command registration (previous builds only had the state variable).
commands_path = project / 'Scripts' / 'impo' / 'commands.gd'
commands = commands_path.read_text(encoding='utf-8')
if 'Console.create_command("gyroGravity"' not in commands:
    marker = 'func _ready():\n'
    func = r'''func _gyro_gravity(mode: String = "toggle") -> String:
\tvar normalized := mode.strip_edges().to_lower()
\tvar enabled: bool
\tmatch normalized:
\t\t"on", "1", "true":
\t\t\tenabled = GlobalVariable.setGyroGravityEnabled(true)
\t\t"off", "0", "false":
\t\t\tGlobalVariable.setGyroGravityEnabled(false)
\t\t\tenabled = false
\t\t_:
\t\t\tenabled = GlobalVariable.toggleGyroGravity()
\tvar result := "gyroGravity: " + ("ON" if enabled else "OFF")
\tConsole.print(result)
\treturn result

'''
    if marker not in commands:
        raise SystemExit('Could not locate commands _ready')
    commands = commands.replace(marker, func + marker, 1)
    reg = '\tConsole.create_command("log", _log, "Log a string to the console.")\n'
    if reg not in commands:
        raise SystemExit('Could not locate command registration anchor')
    commands = commands.replace(reg, reg + '\tConsole.create_command("gyroGravity", _gyro_gravity, "gyroGravity [on|off|toggle] - phone sensor gravity (Android, default ON)")\n', 1)
commands_path.write_text(commands, encoding='utf-8')

# Clean version name, no fix labels.
preset = project / 'export_presets.cfg'
text = preset.read_text(encoding='utf-8')
text = re.sub(r'version/code=\d+', 'version/code=204', text)
text = re.sub(r'version/name="[^"]+"', 'version/name="0.2.3"', text)
preset.write_text(text, encoding='utf-8')

print('Applied Android runtime 0.2.3')
print(' direct SurfaceView touch routing')
print(' console click/focus/drag restored')
print(' body input + native pointer fallback')
print(' gyroGravity command registered, default ON')
print(' direct RigidBody2D sensor gravity force enabled')
