@tool
extends Node3D
## Stark World Engine Runtime portal: walk in to travel to another level (target -1 = the next one). lock_quest keeps it sealed
## until that quest is done. Counts as "reaching" the spot for quests.

const Proxy := preload("res://addons/stark_runtime/world/proxy.gd")

@export var object_index: int = -1
@export var target: int = -1
@export var lock_quest: String = ""
@export var visual_scene: PackedScene
@export var visual_scale: float = 1.0

var _warned: bool = false
var _veil: Node3D
var _t: float = 0.0


func _ready() -> void:
	var vis := Node3D.new()
	vis.name = "Body"
	add_child(vis)
	if Proxy.visual(vis, visual_scene, visual_scale) == null:
		var stone := Color(0.45, 0.45, 0.5)
		Proxy.part(vis, "cube", Vector3(-1.6, 2.0, 0), Vector3(0.6, 4.0, 0.6), stone)
		Proxy.part(vis, "cube", Vector3(1.6, 2.0, 0), Vector3(0.6, 4.0, 0.6), stone)
		Proxy.part(vis, "cube", Vector3(0, 4.2, 0), Vector3(3.8, 0.6, 0.7), stone)
		_veil = Proxy.part(vis, "cube", Vector3(0, 1.95, 0), Vector3(2.6, 3.8, 0.08), Color(0.62, 0.55, 1.0), 2.4)
	if Engine.is_editor_hint():
		return
	add_to_group("stark_portal")
	var ol := OmniLight3D.new()
	ol.position = Vector3(0, 2.0, 0.6)
	ol.light_color = Color(0.7, 0.6, 1.0)
	ol.light_energy = 1.6
	ol.omni_range = 10.0
	add_child(ol)


func destination() -> int:
	return target if target >= 0 else StarkGame.li + 1


func is_locked() -> bool:
	if lock_quest == "" or StarkGame.quest(lock_quest).is_empty():
		return false
	return StarkQuests.state_of(lock_quest) != "done"


func _physics_process(delta: float) -> void:
	if Engine.is_editor_hint():
		return
	_t += delta
	if _veil:
		_veil.scale.x = 1.0 + sin(_t * 3.0) * 0.03
	var pl = StarkGame.player
	if pl == null or not is_instance_valid(pl) or StarkGame.porting:
		return
	var d := Vector2(pl.global_position.x - global_position.x, pl.global_position.z - global_position.z).length()
	if d > 2.5:
		_warned = false
	if d >= 1.3:
		return
	if is_locked():
		if not _warned:
			_warned = true
			StarkGame.emit_toast("Sealed. Finish \"%s\" first." % str(StarkGame.quest(lock_quest).get("title", lock_quest)))
		return
	var to := destination()
	if to < 0 or to >= StarkGame.level_count():
		if not _warned:
			_warned = true
			StarkGame.emit_toast("This portal leads nowhere yet.")
		return
	StarkQuests.event("reach", {"x": pl.global_position.x, "z": pl.global_position.z})
	StarkGame.go_to_level(to)
