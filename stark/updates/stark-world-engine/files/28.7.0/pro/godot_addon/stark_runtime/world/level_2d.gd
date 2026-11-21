extends Node2D
## Stark World Engine Runtime 2D chapter: the Stark World Engine browser platformer, tile for tile.
## Tiles: . air  # ground  o pearl  ^ spikes  G flag (end)  X exit to the next level  e slime  a archer  B boss
##        h potion  k key  D locked door  C checkpoint  ~ water  P start.  NPCs come from the level's objects
## (x = column, z = row). Same speeds, jump and stomp rules as the browser (32 px tiles).

const T := 32.0

@export var level_index: int = 0
@export var tiles: PackedStringArray = PackedStringArray()

var grid: Array = []
var W: int = 0
var H: int = 0
var P: Dictionary = {}
var en: Array = []
var npcs: Array = []
var proj: Array = []
var bursts: Array = []
var total_pearls: int = 0
var warn: bool = false
var cam: Camera2D
var pal: Dictionary = {}
var t: float = 0.0
var shake: float = 0.0
var hit_stop: float = 0.0
var hurt_fx: float = 0.0
var _prompt_t: float = 0.0


func _enter_tree() -> void:
	StarkGame.li = level_index
	StarkGame.level_node = self


func _ready() -> void:
	add_to_group("stark_level")
	var L := StarkGame.level(level_index)
	if tiles.is_empty():
		for r in L.get("tiles", []):
			tiles.append(str(r))
	pal = L.get("palette", {})
	StarkGame.player = self
	reset(false)
	cam = Camera2D.new()
	cam.name = "Camera"
	cam.position_smoothing_enabled = true
	cam.limit_left = 0
	cam.limit_top = 0
	cam.limit_right = int(W * T)
	cam.limit_bottom = int(H * T)
	add_child(cam)
	cam.make_current()
	_fit_zoom()
	StarkGame.level_ready(self, level_index, true)


func _fit_zoom() -> void:
	var vh := float(get_viewport_rect().size.y)
	var sc: float = clamp(vh / max(1.0, H * T), 0.6, 1.6)
	cam.zoom = Vector2(sc, sc)


func gkey(x: int, y: int) -> String:
	return "%d:t%d_%d" % [level_index, x, y]


func reset(keep_pos: bool) -> void:
	var px := float(P.get("x", 64.0))
	var py := float(P.get("y", 64.0))
	grid = []
	for row in tiles:
		var r: Array = []
		for i in range(row.length()):
			r.append(row[i])
		grid.append(r)
	H = grid.size()
	W = (grid[0] as Array).size() if H > 0 else 0
	en = []
	npcs = []
	P = {"x": 64.0, "y": 64.0, "vx": 0.0, "vy": 0.0, "w": 22.0, "h": 28.0, "on": false, "inv": 0.0, "face": 1.0,
		"atk": 0.0, "dash": 0.0, "coyote": 0.0}
	var hm := StarkGame.hp_mul()
	for y in range(H):
		for x in range(W):
			var c: String = grid[y][x]
			if c == "P":
				P["x"] = x * T + 5.0
				P["y"] = y * T + 2.0
			if StarkGame.gone.has(gkey(x, y)) and "ohkDaeB".contains(c):
				grid[y][x] = "."
				continue
			if c == "e" or c == "a" or c == "B":
				var k := "archer" if c == "a" else ("boss" if c == "B" else "grunt")
				var D := StarkGame.enemy_def(k)
				var boss := k == "boss"
				var hp: float = round(float(D.get("hp", 3)) * hm * (0.6 if boss else 1.0))
				en.append({"k": gkey(x, y), "kind": k, "D": D, "x": x * T + 4.0, "y": y * T + (-T if boss else 8.0),
					"vx": 80.0 if boss else 60.0, "w": 56.0 if boss else 24.0, "h": 56.0 if boss else 24.0, "hit": 0.0,
					"hp": hp, "max": hp, "sh": 1.5, "cd": 0.0, "dead": false})
				grid[y][x] = "."
	for o in StarkGame.level(level_index).get("objects", []):
		if str(o["t"]) == "npc":
			npcs.append({"o": o, "id": str(o.get("id", "")), "x": float(o["x"]) * T + 4.0, "y": float(o["z"]) * T + 2.0,
				"col": StarkGame.color_of(str(o.get("col", "#d99a4d")))})
	if keep_pos:
		P["x"] = px
		P["y"] = py
	proj = []
	total_pearls = 0
	for row in tiles:
		total_pearls += row.count("o")
	if StarkGame.quest_list.is_empty():
		StarkGame.extra_goal = "Reach the golden flag" + (" - pearls %d/%d" % [total_pearls - pearls_left(), total_pearls] if total_pearls > 0 else "")


func pearls_left() -> int:
	var n := 0
	for r in grid:
		for c in r:
			if c == "o":
				n += 1
	return n


func solid(px: float, py: float) -> bool:
	var x := int(floor(px / T))
	var y := int(floor(py / T))
	if x < 0 or x >= W:
		return true
	if y < 0 or y >= H:
		return false
	var c: String = grid[y][x]
	return c == "#" or c == "D"


func tile_at(px: float, py: float) -> String:
	var x := int(floor(px / T))
	var y := int(floor(py / T))
	if x < 0 or x >= W or y < 0 or y >= H:
		return "."
	return grid[y][x]


func burst(x: float, y: float, col: Color, cnt: int, sp: float = 1.0) -> void:
	for i in range(min(cnt, max(0, 2000 - bursts.size()))):
		bursts.append({"x": x, "y": y, "vx": (randf() - 0.5) * 300.0 * sp, "vy": -randf() * 300.0 * sp,
			"life": 0.5 + randf() * 0.3, "c": col, "s": 3.0 + randf() * 3.0})


func hurt(d: float) -> void:
	if float(P["inv"]) > 0.0 or float(P["dash"]) > 0.0:
		return
	P["inv"] = 1.0
	shake = 0.6
	hit_stop = 0.06
	hurt_fx = 0.6
	StarkGame.play_sfx("hit")
	burst(float(P["x"]) + 11.0, float(P["y"]) + 14.0, Color(1, 0.3, 0.3), 14)
	StarkInventory.hurt(d if d > 0.0 else 1.0)


func kill(e: Dictionary) -> void:
	e["dead"] = true
	StarkGame.gone[str(e["k"])] = true
	StarkInventory.score += 50
	hit_stop = 0.09
	shake = 0.45
	StarkGame.play_sfx("boom")
	var D: Dictionary = e["D"]
	burst(float(e["x"]) + float(e["w"]) / 2.0, float(e["y"]) + float(e["h"]) / 2.0, Color(1, 0.5, 0.7), 90 if bool(D.get("boss", false)) else 30)
	StarkInventory.add_xp(int(D.get("xp", 10)))
	StarkInventory.gold += int(D.get("gold", 2))
	StarkQuests.event("defeat", {"kind": str(e["kind"])})
	if bool(D.get("boss", false)):
		StarkGame.boss_changed.emit("", -1.0)
		StarkGame.big_text.emit("Victory!", str(D.get("name", "The boss")) + " is defeated", 3.0)
	StarkGame.changed.emit()


func hit_enemy(e: Dictionary, dmg: float) -> void:
	e["hp"] = float(e["hp"]) - dmg
	e["hit"] = 0.2
	hit_stop = 0.06
	shake = 0.35
	StarkGame.play_sfx("hit")
	burst(float(e["x"]) + float(e["w"]) / 2.0, float(e["y"]) + float(e["h"]) / 2.0, Color(1, 0.9, 0.6), 12)
	if float(e["hp"]) <= 0.0:
		kill(e)


func interact() -> void:
	if StarkGame.is_busy():
		return
	var best = null
	var bd := 48.0
	for n in npcs:
		var d := Vector2(float(n["x"]) - float(P["x"]), float(n["y"]) - float(P["y"])).length()
		if d < bd:
			bd = d
			best = n
	if best != null:
		var o: Dictionary = best["o"]
		StarkDialogue.talk({"id": str(o.get("id", "")), "name": str(o.get("name", "")), "dialog": str(o.get("dialog", "")),
			"text": str(o.get("text", ""))})
		return
	var cx := int(floor((float(P["x"]) + float(P["w"]) / 2.0) / T))
	var cy := int(floor((float(P["y"]) + float(P["h"]) / 2.0) / T))
	for dx in [-1, 0, 1]:
		if cy < 0 or cy >= H or cx + dx < 0 or cx + dx >= W:
			continue
		if grid[cy][cx + dx] == "D":
			if StarkInventory.has("key"):
				StarkInventory.take("key", 1)
				grid[cy][cx + dx] = "."
				StarkGame.gone[gkey(cx + dx, cy)] = true
				StarkGame.play_sfx("door")
				StarkGame.emit_toast("Door unlocked")
				burst((cx + dx) * T + 16.0, cy * T + 16.0, _c("stone", [0.4, 0.4, 0.45]), 24)
			else:
				StarkGame.emit_toast("Locked. Find a key.")
				StarkGame.play_sfx("hit")
			return


func exit_level() -> void:
	if StarkGame.porting:
		return
	if level_index + 1 < StarkGame.level_count():
		StarkGame.go_to_level(level_index + 1)
	elif not StarkGame.won:
		if not StarkGame.quest_list.is_empty() and not StarkQuests.active().is_empty():
			if not warn:
				warn = true
				StarkGame.emit_toast("Finish your quests first!")
			return
		StarkGame.win()


func attack() -> void:
	if float(P["atk"]) > 0.0 or StarkGame.is_busy():
		return
	P["atk"] = 0.25
	StarkGame.play_sfx("laser")
	var hx := float(P["x"]) + float(P["w"]) if float(P["face"]) > 0.0 else float(P["x"]) - 40.0
	var atk := float(StarkInventory.stats()["atk"])
	for e in en:
		if not bool(e["dead"]) and hx < float(e["x"]) + float(e["w"]) and hx + 40.0 > float(e["x"]) \
				and float(P["y"]) < float(e["y"]) + float(e["h"]) and float(P["y"]) + float(P["h"]) > float(e["y"]):
			hit_enemy(e, atk)


func bolt() -> void:
	if not StarkGame.use_ability("Star Bolt"):
		return
	StarkGame.play_sfx("magic")
	proj.append({"x": float(P["x"]) + 11.0, "y": float(P["y"]) + 12.0, "vx": float(P["face"]) * 520.0, "vy": 0.0,
		"life": 1.2, "c": Color(0.6, 0.9, 1.0), "own": true, "dmg": float(StarkInventory.stats()["atk"]) + 1.0})


func dash() -> void:
	if not StarkGame.use_ability("Dash"):
		return
	P["dash"] = 0.16
	P["inv"] = max(float(P["inv"]), 0.2)
	StarkGame.play_sfx("jump")


func _physics_process(delta: float) -> void:
	t += delta
	shake = max(0.0, shake - delta * 1.6)
	hurt_fx = max(0.0, hurt_fx - delta * 1.5)
	if hit_stop > 0.0:
		hit_stop -= delta
	else:
		_move(delta)
	bursts = bursts.filter(func(b): return float(b["life"]) > 0.0)
	for b in bursts:
		b["life"] = float(b["life"]) - delta
		b["vy"] = float(b["vy"]) + 900.0 * delta
		b["x"] = float(b["x"]) + float(b["vx"]) * delta
		b["y"] = float(b["y"]) + float(b["vy"]) * delta
	if cam:
		cam.position = Vector2(float(P["x"]) + 11.0, float(P["y"]) + 14.0)
		cam.offset = Vector2(randf_range(-1, 1), randf_range(-1, 1)) * shake * 14.0 if shake > 0.0 else Vector2.ZERO
	queue_redraw()


func _move(dt: float) -> void:
	var busy := StarkGame.is_busy()
	var spd: float = 230.0 * float(StarkInventory.stats()["speed"])
	var dir := 0.0
	if not busy:
		dir = Input.get_axis("stark_left", "stark_right")
		if Input.is_action_just_pressed("stark_attack") or Input.is_action_just_pressed("stark_attack_mouse"):
			attack()
		if Input.is_action_just_pressed("stark_interact"):
			interact()
		if Input.is_action_just_pressed("stark_bolt"):
			bolt()
		if Input.is_action_just_pressed("stark_dash"):
			dash()
	if float(P["dash"]) > 0.0:
		P["dash"] = float(P["dash"]) - dt
		P["vx"] = float(P["face"]) * 620.0
	else:
		P["vx"] = dir * spd
	if dir != 0.0:
		P["face"] = sign(dir)
	P["coyote"] = float(P["coyote"]) - dt
	if bool(P["on"]):
		P["coyote"] = 0.1
	var jump_held := not busy and (Input.is_action_pressed("stark_jump") or Input.is_action_pressed("stark_forward"))
	if jump_held and float(P["coyote"]) > 0.0:
		P["vy"] = -570.0
		P["on"] = false
		P["coyote"] = 0.0
		StarkGame.play_sfx("jump")
	var px := float(P["x"])
	var py := float(P["y"])
	var pw := float(P["w"])
	var ph := float(P["h"])
	var wet := tile_at(px + 11.0, py + 14.0) == "~"
	P["vy"] = min(160.0 if wet else 900.0, float(P["vy"]) + (500.0 if wet else 1500.0) * dt)
	if wet and jump_held:
		P["vy"] = -200.0
	var vx := float(P["vx"])
	var nx := px + vx * dt
	if vx > 0.0 and (solid(nx + pw, py + 1.0) or solid(nx + pw, py + ph - 1.0)):
		nx = floor((nx + pw) / T) * T - pw - 0.01
	if vx < 0.0 and (solid(nx, py + 1.0) or solid(nx, py + ph - 1.0)):
		nx = floor(nx / T + 1.0) * T + 0.01
	px = nx
	var vy := float(P["vy"])
	var ny := py + vy * dt
	var was := bool(P["on"])
	P["on"] = false
	if vy > 0.0 and (solid(px + 1.0, ny + ph) or solid(px + pw - 1.0, ny + ph)):
		ny = floor((ny + ph) / T) * T - ph - 0.01
		if not was and vy > 500.0:
			shake = 0.15
		P["vy"] = 0.0
		P["on"] = true
	if vy < 0.0 and (solid(px + 1.0, ny) or solid(px + pw - 1.0, ny)):
		ny = floor(ny / T + 1.0) * T + 0.01
		P["vy"] = 0.0
	py = ny
	P["x"] = px
	P["y"] = py
	if py > H * T + 64.0:
		hurt(1.0)
		var cp := StarkGame.cp
		if not cp.is_empty() and int(cp.get("li", -1)) == level_index:
			P["x"] = float(cp["x"])
			P["y"] = float(cp["z"])
		else:
			reset(false)
			P["inv"] = 1.0
		P["vy"] = 0.0
	for q in [[px + 4.0, py + 4.0], [px + pw - 4.0, py + ph - 4.0], [px + pw / 2.0, py + ph / 2.0]]:
		var c := tile_at(q[0], q[1])
		var gx := int(floor(q[0] / T))
		var gy := int(floor(q[1] / T))
		if c == "o":
			grid[gy][gx] = "."
			StarkGame.gone[gkey(gx, gy)] = true
			StarkInventory.give("crystal", 1, true)
			StarkInventory.score += 10
			if StarkGame.quest_list.is_empty():
				StarkGame.extra_goal = "Reach the golden flag - pearls %d/%d" % [total_pearls - pearls_left(), total_pearls]
			StarkGame.changed.emit()
			StarkGame.play_sfx("coin")
			burst(gx * T + 16.0, gy * T + 16.0, _c("fx", [0.7, 1.0, 1.0]), 16)
		elif c == "h" or c == "k":
			grid[gy][gx] = "."
			StarkGame.gone[gkey(gx, gy)] = true
			StarkInventory.give("potion" if c == "h" else "key", 1)
			StarkGame.play_sfx("coin")
			burst(gx * T + 16.0, gy * T + 16.0, Color(1, 0.3, 0.4) if c == "h" else Color(1, 0.85, 0.3), 18)
		elif c == "C":
			var cp2 := StarkGame.cp
			if cp2.is_empty() or int(cp2.get("li", -1)) != level_index or abs(float(cp2.get("x", 0.0)) - (gx * T + 5.0)) > 0.5:
				StarkGame.set_checkpoint(gx * T + 5.0, gy * T + 2.0)
				burst(gx * T + 16.0, gy * T, Color(1, 0.9, 0.5), 30)
		elif c == "^":
			hurt(1.0)
		elif c == "G" or c == "X":
			exit_level()
	_enemies(dt, busy)
	_projectiles(dt)
	if float(P["inv"]) > 0.0:
		P["inv"] = float(P["inv"]) - dt
	if float(P["atk"]) > 0.0:
		P["atk"] = float(P["atk"]) - dt
	_prompt_t -= dt
	if _prompt_t <= 0.0:
		_prompt_t = 0.1
		var txt := ""
		if not busy:
			for n in npcs:
				if Vector2(float(n["x"]) - px, float(n["y"]) - py).length() < 48.0:
					txt = "[E]  Talk to " + str(n["o"].get("name", "stranger"))
			var cx := int(floor((px + pw / 2.0) / T))
			var cy := int(floor((py + ph / 2.0) / T))
			if txt == "" and cy >= 0 and cy < H and ((cx - 1 >= 0 and grid[cy][cx - 1] == "D") or (cx + 1 < W and grid[cy][cx + 1] == "D")):
				txt = "[E]  Unlock door"
		StarkUI.set_prompt(txt)


func _enemies(dt: float, busy: bool) -> void:
	var px := float(P["x"])
	var py := float(P["y"])
	var boss_near = null
	for e in en:
		if bool(e["dead"]):
			continue
		var D: Dictionary = e["D"]
		var is_boss := bool(D.get("boss", false))
		e["hit"] = max(0.0, float(e["hit"]) - dt)
		e["cd"] = max(0.0, float(e["cd"]) - dt)
		if is_boss and abs(float(e["x"]) - px) < 600.0:
			boss_near = e
		if busy:
			continue
		var ex := float(e["x"])
		var ey := float(e["y"])
		var ew := float(e["w"])
		var eh := float(e["h"])
		if is_boss:
			e["vx"] = (1.0 if px - ex > 0.0 else -1.0) * abs(float(e["vx"]))
		var nx2 := ex + float(e["vx"]) * dt
		var ahead := nx2 + ew if float(e["vx"]) > 0.0 else nx2
		if solid(ahead, ey + eh / 2.0) or not solid(ahead, ey + eh + 4.0):
			e["vx"] = -float(e["vx"])
		else:
			e["x"] = nx2
			ex = nx2
		if str(e["kind"]) == "archer" or is_boss:
			e["sh"] = float(e["sh"]) - dt
			var dpx := px - ex
			var dpy := py - ey
			if float(e["sh"]) <= 0.0 and Vector2(dpx, dpy).length() < 420.0:
				e["sh"] = 1.3 if is_boss else 2.2
				var n := 5 if is_boss else 1
				for i in range(n):
					var a := atan2(dpy, dpx) + (i - (n - 1) / 2.0) * 0.25
					proj.append({"x": ex + ew / 2.0, "y": ey + eh / 3.0, "vx": cos(a) * 260.0, "vy": sin(a) * 260.0,
						"life": 2.5, "c": Color(1, 0.35, 0.8) if is_boss else Color(0.6, 1.0, 0.4), "own": false, "dmg": 1.0})
				StarkGame.play_sfx("laser")
		var pw := float(P["w"])
		var ph := float(P["h"])
		if px < ex + ew and px + pw > ex and py < ey + eh and py + ph > ey:
			if float(P["vy"]) > 0.0 and py + ph - ey < 16.0:
				P["vy"] = -420.0
				hit_enemy(e, 3.0 if is_boss else 99.0)
			elif float(e["cd"]) <= 0.0:
				e["cd"] = 0.8
				hurt(float(D.get("dmg", 1)))
	if boss_near != null:
		StarkGame.boss_changed.emit(str(boss_near["D"].get("name", "Boss")), float(boss_near["hp"]) / max(1.0, float(boss_near["max"])))
	else:
		StarkGame.boss_changed.emit("", -1.0)


func _projectiles(dt: float) -> void:
	var keep: Array = []
	for p in proj:
		p["life"] = float(p["life"]) - dt
		p["x"] = float(p["x"]) + float(p["vx"]) * dt
		p["y"] = float(p["y"]) + float(p["vy"]) * dt
		var x := float(p["x"])
		var y := float(p["y"])
		if float(p["life"]) <= 0.0 or solid(x, y):
			continue
		if bool(p["own"]):
			var hit := false
			for e in en:
				if not bool(e["dead"]) and x > float(e["x"]) and x < float(e["x"]) + float(e["w"]) \
						and y > float(e["y"]) and y < float(e["y"]) + float(e["h"]):
					hit_enemy(e, float(p["dmg"]))
					hit = true
					break
			if hit:
				continue
		elif x > float(P["x"]) and x < float(P["x"]) + float(P["w"]) and y > float(P["y"]) and y < float(P["y"]) + float(P["h"]):
			hurt(1.0)
			continue
		keep.append(p)
	proj = keep


# ---------------------------------------------------------------- player API used by the game, saves and tests
func respawn(at) -> void:
	if at is Vector2:
		P["x"] = at.x
		P["y"] = at.y
	else:
		reset(true)
		var start := _start_pos()
		P["x"] = start.x
		P["y"] = start.y
	P["vy"] = 0.0
	P["inv"] = 2.0


func _start_pos() -> Vector2:
	for y in range(tiles.size()):
		var i := tiles[y].find("P")
		if i >= 0:
			return Vector2(i * T + 5.0, y * T + 2.0)
	return Vector2(64, 64)


func get_save_pos() -> Dictionary:
	return {"x": float(P["x"]), "z": float(P["y"])}


func set_save_pos(p) -> void:
	if p is Dictionary and p.has("x") and p.has("z"):
		P["x"] = float(p["x"])
		P["y"] = float(p["z"])
		P["vy"] = 0.0


func teleport(px: float, py: float) -> void:
	P["x"] = px
	P["y"] = py
	P["vx"] = 0.0
	P["vy"] = 0.0


func tiles_of(ch: String) -> Array:
	var out: Array = []
	for y in range(H):
		for x in range(W):
			if grid[y][x] == ch:
				out.append(Vector2i(x, y))
	return out


func _c(key: String, fallback: Array) -> Color:
	var a: Array = pal.get(key, fallback)
	return Color(float(a[0]), float(a[1]), float(a[2]))


# ---------------------------------------------------------------- drawing (same look as the browser canvas)
func _draw() -> void:
	var ground := _c("ground", [0.4, 0.5, 0.3])
	var stone := _c("stone", [0.45, 0.45, 0.5])
	var fx := _c("fx", [0.7, 1.0, 1.0])
	var fog := _c("fog", [0.1, 0.2, 0.3])
	var sky := _c("sky2", [0.05, 0.08, 0.15])
	var leaf: Array = pal.get("leaf", [[0.2, 0.5, 0.3]])
	var leaf0 := Color(float(leaf[0][0]), float(leaf[0][1]), float(leaf[0][2]))
	var lw := W * T
	var lh := H * T
	draw_polygon(PackedVector2Array([Vector2(-400, -400), Vector2(lw + 400, -400), Vector2(lw + 400, lh + 200), Vector2(-400, lh + 200)]),
		PackedColorArray([sky, sky, fog, fog]))
	for layer in range(3):
		var par: float = [0.1, 0.25, 0.45][layer]
		var base: float = lh * float([0.4, 0.55, 0.7][layer])
		var amp: float = [70.0, 60.0, 40.0][layer]
		var col: Color = fog.lerp(stone, 0.35 + 0.25 * layer) if layer < 2 else fog.lerp(leaf0, 0.6)
		var pts := PackedVector2Array()
		pts.append(Vector2(-400, lh + 200))
		var x0 := -400.0
		while x0 <= lw + 400.0:
			var wx := x0 * (1.0 + par)
			pts.append(Vector2(x0, base - amp * (sin(wx * 0.004 + layer) * 0.6 + sin(wx * 0.011 + layer * 2.0) * 0.3 + sin(wx * 0.031) * 0.1)))
			x0 += 40.0
		pts.append(Vector2(lw + 400, lh + 200))
		draw_colored_polygon(pts, col)
	var vx0 := float(P.get("x", 0.0)) - 1400.0
	var vx1 := float(P.get("x", 0.0)) + 1400.0
	for y in range(H):
		for x in range(W):
			var X := x * T
			var Y := y * T
			if X + T < vx0 or X > vx1:
				continue
			var c: String = grid[y][x]
			if c == "#":
				var top: bool = y == 0 or (grid[y - 1][x] != "#" and grid[y - 1][x] != "D")
				draw_rect(Rect2(X, Y, T, T), ground * (1.1 if top else 0.85))
				draw_rect(Rect2(X + (x * 7) % 20, Y + (y * 13) % 22 + 4, 6, 3), ground * 0.6)
				if top:
					draw_rect(Rect2(X, Y, T, 6), leaf0 * 1.25)
			elif c == "D":
				draw_rect(Rect2(X + 2, Y, T - 4, T), Color(0.35, 0.23, 0.12))
				draw_rect(Rect2(X + 13, Y + 12, 6, 8), Color(1.0, 0.85, 0.29))
			elif c == "o":
				draw_circle(Vector2(X + 16, Y + 16 + sin(t * 3.0 + x) * 3.0), 7.0, fx)
				draw_circle(Vector2(X + 14, Y + 14 + sin(t * 3.0 + x) * 3.0), 2.5, Color.WHITE)
			elif c == "h":
				draw_rect(Rect2(X + 11, Y + 12, 10, 12), Color(1.0, 0.33, 0.47))
				draw_rect(Rect2(X + 14, Y + 8, 4, 5), Color(1.0, 0.33, 0.47))
			elif c == "k":
				draw_circle(Vector2(X + 12, Y + 16), 5.0, Color(1.0, 0.85, 0.29))
				draw_rect(Rect2(X + 15, Y + 14, 12, 4), Color(1.0, 0.85, 0.29))
			elif c == "^":
				draw_colored_polygon(PackedVector2Array([Vector2(X, Y + T), Vector2(X + 8, Y + 12), Vector2(X + 16, Y + T),
					Vector2(X + 24, Y + 12), Vector2(X + 32, Y + T)]), Color(0.83, 0.2, 0.2))
			elif c == "~":
				draw_rect(Rect2(X, Y + (0.0 if y > 0 and grid[y - 1][x] == "~" else 6.0), T, T), Color(0.1, 0.5, 0.6, 0.6))
			elif c == "G":
				draw_rect(Rect2(X + 12, Y - T, 6, T * 2), Color(1.0, 0.85, 0.29))
				draw_rect(Rect2(X + 18, Y - T + sin(t * 4.0) * 2.0, 16, 11), fx)
			elif c == "X":
				draw_arc(Vector2(X + 16, Y), 18.0, 0.0, TAU, 24, Color(0.6, 0.55, 1.0), 4.0)
			elif c == "C":
				var on: bool = not StarkGame.cp.is_empty() and int(StarkGame.cp.get("li", -1)) == level_index and abs(float(StarkGame.cp.get("x", 0.0)) - (X + 5.0)) < 0.5
				draw_rect(Rect2(X + 8, Y + 12, 16, 20), stone)
				draw_circle(Vector2(X + 16, Y + 6), 6.0, Color(1.0, 0.91, 0.66) if on else Color(0.53, 0.53, 0.6))
	for n in npcs:
		var nc: Color = n["col"]
		var bob := sin(t * 2.0 + float(n["x"])) * 1.5
		var nx := float(n["x"])
		var ny := float(n["y"])
		draw_colored_polygon(PackedVector2Array([Vector2(nx - 2, ny + 30), Vector2(nx + 12, ny + 4 + bob), Vector2(nx + 26, ny + 30)]), nc)
		draw_circle(Vector2(nx + 12, ny + 4 + bob), 7.0, Color(0.96, 0.81, 0.63))
		var mk := ""
		if StarkQuests.offers_quest(str(n["id"])):
			mk = "!"
		if StarkQuests.talk_target(str(n["id"])):
			mk = "?"
		if mk != "":
			draw_string(ThemeDB.fallback_font, Vector2(nx + 7, ny - 18 + sin(t * 4.0) * 3.0), mk, HORIZONTAL_ALIGNMENT_LEFT, -1, 20, Color(1.0, 0.82, 0.4))
	for e in en:
		if bool(e["dead"]):
			continue
		var D: Dictionary = e["D"]
		var dc: Array = D.get("col", [0.75, 0.2, 0.35])
		var ec := Color.WHITE if float(e["hit"]) > 0.0 else Color(float(dc[0]), float(dc[1]), float(dc[2]))
		var ex := float(e["x"])
		var ey := float(e["y"])
		var ew := float(e["w"])
		var eh := float(e["h"])
		if bool(D.get("boss", false)):
			draw_colored_polygon(PackedVector2Array([Vector2(ex, ey + eh), Vector2(ex + 8, ey + 10), Vector2(ex + ew / 2.0, ey - 6),
				Vector2(ex + ew - 8, ey + 10), Vector2(ex + ew, ey + eh)]), ec)
			draw_rect(Rect2(ex + 14, ey + 18, 8, 6), Color(1.0, 0.3, 0.82))
			draw_rect(Rect2(ex + 34, ey + 18, 8, 6), Color(1.0, 0.3, 0.82))
		elif str(e["kind"]) == "archer":
			draw_colored_polygon(PackedVector2Array([Vector2(ex, ey + eh), Vector2(ex + ew / 2.0, ey - 4), Vector2(ex + ew, ey + eh)]), ec)
		else:
			draw_circle(Vector2(ex + ew / 2.0, ey + eh / 2.0 + 4.0), ew / 2.0 + 2.0, ec)
			draw_rect(Rect2(ex + (14.0 if float(e["vx"]) > 0.0 else 4.0), ey + 8, 6, 6), Color.WHITE)
	for p in proj:
		draw_circle(Vector2(float(p["x"]), float(p["y"])), 5.0, p["c"])
	var px := float(P["x"])
	var py := float(P["y"])
	if not (float(P["inv"]) > 0.0 and int(t * 20.0) % 2 == 0):
		var pc := StarkGame.color_of(str(StarkGame.data.get("player", {}).get("col", "#2e8c9e")), Color(0.18, 0.55, 0.62))
		draw_rect(Rect2(px, py + 10, float(P["w"]), float(P["h"]) - 10), pc)
		draw_rect(Rect2(px + 3, py, float(P["w"]) - 6, 12), Color(0.96, 0.81, 0.63))
		draw_rect(Rect2(px + 2, py - 2, float(P["w"]) - 4, 5), Color(0.42, 0.27, 0.14))
		draw_rect(Rect2(px + (14.0 if float(P["face"]) > 0.0 else 4.0), py + 4, 4, 4), Color(0.13, 0.13, 0.13))
		if float(P["atk"]) > 0.0:
			var a0 := -1.2 if float(P["face"]) > 0.0 else PI + 1.2
			draw_arc(Vector2(px + 11, py + 14), 30.0, a0, a0 + float(P["face"]) * 1.0, 8, fx, 4.0)
	for b in bursts:
		var bc: Color = b["c"]
		bc.a = clamp(float(b["life"]) * 2.0, 0.0, 1.0)
		draw_rect(Rect2(float(b["x"]), float(b["y"]), float(b["s"]), float(b["s"])), bc)
