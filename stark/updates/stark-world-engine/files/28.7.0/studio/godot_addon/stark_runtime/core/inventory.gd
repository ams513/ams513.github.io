extends Node
## Stark World Engine Runtime - autoload "StarkInventory": hit points, level, XP, gold, bag and equipment.
## Formulas match the Stark World Engine browser engine (Game.prototype.stats / give / use / addXp / hurt).

var base_hp: int = 6
var hp: float = 6.0
var lvl: int = 1
var xp: int = 0
var gold: int = 0
var score: int = 0
var inv: Dictionary = {}
var eq: Dictionary = {}


func reset(start_hp: int) -> void:
	base_hp = max(1, start_hp)
	hp = float(base_hp)
	lvl = 1
	xp = 0
	gold = 0
	score = 0
	inv = {}
	eq = {}


func stats() -> Dictionary:
	var atk := 1 + int(floor((lvl - 1) / 2.0))
	var def := 0
	var max_hp := base_hp + (lvl - 1)
	var spd := 1.0
	for slot in eq.keys():
		var it := StarkGame.item(str(eq[slot]))
		atk += int(it.get("atk", 0))
		def += int(it.get("def", 0))
		max_hp += int(it.get("hp", 0))
		if float(it.get("speed", 0.0)) > 0.0:
			spd *= float(it["speed"])
	return {"atk": max(1, atk), "def": def, "max_hp": max(1, max_hp), "speed": clamp(spd, 0.2, 4.0)}


func has(id: String, n: int = 1) -> bool:
	return int(inv.get(id, 0)) >= max(1, n)


func count(id: String) -> int:
	return int(inv.get(id, 0))


func give(id: String, n: int = 1, quiet: bool = false) -> void:
	n = max(1, n)
	var it := StarkGame.item(id)
	if str(it.get("kind", "")) == "treasure" and int(it.get("gold", 0)) > 0:
		gold += int(it["gold"]) * n
		if not quiet:
			StarkGame.emit_toast("+%d gold (%s)" % [int(it["gold"]) * n, str(it["name"])])
		StarkGame.changed.emit()
		return
	inv[id] = int(inv.get(id, 0)) + n
	if not quiet:
		StarkGame.emit_toast("+ %s%s" % [str(it["name"]), " x%d" % n if n > 1 else ""])
	if str(it.get("kind", "")) == "equip" and not eq.has(str(it.get("slot", ""))):
		eq[str(it["slot"])] = id
		if not quiet:
			StarkGame.emit_toast("Equipped " + str(it["name"]), "l")
	StarkQuests.event("collect", {"item": id, "n": n})
	StarkGame.changed.emit()


func take(id: String, n: int = 1) -> bool:
	n = max(1, n)
	if not has(id, n):
		return false
	inv[id] = int(inv[id]) - n
	if int(inv[id]) <= 0:
		inv.erase(id)
		for slot in eq.keys():
			if str(eq[slot]) == id:
				eq.erase(slot)
	StarkGame.changed.emit()
	return true


func use(id: String) -> void:
	if not has(id):
		return
	var it := StarkGame.item(id)
	var kind := str(it.get("kind", ""))
	if kind == "consumable":
		var mx: int = stats()["max_hp"]
		if hp >= mx:
			StarkGame.emit_toast("Already at full health")
			return
		take(id, 1)
		var heal: int = max(1, int(it.get("heal", 1)))
		hp = min(float(mx), hp + heal)
		StarkGame.emit_toast("%s: +%d HP" % [str(it["name"]), heal], "l")
		StarkGame.play_sfx("power")
	elif kind == "equip":
		var slot := str(it.get("slot", ""))
		if str(eq.get(slot, "")) == id:
			eq.erase(slot)
			StarkGame.emit_toast("Unequipped " + str(it["name"]))
		else:
			eq[slot] = id
			StarkGame.emit_toast("Equipped " + str(it["name"]), "l")
		hp = min(hp, float(stats()["max_hp"]))
		StarkGame.play_sfx("coin")
	StarkGame.changed.emit()


func quaff() -> void:
	var best := ""
	for id in inv.keys():
		var it := StarkGame.item(str(id))
		if str(it.get("kind", "")) == "consumable":
			if best == "" or int(it.get("heal", 0)) < int(StarkGame.item(best).get("heal", 0)):
				best = str(id)
	if best != "":
		use(best)
	else:
		StarkGame.emit_toast("No potions")


func xp_need() -> int:
	return int(round(StarkGame.rule("xp_base", 40.0) * pow(float(lvl), StarkGame.rule("xp_pow", 1.45))))


func add_xp(n: int) -> void:
	xp += n
	score += n
	var need := xp_need()
	while xp >= need:
		xp -= need
		lvl += 1
		hp = float(stats()["max_hp"])
		StarkGame.play_sfx("levelup")
		StarkGame.emit_toast("Level up! You are now level %d" % lvl, "l")
		for a in StarkGame.abilities:
			if int(a["lvl"]) == lvl:
				StarkGame.emit_toast("New ability: %s (%s)" % [str(a["name"]), str(a["key"])], "q")
		need = xp_need()
	StarkGame.changed.emit()


func hurt(d: float) -> bool:
	# -> true when the hit was fatal (StarkGame handles the respawn)
	if StarkGame.debug_invulnerable:
		return false
	var st := stats()
	d = max(0.5, d * StarkGame.dmg_mul() - float(st["def"]) * 0.5)
	hp = max(0.0, hp - d)
	StarkGame.changed.emit()
	if hp <= 0.0:
		StarkGame.on_player_dead()
		return true
	return false


func snapshot() -> Dictionary:
	return {"hp": hp, "lvl": lvl, "xp": xp, "gold": gold, "score": score, "inv": inv.duplicate(), "eq": eq.duplicate(),
		"base_hp": base_hp}


func restore(s: Dictionary) -> void:
	base_hp = int(s.get("base_hp", base_hp))
	hp = float(s.get("hp", base_hp))
	lvl = max(1, int(s.get("lvl", 1)))
	xp = int(s.get("xp", 0))
	gold = int(s.get("gold", 0))
	score = int(s.get("score", 0))
	inv = {}
	var si = s.get("inv", {})
	if si is Dictionary:
		for k in si.keys():
			inv[str(k)] = int(si[k])
	eq = {}
	var se = s.get("eq", {})
	if se is Dictionary:
		for k in se.keys():
			eq[str(k)] = str(se[k])
	StarkGame.changed.emit()
