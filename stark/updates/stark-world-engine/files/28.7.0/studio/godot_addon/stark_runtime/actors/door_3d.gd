@tool
extends StaticBody3D
## Stark World Engine Runtime locked door / gate: press E with its key in the bag to open it (a "key" item is used up).

const Proxy := preload("res://addons/stark_runtime/world/proxy.gd")

@export var object_index: int = -1
@export var key_item: String = "key"
@export var visual_scene: PackedScene
@export var visual_scale: float = 1.0

var opened: bool = false
var interact_extra: float = 0.6
var _leaf: Node3D
var _shape: CollisionShape3D


func _ready() -> void:
	var vis := Node3D.new()
	vis.name = "Body"
	add_child(vis)
	if Proxy.visual(vis, visual_scene, visual_scale) == null:
		var stone := Color(0.45, 0.45, 0.5)
		Proxy.part(vis, "cube", Vector3(-1.6, 1.5, 0), Vector3(0.6, 3.0, 0.7), stone)
		Proxy.part(vis, "cube", Vector3(1.6, 1.5, 0), Vector3(0.6, 3.0, 0.7), stone)
		Proxy.part(vis, "cube", Vector3(0, 3.25, 0), Vector3(3.9, 0.5, 0.8), stone)
		_leaf = Proxy.part(vis, "cube", Vector3(0, 1.4, 0), Vector3(2.6, 2.8, 0.3), Color(0.35, 0.22, 0.12))
		Proxy.part(_leaf, "cube", Vector3(0.3, 0.0, 0.6), Vector3(0.08, 0.08, 0.4), Color(1.0, 0.85, 0.3), 1.5)
	if Engine.is_editor_hint():
		return
	opened = StarkGame.is_gone(object_index)
	add_to_group("stark_interactable")
	collision_layer = 1
	_shape = CollisionShape3D.new()
	var b := BoxShape3D.new()
	b.size = Vector3(3.8, 3.0, 1.0)
	_shape.shape = b
	_shape.position = Vector3(0, 1.5, 0)
	add_child(_shape)
	_show_open()


func _show_open() -> void:
	if opened:
		if _leaf:
			_leaf.visible = false
		if _shape:
			_shape.disabled = true


func can_interact() -> bool:
	return not opened


func prompt_text() -> String:
	return "Unlock door"


func interact(_by: Node3D) -> void:
	if opened:
		return
	var kd := StarkGame.item(key_item)
	if StarkInventory.has(key_item):
		if str(kd.get("kind", "")) == "key":
			StarkInventory.take(key_item, 1)
		opened = true
		StarkGame.set_gone(object_index)
		StarkGame.play_sfx("door")
		StarkGame.emit_toast("Unlocked with " + str(kd.get("name", key_item)))
		_shape.set_deferred("disabled", true)
		if _leaf:
			_leaf.visible = false
	else:
		StarkGame.emit_toast("Locked. You need: " + str(kd.get("name", key_item)))
		StarkGame.play_sfx("hit")
