"""Stark World Engine: one-click swap of proxies for real assets (proxy_swap_map.csv: Fab / Megascans / your meshes or
Blueprints per class; metahuman_slots.csv: a MetaHuman or character Blueprint per NPC id). Gameplay actors keep
their Stark World Engine logic and only change their look."""
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

gc.REPORT["warnings"] = []
done = {}
for plan in gc.load_plans():
    if plan.get("mode") == "2d":
        continue
    try:
        gc.level_sub().load_level(plan["map"])
    except Exception as e:
        gc.warn("load %s: %s" % (plan["map"], e))
        continue
    done[plan["map"]] = gc.swap_all(plan)
    gc.save_all()
if not any(done.values()):
    gc.warn("nothing to swap: fill asset_path in Content/Python/proxy_swap_map.csv (Copy Reference from Content Browser)")
gc.log("swapped: %s" % done)
