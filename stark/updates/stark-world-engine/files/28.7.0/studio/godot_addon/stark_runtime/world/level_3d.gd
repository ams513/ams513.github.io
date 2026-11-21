extends Node3D
## Stark World Engine Runtime 3D level root (one per level scene: main.tscn is level 1, levels/level_02.tscn is level 2 ...).
## Starts the level's auto quests, keeps "defeat N" steps possible (ensure_foes), points the gold guide beam at the
## current objective, shows the boss bar and runs the weather particles.

const Proxy := preload("res://addons/stark_runtime/world/proxy.gd")
const ENEMY := preload("res://addons/stark_runtime/actors/enemy_3d.gd")
const PICKUP := preload("res://addons/stark_runtime/actors/pickup_3d.gd")
const PROJECTILE := preload("res://addons/stark_runtime/actors/projectile_3d.gd")

@export var level_index: int = 0
@export var show_title: bool = true
@export var guide_beam: bool = true

var _beam: MeshInstance3D
var _beam_t: float = 0.0
var _boss_t: float = 0.0
var _boss_shown: bool = false
var _weather: GPUParticles3D


func _enter_tree() -> void:
	StarkGame.li = level_index
	StarkGame.level_node = self


func _ready() -> void:
	add_to_group("stark_level")
	_make_beam()
	_make_weather()
	StarkGame.level_ready(self, level_index, show_title)


func gameplay_root() -> Node3D:
	var g := get_node_or_null("Gameplay")
	return g if g is Node3D else self


# ---------------------------------------------------------------- enemies on demand (browser ensureFoes)
func enemies() -> Array:
	var out: Array = []
	for e in get_tree().get_nodes_in_group("stark_enemy"):
		if is_instance_valid(e) and not e.dead:
			out.append(e)
	return out


func _matches(e, kind: String) -> bool:
	var k := "any" if kind == "" else kind
	return (k == "boss") == e.is_boss() and (k == "any" or str(e.kind) == k)


func ensure_foes(kind: String, need: int) -> void:
	if need <= 0:
		return
	var alive := 0
	for e in enemies():
		if _matches(e, kind):
			alive += 1
	var L := StarkGame.current_level()
	for o in L.get("objects", []):
		if alive >= need:
			break
		if str(o["t"]) != "enemy" or str(o.get("id", "")) != "" or not StarkGame.is_gone(int(o["i"])):
			continue
		var k := str(o.get("kind", "grunt"))
		if StarkGame.is_minor(str(o.get("id", "")), str(o.get("age", "adult"))):
			continue
		if not ((kind == "boss") == (k == "boss") and (kind == "" or kind == "any" or k == kind)):
			continue
		StarkGame.gone.erase(StarkGame.gone_key(int(o["i"])))
		spawn_enemy(o, Vector3(float(o["x"]), float(o.get("y", 0.0)) + 0.5, float(o["z"])))
		alive += 1
	var homes: Array = []
	for e in enemies():
		if not e.is_boss():
			homes.append(e.home)
	var tries := 0
	var rng := RandomNumberGenerator.new()
	rng.randomize()
	while alive < need and tries < 60:
		tries += 1
		var p := Vector3.ZERO
		if not homes.is_empty():
			var h: Vector3 = homes[tries % homes.size()]
			p = h + Vector3(rng.randf_range(-3, 3), 0, rng.randf_range(-3, 3))
		elif StarkGame.player:
			var a := rng.randf() * TAU
			p = StarkGame.player.global_position + Vector3(cos(a) * 14.0, 0, sin(a) * 14.0)
		var lim := StarkGame.play_size() - 2.0
		p.x = clamp(p.x, -lim, lim)
		p.z = clamp(p.z, -lim, lim)
		if StarkGame.depth(p.x, p.z) > 0.8:
			continue
		p.y = StarkGame.height(p.x, p.z) + 0.5
		spawn_enemy({"i": -1, "kind": "grunt" if kind == "" or kind == "any" else kind, "patrol": 5.0, "s": 1.0}, p)
		alive += 1


func spawn_enemy(o: Dictionary, pos: Vector3) -> Node:
	var e := ENEMY.new()
	e.object_index = int(o.get("i", -1))
	e.kind = str(o.get("kind", "grunt"))
	e.enemy_id = str(o.get("id", ""))
	e.age = str(o.get("age", "adult"))
	e.display_name = str(o.get("name", ""))
	e.hp_override = int(o.get("hp", 0))
	e.patrol = float(o.get("patrol", 5.0))
	e.size_scale = float(o.get("s", 1.0))
	e.name = "Enemy_spawned_%d" % randi()
	gameplay_root().add_child(e)
	e.global_position = pos
	return e


func spawn_drop(item_id: String, pos: Vector3) -> void:
	var p := PICKUP.new()
	p.item = item_id
	p.count = 1
	p.object_index = -1
	gameplay_root().add_child(p)
	p.global_position = Vector3(pos.x, StarkGame.height(pos.x, pos.z), pos.z)


func spawn_projectile(pos: Vector3, vel: Vector3, dmg: float, from_enemy: bool, col: Color) -> void:
	var pr := PROJECTILE.new()
	pr.velocity = vel
	pr.damage = dmg
	pr.from_enemy = from_enemy
	pr.color = col
	add_child(pr)
	pr.global_position = pos


# ---------------------------------------------------------------- guide beam + boss bar + weather
func _make_beam() -> void:
	_beam = MeshInstance3D.new()
	var c := CylinderMesh.new()
	c.top_radius = 0.12
	c.bottom_radius = 0.12
	c.height = 40.0
	_beam.mesh = c
	var m := StandardMaterial3D.new()
	m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	m.albedo_color = Color(1.0, 0.82, 0.3, 0.45)
	m.emission_enabled = true
	m.emission = Color(1.0, 0.8, 0.3)
	_beam.material_override = m
	_beam.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	_beam.visible = false
	add_child(_beam)


func objective_point():
	# -> Vector3 of the current objective (first active quest step), or null
	var me = StarkGame.player
	for x in StarkQuests.cur_steps():
		var s: Dictionary = x["s"]
		var lv := int(s.get("level", -1))
		if lv < 0:
			lv = int(x["q"].get("level", 0))
		if lv != level_index and str(s["type"]) != "collect" and str(s["type"]) != "talk":
			continue
		var t := str(s["type"])
		if t == "reach" or t == "escort":
			var p2: Vector2 = StarkQuests.target_point(s)
			return Vector3(p2.x, StarkGame.height(p2.x, p2.y), p2.y)
		var best = null
		var bd := 1.0e9
		for n in get_tree().get_nodes_in_group("stark_objective"):
			if not is_instance_valid(n) or not n.has_method("objective_match") or not n.objective_match(s):
				continue
			var d: float = n.global_position.distance_to(me.global_position) if me else 0.0
			if d < bd:
				bd = d
				best = n.global_position
		if best != null:
			return best
	return null


func _process(delta: float) -> void:
	_beam_t -= delta
	if _beam_t <= 0.0:
		_beam_t = 0.25
		var p = objective_point() if guide_beam else null
		_beam.visible = p != null
		if p != null:
			_beam.global_position = (p as Vector3) + Vector3(0, 20, 0)
	_boss_t -= delta
	if _boss_t <= 0.0:
		_boss_t = 0.2
		var boss = null
		for e in enemies():
			if e.is_boss() and e.state == "chase" and StarkGame.player and \
					e.global_position.distance_to(StarkGame.player.global_position) < float(e.def.get("sight", 26)) * 1.7:
				boss = e
		if boss != null:
			StarkGame.boss_changed.emit(boss.title(), float(boss.hp) / max(1.0, float(boss.max_hp)))
			_boss_shown = true
		elif _boss_shown:
			StarkGame.boss_changed.emit("", -1.0)
			_boss_shown = false
	if _weather and StarkGame.player and is_instance_valid(StarkGame.player):
		_weather.global_position = StarkGame.player.global_position + Vector3(0, 9, 0)


func _make_weather() -> void:
	var fx := str(StarkGame.level(level_index).get("fx", "clear"))
	if fx == "clear" or fx == "" or fx == "auto":
		return
	var p := GPUParticles3D.new()
	var pm := ParticleProcessMaterial.new()
	pm.emission_shape = ParticleProcessMaterial.EMISSION_SHAPE_BOX
	pm.emission_box_extents = Vector3(24, 1, 24)
	var quad := QuadMesh.new()
	quad.size = Vector2(0.12, 0.12)
	var col := Color(1, 1, 1, 0.8)
	var pal: Dictionary = StarkGame.level(level_index).get("palette", {})
	var fxc: Array = pal.get("fx", [1.0, 0.9, 0.5])
	var glow := Color(float(fxc[0]), float(fxc[1]), float(fxc[2]), 0.9)
	p.amount = 600
	p.lifetime = 6.0
	match fx:
		"rain", "storm":
			pm.gravity = Vector3(0, -32, 0)
			quad.size = Vector2(0.03, 0.7)
			col = Color(0.7, 0.78, 1.0, 0.5)
			p.amount = 1600 if fx == "storm" else 1000
			p.lifetime = 0.9
		"snow":
			pm.gravity = Vector3(0, -1.6, 0)
			p.amount = 900
			p.lifetime = 8.0
		"embers", "bubbles":
			pm.gravity = Vector3(0, 1.2, 0)
			pm.emission_box_extents = Vector3(24, 6, 24)
			col = glow
			p.lifetime = 5.0
		_:
			pm.gravity = Vector3(0, 0.05, 0)
			pm.emission_box_extents = Vector3(24, 7, 24)
			pm.initial_velocity_min = 0.2
			pm.initial_velocity_max = 0.6
			pm.direction = Vector3(1, 0.2, 0)
			pm.spread = 180.0
			col = glow
			p.amount = 300
	var m := StandardMaterial3D.new()
	m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	m.billboard_mode = BaseMaterial3D.BILLBOARD_PARTICLES
	m.albedo_color = col
	if fx != "rain" and fx != "storm" and fx != "snow":
		m.emission_enabled = true
		m.emission = Color(col.r, col.g, col.b)
		m.emission_energy_multiplier = 2.0
	quad.material = m
	p.draw_pass_1 = quad
	p.process_material = pm
	p.visibility_aabb = AABB(Vector3(-30, -30, -30), Vector3(60, 60, 60))
	p.name = "Weather"
	_weather = p
	add_child(p)
