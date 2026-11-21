extends CharacterBody3D
## Stark World Engine Runtime third-person hero. WASD / arrows move, Space jumps, J or left click attacks, E talks / opens /
## unlocks, Shift dash (level 2), K whirl (level 3), F star bolt (level 4), Z / C or right-mouse drag turn the camera.
## Same speeds, jump, water and combat numbers as the Stark World Engine browser engine. res://player.gd extends this
## script: put your own changes there.

const Proxy := preload("res://addons/stark_runtime/world/proxy.gd")

@export var visual_scene: PackedScene
@export var visual_scale: float = 1.0
@export var camera_distance: float = 8.5
@export var mouse_sensitivity: float = 0.006

var cam_yaw: float = 0.6
var cam_pitch: float = 0.42
var face: float = 0.0
var atk_t: float = 0.0
var inv_t: float = 0.0
var dash_t: float = 0.0
var whirl_t: float = 0.0
var reach_t: float = 0.0
var walk_phase: float = 0.0
var moving: bool = false
var floating: bool = false
var spawn_point: Vector3 = Vector3.ZERO
var arm: SpringArm3D
var cam: Camera3D
var body: Node3D
var _legs: Array = []
var _swing: MeshInstance3D
var _dragging: bool = false
var _prompt_t: float = 0.0


func _ready() -> void:
	add_to_group("stark_player")
	collision_layer = 2
	collision_mask = 1 | 8
	floor_max_angle = deg_to_rad(50.0)
	floor_snap_length = 0.4
	spawn_point = global_position
	if get_node_or_null("Shape") == null:
		var cs := CollisionShape3D.new()
		cs.name = "Shape"
		var cap := CapsuleShape3D.new()
		cap.radius = 0.4
		cap.height = 1.8
		cs.shape = cap
		cs.position = Vector3(0, 0.9, 0)
		add_child(cs)
	body = Node3D.new()
	body.name = "Body"
	add_child(body)
	if Proxy.visual(body, visual_scene, visual_scale) == null:
		_build_hero()
	arm = SpringArm3D.new()
	arm.name = "CamArm"
	arm.position = Vector3(0, 1.4, 0)
	arm.spring_length = camera_distance
	arm.collision_mask = 1
	arm.margin = 0.2
	var ball := SphereShape3D.new()
	ball.radius = 0.3
	arm.shape = ball
	arm.add_excluded_object(get_rid())
	add_child(arm)
	cam = Camera3D.new()
	cam.name = "Camera"
	cam.fov = 65.0
	cam.far = 900.0
	arm.add_child(cam)
	cam.current = true
	_update_arm()
	StarkGame.player = self


func _build_hero() -> void:
	var cl := StarkGame.color_of(str(StarkGame.data.get("player", {}).get("col", "#2e8c9e")), Color(0.18, 0.55, 0.62))
	var skin := Color(0.98, 0.8, 0.62)
	_legs = [Proxy.part(body, "cube", Vector3(0.2, 0.35, 0), Vector3(0.24, 0.62, 0.26), Color(0.25, 0.2, 0.18)),
		Proxy.part(body, "cube", Vector3(-0.2, 0.35, 0), Vector3(0.24, 0.62, 0.26), Color(0.25, 0.2, 0.18))]
	Proxy.part(body, "cyl", Vector3(0, 1.0, 0), Vector3(0.72, 0.85, 0.5), cl)
	Proxy.part(body, "cyl", Vector3(0, 0.62, 0), Vector3(0.8, 0.22, 0.56), Color(0.4, 0.26, 0.14))
	Proxy.part(body, "cube", Vector3(0, 1.0, -0.3), Vector3(0.66, 0.95, 0.08), cl * 0.6)
	Proxy.part(body, "cube", Vector3(0.47, 1.0, 0), Vector3(0.2, 0.62, 0.2), cl)
	Proxy.part(body, "cube", Vector3(-0.47, 1.0, 0), Vector3(0.2, 0.62, 0.2), cl)
	Proxy.part(body, "sphere", Vector3(0, 1.72, 0), Vector3(0.56, 0.56, 0.56), skin)
	Proxy.part(body, "sphere", Vector3(0, 1.98, -0.04), Vector3(0.62, 0.32, 0.62), Color(0.45, 0.28, 0.15))
	Proxy.part(body, "cube", Vector3(0.12, 1.76, 0.26), Vector3(0.08, 0.1, 0.06), Color(0.08, 0.08, 0.1))
	Proxy.part(body, "cube", Vector3(-0.12, 1.76, 0.26), Vector3(0.08, 0.1, 0.06), Color(0.08, 0.08, 0.1))
	_swing = Proxy.part(body, "sphere", Vector3(0, 1.0, 1.1), Vector3(2.2, 0.15, 1.4), Color(0.6, 1.0, 0.85), 2.0)
	_swing.visible = false


func _update_arm() -> void:
	cam_pitch = clamp(cam_pitch, 0.05, 1.25)
	arm.rotation = Vector3(-cam_pitch, cam_yaw, 0.0)


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and (event as InputEventMouseButton).button_index == MOUSE_BUTTON_RIGHT:
		_dragging = event.pressed
	elif event is InputEventMouseMotion and _dragging:
		var mm := event as InputEventMouseMotion
		cam_yaw -= mm.relative.x * mouse_sensitivity
		cam_pitch += mm.relative.y * mouse_sensitivity
		_update_arm()


func _physics_process(delta: float) -> void:
	var busy := StarkGame.is_busy()
	if Input.is_action_pressed("stark_cam_left"):
		cam_yaw += delta * 2.0
	if Input.is_action_pressed("stark_cam_right"):
		cam_yaw -= delta * 2.0
	_update_arm()
	var mx := 0.0
	var mz := 0.0
	if not busy:
		mx = Input.get_axis("stark_left", "stark_right")
		mz = Input.get_axis("stark_forward", "stark_back")
	var st := StarkInventory.stats()
	var x := global_position.x
	var z := global_position.z
	var spd: float = StarkGame.rule("walk_speed", 7.0) * float(st["speed"]) * (0.6 if StarkGame.depth(x, z) > 0.15 else 1.0)
	var hv := Vector3.ZERO
	moving = false
	if dash_t > 0.0:
		dash_t -= delta
		hv = Vector3(sin(face), 0, cos(face)) * 24.0
	elif mx != 0.0 or mz != 0.0:
		var dir := (Basis(Vector3.UP, cam_yaw) * Vector3(mx, 0, mz)).normalized()
		hv = dir * spd
		face = lerp_angle(face, atan2(dir.x, dir.z), min(1.0, delta * 14.0))
		moving = true
		walk_phase += delta * spd * 1.3
	# deep water stops the hero (the browser engine refuses steps into water deeper than 1.3 m)
	var deep := StarkGame.rule("deep_water", 1.3)
	var nx := x + hv.x * delta
	var nz := z + hv.z * delta
	if StarkGame.depth(nx, nz) > deep and StarkGame.depth(x, z) <= deep:
		hv = Vector3.ZERO
	var lim := StarkGame.play_size() - 1.0
	if abs(nx) > lim:
		hv.x = 0.0
	if abs(nz) > lim:
		hv.z = 0.0
	velocity.x = hv.x
	velocity.z = hv.z
	var g := StarkGame.rule("gravity", 24.0)
	if not is_on_floor() and not floating:
		velocity.y -= g * delta
	if not busy and Input.is_action_just_pressed("stark_jump") and (is_on_floor() or floating):
		velocity.y = StarkGame.rule("jump_speed", 8.5)
		floating = false
		StarkGame.play_sfx("jump")
	move_and_slide()
	var wl := StarkGame.water_level()
	floating = false
	if wl > -1.0e8 and global_position.y < wl - 0.55:
		global_position.y = wl - 0.55
		velocity.y = max(velocity.y, 0.0)
		floating = true
	global_position.x = clamp(global_position.x, -lim - 0.5, lim + 0.5)
	global_position.z = clamp(global_position.z, -lim - 0.5, lim + 0.5)
	if global_position.y < -50.0:
		respawn(null)
	# timers, animation
	if inv_t > 0.0:
		inv_t -= delta
	if atk_t > 0.0:
		atk_t -= delta
	if whirl_t > 0.0:
		whirl_t -= delta
	body.rotation.y = face + (whirl_t * 25.0 if whirl_t > 0.0 else 0.0)
	body.visible = not (inv_t > 0.0 and int(inv_t * 20.0) % 2 == 0)
	if _legs.size() == 2:
		var sw := sin(walk_phase) * 0.22 if moving else 0.0
		(_legs[0] as Node3D).position.z = sw
		(_legs[1] as Node3D).position.z = -sw
	if _swing:
		_swing.visible = atk_t > 0.12
	# actions
	if not busy:
		if Input.is_action_just_pressed("stark_attack") or Input.is_action_just_pressed("stark_attack_mouse"):
			attack()
		if Input.is_action_just_pressed("stark_interact"):
			interact()
		if Input.is_action_just_pressed("stark_dash"):
			dash()
		if Input.is_action_just_pressed("stark_whirl"):
			whirl()
		if Input.is_action_just_pressed("stark_bolt"):
			bolt()
	reach_t -= delta
	if reach_t <= 0.0:
		reach_t = 0.25
		StarkQuests.event("reach", {"x": global_position.x, "z": global_position.z})
	_prompt_t -= delta
	if _prompt_t <= 0.0:
		_prompt_t = 0.1
		var t = nearest_interactable()
		StarkUI.set_prompt("" if busy or t == null else "[E]  " + str(t.prompt_text()))


func forward() -> Vector3:
	return Vector3(sin(face), 0, cos(face))


func _enemies() -> Array:
	var out: Array = []
	for e in get_tree().get_nodes_in_group("stark_enemy"):
		if is_instance_valid(e) and not e.dead:
			out.append(e)
	return out


func attack() -> void:
	if atk_t > 0.0 or StarkGame.is_busy():
		return
	atk_t = StarkGame.rule("attack_cooldown", 0.28)
	StarkGame.play_sfx("laser")
	var f := forward()
	var atk := float(StarkInventory.stats()["atk"])
	for e in _enemies():
		var d: Vector3 = e.global_position - global_position
		d.y = 0.0
		var dist := d.length()
		var reach: float = StarkGame.rule("attack_reach", 2.5) + (1.5 * float(e.size_scale) if e.is_boss() else 0.0)
		if dist < reach and (d / max(dist, 0.001)).dot(f) > -0.25:
			e.take_hit(atk, d / max(dist, 0.001))


func whirl() -> void:
	if not StarkGame.use_ability("Whirl"):
		return
	whirl_t = 0.5
	StarkGame.play_sfx("magic")
	var dmg: float = ceil(float(StarkInventory.stats()["atk"]) * 1.5)
	for e in _enemies():
		var d: Vector3 = e.global_position - global_position
		d.y = 0.0
		if d.length() < 3.6 + (2.0 if e.is_boss() else 0.0):
			e.take_hit(dmg, d.normalized())


func bolt() -> void:
	if not StarkGame.use_ability("Star Bolt"):
		return
	StarkGame.play_sfx("magic")
	var f := forward()
	if StarkGame.level_node and StarkGame.level_node.has_method("spawn_projectile"):
		StarkGame.level_node.spawn_projectile(global_position + f + Vector3(0, 1.1, 0), f * 18.0,
			float(StarkInventory.stats()["atk"]) + 1.0, false, Color(0.6, 0.9, 1.0))


func dash() -> void:
	if not StarkGame.use_ability("Dash"):
		return
	dash_t = 0.2
	StarkGame.play_sfx("jump")


func nearest_interactable():
	var best = null
	var bd := StarkGame.rule("interact_radius", 2.8)
	for n in get_tree().get_nodes_in_group("stark_interactable"):
		if not is_instance_valid(n) or not n.can_interact():
			continue
		var d := Vector2(n.global_position.x - global_position.x, n.global_position.z - global_position.z).length()
		if d < bd + float(n.interact_extra):
			bd = d
			best = n
	return best


func interact() -> void:
	if StarkGame.is_busy():
		return
	var t = nearest_interactable()
	if t != null:
		t.interact(self)


func hurt(d: float) -> void:
	if inv_t > 0.0 or dash_t > 0.0:
		return
	inv_t = 1.0
	StarkGame.play_sfx("hit")
	StarkInventory.hurt(d)


func respawn(at) -> void:
	if at is Vector2:
		global_position = Vector3(at.x, StarkGame.height(at.x, at.y) + 0.3, at.y)
	else:
		global_position = spawn_point
	velocity = Vector3.ZERO
	inv_t = 2.0


func get_save_pos() -> Dictionary:
	return {"x": global_position.x, "z": global_position.z, "y": global_position.y}


func set_save_pos(p) -> void:
	if p is Dictionary and p.has("x") and p.has("z"):
		var x := float(p["x"])
		var z := float(p["z"])
		global_position = Vector3(x, StarkGame.height(x, z) + 0.3, z)
		velocity = Vector3.ZERO


func teleport(x: float, z: float) -> void:
	# used by scripted tests and cut-scenes
	global_position = Vector3(x, StarkGame.height(x, z) + 0.3, z)
	velocity = Vector3.ZERO
