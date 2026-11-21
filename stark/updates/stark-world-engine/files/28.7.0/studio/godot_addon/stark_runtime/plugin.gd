@tool
extends EditorPlugin
## Stark World Engine Runtime editor helpers: Project > Tools > "Stark World Engine: rebuild terrain and scenery" refreshes the generated
## terrain / props of the open scene after you change stark_game.json or an art slot.

const MENU := "Stark World Engine: rebuild terrain and scenery"


func _enter_tree() -> void:
	add_tool_menu_item(MENU, _rebuild)


func _exit_tree() -> void:
	remove_tool_menu_item(MENU)


func _rebuild() -> void:
	var root := EditorInterface.get_edited_scene_root()
	if root == null:
		return
	for n in root.find_children("*", "", true, false):
		if n.has_method("build"):
			n.build()
