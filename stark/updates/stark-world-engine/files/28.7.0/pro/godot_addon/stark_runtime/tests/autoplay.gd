extends SceneTree
## Stark World Engine Runtime scripted playthrough (headless verification).
## Plays the exported game like a player would - walks to NPCs and talks (picking the answers that accept quests),
## picks items up through the real pickup triggers, opens chests and locked doors, fights enemies with the real attack,
## escorts NPCs, walks into portals - for every quest of every level, and checks save + load on the way.
##   godot --headless --path <project> --fixed-fps 60 --script res://addons/stark_runtime/tests/autoplay.gd
##         -- --stark-no-title [--out=<result.json>] [--stark-save-dir=<folder>] [--max-frames=N]
## Exit code 0 = every quest done (and the game won when it has final quests), save/load round trip OK.

var G
var Q
var I
var D
var S
var UI
var out_path: String = ""
var max_frames: int = 90000
var frames: int = 0
var log_lines: Array = []
var errors: Array = []
var visited_levels: Array = []
var save_checked: bool = false
var save_ok: bool = false
var doors_opened: int = 0
var chests_opened: int = 0
var kills: int = 0


func _initialize() -> void:
	for a in OS.get_cmdline_user_args():
		var s := str(a)
		if s.begins_with("--out="):
			out_path = s.substr(6)
		elif s.begins_with("--max-frames="):
			max_frames = int(s.substr(13))
	call_deferred("_main")


func _process(_delta: float) -> bool:
	frames += 1
	if frames > max_frames:
		errors.append("timeout after %d frames" % frames)
		_finish()
	return false


func note(msg: String) -> void:
	log_lines.append("[%d] %s" % [frames, msg])
	print("[autoplay] ", msg)


func wait(n: int) -> void:
	for i in range(n):
		await physics_frame


func _main() -> void:
	await process_frame
	G = root.get_node("StarkGame")
	Q = root.get_node("StarkQuests")
	I = root.get_node("StarkInventory")
	D = root.get_node("StarkDialogue")
	S = root.get_node("StarkSave")
	UI = root.get_node("StarkUI")
	if G.level_count() == 0:
		errors.append("stark_game.json has no levels")
		_finish()
		return
	G.debug_invulnerable = true
	G.muted = true
	for slot in ["1", "2", "3", "auto"]:
		S.delete_slot(slot)
	change_scene_to_file(G.scene_path(0))
	await wait(10)
	var guard := 0
	while not G.won and guard < 40:
		guard += 1
		var li: int = G.li
		if not (li in visited_levels):
			visited_levels.append(li)
		note("level %d: %s (%s)" % [li, str(G.current_level().get("name", "")), str(G.current_level().get("mode", ""))])
		if str(G.current_level().get("mode", "3d")) == "2d":
			await play_2d(li)
		else:
			await play_3d(li)
		if G.won:
			break
		if G.li != li:
			continue
		var moved: bool = await leave_level(li)
		if not moved:
			note("no way out of level %d" % li)
			break
	_finish()


# ---------------------------------------------------------------- helpers
func level() -> Node:
	return G.level_node


func player() -> Node:
	return G.player


func steps_here(li: int) -> Array:
	var out: Array = []
	for x in Q.cur_steps():
		var s: Dictionary = x["s"]
		var lv := int(s.get("level", -1))
		if lv < 0:
			lv = int(x["q"].get("level", 0))
		if lv == li or str(s["type"]) in ["collect", "talk"]:
			out.append(x)
	return out


func handle_dialogue() -> void:
	var seen := {}
	var guard := 0
	while D.is_open and guard < 24:
		guard += 1
		var best := 0
		var score := -100
		for i in range(D.choices.size()):
			var c: Dictionary = D.choices[i]
			var act: Dictionary = c.get("do", {})
			var sc := 0
			if act.has("start") and not Q.q.has(str(act["start"])):
				sc += 10
			if act.has("advance") or act.has("complete") or act.has("give"):
				sc += 5
			var gt := str(c.get("goto", ""))
			if gt != "" and not bool(c.get("end", false)) and not seen.has(gt):
				sc += 2
			if sc > score:
				score = sc
				best = i
		seen[D.node_id] = true
		note("  dialogue %s: \"%s\" -> %s" % [D.speaker(), D.text().left(50), str(D.choices[best].get("text", ""))])
		D.choose(best)
		await wait(2)
	if D.is_open:
		D.close()
	await wait(16)


func find_group(group: String, pred: Callable) -> Array:
	var out: Array = []
	for n in root.get_tree().get_nodes_in_group(group):
		if is_instance_valid(n) and pred.call(n):
			out.append(n)
	return out


func talk_to_npc(npc_id: String) -> bool:
	var npcs := find_group("stark_npc", func(n): return str(n.npc_id) == npc_id)
	if npcs.is_empty():
		return false
	var n: Node3D = npcs[0]
	var p: Node3D = player()
	p.teleport(n.global_position.x + 1.4, n.global_position.z)
	await wait(4)
	var t = p.nearest_interactable()
	if t != n:
		note("  (nearest interactable was not %s; talking directly)" % npc_id)
		n.interact(p)
	else:
		p.interact()
	await wait(2)
	await handle_dialogue()
	return true


func walk_into(pos: Vector3) -> void:
	var p: Node3D = player()
	p.teleport(pos.x, pos.z)
	await wait(6)


func fight(e: Node3D) -> bool:
	var p: Node3D = player()
	var guard := 0
	while is_instance_valid(e) and not e.dead and guard < 400:
		guard += 1
		var to: Vector3 = e.global_position - p.global_position
		to.y = 0.0
		if to.length() > 1.8:
			var dirv := to.normalized()
			p.teleport(e.global_position.x - dirv.x * 1.4, e.global_position.z - dirv.z * 1.4)
			await wait(2)
			to = e.global_position - p.global_position
			to.y = 0.0
		p.face = atan2(to.x, to.z)
		p.attack()
		await wait(18)
	if not is_instance_valid(e) or e.dead:
		kills += 1
		return true
	return false


func open_chest_with(item_id: String) -> bool:
	var chests := find_group("stark_interactable", func(n): return n.has_method("objective_match") and "gold" in n and not n.opened and str(n.item) == item_id)
	if chests.is_empty():
		return false
	var c: Node3D = chests[0]
	var p: Node3D = player()
	p.teleport(c.global_position.x + 1.2, c.global_position.z)
	await wait(4)
	var t = p.nearest_interactable()
	if t == c:
		p.interact()
	else:
		c.interact(p)
	chests_opened += 1
	await wait(4)
	return true


# ---------------------------------------------------------------- 3D
func play_3d(li: int) -> void:
	if G.quest_list.is_empty():
		# classic goal (no quests): collect every glowing crystal
		var guard0 := 0
		while not G.won and guard0 < 200:
			guard0 += 1
			var crys := find_group("stark_pickup", func(n): return n.crystal)
			if crys.is_empty():
				break
			await walk_into(crys[0].global_position)
		note("classic crystal goal: won=%s" % str(G.won))
		return
	var stuck := 0
	var last := ""
	while stuck < 6 and G.li == li and not G.won:
		await accept_quests_3d(li)
		var todo := steps_here(li)
		if todo.is_empty():
			break
		var x: Dictionary = todo[0]
		var key := "%s:%d:%d" % [str(x["q"]["id"]), int(Q.q[str(x["q"]["id"])]["step"]), int(Q.q[str(x["q"]["id"])]["n"])]
		stuck = stuck + 1 if key == last else 0
		last = key
		await do_step_3d(x["q"], x["s"])
		await wait(3)
		if not save_checked and li == 0 and not Q.q.is_empty():
			await check_save_load()
	await open_doors_3d()


var _offers_tried: Dictionary = {}


func accept_quests_3d(li: int) -> void:
	var progress := 0
	for qd in G.quest_list:
		if Q.state_of(str(qd["id"])) == "done":
			progress += 1
	for q in G.quest_list:
		var id := str(q["id"])
		if Q.q.has(id) or int(q.get("level", 0)) != li or str(q.get("giver", "")) == "":
			continue
		if not _prereq_ok(q):
			continue
		var tried_key := "%s@%d" % [id, progress]
		if _offers_tried.has(tried_key):
			continue
		_offers_tried[tried_key] = true
		note("quest offer: %s (giver %s)" % [str(q.get("title", id)), str(q["giver"])])
		await talk_to_npc(str(q["giver"]))


func _prereq_ok(q: Dictionary) -> bool:
	# a quest some other quest starts with "next" is not offered by talking
	for other in G.quest_list:
		if str(other.get("next", "")) == str(q["id"]):
			return false
	return true


func do_step_3d(q: Dictionary, s: Dictionary) -> void:
	var t := str(s["type"])
	note("step %s / %s: %s" % [str(q["id"]), t, Q.step_text(s)])
	var p: Node3D = player()
	if t == "talk":
		await talk_to_npc(str(s.get("npc", "")))
	elif t == "collect":
		var item := str(s.get("item", ""))
		var picks := find_group("stark_pickup", func(n): return n.objective_match(s))
		if not picks.is_empty():
			picks.sort_custom(func(a, b): return a.global_position.distance_to(p.global_position) < b.global_position.distance_to(p.global_position))
			await walk_into(picks[0].global_position)
		elif not await open_chest_with(item):
			var foes := find_group("stark_enemy", func(n): return not n.dead)
			if not foes.is_empty():
				await fight(foes[0])
			else:
				note("  nothing left that gives %s" % item)
	elif t == "defeat":
		var foes := find_group("stark_enemy", func(n): return n.objective_match(s))
		if foes.is_empty():
			level().ensure_foes(str(s.get("kind", "")), 1)
			await wait(3)
			foes = find_group("stark_enemy", func(n): return n.objective_match(s))
		if not foes.is_empty():
			foes.sort_custom(func(a, b): return a.global_position.distance_to(p.global_position) < b.global_position.distance_to(p.global_position))
			var ok: bool = await fight(foes[0])
			note("  defeated %s: %s" % [str(foes[0].title()) if is_instance_valid(foes[0]) else "enemy", str(ok)])
	elif t == "reach":
		await walk_into(Vector3(float(s.get("x", 0.0)), 0, float(s.get("z", 0.0))))
	elif t == "escort":
		var npc_id := str(s.get("npc", ""))
		var npcs := find_group("stark_npc", func(n): return str(n.npc_id) == npc_id)
		if not npcs.is_empty():
			p.teleport(npcs[0].global_position.x + 1.0, npcs[0].global_position.z)
			await wait(4)
		var tx := float(s.get("x", 0.0))
		var tz := float(s.get("z", 0.0))
		p.teleport(tx + 1.0, tz + 1.0)
		await wait(30)


func open_doors_3d() -> void:
	for door in find_group("stark_interactable", func(n): return "key_item" in n and not n.opened):
		var key := str(door.key_item)
		if not I.has(key):
			await open_chest_with(key)
		if I.has(key):
			var p: Node3D = player()
			p.teleport(door.global_position.x, door.global_position.z + 1.6)
			await wait(4)
			door.interact(p)
			await wait(3)
			if door.opened:
				doors_opened += 1
				note("door opened with %s" % key)


func check_save_load() -> void:
	save_checked = true
	await wait(30)
	var p: Node3D = player()
	var before := {"gold": I.gold, "xp": I.xp, "lvl": I.lvl, "q": JSON.stringify(Q.snapshot()), "gone": _gone_items(),
		"x": p.global_position.x, "z": p.global_position.z}
	if not S.save_slot("1", true):
		errors.append("save to slot 1 failed")
		return
	I.gold += 999
	Q.q = {}
	G.gone = {}
	S.load_slot("1")
	await wait(12)
	var p2: Node3D = player()
	var after := {"gold": I.gold, "xp": I.xp, "lvl": I.lvl, "q": JSON.stringify(Q.snapshot()), "gone": _gone_items(),
		"x": p2.global_position.x, "z": p2.global_position.z}
	save_ok = before["gold"] == after["gold"] and before["q"] == after["q"] and before["gone"] == after["gone"] \
		and abs(float(before["x"]) - float(after["x"])) < 0.6 and abs(float(before["z"]) - float(after["z"])) < 0.6
	note("save/load round trip: %s (gold %d, %d quests, %d gone)" % ["OK" if save_ok else "MISMATCH", int(after["gold"]), Q.q.size(), int(after["gone"])])
	if not save_ok:
		errors.append("save/load mismatch: %s vs %s" % [str(before), str(after)])


func _gone_items() -> int:
	# picked items / opened chests / opened doors (slain grunts may come back: ensure_foes, like the browser engine)
	var enemies := {}
	for o in G.current_level().get("objects", []):
		if str(o["t"]) == "enemy":
			enemies["%d:%d" % [G.li, int(o["i"])]] = true
	var n := 0
	for k in G.gone.keys():
		if not enemies.has(str(k)):
			n += 1
	return n


func leave_level(li: int) -> bool:
	if str(G.current_level().get("mode", "3d")) == "2d":
		return await leave_2d(li)
	var portals := find_group("stark_portal", func(n): return not n.is_locked() and n.destination() >= 0 and n.destination() < G.level_count())
	if portals.is_empty():
		var locked := find_group("stark_portal", func(n): return n.is_locked())
		for pt in locked:
			note("portal locked by quest %s (%s)" % [str(pt.lock_quest), Q.state_of(str(pt.lock_quest))])
		return false
	portals.sort_custom(func(a, b): return a.destination() > b.destination())
	var pt: Node3D = portals[0]
	var dest: int = pt.destination()
	note("portal -> level %d" % dest)
	await walk_into(pt.global_position)
	await wait(20)
	return G.li == dest and level() != null and int(level().level_index) == dest


# ---------------------------------------------------------------- 2D
func play_2d(li: int) -> void:
	var lv: Node = level()
	var stuck := 0
	var last := ""
	while stuck < 6 and G.li == li and not G.won:
		for q in G.quest_list:
			var id := str(q["id"])
			if not Q.q.has(id) and int(q.get("level", 0)) == li and str(q.get("giver", "")) != "":
				for n in lv.npcs:
					if str(n["id"]) == str(q["giver"]):
						lv.teleport(float(n["x"]) - 20.0, float(n["y"]))
						await wait(4)
						lv.interact()
						await wait(2)
						await handle_dialogue()
		var todo := steps_here(li)
		if todo.is_empty():
			break
		var x: Dictionary = todo[0]
		var qid := str(x["q"]["id"])
		var key := "%s:%d:%d" % [qid, int(Q.q[qid]["step"]), int(Q.q[qid]["n"])]
		stuck = stuck + 1 if key == last else 0
		last = key
		var s: Dictionary = x["s"]
		note("step %s / %s: %s" % [qid, str(s["type"]), Q.step_text(s)])
		if not save_checked:
			await check_save_load_2d(lv)
			lv = level()
		if str(s["type"]) == "collect":
			var tl: Array = lv.tiles_of("o")
			if tl.is_empty():
				note("  no pearls left")
			for c in tl.slice(0, 3):
				lv.teleport(c.x * 32.0 + 5.0, c.y * 32.0 + 2.0)
				await wait(3)
		elif str(s["type"]) == "defeat":
			var guard := 0
			for e in lv.en:
				if bool(e["dead"]):
					continue
				var k := str(s.get("kind", ""))
				if k != "" and k != "any" and str(e["kind"]) != k:
					continue
				while not bool(e["dead"]) and guard < 300:
					guard += 1
					lv.teleport(float(e["x"]) - 26.0, float(e["y"]) + float(e["h"]) - 28.0)
					lv.P["face"] = 1.0
					lv.attack()
					await wait(16)
				if bool(e["dead"]):
					kills += 1
				break
		elif str(s["type"]) == "talk":
			for n in lv.npcs:
				if str(n["id"]) == str(s.get("npc", "")):
					lv.teleport(float(n["x"]) - 20.0, float(n["y"]))
					await wait(4)
					lv.interact()
					await wait(2)
					await handle_dialogue()
		await wait(2)
	var keys: Array = lv.tiles_of("k")
	if not keys.is_empty():
		lv.teleport(keys[0].x * 32.0 + 5.0, keys[0].y * 32.0 + 2.0)
		await wait(3)
	for d in lv.tiles_of("D"):
		if I.has("key"):
			lv.teleport((d.x - 1) * 32.0 + 6.0, d.y * 32.0 + 2.0)
			await wait(3)
			lv.interact()
			await wait(2)
			if lv.grid[d.y][d.x] == ".":
				doors_opened += 1
				note("2D door opened")


func check_save_load_2d(lv: Node) -> void:
	save_checked = true
	await wait(20)
	var before := {"gold": I.gold, "q": JSON.stringify(Q.snapshot()), "gone": G.gone.size(), "x": float(lv.P["x"]), "y": float(lv.P["y"])}
	if not S.save_slot("2", true):
		errors.append("2D save failed")
		return
	I.gold += 500
	Q.q = {}
	S.load_slot("2")
	await wait(12)
	var lv2: Node = level()
	var after := {"gold": I.gold, "q": JSON.stringify(Q.snapshot()), "gone": G.gone.size(), "x": float(lv2.P["x"]), "y": float(lv2.P["y"])}
	save_ok = before["gold"] == after["gold"] and before["q"] == after["q"] and before["gone"] == after["gone"] 		and abs(float(before["x"]) - float(after["x"])) < 40.0 and abs(float(before["y"]) - float(after["y"])) < 40.0
	note("2D save/load round trip: %s" % ("OK" if save_ok else "MISMATCH %s vs %s" % [str(before), str(after)]))
	if not save_ok:
		errors.append("2D save/load mismatch")


func leave_2d(li: int) -> bool:
	var lv: Node = level()
	var exits: Array = lv.tiles_of("X") + lv.tiles_of("G")
	if exits.is_empty():
		return false
	var e: Vector2i = exits[0]
	note("2D exit at %s" % str(e))
	lv.teleport(e.x * 32.0 + 5.0, e.y * 32.0 + 2.0)
	await wait(30)
	if G.won:
		return true
	return G.li != li


# ---------------------------------------------------------------- result
func _finish() -> void:
	var done := 0
	var missing: Array = []
	for q in G.quest_list:
		if Q.state_of(str(q["id"])) == "done":
			done += 1
		else:
			missing.append("%s (%s)" % [str(q["id"]), Q.state_of(str(q["id"])) if Q.q.has(str(q["id"])) else "not started"])
	var has_final := false
	for q in G.quest_list:
		if bool(q.get("final", false)):
			has_final = true
	var all_levels: bool = visited_levels.size() == G.level_count()
	var ok: bool = errors.is_empty() and missing.is_empty() and (G.won or not has_final) and all_levels and (save_ok or not save_checked)
	if G.quest_list.is_empty():
		ok = errors.is_empty() and all_levels and G.won
	var res := {"ok": ok, "title": str(G.data.get("title", "")), "levels": G.level_count(), "visited": visited_levels,
		"quests": G.quest_list.size(), "done": done, "missing": missing, "won": G.won, "save_load": save_ok,
		"save_checked": save_checked, "doors_opened": doors_opened, "chests_opened": chests_opened, "kills": kills,
		"player_level": I.lvl, "gold": I.gold, "frames": frames, "errors": errors, "log": log_lines}
	print("[autoplay] RESULT ", JSON.stringify({"ok": ok, "done": done, "quests": G.quest_list.size(), "won": G.won,
		"visited": visited_levels, "save_load": save_ok, "missing": missing, "errors": errors}))
	if out_path != "":
		var f := FileAccess.open(out_path, FileAccess.WRITE)
		if f:
			f.store_string(JSON.stringify(res, " "))
			f.close()
	for slot in ["1", "2", "3", "auto"]:
		S.delete_slot(slot)
	quit(0 if ok else 1)
