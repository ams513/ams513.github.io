@tool
extends CharacterBody3D
## Stark World Engine Runtime NPC: talk with E (branching dialogue from stark_game.json), a gold "!" when they have a quest for
## you and "?" when a quest step wants you to talk to them, turns to face you, follows you on escort quests.
## visual_scene: your own character (glTF / .tscn, e.g. a rigged model from your art pack) replaces the proxy.

const Proxy := preload("res://addons/stark_runtime/world/proxy.gd")

@export var object_index: int = -1
@export var npc_id: String = ""
@export var dialog_id: String = ""
@export var display_name: String = "Villager"
## child / teen / adult (child-safety: minors are never harmed, targeted, captured or romanced)
@export var age: String = "adult"
@export var color: Color = Color(0.85, 0.6, 0.3)
@export_multiline var line: String = ""
@export var visual_scene: PackedScene
@export var visual_scale: float = 1.0

var interact_extra: float = 0.0
var home: Vector3 = Vector3.ZERO
var _face: float = 0.0
var _body: Node3D
var _mark: Label3D
var _safe_said: bool = false


func _ready() -> void:
	_body = Node3D.new()
	_body.name = "Body"
	add_child(_body)
	if Proxy.visual(_body, visual_scene, visual_scale) == null:
		Proxy.part(_body, "cone", Vector3(0, 0.7, 0), Vector3(0.9, 1.4, 0.9), color)
		Proxy.part(_body, "sphere", Vector3(0, 1.55, 0), Vector3(0.5, 0.5, 0.5), Color(0.96, 0.81, 0.63))
		Proxy.part(_body, "cone", Vector3(0, 1.95, 0), Vector3(0.6, 0.45, 0.6), color * 0.6)
	if Engine.is_editor_hint():
		return
	add_to_group("stark_npc")
	add_to_group("stark_interactable")
	add_to_group("stark_objective")
	collision_layer = 8
	collision_mask = 1
	var cs := CollisionShape3D.new()
	var cap := CapsuleShape3D.new()
	cap.radius = 0.4
	cap.height = 1.8
	cs.shape = cap
	cs.position = Vector3(0, 0.9, 0)
	add_child(cs)
	home = global_position
	_mark = Proxy.label(self, "", 2.6)


func info() -> Dictionary:
	return {"id": npc_id, "name": display_name, "dialog": dialog_id, "text": line}


func can_interact() -> bool:
	return true


func prompt_text() -> String:
	return "Talk to " + display_name


func interact(by: Node3D) -> void:
	if by:
		_face = atan2(by.global_position.x - global_position.x, by.global_position.z - global_position.z)
	StarkDialogue.talk(info())


func objective_match(s: Dictionary) -> bool:
	var t := str(s.get("type", ""))
	return (t == "talk" or t == "escort") and str(s.get("npc", "")) == npc_id and npc_id != ""


func _physics_process(delta: float) -> void:
	if Engine.is_editor_hint():
		return
	if not is_on_floor():
		velocity.y -= 24.0 * delta
	velocity.x = 0.0
	velocity.z = 0.0
	var pl = StarkGame.player
	if pl != null and is_instance_valid(pl):
		var to: Vector3 = pl.global_position - global_position
		to.y = 0.0
		var d := to.length()
		if d < 5.0:
			_face = lerp_angle(_face, atan2(to.x, to.z), min(1.0, delta * 5.0))
		var es := StarkQuests.escort_step(npc_id)
		if not es.is_empty() and not StarkGame.is_busy():
			if d > 9.0:
				var f: Vector3 = pl.forward() if pl.has_method("forward") else Vector3.FORWARD
				global_position = pl.global_position - f * 1.8 + Vector3(0, 0.3, 0)
			elif d > 2.2:
				var spd: float = min(StarkGame.rule("walk_speed", 7.0) * 0.95, d * 2.5)
				velocity.x = to.x / d * spd
				velocity.z = to.z / d * spd
			var r := float(es.get("r", 3.0))
			if Vector2(global_position.x - float(es.get("x", 0.0)), global_position.z - float(es.get("z", 0.0))).length() < (r if r > 0.0 else 3.0):
				StarkQuests.event("escort", {"npc": npc_id})
				if not _safe_said:
					_safe_said = true
					StarkGame.emit_toast(display_name + " is safe!", "q")
	move_and_slide()
	_body.rotation.y = _face
	if _mark:
		_mark.text = "?" if StarkQuests.talk_target(npc_id) else ("!" if StarkQuests.offers_quest(npc_id) else "")
