extends SceneTree
## Renders one level with the real renderer and saves a PNG (checks that shaders compile and shows the look).
##   godot --path <project> --script res://addons/stark_runtime/tests/screenshot.gd -- --stark-no-title
##         --level=0 --out=<file.png> [--frames=120] [--yaw=0.6] [--hide-ui]

var level_index: int = 0
var out_path: String = "user://stark_shot.png"
var frames: int = 120
var yaw: float = -1000.0
var hide_ui: bool = false


func _initialize() -> void:
	for a in OS.get_cmdline_user_args():
		var s := str(a)
		if s.begins_with("--level="):
			level_index = int(s.substr(8))
		elif s.begins_with("--out="):
			out_path = s.substr(6)
		elif s.begins_with("--frames="):
			frames = int(s.substr(9))
		elif s.begins_with("--yaw="):
			yaw = float(s.substr(6))
		elif s == "--hide-ui":
			hide_ui = true
	call_deferred("_go")


func _go() -> void:
	await process_frame
	var g = root.get_node("StarkGame")
	g.muted = true
	g.booted = true
	g.new_game()
	change_scene_to_file(g.scene_path(level_index))
	for i in range(10):
		await process_frame
	if yaw > -999.0 and g.player and "cam_yaw" in g.player:
		g.player.cam_yaw = yaw
	if hide_ui:
		root.get_node("StarkUI").visible = false
	for i in range(frames):
		await process_frame
	var img := root.get_viewport().get_texture().get_image()
	var err := img.save_png(out_path)
	print("[screenshot] ", out_path, " ", img.get_width(), "x", img.get_height(), " err=", err)
	quit(0 if err == OK else 1)
