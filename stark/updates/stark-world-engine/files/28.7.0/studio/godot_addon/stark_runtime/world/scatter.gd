@tool
extends Node3D
## Stark World Engine Runtime scenery: trees, rocks, ruins, lamps and houses exactly where the creator placed them, plus ambient
## grass. Proxies are drawn as MultiMeshes (one draw per part). Swap a whole class for real art in the Inspector:
## *_scene = a PackedScene (.glb/.gltf/.tscn, instanced per object), *_scale multiplies its size. Colliders stay.

const Proxy := preload("res://addons/stark_runtime/world/proxy.gd")
const Terrain := preload("res://addons/stark_runtime/world/terrain.gd")

@export var level_index: int = 0
@export var grass: bool = true
@export_group("Art slots (empty = proxy)")
@export var tree_scene: PackedScene
@export var tree_scale: float = 1.0
@export var rock_scene: PackedScene
@export var rock_scale: float = 1.0
@export var ruin_scene: PackedScene
@export var ruin_scale: float = 1.0
@export var lamp_scene: PackedScene
@export var lamp_scale: float = 1.0
@export var house_scene: PackedScene
@export var house_scale: float = 1.0
@export var grass_scene: PackedScene
@export_group("")
@export var rebuild: bool = false:
	set(v):
		rebuild = false
		if is_inside_tree():
			build()

var _parts: Dictionary = {}   # "shape|emit" -> [[Transform3D, Color], ...]


func _ready() -> void:
	build()


func _level() -> Dictionary:
	var lv: Array = Terrain.load_game().get("levels", [])
	return lv[level_index] if level_index >= 0 and level_index < lv.size() else {}


func build() -> void:
	for c in get_children():
		remove_child(c)
		c.queue_free()
	var L := _level()
	if L.is_empty():
		return
	var spec: Dictionary = L.get("terrain", {})
	var pal: Dictionary = L.get("palette", {})
	var leaf: Array = pal.get("leaf", [[0.2, 0.5, 0.3], [0.25, 0.55, 0.3], [0.15, 0.45, 0.25]])
	var stone := _c(pal.get("stone", [0.45, 0.45, 0.5]))
	var fx := _c(pal.get("fx", [1.0, 0.85, 0.4]))
	var seed_value := int(float(L.get("seed", 1.0)))
	_parts = {}
	var bodies := StaticBody3D.new()
	bodies.name = "Colliders"
	add_child(bodies)
	var lights := Node3D.new()
	lights.name = "Lights"
	add_child(lights)
	var art := Node3D.new()
	art.name = "Art"
	add_child(art)
	var n_shadow := 0
	for o in L.get("objects", []):
		var t := str(o["t"])
		if not (t in ["tree", "rock", "ruin", "lamp", "house"]):
			continue
		var idx := int(o["i"])
		var s := float(o.get("s", 1.0))
		var x := float(o["x"])
		var z := float(o["z"])
		var b := Terrain.spec_height(spec, x, z)
		var rng := RandomNumberGenerator.new()
		rng.seed = idx * 13 + seed_value
		var rot := rng.randf() * TAU
		var lc := _c(leaf[idx % leaf.size()])
		var scene: PackedScene = get(t + "_scene")
		if scene != null:
			var inst := Proxy.visual(art, scene, s * float(get(t + "_scale")))
			if inst:
				inst.position = Vector3(x, b, z)
				inst.rotation.y = deg_to_rad(-float(o.get("yaw", 0.0))) if t == "house" else rot
		else:
			_object_parts(t, x, b, z, s, rot, deg_to_rad(-float(o.get("yaw", 0.0))), lc, stone, fx, idx, seed_value)
		# colliders (same footprint as the browser engine) + lights
		if t == "house":
			var hw := 4.2 * s
			var hd := 3.4 * s
			var bs := BoxShape3D.new()
			bs.size = Vector3(hw + 0.2, 2.6 * s + 0.6, hd + 0.2)
			var cs := CollisionShape3D.new()
			cs.shape = bs
			cs.transform = Transform3D(Basis(Vector3.UP, deg_to_rad(-float(o.get("yaw", 0.0)))), Vector3(x, b + 1.3 * s, z))
			bodies.add_child(cs)
		elif t == "ruin":
			for c in range(4):
				var px := x + (1.6 if c % 2 == 1 else -1.6) * s
				var pz := z + (1.6 if c < 2 else -1.6) * s
				_cyl_collider(bodies, Vector3(px, Terrain.spec_height(spec, px, pz), pz), 0.42 * s, 3.0 * s)
		else:
			var r := 0.45 * s if t == "tree" else (0.75 * s if t == "rock" else 0.25)
			_cyl_collider(bodies, Vector3(x, b, z), r, 3.0 * s)
		if t == "lamp":
			var ol := OmniLight3D.new()
			ol.position = Vector3(x, b + 2.35 * s, z)
			ol.light_color = fx
			ol.light_energy = 2.0
			ol.omni_range = 14.0
			ol.shadow_enabled = n_shadow < 6
			n_shadow += 1
			lights.add_child(ol)
	if grass:
		_grass(L, spec, leaf, fx, stone, seed_value)
	for key in _parts.keys():
		var bits := str(key).split("|")
		_multimesh(bits[0], float(bits[1]), _parts[key], fx)


func _add(shape: String, emit: float, xf: Transform3D, col: Color) -> void:
	var key := "%s|%.1f" % [shape, emit]
	if not _parts.has(key):
		_parts[key] = []
	_parts[key].append([xf, col])


func _p(shape: String, origin: Vector3, yaw: float, off: Vector3, size: Vector3, col: Color, emit: float = 0.0, spin: float = 0.0) -> void:
	var by := Basis(Vector3.UP, yaw)
	_add(shape, emit, Transform3D(Basis(Vector3.UP, yaw + spin).scaled(size), origin + by * off), col)


func _object_parts(t: String, x: float, b: float, z: float, s: float, rot: float, yaw: float, lc: Color, stone: Color,
		fx: Color, idx: int, seed_value: int) -> void:
	var o := Vector3(x, b, z)
	var trunk := Color(0.36, 0.23, 0.14)
	if t == "tree":
		if (idx * 7 + seed_value) % 3 < 2:
			_p("cyl", o, rot, Vector3(0, 0.9 * s, 0), Vector3(0.36, 1.8, 0.36) * s, trunk)
			_p("cone", o, rot, Vector3(0, 2.1 * s, 0), Vector3(2.6, 1.7, 2.6) * s, lc)
			_p("cone", o, rot, Vector3(0, 3.0 * s, 0), Vector3(2.0, 1.5, 2.0) * s, lc * 1.1, 0.0, 1.0)
			_p("cone", o, rot, Vector3(0, 3.8 * s, 0), Vector3(1.3, 1.3, 1.3) * s, lc * 1.2, 0.0, 2.0)
		else:
			_p("cyl", o, rot, Vector3(0, 1.1 * s, 0), Vector3(0.4, 2.2, 0.4) * s, trunk)
			_p("sphere", o, rot, Vector3(0, 3.0 * s, 0), Vector3(2.8, 2.3, 2.8) * s, lc)
			_p("sphere", o, rot, Vector3(0.8 * s, 3.6 * s, 0.3 * s), Vector3(1.7, 1.5, 1.7) * s, lc * 1.15)
			_p("sphere", o, rot, Vector3(-0.7 * s, 2.6 * s, -0.5 * s), Vector3(1.5, 1.3, 1.5) * s, lc * 0.9)
	elif t == "rock":
		_p("rock", o, rot, Vector3(0, 0.35 * s, 0), Vector3(1.7, 1.2, 1.4) * s, stone * 0.82)
		_p("rock", o, rot + 2.0, Vector3(0.5 * s, 0.25 * s, 0.4 * s), Vector3(0.8, 0.6, 0.7) * s, stone)
	elif t == "ruin":
		var rng := RandomNumberGenerator.new()
		rng.seed = idx * 31 + seed_value
		for c in range(4):
			var off := Vector3((1.6 if c % 2 == 1 else -1.6) * s, 0, (1.6 if c < 2 else -1.6) * s)
			var ph := (1.2 + rng.randf() * 2.4) * s
			_p("cyl", o, 0.0, off + Vector3(0, ph * 0.5, 0), Vector3(0.75 * s, ph, 0.75 * s), stone)
			_p("cube", o, 0.0, off + Vector3(0, ph + 0.06, 0), Vector3(0.9 * s, 0.14, 0.9 * s), stone * 1.1)
			_p("sphere", o, 0.0, off + Vector3(0, ph + 0.16, 0), Vector3(0.8 * s, 0.25, 0.8 * s), lc)
		_p("cube", o, 0.0, Vector3(0, 3.3 * s, -1.6 * s), Vector3(4.0, 0.5, 0.8) * s, stone)
		_p("rock", o, rot, Vector3(1.2 * s, 0.2, 0.8 * s), Vector3(1.0 * s, 0.6, 0.8 * s), stone * 0.85)
		_p("cube", o, 0.2, Vector3(-0.4 * s, 0.08, 0.3 * s), Vector3(3.4 * s, 0.16, 3.4 * s), stone * 0.75)
	elif t == "lamp":
		_p("cyl", o, 0.0, Vector3(0, 1.1 * s, 0), Vector3(0.16, 2.2, 0.16) * s, Color(0.16, 0.16, 0.18))
		_p("cube", o, 0.785, Vector3(0, 2.35 * s, 0), Vector3(0.42, 0.42, 0.42) * s, fx, 3.0)
		_p("pyr", o, 0.785, Vector3(0, 2.7 * s, 0), Vector3(0.7, 0.3, 0.7) * s, Color(0.14, 0.14, 0.16))
	elif t == "house":
		var hw := 4.2 * s
		var hd := 3.4 * s
		var hh := 2.6 * s
		var wall := Color(0.86, 0.78, 0.64)
		var roof := Color(0.55, 0.22, 0.16).lerp(stone, 0.3)
		_p("cube", o, yaw, Vector3(0, hh * 0.5 - 0.2, 0), Vector3(hw, hh + 0.4, hd), wall)
		_p("pyr", o, yaw, Vector3(0, hh + 0.9 * s, 0), Vector3((hw + 0.8 * s) / 0.707, 2.0 * s, (hd + 0.8 * s) / 0.707), roof, 0.0, 0.785)
		_p("cube", o, yaw, Vector3(0, 0.7 * s, hd * 0.5 + 0.02), Vector3(0.9 * s, 1.5 * s, 0.1), Color(0.3, 0.18, 0.1))
		_p("cube", o, yaw, Vector3(1.3 * s, 1.4 * s, hd * 0.5 + 0.03), Vector3(0.7 * s, 0.6 * s, 0.08), Color(1.0, 0.75, 0.4), 2.0)
		_p("cube", o, yaw, Vector3(-1.3 * s, 1.4 * s, hd * 0.5 + 0.03), Vector3(0.7 * s, 0.6 * s, 0.08), Color(1.0, 0.75, 0.4), 2.0)
		_p("cube", o, yaw, Vector3(1.2 * s, hh + 1.3 * s, -0.6 * s), Vector3(0.5 * s, 1.4 * s, 0.5 * s), stone * 0.9)


func _grass(L: Dictionary, spec: Dictionary, leaf: Array, fx: Color, stone: Color, seed_value: int) -> void:
	var size := float(L.get("size", 48.0))
	var water: float = float(L["water"]) if L.get("water") != null else -1.0e9
	var n: int = int(min(2600.0, round(1000.0 * size * size / (48.0 * 48.0))))
	var rng := RandomNumberGenerator.new()
	rng.seed = seed_value * 7 + 3
	var custom: Mesh = null
	var custom_xf: Array = []
	if grass_scene != null:
		var g := grass_scene.instantiate()
		custom = Proxy.first_mesh(g)
		g.free()
	for i in range(n):
		var x := (rng.randf() * 2.0 - 1.0) * size * 0.97
		var z := (rng.randf() * 2.0 - 1.0) * size * 0.97
		var h := Terrain.spec_height(spec, x, z)
		if h < water + 0.1:
			continue
		var lc := _c(leaf[i % leaf.size()]) * (0.8 + rng.randf() * 0.5) * 1.2
		var o := Vector3(x, h, z)
		if custom != null:
			custom_xf.append(Transform3D(Basis(Vector3.UP, rng.randf() * TAU), o))
			continue
		_p("cone", o, rng.randf() * TAU, Vector3(0, 0.22, 0), Vector3(0.16, 0.5 + rng.randf() * 0.35, 0.16), lc)
		if i % 15 == 0:
			_p("sphere", o, 0.0, Vector3(0.15, 0.4, 0), Vector3(0.14, 0.14, 0.14), fx.lerp(Color(1, 0.6, 0.8), float(i % 30) / 30.0), 0.6)
		if i % 9 == 0:
			_p("rock", o, rng.randf() * TAU, Vector3(0, 0.05, 0), Vector3(0.35, 0.22, 0.3), stone * (0.8 + rng.randf() * 0.3))
	if custom != null and not custom_xf.is_empty():
		var mm := MultiMesh.new()
		mm.transform_format = MultiMesh.TRANSFORM_3D
		mm.mesh = custom
		mm.instance_count = custom_xf.size()
		for i in range(custom_xf.size()):
			mm.set_instance_transform(i, custom_xf[i])
		var mmi := MultiMeshInstance3D.new()
		mmi.name = "GrassArt"
		mmi.multimesh = mm
		add_child(mmi)


func _multimesh(shape: String, emit: float, lst: Array, fx: Color) -> void:
	var mm := MultiMesh.new()
	mm.transform_format = MultiMesh.TRANSFORM_3D
	mm.use_colors = true
	mm.mesh = Proxy.shape(shape)
	mm.instance_count = lst.size()
	for i in range(lst.size()):
		mm.set_instance_transform(i, lst[i][0])
		mm.set_instance_color(i, lst[i][1])
	var mmi := MultiMeshInstance3D.new()
	mmi.name = "%s_%d" % [shape, int(emit * 10)]
	mmi.multimesh = mm
	var m := StandardMaterial3D.new()
	m.vertex_color_use_as_albedo = true
	m.roughness = 0.85
	if emit > 0.0:
		m.emission_enabled = true
		m.emission = fx
		m.emission_energy_multiplier = emit
		m.roughness = 0.3
	mmi.material_override = m
	add_child(mmi)


func _cyl_collider(parent: Node3D, base: Vector3, r: float, h: float) -> void:
	var cs := CollisionShape3D.new()
	var shape := CylinderShape3D.new()
	shape.radius = r
	shape.height = h
	cs.shape = shape
	cs.position = base + Vector3(0, h * 0.5, 0)
	parent.add_child(cs)


static func _c(a) -> Color:
	if a is Array and a.size() >= 3:
		return Color(float(a[0]), float(a[1]), float(a[2]))
	return Color(0.5, 0.5, 0.5)
