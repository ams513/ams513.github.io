@tool
extends StaticBody3D
## Stark World Engine Runtime chest: press E to open; gives its item and/or gold (an empty chest gives 10 gold).

const Proxy := preload("res://addons/stark_runtime/world/proxy.gd")

@export var object_index: int = -1
@export var item: String = ""
@export var count: int = 1
@export var gold: int = 0
@export var visual_scene: PackedScene
@export var visual_scale: float = 1.0

var opened: bool = false
var interact_extra: float = 0.0
var _lid: Node3D


func _ready() -> void:
	var vis := Node3D.new()
	vis.name = "Body"
	add_child(vis)
	if Proxy.visual(vis, visual_scene, visual_scale) == null:
		Proxy.part(vis, "cube", Vector3(0, 0.28, 0), Vector3(0.9, 0.55, 0.6), Color(0.5, 0.3, 0.15))
		_lid = Node3D.new()
		_lid.position = Vector3(0, 0.56, -0.3)
		vis.add_child(_lid)
		Proxy.part(_lid, "cube", Vector3(0, 0.06, 0.3), Vector3(0.95, 0.14, 0.65), Color(0.95, 0.75, 0.25))
	if Engine.is_editor_hint():
		return
	opened = StarkGame.is_gone(object_index)
	add_to_group("stark_interactable")
	add_to_group("stark_objective")
	collision_layer = 1
	var cs := CollisionShape3D.new()
	var b := BoxShape3D.new()
	b.size = Vector3(0.95, 0.6, 0.65)
	cs.shape = b
	cs.position = Vector3(0, 0.3, 0)
	add_child(cs)
	_show_open()


func _show_open() -> void:
	if _lid and opened:
		_lid.rotation.x = -1.1


func can_interact() -> bool:
	return not opened


func prompt_text() -> String:
	return "Open chest"


func interact(_by: Node3D) -> void:
	if opened:
		return
	opened = true
	StarkGame.set_gone(object_index)
	StarkGame.play_sfx("coin")
	if item != "":
		StarkInventory.give(item, max(1, count))
	if gold > 0:
		StarkInventory.gold += gold
		StarkGame.emit_toast("+%d gold" % gold)
	if item == "" and gold <= 0:
		StarkInventory.gold += 10
		StarkGame.emit_toast("+10 gold")
	StarkGame.changed.emit()
	_show_open()


func objective_match(s: Dictionary) -> bool:
	return not opened and item != "" and str(s.get("type", "")) == "collect" and str(s.get("item", "")) == item
