extends Node3D
## Stark World Engine Runtime projectile: archer arrows, boss volleys and the hero's star bolt.

const Proxy := preload("res://addons/stark_runtime/world/proxy.gd")

var velocity: Vector3 = Vector3.ZERO
var damage: float = 1.0
var from_enemy: bool = true
var color: Color = Color(0.6, 1.0, 0.4)
var life: float = 2.0


func _ready() -> void:
	life = 2.4 if from_enemy else 1.4
	Proxy.part(self, "sphere", Vector3.ZERO, Vector3(0.35, 0.35, 0.35), color, 3.0)


func _physics_process(delta: float) -> void:
	life -= delta
	global_position += velocity * delta
	var p := global_position
	if life <= 0.0 or StarkGame.height(p.x, p.z) > p.y:
		queue_free()
		return
	if from_enemy:
		var pl = StarkGame.player
		if pl and is_instance_valid(pl) and Vector2(pl.global_position.x - p.x, pl.global_position.z - p.z).length() < 0.7 \
				and abs(p.y - pl.global_position.y - 0.9) < 1.2:
			pl.hurt(damage)
			queue_free()
	else:
		for e in get_tree().get_nodes_in_group("stark_enemy"):
			if not is_instance_valid(e) or e.dead:
				continue
			var r: float = 0.8 * float(e.size_scale) + (1.2 if e.is_boss() else 0.0)
			if Vector2(e.global_position.x - p.x, e.global_position.z - p.z).length() < r:
				e.take_hit(damage, velocity.normalized())
				queue_free()
				return
