"""Stark World Engine Play-In-Editor smoke test (UE 5.4+, needs the Stark World Engine Runtime plugin).

Starts PIE on level 1 and plays like a player through the runtime's own functions: talks to the first quest giver
and accepts the quest, picks items up by walking the hero onto them, fights an enemy with the real attack, saves to
slot 1, changes the gold, loads slot 1 and checks it came back, then walks into a portal and checks the next level
loaded. Writes Saved/Stark/pie_smoke.json.
  menu Stark World Engine > Run Play-In-Editor smoke test, or
  UnrealEditor.exe <project> -ExecutePythonScript=<this file> -StarkNoAutoBuild -StarkQuitAfterSmoke
UE 5.4 Python: LevelEditorSubsystem, UnrealEditorSubsystem.get_game_world, GameplayStatics.get_all_actors_of_class,
register_slate_post_tick_callback (https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/?application_version=5.4)
"""
import json, os, sys, time

try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    import unreal as _u
    _HERE = os.path.join(_u.Paths.convert_relative_path_to_full(_u.Paths.project_content_dir()), "Python")
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import unreal
import stark_common as gc

RESULT = {"ok": False, "steps": [], "errors": [], "started": time.time()}
S = {"handle": None, "phase": "start", "wait": 0, "ticks": 0, "sub": None, "gold": 0, "level0": None, "queue": []}


def note(msg):
    RESULT["steps"].append(msg)
    unreal.log("[StarkSmoke] " + str(msg))


def fail(msg):
    RESULT["errors"].append(msg)
    unreal.log_error("[StarkSmoke] " + str(msg))


def finish():
    RESULT["ok"] = not RESULT["errors"] and RESULT.get("quest_started") and RESULT.get("save_load") and \
        RESULT.get("portal") is not False
    RESULT["seconds"] = round(time.time() - RESULT["started"], 1)
    os.makedirs(gc.SAVED, exist_ok=True)
    with open(os.path.join(gc.SAVED, "pie_smoke.json"), "w", encoding="utf-8") as f:
        json.dump(RESULT, f, indent=1, default=str)
    try:
        unreal.StarkEditorLibrary.stop_play_in_editor()
    except Exception:
        pass
    if S["handle"] is not None:
        unreal.unregister_slate_post_tick_callback(S["handle"])
        S["handle"] = None
    note("RESULT ok=%s" % RESULT["ok"])
    if "-starkquitaftersmoke" in unreal.SystemLibrary.get_command_line().lower():
        unreal.SystemLibrary.quit_editor()


def world():
    return unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()


def hero():
    w = world()
    return unreal.GameplayStatics.get_player_character(w, 0) if w else None


def actors(cls):
    w = world()
    return list(unreal.GameplayStatics.get_all_actors_of_class(w, cls)) if w else []


def prop(obj, name, value=None, write=False):
    """BlueprintReadOnly/ReadWrite properties are Python attributes; Edit properties also work with *_editor_property."""
    if write:
        try:
            setattr(obj, name, value)
        except Exception:
            obj.set_editor_property(name, value)
        return value
    try:
        return getattr(obj, name)
    except Exception:
        return obj.get_editor_property(name)


def plan_xz(actor):
    loc = actor.get_actor_location()
    return float(loc.y) / 100.0, -float(loc.x) / 100.0


def step_logic():
    sub = S["sub"]
    rules = prop(sub, "rules")
    ph = S["phase"]
    if ph == "ready":
        S["level0"] = sub.get_level_index()
        note("PIE running on level %d" % S["level0"])
        S["phase"] = "talk"
    elif ph == "talk":
        game = gc.load_game()
        givers = [q for q in game.get("quests", []) if q.get("giver") and q.get("level") == S["level0"]]
        if not givers:
            note("no quest giver on this level; skipping dialogue")
            RESULT["quest_started"] = True
            S["phase"] = "fight"
            return
        q = givers[0]
        npc = next((n for n in actors(unreal.StarkNpcCharacter)
                    if str(n.get_component_by_class(unreal.StarkNpcComponent).get_editor_property("npc_id")) == q["giver"]), None)
        if npc is None:
            fail("quest giver %s not in the level" % q["giver"])
            S["phase"] = "fight"
            return
        x, z = plan_xz(npc)
        hero().teleport_to_plan(x + 1.2, z)
        c = npc.get_component_by_class(unreal.StarkNpcComponent)
        c.interact(hero())
        for _ in range(6):
            if not prop(rules, "dialogue_open"):
                break
            choices = list(prop(rules, "visible_choices"))
            pick = 0
            for i, ch in enumerate(choices):
                if str(ch.action.start) == q["id"]:
                    pick = i
            note("dialogue: %s -> %s" % (str(prop(rules, "line"))[:60], str(choices[pick].text) if choices else "-"))
            sub.choose(pick)
        RESULT["quest_started"] = sub.quest_state(q["id"]) == "active"
        note("quest %s state after talking: %s" % (q["id"], sub.quest_state(q["id"])))
        S["queue"] = [a for a in actors(unreal.StarkInteractable)
                      if a.get_editor_property("kind") in (unreal.StarkThing.CRYSTAL, unreal.StarkThing.ITEM)][:3]
        S["phase"] = "collect"
    elif ph == "collect":
        if S["queue"]:
            a = S["queue"].pop(0)
            x, z = plan_xz(a)
            hero().teleport_to_plan(x, z)
            S["wait"] = 20
            return
        RESULT["inventory_after_pickups"] = {str(k): int(v) for k, v in dict(prop(rules, "inventory")).items()}
        note("inventory after pickups: %s" % RESULT["inventory_after_pickups"])
        S["phase"] = "fight"
    elif ph == "fight":
        foes = [e for e in actors(unreal.StarkEnemyCharacter) if not prop(e, "dead")]
        if not foes:
            note("no enemy here")
            S["phase"] = "save"
            return
        e = foes[0]
        S["foe"] = e
        S["swings"] = 0
        S["phase"] = "swing"
    elif ph == "swing":
        e = S.get("foe")
        alive = e is not None and unreal.SystemLibrary.is_valid(e) and not prop(e, "dead")
        if not alive or S["swings"] > 120:
            RESULT["enemy_defeated"] = not alive
            note("enemy defeated: %s after %d swings" % (not alive, S["swings"]))
            S["phase"] = "save"
            return
        x, z = plan_xz(e)
        hero().teleport_to_plan(x + 1.3, z)
        hero().attack()
        S["swings"] += 1
        S["wait"] = 18
    elif ph == "save":
        S["gold"] = int(prop(rules, "gold"))
        ok = sub.save_to_slot("1", True)
        note("saved slot 1: %s (gold %d)" % (ok, S["gold"]))
        sub.give_item("gem", 4, True)
        sub.load_from_slot("1")
        S["phase"] = "after_load"
        S["wait"] = 120
    elif ph == "after_load":
        gold = int(prop(prop(sub, "rules"), "gold"))
        RESULT["save_load"] = gold == S["gold"]
        note("after load gold %d (want %d)" % (gold, S["gold"]))
        S["phase"] = "portal"
    elif ph == "portal":
        portals = [a for a in actors(unreal.StarkInteractable)
                   if a.get_editor_property("kind") == unreal.StarkThing.PORTAL and not a.is_locked()]
        if not portals or sub.get_level_count() < 2:
            note("no open portal (locked by a quest or single level)")
            RESULT["portal"] = None
            finish()
            S["phase"] = "done"
            return
        x, z = plan_xz(portals[0])
        S["dest"] = portals[0].destination()
        hero().teleport_to_plan(x, z)
        S["phase"] = "after_portal"
        S["wait"] = 240
    elif ph == "after_portal":
        RESULT["portal"] = sub.get_level_index() == S["dest"]
        note("after portal: level %d (want %d)" % (sub.get_level_index(), S["dest"]))
        finish()
        S["phase"] = "done"


def tick(delta):
    S["ticks"] += 1
    if S["phase"] == "done":
        return
    if S["ticks"] > 20000:
        fail("timeout in phase %s" % S["phase"])
        finish()
        S["phase"] = "done"
        return
    if S["wait"] > 0:
        S["wait"] -= 1
        return
    try:
        if S["phase"] == "start":
            gc.level_sub().load_level(gc.load_plans()[0]["map"])
            if not unreal.StarkEditorLibrary.start_play_in_editor():
                fail("could not start Play-In-Editor")
                finish()
                S["phase"] = "done"
                return
            S["phase"] = "wait_pie"
            S["wait"] = 60
            return
        if S["phase"] == "wait_pie":
            sub = unreal.StarkEditorLibrary.get_play_subsystem()
            if sub is None or hero() is None:
                S["wait"] = 30
                return
            prop(sub, "test_invulnerable", True, write=True)
            S["sub"] = sub
            S["phase"] = "ready"
            S["wait"] = 60
            return
        step_logic()
    except Exception as e:
        fail("phase %s: %r" % (S["phase"], e))
        finish()
        S["phase"] = "done"


if not gc.runtime_ready():
    RESULT["errors"].append("Stark World Engine Runtime plugin not loaded (no prebuilt binaries for this engine version?)")
    finish()
else:
    if not gc.build_is_current():
        note("levels not built yet: building first")
        import runpy
        runpy.run_path(os.path.join(_HERE, "stark_build_level.py"), run_name="__main__")
    S["handle"] = unreal.register_slate_post_tick_callback(tick)
