"""Runs when the editor starts (PythonScriptPlugin runs every Content/Python/init_unreal.py). The real work is in
stark_startup.py (also registered as a startup script in Config/DefaultEngine.ini; it only runs once per session)."""
import os
import sys

import unreal

try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _HERE = os.path.join(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_content_dir()), "Python")
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
try:
    import stark_startup  # noqa: F401  (adds the Stark World Engine menu, builds once)
except Exception as _e:
    unreal.log_warning("[StarkWorldEngine] startup not run: %r" % (_e,))
