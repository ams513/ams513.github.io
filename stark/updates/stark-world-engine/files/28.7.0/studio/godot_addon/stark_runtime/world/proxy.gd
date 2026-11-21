extends RefCounted
## Stark World Engine Runtime - proxy shapes and materials: simple stand-ins until you drop in real art
## (a glTF/.glb or .tscn in an actor's "visual_scene" slot, or a mesh/scene slot on the Scenery node).

static var _meshes: Dictionary = {}
static var _mats: Dictionary = {}


static func shape(kind: String) -> Mesh:
	if _meshes.has(kind):
		return _meshes[kind]
	var m: Mesh
	match kind:
		"cube":
			m = BoxMesh.new()
		"cyl":
			var c := CylinderMesh.new()
			c.top_radius = 0.5
			c.bottom_radius = 0.5
			c.height = 1.0
			c.radial_segments = 10
			m = c
		"cone":
			var k := CylinderMesh.new()
			k.top_radius = 0.0
			k.bottom_radius = 0.5
			k.height = 1.0
			k.radial_segments = 9
			m = k
		"pyr":
			var p := CylinderMesh.new()
			p.top_radius = 0.0
			p.bottom_radius = 0.5
			p.height = 1.0
			p.radial_segments = 4
			p.rings = 1
			m = p
		"rock":
			var r := SphereMesh.new()
			r.radius = 0.5
			r.height = 1.0
			r.radial_segments = 7
			r.rings = 4
			m = r
		"gem":
			var g := SphereMesh.new()
			g.radius = 0.5
			g.height = 1.0
			g.radial_segments = 4
			g.rings = 2
			m = g
		_:
			var s := SphereMesh.new()
			s.radius = 0.5
			s.height = 1.0
			s.radial_segments = 16
			s.rings = 8
			m = s
	_meshes[kind] = m
	return m


static func mat(col: Color, emit: float = 0.0, rough: float = 0.85, vertex_color: bool = false) -> StandardMaterial3D:
	var key := "%s|%.2f|%.2f|%s" % [col.to_html(), emit, rough, vertex_color]
	if _mats.has(key):
		return _mats[key]
	var m := StandardMaterial3D.new()
	m.albedo_color = col
	m.roughness = rough
	if vertex_color:
		m.vertex_color_use_as_albedo = true
	if emit > 0.0:
		m.emission_enabled = true
		m.emission = col
		m.emission_energy_multiplier = emit
	_mats[key] = m
	return m


static func part(parent: Node3D, kind: String, pos: Vector3, size: Vector3, col: Color, emit: float = 0.0,
		yaw: float = 0.0) -> MeshInstance3D:
	var mi := MeshInstance3D.new()
	mi.mesh = shape(kind)
	mi.material_override = mat(col, emit, 0.3 if emit > 0.0 else 0.85)
	mi.transform = Transform3D(Basis(Vector3.UP, yaw).scaled(size), pos)
	parent.add_child(mi)
	return mi


static func visual(parent: Node3D, scene: PackedScene, scale_value: float) -> Node3D:
	# instance a glTF/.tscn visual; -> the instance or null
	if scene == null:
		return null
	var inst := scene.instantiate()
	if inst is Node3D:
		(inst as Node3D).scale = Vector3.ONE * scale_value
		inst.name = "Visual"
		parent.add_child(inst)
		return inst as Node3D
	inst.free()
	return null


static func first_mesh(node: Node) -> Mesh:
	# the first Mesh inside an instanced glTF scene (used to put library art into MultiMeshes)
	if node is MeshInstance3D and (node as MeshInstance3D).mesh != null:
		return (node as MeshInstance3D).mesh
	for c in node.get_children():
		var m := first_mesh(c)
		if m != null:
			return m
	return null


static func label(parent: Node3D, txt: String, y: float, col: Color = Color(1.0, 0.82, 0.4)) -> Label3D:
	var l := Label3D.new()
	l.text = txt
	l.position = Vector3(0, y, 0)
	l.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	l.modulate = col
	l.font_size = 64
	l.pixel_size = 0.01
	l.outline_size = 12
	l.no_depth_test = true
	parent.add_child(l)
	return l
