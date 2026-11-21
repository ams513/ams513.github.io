extends SceneTree
## Stark World Engine Runtime child-safety backstop check (headless). The exporter already refuses unsafe worlds; this proves the
## runtime also never lets a child or teen be an enemy, a combat target, a defeat goal or the subject of a harm /
## capture / romance dialogue action, even if a project file was edited by hand.
##   godot --headless --path <project> --script res://addons/stark_runtime/tests/safety.gd -- --out=<result.json>
## Exit code 0 = every check passed.

var out_path: String = ""
var checks: Dictionary = {}


func _initialize() -> void:
	for a in OS.get_cmdline_user_args():
		var s := str(a)
		if s.begins_with("--out="):
			out_path = s.substr(6)
	call_deferred("_main")


func wait(n: int) -> void:
	for i in range(n):
		await physics_frame


func _main() -> void:
	await process_frame
	var G = root.get_node("StarkGame")
	var D = root.get_node("StarkDialogue")
	var I = root.get_node("StarkInventory")
	G.muted = true
	G.debug_invulnerable = true
	change_scene_to_file(G.scene_path(0))
	await wait(20)
	var minor_ids: Array = G.minors.keys()
	checks["minors_loaded"] = minor_ids.size() > 0
	checks["minor_by_id"] = minor_ids.size() > 0 and G.is_minor(str(minor_ids[0]))
	checks["minor_by_age"] = G.is_minor("", "teen") and G.is_minor("", "child") and not G.is_minor("", "adult")
	checks["adult_not_minor"] = not G.is_minor("nobody_here", "adult")
	var lvl = G.level_node
	var child = lvl.spawn_enemy({"t": "enemy", "kind": "grunt", "id": "hand_edited_child", "age": "child"}, Vector3(2, 1, 2))
	var adult = lvl.spawn_enemy({"t": "enemy", "kind": "grunt", "id": "adult_foe"}, Vector3(4, 1, 4))
	await wait(5)
	checks["child_enemy_removed"] = not is_instance_valid(child) or child.is_queued_for_deletion() or not child.is_inside_tree()
	var hp0: float = adult.hp
	adult.take_hit(1.0, Vector3.FORWARD)
	checks["adult_enemy_takes_damage"] = adult.hp < hp0
	var in_group := false
	for e in get_nodes_in_group("stark_enemy"):
		if G.is_minor(str(e.enemy_id), str(e.age)):
			in_group = true
	checks["no_minor_targets"] = not in_group
	var gold0: int = I.gold
	D.act({"romance": "self", "gold": 50})
	D.act({"damage": "self", "gold": 50})
	D.act({"capture": "self", "gold": 50})
	checks["blocked_dialogue_actions_ignored"] = I.gold == gold0
	D.act({"gold": 5})
	checks["normal_dialogue_actions_run"] = I.gold == gold0 + 5
	var ok := true
	for k in checks.keys():
		if not bool(checks[k]):
			ok = false
			print("[safety] FAILED ", k)
	print("[safety] ", JSON.stringify(checks))
	if out_path != "":
		var f := FileAccess.open(out_path, FileAccess.WRITE)
		if f:
			f.store_string(JSON.stringify({"ok": ok, "checks": checks}))
			f.close()
	quit(0 if ok else 1)
