@tool
extends CharacterBody3D
## Stark World Engine Runtime enemy: patrol -> chase -> return home, like the browser engine. Archers keep their distance and
## shoot, brutes and bosses wind up a ground slam, bosses fire volleys, enrage at half health and call for help,
## wisps fly. Numbers (health, damage, speed, sight, XP, gold) come from stark_game.json "enemies".
## visual_scene: drop a glTF / .tscn creature here to replace the proxy (the AI and combat stay).

const Proxy := preload("res://addons/stark_runtime/world/proxy.gd")

@export var object_index: int = -1
@export var kind: String = "grunt"
@export var enemy_id: String = ""
## child / teen / adult (child-safety: a child or teen is never a combat target)
@export var age: String = "adult"
@export var display_name: String = ""
@export var hp_override: int = 0
@export var patrol: float = 5.0
@export var size_scale: float = 1.0
@export var color: Color = Color(0, 0, 0, 0)
@export var visual_scene: PackedScene
@export var visual_scale: float = 1.0

var def: Dictionary = {}
var hp: float = 3.0
var max_hp: float = 3.0
var home: Vector3 = Vector3.ZERO
var state: String = "patrol"
var dead: bool = false
var _wt: float = 0.0
var _target: Vector3 = Vector3.ZERO
var _cd: float = 0.6
var _sh: float = 1.0
var _wind: float = 0.0
var _vol: float = 4.0
var _enraged: bool = false
var _hit: float = 0.0
var _face: float = 0.0
var _t: float = 0.0
var _visual: Node3D


func _ready() -> void:
	if Engine.is_editor_hint():
		_build_visual({})
		return
	def = StarkGame.enemy_def(kind)
	if StarkGame.is_gone(object_index):
		queue_free()
		return
	if is_protected():
		# a child or teen can never be an enemy (the exporter refuses such worlds; this is the runtime backstop)
		push_warning("Stark World Engine child-safety: %s is a minor and cannot be an enemy; removed" % name)
		queue_free()
		return
	add_to_group("stark_enemy")
	add_to_group("stark_objective")
	collision_layer = 4
	collision_mask = 1
	floor_max_angle = deg_to_rad(55.0)
	var base := float(hp_override) if hp_override > 0 else float(def.get("hp", 3))
	max_hp = max(1.0, round(base * StarkGame.hp_mul()))
	hp = max_hp
	home = global_position
	_target = home
	_sh = 1.0 + randf()
	var cs := CollisionShape3D.new()
	var cap := CapsuleShape3D.new()
	var s := size_scale * (1.8 if is_boss() else 1.0)
	cap.radius = 0.45 * s
	cap.height = max(1.0 * s, cap.radius * 2.0 + 0.01)
	cs.shape = cap
	cs.position = Vector3(0, cap.height * 0.5, 0)
	add_child(cs)
	_build_visual(def)


func _build_visual(d: Dictionary) -> void:
	_visual = Node3D.new()
	_visual.name = "Body"
	add_child(_visual)
	if Proxy.visual(_visual, visual_scene, visual_scale * size_scale) != null:
		return
	var c := color
	if c.a <= 0.0:
		var dc: Array = d.get("col", [0.75, 0.2, 0.35])
		c = Color(float(dc[0]), float(dc[1]), float(dc[2]))
	var s := size_scale
	if bool(d.get("boss", false)) or kind == "boss":
		s *= 1.8
		Proxy.part(_visual, "sphere", Vector3(0, 1.1 * s, 0), Vector3(1.6, 1.8, 1.6) * s, c)
		Proxy.part(_visual, "cone", Vector3(0, 2.2 * s, 0), Vector3(1.2, 0.9, 1.2) * s, c * 0.7)
		Proxy.part(_visual, "sphere", Vector3(0.3 * s, 1.5 * s, 0.7 * s), Vector3(0.22, 0.18, 0.1) * s, Color(1.0, 0.3, 0.8), 3.0)
		Proxy.part(_visual, "sphere", Vector3(-0.3 * s, 1.5 * s, 0.7 * s), Vector3(0.22, 0.18, 0.1) * s, Color(1.0, 0.3, 0.8), 3.0)
	elif kind == "archer":
		Proxy.part(_visual, "cone", Vector3(0, 0.7 * s, 0), Vector3(0.9, 1.4, 0.9) * s, c)
		Proxy.part(_visual, "cube", Vector3(0.12 * s, 1.0 * s, 0.35 * s), Vector3(0.14, 0.1, 0.06) * s, Color(0.75, 1.0, 0.5), 2.0)
	elif kind == "wisp":
		Proxy.part(_visual, "sphere", Vector3(0, 0.5 * s, 0), Vector3(0.8, 0.8, 0.8) * s, c, 2.5)
	elif kind == "brute":
		Proxy.part(_visual, "rock", Vector3(0, 0.8 * s, 0), Vector3(1.5, 1.6, 1.3) * s, c)
		Proxy.part(_visual, "rock", Vector3(0.75 * s, 0.7 * s, 0.2 * s), Vector3(0.5, 0.9, 0.5) * s, c * 0.85)
		Proxy.part(_visual, "rock", Vector3(-0.75 * s, 0.7 * s, 0.2 * s), Vector3(0.5, 0.9, 0.5) * s, c * 0.85)
	else:
		Proxy.part(_visual, "sphere", Vector3(0, 0.55 * s, 0), Vector3(1.0, 1.1, 1.0) * s, c)
		Proxy.part(_visual, "cube", Vector3(0.18 * s, 0.75 * s, 0.45 * s), Vector3(0.14, 0.14, 0.06) * s, Color.WHITE)
		Proxy.part(_visual, "cube", Vector3(-0.18 * s, 0.75 * s, 0.45 * s), Vector3(0.14, 0.14, 0.06) * s, Color.WHITE)


func is_protected() -> bool:
	return StarkGame.is_minor(enemy_id, age)


func is_boss() -> bool:
	return bool(def.get("boss", false)) or kind == "boss"


func title() -> String:
	return display_name if display_name != "" else str(def.get("name", kind.capitalize()))


func objective_match(s: Dictionary) -> bool:
	if dead or str(s.get("type", "")) != "defeat":
		return false
	if str(s.get("id", "")) != "":
		return str(s["id"]) == enemy_id
	var k := str(s.get("kind", ""))
	return k == "" or k == "any" or k == kind


func _physics_process(delta: float) -> void:
	if Engine.is_editor_hint() or dead:
		return
	_t += delta
	_hit = max(0.0, _hit - delta)
	_cd = max(0.0, _cd - delta)
	var fly := bool(def.get("fly", false))
	if not fly and not is_on_floor():
		velocity.y -= 24.0 * delta
	var pl = StarkGame.player
	var mv := Vector3.ZERO
	if not StarkGame.is_busy() and pl != null and is_instance_valid(pl):
		mv = _think(delta, pl)
	var deep := StarkGame.rule("deep_water", 1.3)
	var np := global_position + mv * delta
	if StarkGame.depth(np.x, np.z) > deep:
		mv = Vector3.ZERO
	var lim := StarkGame.play_size() - 1.0
	if abs(np.x) > lim or abs(np.z) > lim:
		mv = Vector3.ZERO
	velocity.x = mv.x
	velocity.z = mv.z
	if fly:
		var gy := StarkGame.height(global_position.x, global_position.z) + 1.2 + sin(_t * 2.0 + home.x) * 0.4
		velocity.y = (gy - global_position.y) * 6.0
	move_and_slide()
	if _visual:
		_visual.rotation.y = _face
		var k := 1.0 + (0.25 if _hit > 0.0 else 0.0) + (0.15 * sin(_t * 30.0) if _wind > 0.0 else 0.0)
		_visual.scale = Vector3.ONE * k


func _think(delta: float, pl: Node3D) -> Vector3:
	var to := pl.global_position - global_position
	to.y = 0.0
	var d := to.length()
	var dir: Vector3 = to / maxf(d, 0.001)
	var hm := Vector2(global_position.x - home.x, global_position.z - home.z).length()
	var es := float(def.get("speed", 2.6)) * (1.35 if _enraged else 1.0)
	var sight := float(def.get("sight", 14.0))
	var s := size_scale
	if d > 80.0 and state == "patrol":
		return Vector3.ZERO
	if state != "chase" and d < sight and hm < 26.0:
		state = "chase"
	if state == "chase" and (d > sight * 1.7 or hm > 30.0):
		state = "return"
	var mv := Vector3.ZERO
	if state == "return":
		var back := home - global_position
		back.y = 0.0
		mv = back.normalized() * es
		_face = atan2(back.x, back.z)
		if hm < 1.0:
			state = "patrol"
	elif state == "patrol":
		_wt -= delta
		if _wt <= 0.0:
			_wt = 2.0 + randf() * 3.0
			var a := randf() * TAU
			var rr := randf() * patrol
			_target = home + Vector3(cos(a) * rr, 0, sin(a) * rr)
		var pd := _target - global_position
		pd.y = 0.0
		if pd.length() > 0.4:
			mv = pd.normalized() * es * 0.45
			_face = atan2(pd.x, pd.z)
	elif _hit <= 0.0:
		_face = atan2(dir.x, dir.z)
		var dmg := float(def.get("dmg", 1))
		if bool(def.get("ranged", false)):
			if d < 6.0:
				mv = -dir * es
			elif d > 11.0:
				mv = dir * es
			_sh -= delta
			if _sh <= 0.0 and d < 16.0:
				_sh = 1.9
				_shoot(dir * 11.0, dmg, Color(0.6, 1.0, 0.4))
				StarkGame.play_sfx("laser")
		elif _wind > 0.0:
			_wind -= delta
			if _wind <= 0.0:
				if d < 2.6 + s:
					pl.hurt(dmg)
				_cd = 1.6
		else:
			var reach := 1.1 + (1.4 * s if is_boss() else (0.2 if bool(def.get("fly", false)) else 0.3 * s))
			if d > reach * 0.9:
				mv = dir * es
			if d < reach and _cd <= 0.0:
				if kind == "brute" or is_boss():
					_wind = 0.55
				else:
					_cd = 1.2
					pl.hurt(dmg)
		if is_boss():
			_vol -= delta
			if _vol <= 0.0:
				_vol = 3.2 if _enraged else 5.0
				for b in range(14):
					var ba := float(b) / 14.0 * TAU
					_shoot(Vector3(cos(ba), 0, sin(ba)) * 8.0, dmg, Color(1.0, 0.35, 0.8))
				StarkGame.play_sfx("boom")
			if not _enraged and hp < max_hp * 0.5:
				_enraged = true
				StarkGame.emit_toast(title() + " is enraged!", "q")
				if StarkGame.level_node and StarkGame.level_node.has_method("spawn_enemy"):
					for sm in range(2):
						var off := Vector3(3.0 if sm == 1 else -3.0, 0.5, 2.0)
						StarkGame.level_node.spawn_enemy({"i": -1, "kind": "grunt", "patrol": 4.0, "s": 1.0}, global_position + off)
	return mv


func _shoot(vel: Vector3, dmg: float, col: Color) -> void:
	if StarkGame.level_node and StarkGame.level_node.has_method("spawn_projectile"):
		StarkGame.level_node.spawn_projectile(global_position + Vector3(0, 1.2, 0), vel, dmg, true, col)


func take_hit(dmg: float, dir: Vector3) -> void:
	if dead or is_protected():
		return
	var crit := randf() < StarkGame.rule("crit_chance", 0.15)
	hp -= dmg * (2.0 if crit else 1.0)
	_hit = 0.22
	if not is_boss():
		var kp := global_position + Vector3(dir.x, 0, dir.z) * 1.2
		if StarkGame.depth(kp.x, kp.z) <= StarkGame.rule("deep_water", 1.3):
			global_position = Vector3(kp.x, max(global_position.y, StarkGame.height(kp.x, kp.z)), kp.z)
	state = "chase"
	StarkGame.play_sfx("hit")
	if crit:
		StarkGame.emit_toast("Critical hit!")
	if hp <= 0.0:
		die()


func die() -> void:
	if dead:
		return
	dead = true
	hp = 0.0
	StarkGame.set_gone(object_index)
	StarkInventory.score += 50
	StarkGame.play_sfx("boom")
	StarkInventory.add_xp(int(def.get("xp", 10)))
	StarkInventory.gold += int(def.get("gold", 2))
	StarkQuests.event("defeat", {"kind": kind, "id": enemy_id})
	if randf() < (1.0 if is_boss() else 0.18) and StarkGame.level_node and StarkGame.level_node.has_method("spawn_drop"):
		StarkGame.level_node.spawn_drop("elixir" if is_boss() else "potion", global_position)
	if is_boss():
		StarkGame.boss_changed.emit("", -1.0)
		StarkGame.big_text.emit("Victory!", title() + " is defeated", 3.0)
	StarkGame.changed.emit()
	remove_from_group("stark_enemy")
	remove_from_group("stark_objective")
	queue_free()
