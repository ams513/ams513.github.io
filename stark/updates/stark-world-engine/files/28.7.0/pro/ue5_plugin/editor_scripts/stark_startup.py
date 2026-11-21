"""Stark World Engine editor startup (UE 5.4+): adds the Stark World Engine menu and builds the Stark World Engine levels by itself ONCE on the
first editor start (and again only when the exported game data changes). Registered as a PythonScriptPlugin startup
script in Config/DefaultEngine.ini; init_unreal.py imports it too (a guard keeps it to one run per editor session).
Startup scripts / init_unreal.py: https://dev.epicgames.com/documentation/en-us/unreal-engine/scripting-the-unreal-editor-using-python
Slate post-tick callbacks: https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/module/unreal?application_version=5.4
"""
import builtins, os, runpy, sys

import unreal

try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _HERE = os.path.join(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_content_dir()), "Python")
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

MENU_SCRIPTS = (("GSRebuild", "Rebuild from Stark World Engine", "Rebuild every Stark World Engine level and data asset from the exported game",
                 "stark_build_level.py"),
                ("GSSwap", "Swap proxies for real assets", "Use proxy_swap_map.csv and metahuman_slots.csv",
                 "stark_swap_proxies.py"),
                ("GSShots", "Take hero screenshots", "High-res shots from the GS_Shot_* cameras", "stark_screenshots.py"),
                ("GSSmoke", "Run Play-In-Editor smoke test", "Plays a quest, a fight, save/load and a portal by itself",
                 "stark_pie_smoke.py"))


def run_script(name):
    runpy.run_path(os.path.join(_HERE, name), run_name="__main__")


def _entry(section_menu, name, label, tip, script):
    e = unreal.ToolMenuEntry(name=name, type=unreal.MultiBlockType.MENU_ENTRY)
    e.set_label(label)
    e.set_tool_tip(tip)
    cmd = "import stark_startup; stark_startup.run_script('%s')" % script
    e.set_string_command(unreal.ToolMenuStringCommandType.PYTHON, "", cmd)
    section_menu.add_menu_entry("StarkWorldEngine", e)


def add_menu():
    try:
        menus = unreal.ToolMenus.get()
        main = menus.find_menu("LevelEditor.MainMenu")
        if main:
            sub = main.add_sub_menu(main.get_name(), "StarkSection", "StarkWorldEngine", "Stark World Engine", "Stark World Engine tools")
            for name, label, tip, script in MENU_SCRIPTS:
                _entry(sub, name, label, tip, script)
            menus.refresh_all_widgets()
    except Exception as e:
        unreal.log_warning("[StarkWorldEngine] menu not added: %r" % (e,))


def _is_commandlet():
    try:
        cl = unreal.SystemLibrary.get_command_line().lower()
    except Exception:
        cl = ""
    return "-run=" in cl or "-starknoautobuild" in cl


_STATE = {"handle": None, "ticks": 0}


def _tick(delta):
    _STATE["ticks"] += 1
    try:
        reg = unreal.AssetRegistryHelpers.get_asset_registry()
        if reg.is_loading_assets() or _STATE["ticks"] < 30:
            return
    except Exception:
        if _STATE["ticks"] < 120:
            return
    unreal.unregister_slate_post_tick_callback(_STATE["handle"])
    _STATE["handle"] = None
    unreal.log("[StarkWorldEngine] first start: building the Stark World Engine levels (this happens once)")
    try:
        run_script("stark_build_level.py")
    except Exception as e:
        unreal.log_error("[StarkWorldEngine] automatic build failed: %r (menu Stark World Engine > Rebuild from Stark World Engine)" % (e,))


def start():
    if getattr(builtins, "_stark_startup_done", False):
        return
    builtins._stark_startup_done = True
    add_menu()
    if _is_commandlet():
        return
    import stark_common as gc
    if gc.build_is_current():
        unreal.log("[StarkWorldEngine] levels are up to date (menu Stark World Engine > Rebuild from Stark World Engine rebuilds them)")
        return
    _STATE["handle"] = unreal.register_slate_post_tick_callback(_tick)


start()
