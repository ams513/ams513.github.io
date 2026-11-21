extends Node
## Stark World Engine Runtime - autoload "StarkSave": save slots 1-3 + "auto" (checkpoints, level changes).
## Snapshot format = the Stark World Engine browser engine's (v 2): li, pos, st, q, gone, flags, cp, won, diff, clock.
## Files: user://stark_saves/<game key>/slot_<n>.json  (override the folder with --stark-save-dir=<path>).

signal saved(slot: String)
signal loaded(slot: String)

var save_dir: String = ""


func _ready() -> void:
	for a in OS.get_cmdline_user_args():
		if str(a).begins_with("--stark-save-dir="):
			save_dir = str(a).substr(18)
	if save_dir == "":
		var key := str(StarkGame.data.get("save_key", "game"))
		var title := str(StarkGame.data.get("title", "game")).validate_filename().replace(" ", "_").left(40)
		save_dir = "user://stark_saves/%s_%s" % [title, key]
		_adopt_legacy("user://gorgon_saves/%s_%s" % [title, key])


## Saves a pre-28.7 export wrote under the old folder name are copied once (never moved or deleted).
func _adopt_legacy(old_dir: String) -> void:
	if DirAccess.dir_exists_absolute(save_dir) or not DirAccess.dir_exists_absolute(old_dir):
		return
	DirAccess.make_dir_recursive_absolute(save_dir)
	for f in DirAccess.get_files_at(old_dir):
		if f.begins_with("slot_") and f.ends_with(".json"):
			DirAccess.copy_absolute(old_dir.path_join(f), save_dir.path_join(f))


func slot_path(slot: String) -> String:
	return save_dir.path_join("slot_%s.json" % slot)


func snapshot() -> Dictionary:
	var pos = null
	if StarkGame.player and is_instance_valid(StarkGame.player) and StarkGame.player.has_method("get_save_pos"):
		pos = StarkGame.player.get_save_pos()
	return {"v": 2, "li": StarkGame.li, "pos": pos, "st": StarkInventory.snapshot(), "q": StarkQuests.snapshot(),
		"gone": StarkGame.gone.duplicate(), "flags": StarkGame.flags.duplicate(), "cp": StarkGame.cp.duplicate(),
		"won": StarkGame.won, "diff": StarkGame.diff, "clock": StarkGame.clock,
		"t": int(Time.get_unix_time_from_system() * 1000.0), "runtime": StarkGame.RUNTIME_VERSION}


func save_slot(slot: String, quiet: bool = false) -> bool:
	DirAccess.make_dir_recursive_absolute(save_dir)
	var f := FileAccess.open(slot_path(slot), FileAccess.WRITE)
	if f == null:
		if not quiet:
			StarkGame.emit_toast("Could not save (folder not writable)")
		return false
	f.store_string(JSON.stringify(snapshot()))
	f.close()
	if not quiet:
		StarkGame.emit_toast("Saved to " + ("autosave" if slot == "auto" else "slot " + slot), "l")
	saved.emit(slot)
	return true


func read_slot(slot: String) -> Dictionary:
	if not FileAccess.file_exists(slot_path(slot)):
		return {}
	var f := FileAccess.open(slot_path(slot), FileAccess.READ)
	if f == null:
		return {}
	var j = JSON.parse_string(f.get_as_text())
	return j if _ok(j) else {}


func _ok(j) -> bool:
	if not (j is Dictionary) or not (j.get("st") is Dictionary):
		return false
	var lv := int(j.get("li", -1))
	return lv >= 0 and lv < StarkGame.level_count()


func has_slot(slot: String) -> bool:
	return not read_slot(slot).is_empty()


func slot_info(slot: String) -> String:
	var j := read_slot(slot)
	if j.is_empty():
		return ""
	var L := StarkGame.level(int(j["li"]))
	var when := Time.get_datetime_string_from_unix_time(int(float(j.get("t", 0)) / 1000.0), true)
	return "Lv %d - %s - %s" % [int(j["st"].get("lvl", 1)), str(L.get("name", "Level %d" % (int(j["li"]) + 1))), when]


func load_slot(slot: String) -> bool:
	var j := read_slot(slot)
	if j.is_empty():
		StarkGame.emit_toast("That slot is empty")
		return false
	StarkInventory.restore(j["st"])
	StarkQuests.restore(j.get("q", {}))
	StarkGame.gone = {}
	var g = j.get("gone", {})
	if g is Dictionary:
		for k in g.keys():
			StarkGame.gone[str(k)] = true
	StarkGame.flags = {}
	var fl = j.get("flags", {})
	if fl is Dictionary:
		for k in fl.keys():
			StarkGame.flags[str(k)] = true
	StarkGame.cp = j.get("cp", {}) if j.get("cp") is Dictionary else {}
	StarkGame.won = bool(j.get("won", false))
	if StarkGame.data.get("diff", {}).has(str(j.get("diff", ""))):
		StarkGame.diff = str(j["diff"])
	StarkGame.clock = float(j.get("clock", -1.0)) if j.get("clock") != null else -1.0
	StarkGame.pending_pos = j.get("pos")
	StarkGame.li = int(j["li"])
	StarkGame.porting = false
	if StarkDialogue.is_open:
		StarkDialogue.close()
	StarkUI.close_modal()
	get_tree().call_deferred("change_scene_to_file", StarkGame.scene_path(int(j["li"])))
	StarkGame.emit_toast("Loaded " + ("autosave" if slot == "auto" else "slot " + slot), "l")
	loaded.emit(slot)
	StarkGame.changed.emit()
	return true


func delete_slot(slot: String) -> void:
	if FileAccess.file_exists(slot_path(slot)):
		DirAccess.remove_absolute(slot_path(slot))
