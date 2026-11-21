extends Node
## Stark World Engine Runtime - autoload "StarkDialogue": branching dialogue with conditions and actions.
## Data: stark_game.json "dialogs" {id: {start, branches: [{if, node}], nodes: {id: {speaker, text, next, do, choices}}}}
## COND = {has, n, lacks, done, active, notStarted, flag, minLevel}
## ACTION = {start, complete, advance, give, take, n, gold, xp, flag, heal, win}

signal dialogue_changed

var is_open: bool = false
var npc: Dictionary = {}        # {"id", "name", "dialog", "text"}
var dlg: Dictionary = {}
var node_id: String = ""
var node: Dictionary = {}
var choices: Array = []          # visible choices of the current node


func cond(c) -> bool:
	if not (c is Dictionary) or c.is_empty():
		return true
	if c.has("has") and not StarkInventory.has(str(c["has"]), int(c.get("n", 1))):
		return false
	if c.has("lacks") and StarkInventory.has(str(c["lacks"])):
		return false
	if c.has("done") and StarkQuests.state_of(str(c["done"])) != "done":
		return false
	if c.has("active") and StarkQuests.state_of(str(c["active"])) != "active":
		return false
	if c.has("notStarted") and StarkQuests.q.has(str(c["notStarted"])):
		return false
	if c.has("flag") and not StarkGame.flags.has(str(c["flag"])):
		return false
	if c.has("minLevel") and StarkInventory.lvl < int(c["minLevel"]):
		return false
	return true


func talk(who: Dictionary) -> void:
	# who: {"id", "name", "dialog", "text"} (an NPC node passes its own info)
	npc = who
	StarkQuests.event("talk", {"npc": str(who.get("id", ""))})
	StarkGame.play_sfx("talk")
	var d := StarkGame.dialog(str(who.get("dialog", "")))
	if d.is_empty():
		var line := str(who.get("text", ""))
		if line == "":
			line = "Lovely day for an adventure, isn't it?"
		dlg = {"nodes": {"a": {"speaker": str(who.get("name", "")), "text": line, "next": "", "do": {}, "choices": []}}}
		show_node("a")
		return
	dlg = d
	var start := str(d.get("start", ""))
	var nodes: Dictionary = d.get("nodes", {})
	if start == "" and not nodes.is_empty():
		start = str(nodes.keys()[0])
	for b in d.get("branches", []):
		if cond(b.get("if")) and nodes.has(str(b.get("node", ""))):
			start = str(b["node"])
			break
	show_node(start)


func show_node(id: String) -> void:
	var nodes: Dictionary = dlg.get("nodes", {})
	if not nodes.has(id):
		close()
		return
	node_id = id
	node = nodes[id]
	if node.get("do") is Dictionary and not (node["do"] as Dictionary).is_empty():
		act(node["do"])
	choices = []
	for c in node.get("choices", []):
		if cond(c.get("if")):
			choices.append(c)
	if choices.is_empty():
		var nx := str(node.get("next", ""))
		choices = [{"text": "Continue" if nx != "" else "Farewell", "goto": nx, "end": nx == "", "do": {}}]
	is_open = true
	dialogue_changed.emit()
	StarkGame.changed.emit()


func speaker() -> String:
	var s := str(node.get("speaker", ""))
	if s == "":
		s = str(npc.get("name", ""))
	return s if s != "" else "Stranger"


func text() -> String:
	return str(node.get("text", ""))


func choose(index: int) -> void:
	if not is_open or index < 0 or index >= choices.size():
		return
	var c: Dictionary = choices[index]
	StarkGame.play_sfx("talk")
	act(c.get("do", {}))
	if str(c.get("goto", "")) != "" and not bool(c.get("end", false)):
		show_node(str(c["goto"]))
	else:
		close()


func close() -> void:
	is_open = false
	choices = []
	node = {}
	StarkGame.busy_t = 0.25
	dialogue_changed.emit()
	StarkGame.changed.emit()


func act(a) -> void:
	if not (a is Dictionary) or a.is_empty():
		return
	for k in a.keys():
		if str(k) in StarkGame.BLOCKED_ACTIONS:
			# child-safety backstop: harm / capture / romance actions never run from dialogue data
			push_warning("Stark World Engine child-safety: dialogue action '%s' ignored" % str(k))
			return
	if a.has("take"):
		StarkInventory.take(str(a["take"]), int(a.get("n", 1)))
	for g in a.get("give", []):
		StarkInventory.give(str(g), 1)
	if int(a.get("gold", 0)) != 0:
		StarkInventory.gold += int(a["gold"])
		StarkGame.emit_toast(("+" if int(a["gold"]) > 0 else "") + str(int(a["gold"])) + " gold")
	if a.has("start"):
		StarkQuests.start(str(a["start"]))
	if a.has("advance"):
		StarkQuests.event("talk", {"npc": str(a["advance"])})
	if a.has("flag"):
		StarkGame.flags[str(a["flag"])] = true
	if int(a.get("xp", 0)) > 0:
		StarkInventory.add_xp(int(a["xp"]))
	if bool(a.get("heal", false)):
		StarkInventory.hp = float(StarkInventory.stats()["max_hp"])
	if a.has("complete"):
		var qd := StarkGame.quest(str(a["complete"]))
		if not qd.is_empty() and StarkQuests.state_of(str(a["complete"])) == "active":
			StarkQuests.complete(qd)
	if bool(a.get("win", false)):
		StarkGame.win()
	StarkGame.changed.emit()
