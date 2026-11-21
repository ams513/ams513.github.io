extends Node
## Stark World Engine Runtime - autoload "StarkQuests": quest log and step tracking.
## Same rules as the Stark World Engine browser engine: steps collect / defeat / talk / reach / escort,
## counts, consumed items, rewards (xp, gold, items), follow-up quests ("next") and final quests that win the game.

signal quest_changed(quest_id: String)

var q: Dictionary = {}   # quest id -> {"state": "active" | "done", "step": int, "n": int}


func reset() -> void:
	q = {}


func state_of(id: String) -> String:
	return str(q[id]["state"]) if q.has(id) else ""


func start(id: String, quiet: bool = false) -> void:
	var qd := StarkGame.quest(id)
	if qd.is_empty() or q.has(id):
		return
	q[id] = {"state": "active", "step": 0, "n": 0}
	_init_step(qd)
	if not quiet:
		StarkGame.emit_toast("New quest: " + str(qd.get("title", id)), "q")
		StarkGame.play_sfx("quest")
	quest_changed.emit(id)
	StarkGame.changed.emit()
	_check_step(qd)


func current_step(qd: Dictionary) -> Dictionary:
	var r: Dictionary = q.get(str(qd["id"]), {})
	var steps: Array = qd.get("steps", [])
	if r.is_empty() or int(r["step"]) >= steps.size():
		return {}
	return steps[int(r["step"])]


func _init_step(qd: Dictionary) -> void:
	var r: Dictionary = q[str(qd["id"])]
	var s := current_step(qd)
	r["n"] = 0
	if not s.is_empty() and str(s["type"]) == "collect":
		r["n"] = min(StarkInventory.count(str(s["item"])), int(s.get("count", 1)))
	foes(qd)


func foes(qd: Dictionary) -> void:
	# a "defeat N slimes" step must stay possible even if the camps were cleared before the quest was taken
	var r: Dictionary = q.get(str(qd["id"]), {})
	var s := current_step(qd)
	if s.is_empty() or str(s["type"]) != "defeat" or str(s.get("id", "")) != "" or str(r.get("state", "")) != "active":
		return
	var lv := int(s.get("level", -1))
	if lv < 0:
		lv = int(qd.get("level", 0))
	if lv == StarkGame.li and StarkGame.level_node and StarkGame.level_node.has_method("ensure_foes"):
		StarkGame.level_node.ensure_foes(str(s.get("kind", "")), int(s.get("count", 1)) - int(r["n"]))


func _step_done(qd: Dictionary) -> bool:
	var s := current_step(qd)
	return not s.is_empty() and int(q[str(qd["id"])]["n"]) >= int(s.get("count", 1))


func _check_step(qd: Dictionary) -> void:
	var id := str(qd["id"])
	if not q.has(id) or str(q[id]["state"]) != "active":
		return
	var steps: Array = qd.get("steps", [])
	var guard := 0
	while _step_done(qd) and guard < 20:
		guard += 1
		var s := current_step(qd)
		if str(s["type"]) == "collect" and bool(s.get("consume", false)):
			StarkInventory.take(str(s["item"]), int(s.get("count", 1)))
		q[id]["step"] = int(q[id]["step"]) + 1
		if int(q[id]["step"]) >= steps.size():
			complete(qd)
			return
		_init_step(qd)
		StarkGame.emit_toast("Next: " + step_text(current_step(qd)), "q")
	if steps.is_empty():
		complete(qd)


func complete(qd: Dictionary) -> void:
	var id := str(qd["id"])
	if not q.has(id) or str(q[id]["state"]) == "done":
		return
	q[id]["state"] = "done"
	var rw: Dictionary = qd.get("reward", {})
	StarkGame.emit_toast("Quest complete: " + str(qd.get("title", id)), "q")
	StarkGame.play_sfx("power")
	if int(rw.get("gold", 0)) > 0:
		StarkInventory.gold += int(rw["gold"])
		StarkGame.emit_toast("+%d gold" % int(rw["gold"]))
	for it in rw.get("items", []):
		StarkInventory.give(str(it), 1)
	if int(rw.get("xp", 0)) > 0:
		StarkInventory.add_xp(int(rw["xp"]))
	if str(qd.get("next", "")) != "":
		start(str(qd["next"]))
	quest_changed.emit(id)
	StarkGame.changed.emit()
	check_win()


func event(type: String, d: Dictionary) -> void:
	var changed_any := false
	for qd in StarkGame.quest_list:
		var id := str(qd["id"])
		if not q.has(id) or str(q[id]["state"]) != "active":
			continue
		var s := current_step(qd)
		if s.is_empty() or str(s["type"]) != type:
			continue
		if int(s.get("level", -1)) >= 0 and int(s["level"]) != StarkGame.li:
			continue
		var ok := false
		var add := 1
		if type == "collect":
			ok = str(s.get("item", "")) == str(d.get("item", ""))
			add = int(d.get("n", 1))
		elif type == "defeat":
			if StarkGame.is_minor(str(d.get("id", ""))) or StarkGame.is_minor(str(s.get("id", ""))):
				continue
			var k := str(s.get("kind", ""))
			ok = (k == "" or k == "any" or k == str(d.get("kind", ""))) and \
				(str(s.get("id", "")) == "" or str(s.get("id", "")) == str(d.get("id", "")))
		elif type == "talk" or type == "escort":
			ok = str(s.get("npc", "")) == str(d.get("npc", ""))
		elif type == "reach":
			var r: float = float(s.get("r", 3.0))
			if r <= 0.0:
				r = 3.0
			ok = Vector2(float(d.get("x", 0.0)) - float(s.get("x", 0.0)), float(d.get("z", 0.0)) - float(s.get("z", 0.0))).length() < r
		if ok:
			q[id]["n"] = min(int(s.get("count", 1)), int(q[id]["n"]) + add)
			changed_any = true
			quest_changed.emit(id)
			_check_step(qd)
	if changed_any:
		StarkGame.changed.emit()


func step_text(s: Dictionary) -> String:
	if s.is_empty():
		return ""
	if str(s.get("text", "")) != "":
		return str(s["text"])
	var c := int(s.get("count", 1))
	var t := str(s["type"])
	if t == "collect":
		return "Collect " + StarkGame.item_name(str(s.get("item", ""))) + (" (%d)" % c if c > 1 else "")
	if t == "defeat":
		var who := ""
		if str(s.get("id", "")) != "":
			who = _enemy_name(str(s["id"]))
		elif str(s.get("kind", "")) != "" and str(s["kind"]) != "any":
			who = str(StarkGame.enemy_def(str(s["kind"])).get("name", s["kind"]))
		else:
			who = "enemies"
		return "Defeat " + who + (" (%d)" % c if c > 1 else "")
	if t == "talk":
		return "Talk to " + StarkGame.npc_name(str(s.get("npc", "")))
	if t == "escort":
		return "Escort " + StarkGame.npc_name(str(s.get("npc", ""))) + " to " + (str(s["label"]) if str(s.get("label", "")) != "" else "safety")
	return "Reach " + (str(s["label"]) if str(s.get("label", "")) != "" else "the marked spot")


func _enemy_name(id: String) -> String:
	for L in StarkGame.levels:
		for o in L.get("objects", []):
			if str(o["t"]) == "enemy" and str(o.get("id", "")) == id:
				return str(o["name"]) if str(o.get("name", "")) != "" else id
	return StarkGame.npc_name(id)


func active() -> Array:
	var out: Array = []
	for qd in StarkGame.quest_list:
		if state_of(str(qd["id"])) == "active":
			out.append(qd)
	return out


func cur_steps() -> Array:
	# -> [{"q": quest, "s": step}] for every active quest
	var out: Array = []
	for qd in active():
		var s := current_step(qd)
		if not s.is_empty():
			out.append({"q": qd, "s": s})
	return out


func escort_step(npc_id: String) -> Dictionary:
	for x in cur_steps():
		if str(x["s"]["type"]) == "escort" and str(x["s"].get("npc", "")) == npc_id:
			return x["s"]
	return {}


func talk_target(npc_id: String) -> bool:
	for x in cur_steps():
		if str(x["s"]["type"]) == "talk" and str(x["s"].get("npc", "")) == npc_id:
			return true
	return false


func offers_quest(npc_id: String) -> bool:
	for qd in StarkGame.quest_list:
		if str(qd.get("giver", "")) == npc_id and not q.has(str(qd["id"])):
			return true
	return false


func check_win() -> void:
	if StarkGame.won or StarkGame.quest_list.is_empty():
		return
	var fin: Array = []
	for qd in StarkGame.quest_list:
		if bool(qd.get("final", false)):
			fin.append(qd)
	var lst: Array = fin if not fin.is_empty() else StarkGame.quest_list
	for qd in lst:
		if state_of(str(qd["id"])) != "done":
			return
	StarkGame.win()


func target_point(s: Dictionary):
	# -> Vector2(x, z) the gold guide beam points at, or null
	if s.is_empty():
		return null
	var t := str(s["type"])
	if t == "reach" or t == "escort":
		return Vector2(float(s.get("x", 0.0)), float(s.get("z", 0.0)))
	return null


func snapshot() -> Dictionary:
	return q.duplicate(true)


func restore(d) -> void:
	q = {}
	if d is Dictionary:
		for k in d.keys():
			var r = d[k]
			if r is Dictionary:
				q[str(k)] = {"state": str(r.get("state", "active")), "step": int(r.get("step", 0)), "n": int(r.get("n", 0))}
	StarkGame.changed.emit()
