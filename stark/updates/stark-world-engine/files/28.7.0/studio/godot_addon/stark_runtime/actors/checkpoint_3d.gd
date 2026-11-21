@tool
extends Node3D
## Stark World Engine Runtime checkpoint banner: touching it heals you, saves the autosave slot and becomes your respawn point.

const Proxy := preload("res://addons/stark_runtime/world/proxy.gd")

@export var object_index: int = -1
@export var visual_scene: PackedScene
@export var visual_scale: float = 1.0

var _flag: MeshInstance3D


func _ready() -> void:
	var vis := Node3D.new()
	vis.name = "Body"
	add_child(vis)
	if Proxy.visual(vis, visual_scene, visual_scale) == null:
		Proxy.part(vis, "cyl", Vector3(0, 1.3, 0), Vector3(0.1, 2.6, 0.1), Color(0.15, 0.15, 0.17))
		_flag = Proxy.part(vis, "cube", Vector3(0.48, 2.25, 0), Vector3(0.9, 0.55, 0.04), Color(0.8, 0.18, 0.12))
	if Engine.is_editor_hint():
		return
	add_to_group("stark_checkpoint")


func is_active() -> bool:
	var cp := StarkGame.cp
	return not cp.is_empty() and int(cp.get("li", -1)) == StarkGame.li and \
		Vector2(float(cp.get("x", 0.0)) - global_position.x, float(cp.get("z", 0.0)) - (global_position.z + 1.5)).length() < 0.6


func _physics_process(_delta: float) -> void:
	if Engine.is_editor_hint():
		return
	var pl = StarkGame.player
	if pl == null or not is_instance_valid(pl):
		return
	var d := Vector2(pl.global_position.x - global_position.x, pl.global_position.z - global_position.z).length()
	if d < 1.6 and not is_active():
		StarkGame.set_checkpoint(global_position.x, global_position.z + 1.5)
	if _flag:
		_flag.material_override = Proxy.mat(Color(1.0, 0.85, 0.4) if is_active() else Color(0.8, 0.18, 0.12), 1.5 if is_active() else 0.0)
