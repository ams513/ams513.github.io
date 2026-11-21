extends Node
## Stark World Engine Runtime - autoload "StarkGame": game data, rules, level flow, sounds.
## Reads res://stark_game.json (written by Stark World Engine) and plays it with the same rules as the
## Stark World Engine browser engine. Other autoloads: StarkInventory, StarkQuests, StarkDialogue, StarkSave, StarkUI.

signal toast(message: String, kind: String)
signal big_text(title: String, subtitle: String, seconds: float)
signal changed
signal level_started(index: int)
signal game_won
signal boss_changed(boss_name: String, fraction: float)

const GAME_PATH := "res://stark_game.json"
const RUNTIME_VERSION := "1.0.0"

var data: Dictionary = {}
var items: Dictionary = {}
var dialogs: Dictionary = {}
var quest_list: Array = []
var quests_by_id: Dictionary = {}
var npcs: Dictionary = {}
var levels: Array = []
var rules: Dictionary = {}
var enemies: Dictionary = {}
var abilities: Array = []
## child-safety (stark_systems CHILD_SAFETY.md): ids of child / teen characters. They can never be damaged, targeted,
## captured or romanced; nothing in the game can switch this off.
var minors: Dictionary = {}
const BLOCKED_ACTIONS := ["romance", "romance_start", "start_romance", "intimacy", "intimate", "date", "marry", "propose",
	"seduce", "flirt", "kiss", "love", "undress", "strip", "nude", "nudity", "remove_clothes", "unclothe", "capture", "kidnap", "abduct", "imprison",
	"enslave", "cage", "jail", "arrest", "bind", "damage", "harm", "hurt", "kill", "attack", "execute", "sacrifice",
	"torture", "punish", "hit", "slap", "whip", "beat", "wound", "poison", "burn", "stun"]

var li: int = 0
var diff: String = "normal"
var gone: Dictionary = {}
var flags: Dictionary = {}
var cp: Dictionary = {}
var won: bool = false
var play_time: float = 0.0
var clock: float = -1.0
var pending_pos = null
var porting: bool = false
var title_open: bool = false
var busy_t: float = 0.0
var cooldowns: Dictionary = {}
var extra_goal: String = ""
var _player: Node = null
var _level_node: Node = null
## the current hero / level root; null once that node is gone (between levels)
var player: Node:
	get:
		return _player if is_instance_valid(_player) else null
	set(v):
		_player = v
var level_node: Node:
	get:
		return _level_node if is_instance_valid(_level_node) else null
	set(v):
		_level_node = v
var debug_invulnerable: bool = false
var muted: bool = false
var _sfx_cache: Dictionary = {}
var _players: Array = []


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	_setup_input()
	load_game_data(GAME_PATH)
	for i in range(6):
		var p := AudioStreamPlayer.new()
		p.bus = "Master"
		add_child(p)
		_players.append(p)


func load_game_data(path: String) -> bool:
	var f := FileAccess.open(path, FileAccess.READ)
	if f == null:
		push_warning("Stark World Engine: %s not found" % path)
		return false
	var d = JSON.parse_string(f.get_as_text())
	if not (d is Dictionary):
		push_error("Stark World Engine: %s is not valid JSON" % path)
		return false
	data = d
	items = data.get("items", {})
	dialogs = data.get("dialogs", {})
	quest_list = data.get("quests", [])
	quests_by_id = {}
	for q in quest_list:
		quests_by_id[str(q["id"])] = q
	npcs = data.get("npcs", {})
	levels = data.get("levels", [])
	rules = data.get("rules", {})
	enemies = data.get("enemies", {})
	abilities = data.get("abilities", [])
	diff = str(data.get("difficulty", "normal"))
	minors = {}
	for id in data.get("child_safety", {}).get("minors", []):
		minors[str(id)] = true
	for id in npcs.keys():
		if str(npcs[id].get("age", "adult")) != "adult":
			minors[str(id)] = true
	return true


func is_minor(id: String, age: String = "") -> bool:
	return (age != "" and age != "adult") or (id != "" and minors.has(id))


# ---------------------------------------------------------------- data access
func item(id: String) -> Dictionary:
	if items.has(id):
		return items[id]
	return {"id": id, "name": id.replace("_", " ").capitalize(), "kind": "quest", "col": "#dddddd", "desc": ""}


func item_name(id: String) -> String:
	return str(item(id).get("name", id))


func quest(id: String) -> Dictionary:
	return quests_by_id.get(id, {})


func dialog(id: String) -> Dictionary:
	return dialogs.get(id, {})


func npc_name(id: String) -> String:
	if npcs.has(id):
		return str(npcs[id].get("name", id))
	return id if id != "" else "someone"


func enemy_def(kind: String) -> Dictionary:
	return enemies.get(kind, enemies.get("grunt", {"name": "Slime", "hp": 3, "dmg": 1, "speed": 2.6, "sight": 14, "xp": 10, "gold": 2}))


func level(index: int) -> Dictionary:
	if index >= 0 and index < levels.size():
		return levels[index]
	return {}


func level_count() -> int:
	return levels.size()


func current_level() -> Dictionary:
	return level(li)


func rule(key: String, default_value: float) -> float:
	return float(rules.get(key, default_value))


func hp_mul() -> float:
	return float(data.get("diff", {}).get(diff, {"hp": 1.0}).get("hp", 1.0))


func dmg_mul() -> float:
	return float(data.get("diff", {}).get(diff, {"dmg": 1.0}).get("dmg", 1.0))


func color_of(hex: String, fallback: Color = Color(0.85, 0.85, 0.85)) -> Color:
	if hex.length() >= 6 and Color.html_is_valid(hex):
		return Color.html(hex)
	return fallback


# ---------------------------------------------------------------- terrain (same formula as the browser engine)
static func terrain_h(x: float, z: float, seed_value: float, amp: float) -> float:
	var s := seed_value
	var v := sin(x * 0.13 + s) * 0.6 + cos(z * 0.11 + s * 0.7) * 0.6 + sin((x + z) * 0.05 + s) * 0.8 \
		+ cos(x * 0.045 - z * 0.06 + s * 0.4) * 0.9 + sin(x * 0.29 + z * 0.23 + s * 1.3) * 0.18
	return amp * v * 0.55


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
		var tx := gx - x0
		var tz := gz - z0
		var a: float = lerp(float(hs[z0 * res + x0]), float(hs[z0 * res + x0 + 1]), tx)
		var b: float = lerp(float(hs[(z0 + 1) * res + x0]), float(hs[(z0 + 1) * res + x0 + 1]), tx)
		return lerp(a, b, tz)
	var h := terrain_h(x, z, float(spec.get("seed", 1.0)), float(spec.get("amp", 1.0)))
	var d: float = max(abs(x), abs(z)) - float(spec.get("size", 48.0))
	if d > 0.0:
		var t: float = min(1.0, d / float(spec.get("margin", 32.0)))
		h += float(spec.get("edge", 8.0)) * t * t * (3.0 - 2.0 * t)
	return h


func height(x: float, z: float) -> float:
	var L := current_level()
	if not L.has("terrain"):
		return 0.0
	return spec_height(L["terrain"], x, z)


func water_level() -> float:
	var L := current_level()
	if L.get("water") == null:
		return -1.0e9
	return float(L["water"])


func depth(x: float, z: float) -> float:
	var w := water_level()
	if w < -1.0e8:
		return -9.0
	return w - height(x, z)


func play_size() -> float:
	return float(current_level().get("size", 48.0))


# ---------------------------------------------------------------- game flow
func new_game() -> void:
	gone = {}
	flags = {}
	cp = {}
	won = false
	play_time = 0.0
	clock = -1.0
	pending_pos = null
	cooldowns = {}
	diff = str(data.get("difficulty", "normal"))
	StarkQuests.reset()
	StarkInventory.reset(int(data.get("player", {}).get("hp", 6)))
	for id in data.get("player", {}).get("items", []):
		StarkInventory.give(str(id), 1, true)
	li = 0
	changed.emit()


var booted: bool = false


func level_ready(node: Node, index: int, show_title: bool = true) -> void:
	# Every level scene calls this from _ready. The first level of a session starts a new game (and the title screen).
	level_node = node
	li = index
	if not booted:
		booted = true
		new_game()
		li = index
		if show_title and not OS.get_cmdline_user_args().has("--stark-no-title"):
			StarkUI.open_title()
	start_level(index)
	if pending_pos != null and player and is_instance_valid(player) and player.has_method("set_save_pos"):
		player.set_save_pos(pending_pos)
	pending_pos = null


func scene_path(index: int) -> String:
	return str(level(index).get("scene", "res://main.tscn"))


func start_level(index: int) -> void:
	# Called by every level scene when it is ready.
	li = index
	porting = false
	var L := current_level()
	for q in quest_list:
		if bool(q.get("auto", false)) and int(q.get("level", 0)) == index and not StarkQuests.q.has(str(q["id"])):
			StarkQuests.start(str(q["id"]))
	for q in StarkQuests.active():
		StarkQuests.foes(q)
	_update_extra_goal()
	level_started.emit(index)
	big_text.emit(str(L.get("name", "Level %d" % (index + 1))), str(L.get("story", "")).left(160), 3.2)
	changed.emit()


func go_to_level(index: int) -> void:
	if porting or index < 0 or index >= levels.size():
		return
	porting = true
	play_sfx("portal")
	var from := li
	li = index
	if index != from:
		StarkSave.save_slot("auto", true)
	get_tree().call_deferred("change_scene_to_file", scene_path(index))


func is_busy() -> bool:
	return StarkDialogue.is_open or StarkUI.modal != "" or title_open or busy_t > 0.0


func set_checkpoint(x: float, z: float) -> void:
	if cp.get("li", -1) == li and Vector2(float(cp.get("x", 0.0)), float(cp.get("z", 0.0))).distance_to(Vector2(x, z)) < 0.5:
		return
	cp = {"li": li, "x": x, "z": z}
	StarkInventory.hp = StarkInventory.stats()["max_hp"]
	StarkSave.save_slot("auto", true)
	emit_toast("Checkpoint - progress saved", "l")
	play_sfx("power")
	changed.emit()


func on_player_dead() -> void:
	StarkInventory.gold = int(floor(StarkInventory.gold * rule("death_gold_keep", 0.9)))
	StarkInventory.hp = StarkInventory.stats()["max_hp"]
	big_text.emit("You fell...", "Back to the last checkpoint. (Lost 10% gold)", 2.2)
	if player and player.has_method("respawn"):
		if not cp.is_empty() and int(cp.get("li", -1)) == li:
			player.respawn(Vector2(float(cp["x"]), float(cp["z"])))
		else:
			player.respawn(null)
	changed.emit()


func win() -> void:
	if won:
		return
	won = true
	StarkInventory.score += 100
	play_sfx("power")
	game_won.emit()
	changed.emit()


func gone_key(index: int, level_index: int = -1) -> String:
	return "%d:%d" % [li if level_index < 0 else level_index, index]


func is_gone(index: int, level_index: int = -1) -> bool:
	return index >= 0 and gone.has(gone_key(index, level_index))


func set_gone(index: int, level_index: int = -1) -> void:
	if index >= 0:
		gone[gone_key(index, level_index)] = true


func emit_toast(message: String, kind: String = "") -> void:
	toast.emit(message, kind)


func has_ability(ability_name: String) -> bool:
	for a in abilities:
		if str(a["name"]) == ability_name and StarkInventory.lvl >= int(a["lvl"]):
			return true
	return false


func use_ability(ability_name: String) -> bool:
	# -> true when the ability is learnt and off cooldown (and starts the cooldown).
	if not has_ability(ability_name) or float(cooldowns.get(ability_name, 0.0)) > 0.0:
		return false
	for a in abilities:
		if str(a["name"]) == ability_name:
			cooldowns[ability_name] = float(a["cd"])
	changed.emit()
	return true


func _update_extra_goal() -> void:
	extra_goal = ""
	if not quest_list.is_empty():
		return
	var L := current_level()
	if str(L.get("mode", "3d")) == "2d":
		extra_goal = "Reach the golden flag"
		return
	var total := 0
	var got := 0
	for o in L.get("objects", []):
		if str(o["t"]) == "crystal":
			total += 1
			if is_gone(int(o["i"])):
				got += 1
	if total > 0:
		extra_goal = "Collect the glowing crystals (%d/%d)" % [got, total]


func crystal_collected() -> void:
	_update_extra_goal()
	if quest_list.is_empty() and str(current_level().get("mode", "3d")) == "3d":
		var left := 0
		for o in current_level().get("objects", []):
			if str(o["t"]) == "crystal" and not is_gone(int(o["i"])):
				left += 1
		if left == 0:
			win()
	changed.emit()


func _process(delta: float) -> void:
	if busy_t > 0.0:
		busy_t -= delta
	if title_open:
		return
	play_time += delta
	var ch := false
	for k in cooldowns.keys():
		if float(cooldowns[k]) > 0.0:
			cooldowns[k] = float(cooldowns[k]) - delta
			if float(cooldowns[k]) <= 0.0:
				ch = true
	var day: Dictionary = current_level().get("day", {})
	if float(day.get("len", 0.0)) > 0.0:
		if clock < 0.0:
			clock = float(day.get("start", 0.3)) if day.get("start") != null else 0.3
		clock = fmod(clock + delta / float(day["len"]), 1.0)
	if ch:
		changed.emit()


func _exit_tree() -> void:
	for pl in _players:
		(pl as AudioStreamPlayer).stop()
		(pl as AudioStreamPlayer).stream = null
	_sfx_cache.clear()


# ---------------------------------------------------------------- sounds (same tiny synth as the browser engine)
func play_sfx(sfx_name: String) -> void:
	if muted:
		return
	var p: Dictionary = data.get("sfx", {}).get(sfx_name, {})
	if p.is_empty():
		return
	if not _sfx_cache.has(sfx_name):
		_sfx_cache[sfx_name] = _make_sfx(p)
	for pl in _players:
		var ap := pl as AudioStreamPlayer
		if not ap.playing:
			ap.stream = _sfx_cache[sfx_name]
			ap.play()
			return


static func _make_sfx(p: Dictionary) -> AudioStreamWAV:
	var rate := 22050
	var n: int = max(1, int(float(p.get("dur", 0.3)) * rate))
	var bytes := PackedByteArray()
	bytes.resize(n * 2)
	var rng := RandomNumberGenerator.new()
	rng.seed = int(p.get("seed", 7))
	var ph := 0.0
	var f := float(p.get("freq", 440.0))
	var slide := float(p.get("slide", 0.0))
	var wave := str(p.get("wave", "square"))
	var noise := float(p.get("noise", 0.0))
	var decay := float(p.get("decay", 2.0))
	var vol := float(p.get("vol", 0.5))
	for i in range(n):
		var t := float(i) / float(n)
		var fr: float = max(20.0, f * (1.0 + slide * t))
		ph += fr / rate
		var v := 0.0
		if wave == "square":
			v = 1.0 if fmod(ph, 1.0) < 0.5 else -1.0
		elif wave == "saw":
			v = 2.0 * fmod(ph, 1.0) - 1.0
		elif wave == "sine":
			v = sin(TAU * ph)
		else:
			v = rng.randf() * 2.0 - 1.0
		if noise > 0.0:
			v = v * (1.0 - noise) + (rng.randf() * 2.0 - 1.0) * noise
		v *= min(1.0, t * 40.0) * pow(1.0 - t, decay) * vol
		bytes.encode_s16(i * 2, int(clamp(v, -1.0, 1.0) * 32767.0))
	var s := AudioStreamWAV.new()
	s.format = AudioStreamWAV.FORMAT_16_BITS
	s.mix_rate = rate
	s.stereo = false
	s.data = bytes
	return s


# ---------------------------------------------------------------- input (created at start unless the project defines them)
func _setup_input() -> void:
	var keys := {
		"stark_forward": [KEY_W, KEY_UP], "stark_back": [KEY_S, KEY_DOWN], "stark_left": [KEY_A, KEY_LEFT],
		"stark_right": [KEY_D, KEY_RIGHT], "stark_jump": [KEY_SPACE], "stark_attack": [KEY_J],
		"stark_interact": [KEY_E], "stark_potion": [KEY_H], "stark_dash": [KEY_SHIFT], "stark_whirl": [KEY_K],
		"stark_bolt": [KEY_F], "stark_cam_left": [KEY_Z], "stark_cam_right": [KEY_C], "stark_quests": [KEY_L],
		"stark_bag": [KEY_I, KEY_TAB], "stark_menu": [KEY_ESCAPE, KEY_M],
	}
	for action in keys.keys():
		if InputMap.has_action(action):
			continue
		InputMap.add_action(action)
		for k in keys[action]:
			var ev := InputEventKey.new()
			ev.physical_keycode = k
			InputMap.action_add_event(action, ev)
	if not InputMap.has_action("stark_attack_mouse"):
		InputMap.add_action("stark_attack_mouse")
		var mb := InputEventMouseButton.new()
		mb.button_index = MOUSE_BUTTON_LEFT
		InputMap.action_add_event("stark_attack_mouse", mb)
