extends CanvasLayer
## Stark World Engine Runtime - autoload "StarkUI": HUD, quest tracker, toasts, prompts, dialogue, boss bar, quest log, bag,
## pause menu (save slots 1-3 + autosave, difficulty, sound), title screen and credits. Built in code: restyle it
## freely, or replace it with your own scenes (every game rule lives in the other autoloads).

const PANEL_BG := Color(0.04, 0.055, 0.086, 0.78)
const GOLD := Color(1.0, 0.82, 0.4)
const MINT := Color(0.37, 0.83, 0.71)

var modal: String = ""
var _root: Control
var _hud_line: Label
var _hp: ProgressBar
var _xp: ProgressBar
var _hud_stats: Label
var _hud_abilities: Label
var _tracker: PanelContainer
var _tracker_box: VBoxContainer
var _toasts: VBoxContainer
var _prompt: PanelContainer
var _prompt_label: Label
var _boss: PanelContainer
var _boss_label: Label
var _boss_bar: ProgressBar
var _big: VBoxContainer
var _big_title: Label
var _big_sub: Label
var _big_t: float = 0.0
var _dlg: PanelContainer
var _dlg_speaker: Label
var _dlg_text: Label
var _dlg_choices: VBoxContainer
var _modal: PanelContainer
var _modal_box: VBoxContainer
var _title: ColorRect
var _credits_t: float = -1.0


func _ready() -> void:
	layer = 10
	process_mode = Node.PROCESS_MODE_ALWAYS
	_build()
	StarkGame.toast.connect(show_toast)
	StarkGame.big_text.connect(show_big)
	StarkGame.changed.connect(refresh)
	StarkGame.boss_changed.connect(_on_boss)
	StarkGame.game_won.connect(_on_won)
	StarkDialogue.dialogue_changed.connect(_on_dialogue)
	refresh()


# ---------------------------------------------------------------- building blocks
func _panel(min_w: float = 0.0) -> PanelContainer:
	var p := PanelContainer.new()
	var sb := StyleBoxFlat.new()
	sb.bg_color = PANEL_BG
	sb.border_color = Color(1, 1, 1, 0.14)
	sb.set_border_width_all(1)
	sb.set_corner_radius_all(12)
	sb.content_margin_left = 12
	sb.content_margin_right = 12
	sb.content_margin_top = 8
	sb.content_margin_bottom = 8
	p.add_theme_stylebox_override("panel", sb)
	p.custom_minimum_size = Vector2(min_w, 0)
	p.mouse_filter = Control.MOUSE_FILTER_IGNORE
	return p


func _label(txt: String = "", font_size: int = 14, col: Color = Color(0.96, 0.95, 0.92)) -> Label:
	var l := Label.new()
	l.text = txt
	l.add_theme_font_size_override("font_size", font_size)
	l.add_theme_color_override("font_color", col)
	l.mouse_filter = Control.MOUSE_FILTER_IGNORE
	return l


func _bar(col: Color) -> ProgressBar:
	var b := ProgressBar.new()
	b.custom_minimum_size = Vector2(200, 10)
	b.show_percentage = false
	var bg := StyleBoxFlat.new()
	bg.bg_color = Color(1, 1, 1, 0.12)
	bg.set_corner_radius_all(6)
	var fg := StyleBoxFlat.new()
	fg.bg_color = col
	fg.set_corner_radius_all(6)
	b.add_theme_stylebox_override("background", bg)
	b.add_theme_stylebox_override("fill", fg)
	b.mouse_filter = Control.MOUSE_FILTER_IGNORE
	return b


func _button(txt: String, cb: Callable) -> Button:
	var b := Button.new()
	b.text = txt
	b.alignment = HORIZONTAL_ALIGNMENT_LEFT
	b.add_theme_font_size_override("font_size", 15)
	b.pressed.connect(cb)
	return b


func _place(c: Control, preset: int, left: float, top: float, right: float, bottom: float) -> void:
	c.set_anchors_preset(preset)
	c.offset_left = left
	c.offset_top = top
	c.offset_right = right
	c.offset_bottom = bottom


func _build() -> void:
	_root = Control.new()
	_root.set_anchors_preset(Control.PRESET_FULL_RECT)
	_root.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(_root)
	# HUD (top left)
	var hud := _panel(220)
	hud.position = Vector2(12, 12)
	var hv := VBoxContainer.new()
	hud.add_child(hv)
	_hud_line = _label("", 14)
	_hp = _bar(Color(1.0, 0.3, 0.43))
	_xp = _bar(MINT)
	_hud_stats = _label("", 12, Color(0.62, 0.69, 0.75))
	_hud_abilities = _label("", 11, MINT)
	for c in [_hud_line, _hp, _xp, _hud_stats, _hud_abilities]:
		hv.add_child(c)
	_root.add_child(hud)
	# quest tracker (top right)
	_tracker = _panel(260)
	_place(_tracker, Control.PRESET_TOP_RIGHT, -290, 12, -12, 12)
	_tracker_box = VBoxContainer.new()
	_tracker.add_child(_tracker_box)
	_root.add_child(_tracker)
	# toasts (top centre)
	_toasts = VBoxContainer.new()
	_place(_toasts, Control.PRESET_CENTER_TOP, -220, 70, 220, 70)
	_toasts.alignment = BoxContainer.ALIGNMENT_CENTER
	_toasts.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_root.add_child(_toasts)
	# prompt (bottom centre)
	_prompt = _panel()
	_place(_prompt, Control.PRESET_CENTER_BOTTOM, -170, -150, 170, -150)
	_prompt.grow_vertical = Control.GROW_DIRECTION_BEGIN
	_prompt_label = _label("", 15)
	_prompt.add_child(_prompt_label)
	_prompt.visible = false
	_root.add_child(_prompt)
	# boss bar
	_boss = _panel(420)
	_place(_boss, Control.PRESET_CENTER_TOP, -210, 14, 210, 14)
	var bv := VBoxContainer.new()
	_boss_label = _label("", 15, Color(1, 0.75, 0.9))
	_boss_bar = _bar(Color(0.71, 0.09, 0.62))
	_boss_bar.custom_minimum_size = Vector2(400, 12)
	bv.add_child(_boss_label)
	bv.add_child(_boss_bar)
	_boss.add_child(bv)
	_boss.visible = false
	_root.add_child(_boss)
	# big title (level names, victory)
	_big = VBoxContainer.new()
	_place(_big, Control.PRESET_CENTER, -400, -150, 400, -150)
	_big.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_big_title = _label("", 44)
	_big_title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_big_sub = _label("", 16)
	_big_sub.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_big_sub.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_big.add_child(_big_title)
	_big.add_child(_big_sub)
	_big.visible = false
	_root.add_child(_big)
	# dialogue (bottom)
	_dlg = _panel(700)
	_place(_dlg, Control.PRESET_CENTER_BOTTOM, -360, -18, 360, -18)
	_dlg.grow_vertical = Control.GROW_DIRECTION_BEGIN
	_dlg.mouse_filter = Control.MOUSE_FILTER_STOP
	var dv := VBoxContainer.new()
	_dlg_speaker = _label("", 16, GOLD)
	_dlg_text = _label("", 17)
	_dlg_text.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_dlg_text.custom_minimum_size = Vector2(680, 44)
	_dlg_choices = VBoxContainer.new()
	dv.add_child(_dlg_speaker)
	dv.add_child(_dlg_text)
	dv.add_child(_dlg_choices)
	_dlg.add_child(dv)
	_dlg.visible = false
	_root.add_child(_dlg)
	# modal (quest log, bag, menu, credits)
	_modal = _panel(560)
	_place(_modal, Control.PRESET_CENTER, -280, -240, 280, -240)
	_modal.mouse_filter = Control.MOUSE_FILTER_STOP
	_modal_box = VBoxContainer.new()
	_modal.add_child(_modal_box)
	_modal.visible = false
	_root.add_child(_modal)


# ---------------------------------------------------------------- HUD refresh
func refresh() -> void:
	if _hud_line == null:
		return
	var st := StarkInventory.stats()
	StarkInventory.hp = min(StarkInventory.hp, float(st["max_hp"]))
	var L := StarkGame.current_level()
	_hud_line.text = "Lv %d   HP %d/%d   %d gold" % [StarkInventory.lvl, int(ceil(StarkInventory.hp)), int(st["max_hp"]), StarkInventory.gold]
	_hp.max_value = float(st["max_hp"])
	_hp.value = StarkInventory.hp
	_xp.max_value = float(StarkInventory.xp_need())
	_xp.value = float(StarkInventory.xp)
	_hud_stats.text = "ATK %d  DEF %d  %s" % [int(st["atk"]), int(st["def"]), str(L.get("name", StarkGame.data.get("title", "")))]
	var ab: Array = []
	for a in StarkGame.abilities:
		var learnt := StarkInventory.lvl >= int(a["lvl"])
		var cd := float(StarkGame.cooldowns.get(str(a["name"]), 0.0)) > 0.0
		ab.append(("%s %s" % [str(a["key"]), str(a["name"])]) + ("" if learnt and not cd else (" (lv %d)" % int(a["lvl"]) if not learnt else " ...")))
	_hud_abilities.text = "   ".join(ab)
	for c in _tracker_box.get_children():
		c.queue_free()
	var cs: Array = StarkQuests.cur_steps()
	if StarkGame.extra_goal != "":
		cs.append({"q": {"title": "Main goal", "id": ""}, "s": {"text": StarkGame.extra_goal, "type": "goal", "count": 1}})
	_tracker.visible = not cs.is_empty()
	for i in range(min(3, cs.size())):
		var x: Dictionary = cs[i]
		var qid := str(x["q"].get("id", ""))
		var c := int(x["s"].get("count", 1))
		var prog := ""
		if qid != "" and c > 1 and StarkQuests.q.has(qid):
			prog = " - %d/%d" % [int(StarkQuests.q[qid]["n"]), c]
		_tracker_box.add_child(_label(str(x["q"].get("title", qid)), 14, GOLD))
		_tracker_box.add_child(_label(StarkQuests.step_text(x["s"]) + prog, 12, Color(0.8, 0.93, 0.93)))
	if not cs.is_empty():
		_tracker_box.add_child(_label("L quests  -  I bag  -  Esc menu", 11, Color(0.62, 0.69, 0.75)))
	if modal == "quests":
		open_quests()
	elif modal == "bag":
		open_bag()


func set_prompt(txt: String) -> void:
	if _prompt == null:
		return
	_prompt.visible = txt != ""
	_prompt_label.text = txt


func show_toast(message: String, kind: String = "") -> void:
	if _toasts == null:
		return
	var kids := _toasts.get_children()
	if not kids.is_empty() and kids[kids.size() - 1].has_meta("msg") and str(kids[kids.size() - 1].get_meta("msg")) == message:
		return
	var p := _panel()
	var col := GOLD if kind == "q" else (Color(0.72, 1.0, 0.91) if kind == "l" else Color(0.96, 0.95, 0.92))
	p.add_child(_label(message, 15, col))
	p.set_meta("msg", message)
	p.set_meta("t", 3.2)
	_toasts.add_child(p)
	while _toasts.get_child_count() > 4:
		var first := _toasts.get_child(0)
		_toasts.remove_child(first)
		first.queue_free()


func show_big(title_text: String, sub: String, seconds: float) -> void:
	if _big == null:
		return
	_big_title.text = title_text
	_big_sub.text = sub
	_big.visible = true
	_big_t = seconds


func _on_boss(boss_name: String, fraction: float) -> void:
	_boss.visible = fraction >= 0.0
	_boss_label.text = boss_name
	_boss_bar.value = clamp(fraction, 0.0, 1.0) * 100.0


func _on_won() -> void:
	show_big("Victory!", str(StarkGame.data.get("title", "")) + " is complete", 3.0)
	_credits_t = 1.6


func _process(delta: float) -> void:
	if _big_t > 0.0:
		_big_t -= delta
		if _big_t <= 0.0:
			_big.visible = false
	for t in _toasts.get_children():
		var left := float(t.get_meta("t", 3.2)) - delta
		t.set_meta("t", left)
		if left <= 0.0:
			_toasts.remove_child(t)
			t.queue_free()
	if _credits_t > 0.0:
		_credits_t -= delta
		if _credits_t <= 0.0:
			credits()


# ---------------------------------------------------------------- dialogue
func _on_dialogue() -> void:
	_dlg.visible = StarkDialogue.is_open
	for c in _dlg_choices.get_children():
		c.queue_free()
	if not StarkDialogue.is_open:
		return
	_dlg_speaker.text = StarkDialogue.speaker()
	_dlg_text.text = StarkDialogue.text()
	for i in range(StarkDialogue.choices.size()):
		var idx := i
		var c: Dictionary = StarkDialogue.choices[i]
		_dlg_choices.add_child(_button("%d   %s" % [i + 1, str(c.get("text", "..."))], func() -> void: StarkDialogue.choose(idx)))


# ---------------------------------------------------------------- modals
func _clear_modal() -> void:
	for c in _modal_box.get_children():
		_modal_box.remove_child(c)
		c.queue_free()


func close_modal() -> void:
	if _modal == null:
		return
	_modal.visible = false
	modal = ""
	StarkGame.busy_t = 0.15
	StarkGame.changed.emit()


func _open(kind: String, heading: String) -> void:
	_clear_modal()
	modal = kind
	_modal.visible = true
	_modal_box.add_child(_label(heading, 22, GOLD))


func open_quests() -> void:
	_open("quests", "Quest log")
	var any := false
	for qd in StarkGame.quest_list:
		var id := str(qd["id"])
		if not StarkQuests.q.has(id):
			continue
		any = true
		var r: Dictionary = StarkQuests.q[id]
		var done := str(r["state"]) == "done"
		_modal_box.add_child(_label(str(qd.get("title", id)) + (" (done)" if done else ""), 16, Color(0.47, 0.87, 0.47) if done else GOLD))
		if str(qd.get("desc", "")) != "":
			var dl := _label(str(qd["desc"]), 12, Color(0.62, 0.69, 0.75))
			dl.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
			dl.custom_minimum_size = Vector2(520, 0)
			_modal_box.add_child(dl)
		var steps: Array = qd.get("steps", [])
		for i in range(steps.size()):
			var ok := done or i < int(r["step"])
			_modal_box.add_child(_label(("  [x] " if ok else "  [ ] ") + StarkQuests.step_text(steps[i]), 12,
				Color(0.47, 0.87, 0.47) if ok else (Color.WHITE if i == int(r["step"]) else Color(0.47, 0.53, 0.6))))
	if not any:
		_modal_box.add_child(_label("No quests yet. Look for people with a gold ! above their heads and press E.", 13))
	_modal_box.add_child(_button("Close (L)", close_modal))


func open_bag() -> void:
	var st := StarkInventory.stats()
	_open("bag", "Bag")
	_modal_box.add_child(_label("ATK %d  -  DEF %d  -  Max HP %d  -  %d gold" % [int(st["atk"]), int(st["def"]), int(st["max_hp"]), StarkInventory.gold], 13))
	if StarkInventory.inv.is_empty():
		_modal_box.add_child(_label("Empty. Open chests and pick things up to fill it.", 13))
	for id in StarkInventory.inv.keys():
		var it := StarkGame.item(str(id))
		var n := int(StarkInventory.inv[id])
		var equipped := str(StarkInventory.eq.get(str(it.get("slot", "")), "")) == str(id)
		var row := HBoxContainer.new()
		var sw := ColorRect.new()
		sw.color = StarkGame.color_of(str(it.get("col", "#888888")))
		sw.custom_minimum_size = Vector2(14, 14)
		row.add_child(sw)
		row.add_child(_label("%s%s%s - %s" % [str(it["name"]), " x%d" % n if n > 1 else "", " (equipped)" if equipped else "", str(it.get("desc", it.get("kind", "")))], 13))
		var kind := str(it.get("kind", ""))
		if kind == "consumable" or kind == "equip":
			var item_id := str(id)
			row.add_child(_button("Use" if kind == "consumable" else ("Unequip" if equipped else "Equip"), func() -> void: StarkInventory.use(item_id)))
		_modal_box.add_child(row)
	_modal_box.add_child(_button("Close (I)", close_modal))


func open_menu() -> void:
	_open("menu", "Paused")
	_modal_box.add_child(_button("Resume", close_modal))
	_modal_box.add_child(_label("Save", 16, GOLD))
	for i in [1, 2, 3]:
		var slot := str(i)
		var row := HBoxContainer.new()
		var info := StarkSave.slot_info(slot)
		row.add_child(_label("Slot %s  %s" % [slot, info if info != "" else "(empty)"], 13))
		row.add_child(_button("Save", _menu_save.bind(slot)))
		row.add_child(_button("Load", func() -> void: StarkSave.load_slot(slot)))
		_modal_box.add_child(row)
	var arow := HBoxContainer.new()
	var ainfo := StarkSave.slot_info("auto")
	arow.add_child(_label("Autosave (checkpoints)  %s" % (ainfo if ainfo != "" else "(empty)"), 13))
	arow.add_child(_button("Load", func() -> void: StarkSave.load_slot("auto")))
	_modal_box.add_child(arow)
	var drow := HBoxContainer.new()
	drow.add_child(_label("Difficulty", 13))
	for d in ["easy", "normal", "hard"]:
		var dd: String = d
		drow.add_child(_button(("> " if StarkGame.diff == dd else "") + dd, _menu_diff.bind(dd)))
	drow.add_child(_button("Sound: off" if StarkGame.muted else "Sound: on", _menu_sound))
	_modal_box.add_child(drow)
	_modal_box.add_child(_label("Move WASD  Jump Space  Attack J/click  Talk E  Answers 1-4  Potion H  Dash Shift  Whirl K  Bolt F  Camera Z/C or right mouse  Quests L  Bag I", 11, Color(0.62, 0.69, 0.75)))


func _menu_save(slot: String) -> void:
	StarkSave.save_slot(slot)
	open_menu()


func _menu_diff(d: String) -> void:
	StarkGame.diff = d
	open_menu()


func _menu_sound() -> void:
	StarkGame.muted = not StarkGame.muted
	open_menu()


func credits() -> void:
	var w := StarkGame.data
	var mins: int = max(1, int(round(StarkGame.play_time / 60.0)))
	_open("credits", str(w.get("title", "The End")) + " - complete!")
	_modal_box.add_child(_label("Level %d  -  %d gold  -  %d quests  -  about %d min" % [StarkInventory.lvl, StarkInventory.gold, StarkQuests.q.size(), mins], 14))
	for L in StarkGame.levels:
		_modal_box.add_child(_label(str(L.get("name", "")), 14))
	_modal_box.add_child(_label("A game by %s  -  Made with Stark World Engine" % str(w.get("author", "you")), 12, Color(0.62, 0.69, 0.75)))
	_modal_box.add_child(_button("Keep exploring", close_modal))


func open_title() -> void:
	if _title != null:
		return
	StarkGame.title_open = true
	_title = ColorRect.new()
	_title.color = Color(0, 0, 0, 0.78)
	_title.set_anchors_preset(Control.PRESET_FULL_RECT)
	var v := VBoxContainer.new()
	_place(v, Control.PRESET_CENTER, -320, -160, 320, -160)
	var t := _label(str(StarkGame.data.get("title", "Untitled Adventure")), 54, GOLD)
	t.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	var s := _label(str(StarkGame.data.get("story", "")), 16)
	s.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	s.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	v.add_child(t)
	v.add_child(s)
	v.add_child(_button("New game", func() -> void: _close_title(false)))
	if StarkSave.has_slot("auto") or StarkSave.has_slot("1"):
		v.add_child(_button("Continue", func() -> void: _close_title(true)))
	var n := StarkGame.level_count()
	v.add_child(_label(("%d levels  -  " % n if n > 1 else "") + "Press Enter to start  -  Made with Stark World Engine", 12, Color(0.62, 0.69, 0.75)))
	_title.add_child(v)
	_root.add_child(_title)


func _close_title(load_game: bool) -> void:
	if _title == null:
		return
	_root.remove_child(_title)
	_title.queue_free()
	_title = null
	StarkGame.title_open = false
	StarkGame.play_sfx("portal")
	if load_game:
		if not StarkSave.load_slot("auto"):
			StarkSave.load_slot("1")


func title_is_open() -> bool:
	return _title != null


# ---------------------------------------------------------------- keys (dialogue, menus, potion)
func _unhandled_input(event: InputEvent) -> void:
	if not (event is InputEventKey) or not event.pressed or event.echo:
		return
	var k: int = (event as InputEventKey).physical_keycode
	if _title != null:
		if k == KEY_ENTER or k == KEY_SPACE:
			_close_title(false)
		get_viewport().set_input_as_handled()
		return
	if StarkDialogue.is_open:
		if k >= KEY_1 and k <= KEY_9:
			StarkDialogue.choose(k - KEY_1)
		elif (k == KEY_E or k == KEY_ENTER or k == KEY_SPACE) and StarkDialogue.choices.size() == 1:
			StarkDialogue.choose(0)
		elif k == KEY_ESCAPE:
			StarkDialogue.close()
		get_viewport().set_input_as_handled()
		return
	if event.is_action("stark_menu"):
		if modal != "":
			close_modal()
		else:
			open_menu()
	elif event.is_action("stark_quests"):
		if modal == "quests":
			close_modal()
		else:
			open_quests()
	elif event.is_action("stark_bag"):
		if modal == "bag":
			close_modal()
		else:
			open_bag()
	elif event.is_action("stark_potion") and modal == "":
		StarkInventory.quaff()
	else:
		return
	get_viewport().set_input_as_handled()
