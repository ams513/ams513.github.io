@tool
extends Area3D
## Stark World Engine Runtime pickup: an item lying in the world (potion, key, quest item ...) or a glowing crystal.
## Walk into it to pick it up. visual_scene: your own model (glTF / .tscn) replaces the proxy gem.

const Proxy := preload("res://addons/stark_runtime/world/proxy.gd")

@export var object_index: int = -1
@export var item: String = "potion"
@export var count: int = 1
@export var crystal: bool = false
@export var visual_scene: PackedScene
@export var visual_scale: float = 1.0

var _vis: Node3D
var _t: float = 0.0
var _taken: bool = false


func _ready() -> void:
	_vis = Node3D.new()
	_vis.name = "Body"
	add_child(_vis)
	if Proxy.visual(_vis, visual_scene, visual_scale) == null:
		var col := Color(0.5, 1.0, 0.8)
		if not Engine.is_editor_hint():
			var pal: Dictionary = StarkGame.current_level().get("palette", {})
			var fx: Array = pal.get("fx", [0.5, 1.0, 0.8])
			col = Color(float(fx[0]), float(fx[1]), float(fx[2])) if crystal else StarkGame.color_of(str(StarkGame.item(item).get("col", "#88ffcc")))
		if crystal:
			Proxy.part(_vis, "cone", Vector3(0, 0.75, 0), Vector3(0.45, 1.5, 0.45), col, 3.0)
			Proxy.part(_vis, "cone", Vector3(0.35, 0.4, 0.15), Vector3(0.3, 0.9, 0.3), col, 3.0)
			Proxy.part(_vis, "cone", Vector3(-0.3, 0.3, -0.1), Vector3(0.25, 0.7, 0.25), col, 3.0)
		else:
			Proxy.part(_vis, "gem", Vector3(0, 0.7, 0), Vector3(0.4, 0.55, 0.4), col, 2.0)
	if Engine.is_editor_hint():
		return
	if StarkGame.is_gone(object_index):
		queue_free()
		return
	add_to_group("stark_pickup")
	add_to_group("stark_objective")
	collision_layer = 16
	collision_mask = 2
	monitoring = true
	var cs := CollisionShape3D.new()
	var sp := SphereShape3D.new()
	sp.radius = 1.4 if crystal else 1.3
	cs.shape = sp
	cs.position = Vector3(0, 0.8, 0)
	add_child(cs)
	body_entered.connect(_on_body)
	if crystal:
		var ol := OmniLight3D.new()
		ol.position = Vector3(0, 0.9, 0)
		ol.light_color = Color(0.6, 1.0, 0.9)
		ol.light_energy = 0.8
		ol.omni_range = 6.0
		add_child(ol)


func _on_body(b: Node) -> void:
	if b.is_in_group("stark_player"):
		collect()


func collect() -> void:
	if _taken:
		return
	_taken = true
	StarkGame.set_gone(object_index)
	StarkGame.play_sfx("coin")
	if crystal:
		StarkInventory.score += 10
		StarkInventory.give("crystal", 1, true)
		var total := 0
		var got := 0
		for o in StarkGame.current_level().get("objects", []):
			if str(o["t"]) == "crystal":
				total += 1
				if StarkGame.is_gone(int(o["i"])):
					got += 1
		StarkGame.emit_toast("Crystal %d/%d" % [got, total])
		StarkGame.crystal_collected()
	else:
		StarkInventory.give(item, count)
	queue_free()


func objective_match(s: Dictionary) -> bool:
	return not _taken and str(s.get("type", "")) == "collect" and str(s.get("item", "")) == ("crystal" if crystal else item)


func _process(delta: float) -> void:
	_t += delta
	if _vis:
		_vis.rotation.y = _t * 1.5
		_vis.position.y = sin(_t * 3.0) * 0.12
