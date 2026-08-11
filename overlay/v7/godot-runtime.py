#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: godot-runtime.py <godot-project>')
project = Path(sys.argv[1]).resolve()

main_gd = r'''extends Node2D

@onready var settings = gbData.settings

var screenWidth: int = 1
var screenHeight: int = 1
var taskbarPos: int = 1
var _android_overlay: Object = null
var _android_camera: Camera2D = null
var _android_visual_origin := Vector2.ZERO

@export var console: Node

func _ready():
	if OS.get_name() == "Android" and Engine.has_singleton("DeskSawOverlay"):
		_android_overlay = Engine.get_singleton("DeskSawOverlay")
	_refresh_screen_size()

	if OS.get_name() == "Android":
		get_window().transparent = true
		get_window().transparent_bg = true
		RenderingServer.set_default_clear_color(Color(0, 0, 0, 0))
		_setup_android_camera()
		get_viewport().size_changed.connect(_on_viewport_size_changed)
	else:
		DisplayServer.window_set_size(Vector2i(screenWidth, screenHeight) - Vector2i(1, 1))
		DisplayServer.window_set_position(DisplayServer.screen_get_position())
		if OS.get_name() == "Linux":
			DisplayServer.window_set_mode(DisplayServer.WINDOW_MODE_MAXIMIZED)

	if OS.get_name() == "Linux" and OS.get_environment("XDG_SESSION_TYPE").to_lower() == "wayland" and not TransparentWindow.UsesInputRegions():
		OS.alert("DeskSaw could not enable its XWayland input-region workaround. Click-through interaction may not work correctly. Make sure DeskSaw is running through X11/XWayland with the XShape extension available, or use an X11 session.")

	GlobalVariable.console.connect(yeah)
	createBorders()
	GlobalVariable.resize.connect(updateBorders)
	update_obj_metas()

	var def = gbData.settings.get("defaultSkin", "Body")
	GlobalVariable.userSkinPath = "user://skin/" + def + "/"

	if gbData.settings["expiePersistence"]:
		loadExpiePersistence()
	else:
		$CanvasLayer2/ConsoleContainer/Main/ConsoleContainer/Commands.spawnExpie()

func _process(_delta: float) -> void:
	if not _android_overlay:
		return
	_sync_android_view()

	if console is Control and console.visible:
		var c := console as Control
		var rect := Rect2(c.position, c.size).grow(8.0)
		_android_overlay.setTouchRegion("__console", rect.position.x, rect.position.y, rect.size.x, rect.size.y)
	else:
		_android_overlay.removeTouchRegion("__console")

func _exit_tree() -> void:
	if _android_overlay:
		_android_overlay.removeTouchRegion("__console")

func _setup_android_camera() -> void:
	if _android_camera != null:
		return
	_android_camera = Camera2D.new()
	_android_camera.name = "AndroidOverlayCamera"
	add_child(_android_camera)
	_android_camera.enabled = true
	_sync_android_view()

func _sync_android_view() -> void:
	if not _android_overlay:
		return

	var new_width := maxi(1, int(_android_overlay.getDisplayWidth()))
	var new_height := maxi(1, int(_android_overlay.getDisplayHeight()))
	if new_width != screenWidth or new_height != screenHeight:
		screenWidth = new_width
		screenHeight = new_height
		taskbarPos = screenHeight
		GlobalVariable.screenWidth = screenWidth
		GlobalVariable.screenHeight = screenHeight
		GlobalVariable.taskbarPos = taskbarPos
		_clamp_rigid_bodies_to_screen(self)
		createBorders()

	_android_visual_origin = Vector2(float(_android_overlay.getVisualX()), float(_android_overlay.getVisualY()))
	var viewport_size := get_viewport().get_visible_rect().size
	if _android_camera != null:
		_android_camera.global_position = _android_visual_origin + viewport_size * 0.5
	$CanvasLayer2.offset = -_android_visual_origin

func _refresh_screen_size() -> void:
	if OS.get_name() == "Android" and _android_overlay:
		screenWidth = maxi(1, int(_android_overlay.getDisplayWidth()))
		screenHeight = maxi(1, int(_android_overlay.getDisplayHeight()))
		taskbarPos = screenHeight
	else:
		var usable := DisplayServer.screen_get_usable_rect()
		screenWidth = maxi(1, usable.size.x)
		screenHeight = maxi(1, usable.size.y)
		taskbarPos = usable.end.y

	GlobalVariable.screenWidth = screenWidth
	GlobalVariable.screenHeight = screenHeight
	GlobalVariable.taskbarPos = taskbarPos

func _on_viewport_size_changed() -> void:
	call_deferred("_sync_android_view")

func yeah(t: bool):
	console.visible = t
	if t:
		console.showw()

func createBorders():
	taskbarPos = clampi(taskbarPos, 0, screenHeight)
	$Floor.position = Vector2(screenWidth / 2.0, taskbarPos)
	$SideL.position = Vector2(0, screenHeight / 2.0)
	$SideR.position = Vector2(screenWidth, screenHeight / 2.0)

func updateBorders():
	var old_width := screenWidth
	var old_height := screenHeight
	_refresh_screen_size()
	if OS.get_name() != "Android":
		DisplayServer.window_set_size(Vector2i(screenWidth, screenHeight) - Vector2i(1, 1))
		DisplayServer.window_set_position(DisplayServer.screen_get_position())
	elif old_width != screenWidth or old_height != screenHeight:
		_clamp_rigid_bodies_to_screen(self)
	createBorders()

func _clamp_rigid_bodies_to_screen(node: Node) -> void:
	for child in node.get_children():
		if child is RigidBody2D:
			var body := child as RigidBody2D
			body.global_position.x = clampf(body.global_position.x, 0.0, float(screenWidth))
			body.global_position.y = clampf(body.global_position.y, 0.0, float(screenHeight))
		_clamp_rigid_bodies_to_screen(child)

func update_obj_metas():
	var dir = DirAccess.open("res://scenes/objects")
	if dir == null:
		return
	dir.list_dir_begin()
	var fileName = dir.get_next()
	while fileName != "":
		if fileName.ends_with(".tscn"):
			var path = "res://scenes/object".path_join(fileName)
			var object = load(path)
			if object is PackedScene:
				var instance = object.instantiate()
				add_child(instance)
		fileName = dir.get_next()
	dir.list_dir_end()

func loadExpiePersistence():
	print("loading expies...")
	if gbData.data["saw"].size() > 20:
		GlobalVariable.persistenceWarning.emit()
		await GlobalVariable.persistenceWarning
	for petId in gbData.data["saw"].keys():
		var petData = gbData.data["saw"][petId]
		await get_tree().create_timer(0.25).timeout
		GlobalVariable.userSkinPath = "user://skin/" + petData.get("skin", "Default") + "/"
		$CanvasLayer2/ConsoleContainer/Main/ConsoleContainer/Commands.spawnExpie(petId)

func lol():
	while get_tree():
		await get_tree().create_timer(1).timeout
		var r = randi_range(1, 200)
		$CanvasLayer2/TextureRect.visible = (r == 1)
		if r == 1:
			AudioManager.play_sfx(preload("res://assets/sounds/effects/stalkerscream.wav"))
		await get_tree().create_timer(.2).timeout
		$CanvasLayer2/TextureRect.visible = false
'''
(project / 'Scripts/impo/main.gd').write_text(main_gd, encoding='utf-8')

global_gd = r'''extends Node

var screenWidth: int = DisplayServer.screen_get_usable_rect().size.x
var screenHeight: int = DisplayServer.screen_get_usable_rect().size.y
var taskbarPos: int = DisplayServer.screen_get_usable_rect().end.y
var clickZoneSum: int = 0
var gyroGravityEnabled: bool = OS.get_name() == "Android"
var _lastGravityDirection := Vector2.DOWN
var _android_overlay: Object = null
const SENSOR_GRAVITY_MIN := 0.20
const GRAVITY_DIRECTION_DOT_THRESHOLD := 0.9995

func _ready() -> void:
	if OS.get_name() == "Android" and Engine.has_singleton("DeskSawOverlay"):
		_android_overlay = Engine.get_singleton("DeskSawOverlay")
		screenWidth = maxi(1, int(_android_overlay.getDisplayWidth()))
		screenHeight = maxi(1, int(_android_overlay.getDisplayHeight()))
		taskbarPos = screenHeight
		setGyroGravityEnabled(true)

func setGyroGravityEnabled(enabled: bool) -> bool:
	gyroGravityEnabled = enabled and OS.get_name() == "Android"
	if not gyroGravityEnabled:
		_lastGravityDirection = Vector2.DOWN
		_applyGravityDirection(Vector2.DOWN, true)
	return gyroGravityEnabled

func toggleGyroGravity() -> bool:
	return setGyroGravityEnabled(not gyroGravityEnabled)

func _physics_process(_delta: float) -> void:
	if OS.get_name() != "Android" or not gyroGravityEnabled:
		return
	var screen_gravity := Vector2.ZERO
	if _android_overlay and bool(_android_overlay.hasGravitySample()):
		screen_gravity = Vector2(float(_android_overlay.getGravityX()), float(_android_overlay.getGravityY()))
	else:
		var sensor := Input.get_gravity()
		if sensor.length() < SENSOR_GRAVITY_MIN:
			sensor = Input.get_accelerometer()
		screen_gravity = Vector2(sensor.x, -sensor.y)
	if screen_gravity.length() < SENSOR_GRAVITY_MIN:
		return
	var direction := screen_gravity.normalized()
	if direction.dot(_lastGravityDirection) < GRAVITY_DIRECTION_DOT_THRESHOLD:
		_lastGravityDirection = direction
		_applyGravityDirection(direction, true)

func _applyGravityDirection(direction: Vector2, wake_bodies: bool = false) -> void:
	if direction.length_squared() <= 0.0001:
		return
	var viewport := get_viewport()
	if viewport == null:
		return
	var world := viewport.find_world_2d()
	if world == null or not world.space.is_valid():
		return
	PhysicsServer2D.area_set_param(world.space, PhysicsServer2D.AREA_PARAM_GRAVITY_VECTOR, direction.normalized())
	if wake_bodies and get_tree() and get_tree().current_scene:
		_wake_rigid_bodies(get_tree().current_scene)

func _wake_rigid_bodies(node: Node) -> void:
	for child in node.get_children():
		if child is RigidBody2D:
			(child as RigidBody2D).sleeping = false
		_wake_rigid_bodies(child)

signal persistenceWarning()
signal raga()
signal skinswap()
signal resize()
signal pet(t: bool)
signal console(t: bool)
signal raisemood(t: int)
signal feed(t: int)
func petf(t: bool): pet.emit(t)
func Fresize(): resize.emit()
func ragaa(): raga.emit()
func skinswapFunc(data): skinswap.emit(data)
func consoleF(t: bool): console.emit(t)
func raisemoodF(t: int): raisemood.emit(t)
func feedf(t: int): feed.emit(t)

func makePopUp(text: String, parent: CanvasLayer, position: Vector2) -> bool:
	var scene = load("res://scenes/popUp.tscn")
	var instance = scene.instantiate()
	parent.add_child(instance)
	instance.owner = parent
	instance.position = position
	return await instance.setup(text)

func _apply_renderer_and_restart(use_vulkan: bool) -> void:
	var method := "forward_plus" if use_vulkan else "gl_compatibility"
	ProjectSettings.set_setting("rendering/renderer/rendering_method", method)
	ProjectSettings.save()
	OS.set_restart_on_exit(true, OS.get_cmdline_args())
	gbData.settings.renderingMode = use_vulkan
	gbData.data["firstLaunch"] = false
	gbData.savetodisk("user://SAVE.json", gbData.data)
	gbData.savetodisk("user://CONFIG.json", gbData.settings)
	get_tree().quit()

var userSkinPath = "user://skin/Body/"
'''
(project / 'Scripts/preload/globalVariable.gd').write_text(global_gd, encoding='utf-8')

window_handler = r'''extends Control

@export var Handle: Button
@export var Minimize: Button
@export var Exit: Button
@export var ConsoleN: Control
@export var SettingsN: Control
@export var StatN: Control
@export var SkinsN: Control
@export var ChatN: Control
var offset = Vector2.ZERO
var dragging = false
var _android_overlay: Object = null
var _android_last_pointer_sequence := -1
var _android_dragging := false
var _android_drag_offset := Vector2.ZERO
var global_top_left: Vector2
var global_top_right: Vector2
var global_bottom_left: Vector2
var global_bottom_right: Vector2

func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	_on_tab_switch_item_selected(1)
	if OS.get_name() == "Android" and Engine.has_singleton("DeskSawOverlay"):
		_android_overlay = Engine.get_singleton("DeskSawOverlay")
		GlobalVariable.screenWidth = maxi(1, int(_android_overlay.getDisplayWidth()))
		GlobalVariable.screenHeight = maxi(1, int(_android_overlay.getDisplayHeight()))
		GlobalVariable.taskbarPos = GlobalVariable.screenHeight
		set_anchors_preset(Control.PRESET_TOP_LEFT, true)
	position = Vector2(GlobalVariable.screenWidth / 2.0, GlobalVariable.screenHeight / 2.0)
	_clamp_to_screen()
	global_top_left = global_position
	global_top_right = global_position + Vector2(size.x, 0)
	global_bottom_left = global_position + Vector2(0, size.y)
	global_bottom_right = global_position + size

func _process(_delta: float) -> void:
	if _android_overlay:
		_process_android_drag()
	elif dragging:
		global_position = get_global_mouse_position() - offset

func _process_android_drag() -> void:
	var sequence := int(_android_overlay.getPointerSequence())
	var down := bool(_android_overlay.isPointerDown())
	var owner := str(_android_overlay.getPointerOwner())
	var pointer := Vector2(float(_android_overlay.getPointerX()), float(_android_overlay.getPointerY()))
	if sequence != _android_last_pointer_sequence:
		_android_last_pointer_sequence = sequence
		if down and owner == "__console" and _point_is_on_drag_handle(pointer):
			_android_dragging = true
			_android_drag_offset = pointer - position
			move_to_front()
	if _android_dragging:
		if down and owner == "__console":
			position = pointer - _android_drag_offset
			_clamp_to_screen()
		else:
			_android_dragging = false

func _point_is_on_drag_handle(screen_point: Vector2) -> bool:
	if Handle == null or not Handle.visible:
		return false
	var handle_rect := Rect2(position + Handle.position, Handle.size)
	if not handle_rect.has_point(screen_point):
		return false
	for child in Handle.get_children():
		if child is Control:
			var control := child as Control
			if control.visible:
				var child_rect := Rect2(position + Handle.position + control.position, control.size)
				if child_rect.has_point(screen_point):
					return false
	return true

func _clamp_to_screen() -> void:
	var max_x := maxf(0.0, float(GlobalVariable.screenWidth) - size.x)
	var max_y := maxf(0.0, float(GlobalVariable.screenHeight) - size.y)
	position.x = clampf(position.x, 0.0, max_x)
	position.y = clampf(position.y, 0.0, max_y)

func _downDrag() -> void:
	if OS.get_name() == "Android": return
	offset = get_global_mouse_position() - global_position
	dragging = true
	move_to_front()
func _upDrag() -> void:
	if OS.get_name() == "Android": return
	dragging = false
func showw() -> void:
	self.visible = true
	$ClickArea.enabled = self.visible
func _hide(_t: bool) -> void:
	self.visible = false
	$ClickArea.enabled = self.visible
func _on_tab_switch_item_selected(index: int) -> void:
	ConsoleN.visible = false
	SettingsN.visible = false
	SkinsN.visible = false
	match index:
		0:
			if gbData.devMode: print("Statistics")
		1:
			ConsoleN.visible = true
		2:
			SettingsN.visible = true
		3:
			SkinsN.visible = true
'''
(project / 'Scripts/nimpo/windowHandler.gd').write_text(window_handler, encoding='utf-8')

# Patch dragExp after overlay/v5 has converted Android hit regions to per-body IDs.
drag_path = project / 'Scripts/impo/dragExp.gd'
gd = drag_path.read_text(encoding='utf-8')
if '_android_region_ids' not in gd or '_android_region_id(body' not in gd:
    raise SystemExit('overlay/v5 per-body Android touch patch is not applied')
needle = 'var _android_overlay: Object = null\n'
if needle not in gd:
    raise SystemExit('dragExp Android overlay field not found')
gd = gd.replace(needle, 'var _android_overlay: Object = null\nvar _android_last_pointer_sequence := -1\nvar _android_pointer_was_down := false\n', 1)
gd = gd.replace('const MOBILE_TOUCH_MARGIN := 12.0\n', 'const MOBILE_TOUCH_MARGIN := 8.0\nconst MOBILE_TOUCH_MAX_SIDE := 220.0\n', 1)
start = gd.find('func _process(_delta: float) -> void:\n')
end = gd.find('func _update_x11_input_regions() -> void:\n')
if start < 0 or end < 0 or end <= start:
    raise SystemExit('Could not locate dragExp _process block')
new_process = r'''func _process(_delta: float) -> void:
	if _use_x11_input_regions:
		_update_x11_input_regions()
	if _android_overlay:
		_update_android_touch_regions()
		_process_android_pointer()
		return
	if _dragging:
		var mouse_pos := rigid_bodies_container.get_global_mouse_position()
		if is_instance_valid(_dragger): _dragger.global_position = mouse_pos
		if not Input.is_mouse_button_pressed(MOUSE_BUTTON_RIGHT):
			_stopDrag()
			return
	elif not _use_x11_input_regions:
		if GlobalVariable.clickZoneSum <= 0: _isMouseOver()
		else: _validateHoverState()

func _process_android_pointer() -> void:
	var sequence := int(_android_overlay.getPointerSequence())
	var down := bool(_android_overlay.isPointerDown())
	var owner := str(_android_overlay.getPointerOwner())
	var pointer_pos := Vector2(float(_android_overlay.getPointerX()), float(_android_overlay.getPointerY()))
	if sequence != _android_last_pointer_sequence:
		_android_last_pointer_sequence = sequence
		if down:
			var body := _find_body_for_android_region(owner)
			if is_instance_valid(body):
				_mobile_touch_pending = true
				_mobile_pending_body = body
				_mobile_touch_start_pos = pointer_pos
	if down:
		if _mobile_touch_pending and pointer_pos.distance_to(_mobile_touch_start_pos) >= MOBILE_DRAG_THRESHOLD:
			var body := _mobile_pending_body
			_mobile_touch_pending = false
			_mobile_pending_body = null
			if is_instance_valid(body): _startDrag(body, pointer_pos)
		if _dragging and is_instance_valid(_dragger): _dragger.global_position = pointer_pos
	else:
		if _android_pointer_was_down:
			if _dragging: _stopDrag()
			elif _mobile_touch_pending: _finish_mobile_tap()
	_android_pointer_was_down = down

func _find_body_for_android_region(region_id: String) -> RigidBody2D:
	for child in rigid_bodies_container.get_children():
		if child is RigidBody2D:
			var body := child as RigidBody2D
			if _android_region_id(body) == region_id: return body
	return null

'''
gd = gd[:start] + new_process + gd[end:]
needle = '\t\trect = rect.grow(MOBILE_TOUCH_MARGIN)\n\t\t_android_overlay.setTouchRegion(\n'
replace = '''\t\trect = rect.grow(MOBILE_TOUCH_MARGIN)\n\t\tif rect.size.x > MOBILE_TOUCH_MAX_SIDE:\n\t\t\trect.position.x = body.global_position.x - MOBILE_TOUCH_MAX_SIDE * 0.5\n\t\t\trect.size.x = MOBILE_TOUCH_MAX_SIDE\n\t\tif rect.size.y > MOBILE_TOUCH_MAX_SIDE:\n\t\t\trect.position.y = body.global_position.y - MOBILE_TOUCH_MAX_SIDE * 0.5\n\t\t\trect.size.y = MOBILE_TOUCH_MAX_SIDE\n\t\t_android_overlay.setTouchRegion(\n'''
if needle not in gd:
    raise SystemExit('Could not locate per-body Android region grow block')
gd = gd.replace(needle, replace, 1)
func_marker = 'func _on_body_part_input(_viewport: Node, event: InputEvent, _shape_idx: int, body: RigidBody2D) -> void:\n'
idx = gd.find(func_marker)
if idx < 0:
    raise SystemExit('dragExp input handler not found')
body_start = idx + len(func_marker)
gd = gd[:body_start] + '\tif OS.get_name() == "Android":\n\t\treturn\n\n' + gd[body_start:]
old_branch = '''\tif OS.get_name() == "Android" and event.button_index == MOUSE_BUTTON_LEFT:\n\t\tif event.pressed and not _dragging and not _mobile_touch_pending:\n\t\t\t_mobile_touch_pending = true\n\t\t\t_mobile_pending_body = body\n\t\t\t_mobile_touch_start_pos = rigid_bodies_container.get_global_mouse_position()\n\t\telif not event.pressed and _mobile_touch_pending:\n\t\t\t_finish_mobile_tap()\n\t\treturn\n\n'''
gd = gd.replace(old_branch, '', 1)
drag_path.write_text(gd, encoding='utf-8')
print('Applied Godot runtime v7: cropped viewport camera, native pet drag, draggable console, native gravity default ON')
