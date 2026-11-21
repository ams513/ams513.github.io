@tool
extends StaticBody3D
## Stark World Engine Runtime terrain: heightmap mesh + HeightMapShape3D collision + splat shader (grass / rock / sand / snow).
## The heights come from res://stark_game.json (the same formula the Stark World Engine browser engine uses, so every
## NPC, chest and portal stands exactly where you put it). Works in the editor too (@tool), so you see the ground.

const SHADER := preload("res://addons/stark_runtime/world/terrain_splat.gdshader")
const GAME_PATH := "res://stark_game.json"

@export var level_index: int = 0
@export_group("Layers (empty = mood colour)")
@export var layer_grass: Texture2D
@export var layer_rock: Texture2D
@export var layer_sand: Texture2D
@export var layer_snow: Texture2D
@export var splat_map: Texture2D
@export var uv_scale: float = 0.25
@export var ground_material: Material
@export_group("")
@export var rebuild: bool = false:
	set(v):
		rebuild = false
		if is_inside_tree():
			build()

static var _game_cache: Dictionary = {}


static func load_game() -> Dictionary:
	if not _game_cache.is_empty():
		return _game_cache
	var f := FileAccess.open(GAME_PATH, FileAccess.READ)
	if f == null:
		return {}
	var d = JSON.parse_string(f.get_as_text())
	if d is Dictionary:
		_game_cache = d
	return _game_cache


static func spec_height(spec: Dictionary, x: float, z: float) -> float:
	if str(spec.get("kind", "stark")) == "grid":
		var hs: Array = spec["heights"]
		var res: int = int(spec["res"])
		var span: float = float(spec["span"])
		var half := span * 0.5
		var cell := span / float(res - 1)
		var gx: float = clamp((x + half) / cell, 0.0, float(res) - 1.0001)
		var gz: float = clamp((z + half) / cell, 0.0, float(res) - 1.0001)
		var x0 := int(gx)
		var z0 := int(gz)
		var a: float = lerp(float(hs[z0 * res + x0]), float(hs[z0 * res + x0 + 1]), gx - x0)
		var b: float = lerp(float(hs[(z0 + 1) * res + x0]), float(hs[(z0 + 1) * res + x0 + 1]), gx - x0)
		return lerp(a, b, gz - z0)
	var s := float(spec.get("seed", 1.0))
	var v := sin(x * 0.13 + s) * 0.6 + cos(z * 0.11 + s * 0.7) * 0.6 + sin((x + z) * 0.05 + s) * 0.8 \
		+ cos(x * 0.045 - z * 0.06 + s * 0.4) * 0.9 + sin(x * 0.29 + z * 0.23 + s * 1.3) * 0.18
	var h := float(spec.get("amp", 1.0)) * v * 0.55
	var d: float = max(abs(x), abs(z)) - float(spec.get("size", 48.0))
	if d > 0.0:
		var t: float = min(1.0, d / float(spec.get("margin", 32.0)))
		h += float(spec.get("edge", 8.0)) * t * t * (3.0 - 2.0 * t)
	return h


func _ready() -> void:
	build()


func _level() -> Dictionary:
	var g := load_game()
	var lv: Array = g.get("levels", [])
	return lv[level_index] if level_index >= 0 and level_index < lv.size() else {}


func build() -> void:
	for c in get_children():
		if c.has_meta("gs_generated"):
			remove_child(c)
			c.queue_free()
	var L := _level()
	if not L.has("terrain"):
		return
	var spec: Dictionary = L["terrain"]
	var span := float(spec.get("span", 160.0))
	var res := int(spec["res"]) if str(spec.get("kind", "")) == "grid" else int(clamp(ceil(span / max(1.0, span / 256.0)) + 1.0, 65.0, 257.0))
	var cell := span / float(res - 1)
	var half := span * 0.5
	var hs := PackedFloat32Array()
	hs.resize(res * res)
	for iz in range(res):
		for ix in range(res):
			hs[iz * res + ix] = spec_height(spec, -half + ix * cell, -half + iz * cell)
	var verts := PackedVector3Array()
	var norms := PackedVector3Array()
	var uvs := PackedVector2Array()
	var uv2s := PackedVector2Array()
	verts.resize(res * res)
	norms.resize(res * res)
	uvs.resize(res * res)
	uv2s.resize(res * res)
	for iz in range(res):
		for ix in range(res):
			var i := iz * res + ix
			var x := -half + ix * cell
			var z := -half + iz * cell
			verts[i] = Vector3(x, hs[i], z)
			var hl := hs[iz * res + maxi(ix - 1, 0)]
			var hr := hs[iz * res + mini(ix + 1, res - 1)]
			var hd := hs[maxi(iz - 1, 0) * res + ix]
			var hu := hs[mini(iz + 1, res - 1) * res + ix]
			norms[i] = Vector3(hl - hr, 2.0 * cell, hd - hu).normalized()
			uvs[i] = Vector2(x, z) * 0.25
			uv2s[i] = Vector2(float(ix) / float(res - 1), float(iz) / float(res - 1))
	var idx := PackedInt32Array()
	idx.resize((res - 1) * (res - 1) * 6)
	var k := 0
	for iz in range(res - 1):
		for ix in range(res - 1):
			var a := iz * res + ix
			var b := a + 1
			var c := a + res
			var d := c + 1
			idx[k] = a
			idx[k + 1] = b
			idx[k + 2] = c
			idx[k + 3] = b
			idx[k + 4] = d
			idx[k + 5] = c
			k += 6
	var arrays := []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = verts
	arrays[Mesh.ARRAY_NORMAL] = norms
	arrays[Mesh.ARRAY_TEX_UV] = uvs
	arrays[Mesh.ARRAY_TEX_UV2] = uv2s
	arrays[Mesh.ARRAY_INDEX] = idx
	var mesh := ArrayMesh.new()
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	var mi := MeshInstance3D.new()
	mi.name = "TerrainMesh"
	mi.mesh = mesh
	mi.material_override = ground_material if ground_material else _splat_material(L)
	mi.set_meta("gs_generated", true)
	add_child(mi)
	var shape := HeightMapShape3D.new()
	shape.map_width = res
	shape.map_depth = res
	var data := PackedFloat32Array()
	data.resize(res * res)
	for i in range(res * res):
		data[i] = hs[i] / cell
	shape.map_data = data
	var cs := CollisionShape3D.new()
	cs.name = "TerrainShape"
	cs.shape = shape
	cs.scale = Vector3(cell, cell, cell)
	cs.set_meta("gs_generated", true)
	add_child(cs)


func _splat_material(L: Dictionary) -> ShaderMaterial:
	var pal: Dictionary = L.get("palette", {})
	var m := ShaderMaterial.new()
	m.shader = SHADER
	m.set_shader_parameter("grass_color", _col(pal.get("ground", [0.3, 0.5, 0.25])))
	m.set_shader_parameter("rock_color", _col(pal.get("stone", [0.45, 0.43, 0.42])))
	m.set_shader_parameter("sand_color", _col(pal.get("sand", [0.78, 0.7, 0.5])))
	m.set_shader_parameter("snow_color", _col(pal.get("snow", [0.92, 0.94, 0.97])))
	m.set_shader_parameter("water_level", float(L["water"]) if L.get("water") != null else -1000.0)
	m.set_shader_parameter("snow_line", float(pal.get("snow_line", 1000.0)))
	m.set_shader_parameter("uv_scale", uv_scale)
	for pair in [["grass", layer_grass], ["rock", layer_rock], ["sand", layer_sand], ["snow", layer_snow]]:
		if pair[1] != null:
			m.set_shader_parameter(str(pair[0]) + "_tex", pair[1])
			m.set_shader_parameter("use_" + str(pair[0]) + "_tex", true)
	if splat_map != null:
		m.set_shader_parameter("splat_tex", splat_map)
		m.set_shader_parameter("use_splat", true)
	var noise := FastNoiseLite.new()
	noise.frequency = 0.05
	noise.seed = int(float(L.get("seed", 1.0)))
	var tex := NoiseTexture2D.new()
	tex.noise = noise
	tex.seamless = true
	tex.width = 256
	tex.height = 256
	m.set_shader_parameter("variation_tex", tex)
	return m


static func _col(a) -> Color:
	if a is Array and a.size() >= 3:
		return Color(float(a[0]), float(a[1]), float(a[2]))
	return Color(0.5, 0.5, 0.5)
