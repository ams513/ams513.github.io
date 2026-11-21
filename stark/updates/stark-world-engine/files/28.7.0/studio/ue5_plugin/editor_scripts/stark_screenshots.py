"""Stark World Engine: high-res screenshots from every GS_Shot_* cine camera of the open level (Saved/Screenshots).
AutomationLibrary.take_high_res_screenshot: https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/AutomationLibrary?application_version=5.4
"""
import importlib, os, sys

try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    import unreal as _u
    _HERE = os.path.join(_u.Paths.convert_relative_path_to_full(_u.Paths.project_content_dir()), "Python")
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import unreal
import stark_common as gc
importlib.reload(gc)

for cam in gc.gs_actors("GS_Shot"):
    name = cam.get_actor_label()
    try:
        unreal.AutomationLibrary.take_high_res_screenshot(3840, 2160, name + ".png", cam)
        gc.log("screenshot queued: %s" % name)
    except Exception as e:
        gc.warn("screenshot %s: %s" % (name, e))
