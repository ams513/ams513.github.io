"""Stark World Engine: builds every Stark World Engine level (/Game/Stark/Maps/GS_Level_00 ...) and the game's data assets from
Content/Stark/Data/stark_game.json + Content/Python/stark_plan.json (UE 5.4+).

Runs by itself once on the first editor start (stark_startup.py), from the menu Stark World Engine > Rebuild from Stark World Engine,
Tools > Execute Python Script, or headless: UnrealEditor-Cmd.exe <project> -run=pythonscript -script=<this file>.
Re-running rebuilds the actors tagged GS and keeps your own work. Every engine call is from the UE 5.4 Python API:
https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/?application_version=5.4
"""
import importlib, json, math, os, sys, time

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

T0 = time.time()
GAME = gc.load_game()
PLANS = gc.load_plans()
RUNTIME = gc.runtime_ready()
gc.REPORT["warnings"] = []
gc.REPORT["levels"] = []
ART = {}


def open_level(path):
    """LevelEditorSubsystem.new_level(asset_path, is_partitioned_world) / load_level (UE 5.4)."""
    les = gc.level_sub()
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        les.load_level(path)
    else:
        made = False
        try:
            made = les.new_level(path, True)          # World Partition map
        except TypeError:
            made = les.new_level(path)
        if not made:
            gc.warn("could not create %s; building into the open level" % path)
    gc.destroy(gc.gs_actors("GS"))


def sky_stack(plan):
    """SkyAtmosphere + sun (atmosphere light) + real-time SkyLight + VolumetricCloud + ExponentialHeightFog."""
    look, sun, w, base = plan["look"], plan["sun"], plan["weather"], plan["base"]
    weather_fog = {"rain": 1.8, "snow": 1.5, "fog": 2.5, "storm": 2.2}.get(w["type"], 1.0)
    gc.spawn(unreal.SkyAtmosphere, unreal.Vector(0, 0, 0), None, "GS_SkyAtmosphere", "Stark/Sky")
    sun_a = gc.spawn(unreal.DirectionalLight, unreal.Vector(0, 0, 3000), gc.rot(sun["azim"], -sun["elev"]),
                     "GS_Sun", "Stark/Sky")
    lc = gc.comp(sun_a, unreal.DirectionalLightComponent)
    if lc:
        lc.set_mobility(unreal.ComponentMobility.MOVABLE)
        gc.setp(lc, "intensity", float(sun["lux"]) * (0.6 if w["type"] in ("rain", "storm") else 1.0))
        lc.set_light_color(gc.lin(sun["color"]))
        gc.setp(lc, "atmosphere_sun_light", True)
        gc.setp(lc, "light_source_angle", 0.6)
        gc.setp(lc, "cast_cloud_shadows", True)
        gc.setp(lc, "cast_shadows", True)
    sky = gc.spawn(unreal.SkyLight, unreal.Vector(0, 0, 2000), None, "GS_SkyLight", "Stark/Sky")
    sc = gc.comp(sky, unreal.SkyLightComponent)
    if sc:
        sc.set_mobility(unreal.ComponentMobility.MOVABLE)
        gc.setp(sc, "real_time_capture", True)
        gc.setp(sc, "source_type", unreal.SkyLightSourceType.SLS_CAPTURED_SCENE)
        gc.setp(sc, "intensity", float(look["sky"]))
        gc.setp(sc, "lower_hemisphere_is_black", False)
        gc.setp(sc, "lower_hemisphere_color", gc.lin(base["ground"], 0.5))
    cloud = gc.spawn(unreal.VolumetricCloud, unreal.Vector(0, 0, 0), None, "GS_VolumetricCloud", "Stark/Sky")
    cc = gc.comp(cloud, unreal.VolumetricCloudComponent)
    if cc and w["type"] in ("rain", "storm", "snow"):
        gc.setp(cc, "layer_bottom_altitude", 1.0)
    fog = gc.spawn(unreal.ExponentialHeightFog, unreal.Vector(0, 0, -200), None, "GS_HeightFog", "Stark/Sky")
    fc = gc.comp(fog, unreal.ExponentialHeightFogComponent)
    if fc:
        gc.setp(fc, "fog_density", float(look["fog"]) * weather_fog)
        gc.setp(fc, "fog_height_falloff", float(look["falloff"]))
        if not gc.setp(fc, "fog_inscattering_luminance", gc.lin(base["fog"])):
            try:
                fc.set_fog_inscattering_color(gc.lin(base["fog"]))
            except Exception:
                pass
        gc.setp(fc, "enable_volumetric_fog", True)
        gc.setp(fc, "volumetric_fog_scattering_distribution", 0.6)
        gc.setp(fc, "volumetric_fog_extinction_scale", float(look["vfog"]) * weather_fog)
        alb = [int(min(255, 140 + 115 * c)) for c in base["fog"]]
        gc.setp(fc, "volumetric_fog_albedo", unreal.Color(r=alb[0], g=alb[1], b=alb[2], a=255))


def post_process(plan):
    """Unbound PostProcessVolume: Lumen GI + reflections, histogram exposure, grading, bloom, vignette, grain."""
    look, w = plan["look"], plan["weather"]
    ppv = gc.spawn(unreal.PostProcessVolume, unreal.Vector(0, 0, 0), None, "GS_PostProcess", "Stark/Sky")
    gc.setp(ppv, "unbound", True)
    s = ppv.get_editor_property("settings")
    wet = w["type"] in ("rain", "storm")

    def pp(name, value):
        try:
            s.set_editor_property("override_" + name, True)
        except Exception:
            pass
        gc.setp(s, name, value)
    pp("dynamic_global_illumination_method", unreal.DynamicGlobalIlluminationMethod.LUMEN)
    pp("reflection_method", unreal.ReflectionMethod.LUMEN)
    pp("lumen_final_gather_quality", 2.0)
    pp("lumen_scene_lighting_quality", 2.0)
    pp("auto_exposure_method", unreal.AutoExposureMethod.AEM_HISTOGRAM)
    pp("auto_exposure_bias", float(look["ev_bias"]))
    pp("auto_exposure_min_brightness", float(look["ev_min"]))
    pp("auto_exposure_max_brightness", 16.0)
    pp("bloom_intensity", float(look["bloom"]))
    pp("vignette_intensity", float(look["vign"]))
    pp("film_grain_intensity", float(look["grain"]))
    pp("scene_fringe_intensity", 0.15)
    pp("motion_blur_amount", 0.25)
    pp("ambient_occlusion_intensity", 0.55)
    sat = float(look["sat"]) * (0.85 if wet else 1.0)
    pp("color_saturation", unreal.Vector4(sat, sat, sat, 1.0))
    pp("color_contrast", unreal.Vector4(look["con"], look["con"], look["con"], 1.0))
    g = look["gain"]
    pp("color_gain", unreal.Vector4(g[0], g[1], g[2], 1.0))
    ppv.set_editor_property("settings", s)


def build_terrain(plan, L, mats):
    """Landscape (StarkEditorLibrary.CreateLandscapeFromHeights) with the auto-material; fallback: a Nanite mesh with
    the same heights; last resort: a flat plane. -> (shaped, kind)"""
    pal = dict(L.get("palette") or {}, water_level=L.get("water"))
    textures = {k: ART.get(c) for k, c in (("grass", "ground"), ("rock", "ground_rock"), ("sand", "ground_sand"),
                                         ("snow", "ground_snow")) if ART.get(c) is not None and "Texture" in gc.class_name(ART.get(c))}
    if RUNTIME:
        try:
            heights, n, loc, scale = gc.landscape_heights(plan)
            mat = gc.auto_landscape_material(plan["level"], pal, textures)
            ls = unreal.StarkEditorLibrary.create_landscape_from_heights(heights, n, n, loc, scale, mat, 63, 1)
            if ls is not None:
                ls.set_actor_label("GS_Terrain")
                ls.set_folder_path("Stark/Terrain")
                gc.setp(ls, "tags", [unreal.Name("GS"), unreal.Name("GS_Terrain")])
                try:
                    ls.set_editor_property("is_spatially_loaded", False)
                except Exception:
                    pass
                return True, "landscape"
            gc.warn("landscape helper returned nothing; using a mesh terrain")
        except Exception as e:
            gc.warn("landscape unavailable (%s); using a mesh terrain" % e)
    try:
        mesh = gc.terrain_mesh(plan)
        a = gc.spawn(unreal.StaticMeshActor, unreal.Vector(0, 0, 0), None, "GS_Terrain", "Stark/Terrain", ["GS_Terrain"])
        a.static_mesh_component.set_static_mesh(mesh)
        a.static_mesh_component.set_material(0, mats["ground"])
        return True, "nanite_mesh"
    except Exception as e:
        gc.warn("shaped terrain unavailable (%s); using a flat ground plane" % e)
    t = plan["terrain"]
    plane = unreal.EditorAssetLibrary.load_asset(gc.SHAPES["plane"])
    a = gc.spawn(unreal.StaticMeshActor, unreal.Vector(0, 0, 0), None, "GS_Terrain", "Stark/Terrain", ["GS_Terrain"])
    a.static_mesh_component.set_static_mesh(plane)
    a.static_mesh_component.set_material(0, mats["ground"])
    a.set_actor_scale3d(unreal.Vector(t["span"], t["span"], 1.0))
    return False, "flat"


def build_water(plan, L):
    if L.get("water") is None:
        return False
    span = float(plan["terrain"]["span"])
    plane = unreal.EditorAssetLibrary.load_asset(gc.SHAPES["plane"])
    a = gc.spawn(unreal.StaticMeshActor, gc.cm(0.0, float(L["water"]), 0.0), None, "GS_Water", "Stark/Water", ["GS_Water"])
    c = a.static_mesh_component
    c.set_static_mesh(plane)
    c.set_material(0, gc.water_material(plan.get("water_color", [0.05, 0.3, 0.4])))
    c.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
    a.set_actor_scale3d(unreal.Vector(span, span, 1.0))
    return True


def build_scenery(plan, mats, shaped, gameplay_actors):
    """Creator-placed objects at their exact spots. With the runtime, gameplay objects become Stark World Engine actors (see
    build_gameplay); scenery (and everything when the runtime is off) is placed as proxies or library art."""
    shapes = {k: unreal.EditorAssetLibrary.load_asset(v) for k, v in gc.SHAPES.items()}
    if not shaped:
        gc.flatten(plan)
    by_cls = {}
    for o in plan["objects"]:
        if gameplay_actors and o["cls"] not in ("tree", "rock", "ruin", "lamp", "house"):
            continue
        by_cls.setdefault(o["cls"], []).append(o)
    for cls, objs in by_cls.items():
        tags = ["GS_Class_" + cls, "GS_Proxy"]
        art = ART.get(cls)
        if art is not None and gc.class_name(art) == "StaticMesh":
            xf = [gc.part_transform(o, None, uniform=float(o["s"])) for o in objs]
            gc.place(cls, "Art", art, None, xf, ["GS_%s_%03d" % (gc.kind(cls), o["i"]) for o in objs], tags)
        else:
            for part in plan["proxies"].get(cls, []):
                try:
                    xf = [gc.part_transform(o, part) for o in objs]
                    main = part is plan["proxies"][cls][0]
                    labels = [("GS_%s_%03d" % (gc.kind(cls), o["i"])) + ("" if main else "_" + part["part"]) for o in objs]
                    gc.place(cls, part["part"], shapes[part["shape"]], mats.get(part["mat"]), xf, labels, tags)
                except Exception as e:
                    gc.warn("%s %s proxies failed: %s" % (cls, part.get("part"), e))
        gc.REPORT["counts"][cls] = gc.REPORT["counts"].get(cls, 0) + len(objs)


def build_ambient(plan, L):
    """PCG ambient scatter on the landscape: grass cones / bushes / pebbles (library art when available)."""
    meshes = []
    for cls, w in (("grass", 6), ("bush", 2), ("pebble", 1)):
        m = ART.get(cls)
        if m is not None and gc.class_name(m) == "StaticMesh":
            meshes.append((m, w))
    if not meshes:
        meshes = [(unreal.EditorAssetLibrary.load_asset(gc.SHAPES["cone"]), 6),
                  (unreal.EditorAssetLibrary.load_asset(gc.SHAPES["sphere"]), 1)]
    try:
        graph = gc.pcg_graph(plan["level"], meshes, 0.08)
        size = float(L.get("size", 48.0))
        vol = gc.spawn(unreal.PCGVolume, gc.cm(0.0, 0.0, 0.0), None, "GS_PCG_Ambient", "Stark/PCG", ["GS_PCG"])
        vol.set_actor_scale3d(unreal.Vector(size * 2.0, size * 2.0, 20.0))
        pc = gc.comp(vol, unreal.PCGComponent)
        if pc:
            pc.set_graph(graph)
            pc.generate(True)
        return True
    except Exception as e:
        gc.warn("PCG ambient scatter skipped (%s); see pcg_hooks.json" % e)
        return False


def thing(kind_name):
    return getattr(unreal.StarkThing, kind_name)


def gameplay_actor(o, L):
    """One Stark World Engine actor for a gameplay object (NPC, enemy, item, crystal, chest, door, portal, checkpoint)."""
    t, x, y, z, yaw = o["t"], o["x"], o.get("y", 0.0), o["z"], o.get("yaw", 0.0)
    folder = "Stark/" + gc.kind(t) + "s"
    label = "GS_%s_%03d" % (gc.kind(t), o["i"]) + ("_" + o["id"] if o.get("id") else "")
    tags = ["GS_Class_" + t, "GS_Gameplay"]
    if t == "npc":
        a = gc.spawn(unreal.StarkNpcCharacter, gc.cm(x, y + 0.95, z), gc.rot(yaw), label, folder, tags, True)
        c = gc.comp(a, unreal.StarkNpcComponent)
        if c:
            for k, v in (("npc_id", o.get("id", "")), ("dialog_id", o.get("dialog", "")),
                         ("display_name", o.get("name", "Villager")), ("fallback_line", o.get("text", "")),
                         ("object_index", int(o["i"]))):
                gc.setp(c, k, v)
        gc.setp(a, "color", gc.lin(gc_rgb(o.get("col") or "#d99a4d")))
        return a
    if t == "enemy":
        s = float(o.get("s", 1.0)) * (1.8 if o.get("kind") == "boss" else 1.0)
        a = gc.spawn(unreal.StarkEnemyCharacter, gc.cm(x, y + 0.65 * s, z), gc.rot(yaw), label, folder, tags, True)
        for k, v in (("kind", o.get("kind", "grunt")), ("enemy_id", o.get("id", "")), ("age", o.get("age", "adult")),
                     ("display_name", o.get("name", "")),
                     ("hp_override", int(o.get("hp", 0))), ("patrol", float(o.get("patrol", 5.0))),
                     ("size_scale", float(o.get("s", 1.0))), ("object_index", int(o["i"]))):
            gc.setp(a, k, v)
        return a
    kinds = {"item": "ITEM", "crystal": "CRYSTAL", "chest": "CHEST", "door": "DOOR", "portal": "PORTAL",
             "checkpoint": "CHECKPOINT"}
    a = gc.spawn(unreal.StarkInteractable, gc.cm(x, y, z), gc.rot(yaw), label, folder, tags, True)
    gc.setp(a, "kind", thing(kinds[t]))
    gc.setp(a, "object_index", int(o["i"]))
    if t in ("item", "chest"):
        gc.setp(a, "item", o.get("item", ""))
        gc.setp(a, "count", int(o.get("n", 1)))
    if t == "item":
        it = (GAME.get("items") or {}).get(o.get("item", ""), {})
        gc.setp(a, "color", gc.lin(gc_rgb(it.get("col") or "#88ffcc")))
    if t == "crystal":
        gc.setp(a, "color", gc.lin((L.get("palette") or {}).get("fx", [0.5, 1.0, 0.8])))
    if t == "chest":
        gc.setp(a, "gold", int(o.get("gold", 0)))
    if t == "door":
        gc.setp(a, "key_item", o.get("key", "key"))
    if t == "portal":
        gc.setp(a, "target", int(o.get("to", -1)))
        gc.setp(a, "lock_quest", o.get("lock", ""))
    art = ART.get(t)
    if art is not None and gc.class_name(art) == "StaticMesh":
        gc.setp(a, "art_mesh", art)
    try:
        a.refresh_visuals()
    except Exception:
        pass
    return a


def gc_rgb(h):
    h = str(h).lstrip("#")
    try:
        return [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    except ValueError:
        return [0.8, 0.8, 0.8]


def build_gameplay(plan, L):
    n = 0
    for o in L.get("objects", []):
        if o["t"] in ("tree", "rock", "ruin", "lamp", "house"):
            continue
        try:
            gameplay_actor(o, L)
            n += 1
        except Exception as e:
            gc.warn("gameplay %s %s failed: %s" % (o["t"], o["i"], e))
    return n


def build_markers(plan):
    for m in plan.get("markers", []):
        gc.spawn(unreal.TargetPoint, gc.cm(m["x"], m["y"] + 0.5, m["z"]), None, m["label"],
                 "Stark/Markers/" + m["kind"] + "s", ["GS_Marker", "GS_" + m["kind"]])


def build_lights(plan, runtime_lights):
    n = 0
    for Lt in plan["lights"]:
        if runtime_lights and (Lt["label"].startswith("GS_CrystalLight") or Lt["label"].startswith("GS_PortalLight")):
            continue                                      # Stark World Engine actors carry their own glow
        try:
            cls = unreal.SpotLight if Lt["type"] == "spot" else unreal.PointLight
            r = gc.rot(0.0, -90.0) if Lt["type"] == "spot" else None
            a = gc.spawn(cls, gc.cm(Lt["x"], Lt["y"], Lt["z"]), r, Lt["label"], "Stark/Lights", ["GS_Light"])
            c = gc.comp(a, unreal.PointLightComponent) or gc.comp(a, unreal.SpotLightComponent)
            if not c:
                continue
            c.set_mobility(unreal.ComponentMobility.MOVABLE)
            gc.setp(c, "intensity_units", unreal.LightUnits.CANDELAS)
            gc.setp(c, "intensity", float(Lt["intensity"]))
            c.set_light_color(gc.lin(Lt["color"]))
            gc.setp(c, "attenuation_radius", float(Lt["radius"]) * 100.0)
            gc.setp(c, "source_radius", 8.0)
            gc.setp(c, "cast_shadows", bool(Lt["shadows"]))
            n += 1
        except Exception as e:
            gc.warn("light %s failed: %s" % (Lt.get("label"), e))
    return n


def build_start_and_cameras(plan):
    sp = plan["spawn"]
    gc.spawn(unreal.PlayerStart, gc.cm(sp["x"], sp["y"] + 1.2, sp["z"]), gc.rot(45.0), "GS_PlayerStart", "Stark",
             (), True)
    for c in plan["cameras"]:
        pos, tgt = gc.cm(*c["pos"]), gc.cm(*c["target"])
        r = unreal.MathLibrary.find_look_at_rotation(pos, tgt)
        cam = gc.spawn(unreal.CineCameraActor, pos, r, c["name"], "Stark/Cameras", ["GS_Shot"])
        cc = cam.get_cine_camera_component()
        gc.setp(cc, "current_focal_length", float(c["focal"]))
        gc.setp(cc, "current_aperture", float(c["aperture"]))
        try:
            fs = cc.get_editor_property("focus_settings")
            fs.set_editor_property("focus_method", unreal.CameraFocusMethod.MANUAL)
            d = math.sqrt(sum((a - b) ** 2 for a, b in zip(c["pos"], c["target"]))) * 100.0
            fs.set_editor_property("manual_focus_distance", d)
            cc.set_editor_property("focus_settings", fs)
        except Exception as e:
            gc.warn("camera focus: %s" % e)


def build_2d(plan, L):
    """A 2D chapter as a 2.5D side-scroller map: tiles are 2 m blocks on the X/Z plane (Y = 0)."""
    tiles = L.get("tiles") or []
    rows = len(tiles)
    li = L["index"]
    sky_stack(plan if "look" in plan else dict(plan, look=PLANS[0]["look"]))
    cube = unreal.EditorAssetLibrary.load_asset(gc.SHAPES["cube"])
    mats = gc.proxy_materials({"materials": {"tile_%02d" % li: (L.get("palette") or {}).get("ground", [0.4, 0.5, 0.3]),
                                             "back_%02d" % li: (L.get("palette") or {}).get("fog", [0.1, 0.2, 0.3]),
                                             "water2d": [0.1, 0.5, 0.6]}, "emissive": {}})
    solid, water, counts = [], [], {}
    for row, line in enumerate(tiles):
        for col, ch in enumerate(line):
            loc = gc.tile_cm(col, row, rows)
            key = "%d:t%d_%d" % (li, col, row)
            if ch == "#":
                solid.append((loc, gc.rot(), unreal.Vector(2.0, 4.0, 2.0)))
            elif ch == "~":
                water.append((loc, gc.rot(), unreal.Vector(2.0, 4.0, 2.0)))
            elif ch == "P":
                gc.spawn(unreal.PlayerStart, unreal.Vector(loc.x, 0.0, loc.z + 40.0), None, "GS_PlayerStart", "Stark", (), True)
            elif RUNTIME and ch in "ohkD^CGX":
                kinds = {"o": "CRYSTAL", "h": "ITEM", "k": "ITEM", "D": "DOOR", "^": "HAZARD", "C": "CHECKPOINT",
                         "G": "EXIT", "X": "EXIT"}
                a = gc.spawn(unreal.StarkInteractable, unreal.Vector(loc.x, 0.0, loc.z - 100.0), None,
                             "GS_Tile_%s_%d_%d" % (kinds[ch], col, row), "Stark/Tiles", ["GS_Class_tile"], True)
                gc.setp(a, "kind", thing(kinds[ch]))
                gc.setp(a, "gone_key_override", key)
                if ch in "hk":
                    gc.setp(a, "item", "potion" if ch == "h" else "key")
                if ch == "o":
                    gc.setp(a, "color", gc.lin((L.get("palette") or {}).get("fx", [0.7, 1.0, 1.0])))
                try:
                    a.refresh_visuals()
                except Exception:
                    pass
                counts[ch] = counts.get(ch, 0) + 1
            elif RUNTIME and ch in "eaB":
                k = {"e": "grunt", "a": "archer", "B": "boss"}[ch]
                a = gc.spawn(unreal.StarkEnemyCharacter, unreal.Vector(loc.x, 0.0, loc.z), None,
                             "GS_Tile_Enemy_%d_%d" % (col, row), "Stark/Enemies", ["GS_Class_enemy"], True)
                for kk, v in (("kind", k), ("gone_key_override", key), ("side_view", True)):
                    gc.setp(a, kk, v)
                counts[ch] = counts.get(ch, 0) + 1
    if solid:
        gc.place("tile", "Solid", cube, mats["tile_%02d" % li], solid, ["GS_Tile_%d" % i for i in range(len(solid))],
                 ["GS_Class_tile"])
    if water:
        gc.place("water", "Water2D", cube, mats["water2d"], water, ["GS_Water_%d" % i for i in range(len(water))],
                 ["GS_Class_water"], collision=False)
    width = max((len(r) for r in tiles), default=10) * gc.TILE
    back = gc.spawn(unreal.StaticMeshActor, unreal.Vector(width * 0.5, 2500.0, rows * gc.TILE * 0.5), None,
                    "GS_Backdrop", "Stark/Sky", ["GS_Backdrop"])
    back.static_mesh_component.set_static_mesh(cube)
    back.static_mesh_component.set_material(0, mats["back_%02d" % li])
    back.set_actor_scale3d(unreal.Vector(width / 100.0 + 40.0, 1.0, rows * gc.TILE / 100.0 + 30.0))
    if RUNTIME:
        for o in L.get("objects", []):
            if o["t"] == "npc":
                loc = gc.tile_cm(float(o["x"]), float(o["z"]), rows)
                a = gc.spawn(unreal.StarkNpcCharacter, unreal.Vector(loc.x, 0.0, loc.z), None,
                             "GS_NPC_%03d_%s" % (o["i"], o.get("id", "")), "Stark/NPCs", ["GS_Class_npc"], True)
                c = gc.comp(a, unreal.StarkNpcComponent)
                if c:
                    for k, v in (("npc_id", o.get("id", "")), ("dialog_id", o.get("dialog", "")),
                                 ("display_name", o.get("name", "Villager")), ("object_index", int(o["i"]))):
                        gc.setp(c, k, v)
    return {"solid": len(solid), "water": len(water), "things": counts}


def build_level(plan):
    li = plan["level"]
    L = GAME["levels"][li] if li < len(GAME.get("levels", [])) else {"index": li, "objects": []}
    open_level(plan["map"])
    info = {"level": li, "map": plan["map"], "mode": plan.get("mode", "3d"), "name": plan.get("name")}
    if plan.get("mode") == "2d":
        info.update(build_2d(plan, L))
        post_process(dict(plan, look=plan.get("look") or PLANS[0].get("look")))
    else:
        mats = gc.proxy_materials(plan)
        sky_stack(plan)
        post_process(plan)
        shaped, terrain = build_terrain(plan, L, mats)
        info["terrain"] = terrain
        info["water"] = build_water(plan, L)
        build_scenery(plan, mats, shaped, RUNTIME)
        info["pcg"] = build_ambient(plan, L) if shaped else False
        info["gameplay_actors"] = build_gameplay(plan, L) if RUNTIME else 0
        build_markers(plan)
        info["lights"] = build_lights(plan, RUNTIME)
        build_start_and_cameras(plan)
        info["landscape_file"] = gc.heightmap_png(plan) if shaped and terrain != "landscape" else None
        if plan["weather"]["type"] in ("rain", "snow", "storm"):
            gc.warn("level %d weather '%s': fog/clouds/grading set; add a Niagara rain/snow system for particles"
                    % (li, plan["weather"]["type"]))
    gc.save_all()
    gc.REPORT["levels"].append(info)
    gc.log("built %s (%s)" % (plan["map"], info))
    return info


def main():
    global ART
    if not RUNTIME:
        gc.warn("Stark World Engine Runtime plugin is not loaded: levels are built as scenery + markers; gameplay needs the "
                "plugin (README_UE5.md)")
    try:
        ART = gc.import_art()
    except Exception as e:
        gc.warn("art import: %s" % e)
        ART = {}
    for plan in PLANS:
        try:
            build_level(plan)
        except Exception as e:
            gc.warn("level %s failed: %r" % (plan.get("level"), e))
    sounds = {}
    try:
        sounds = gc.build_sounds(GAME)
    except Exception as e:
        gc.warn("sounds: %s" % e)
    data_asset = None
    try:
        data_asset = gc.build_data_assets(GAME, sounds)
    except Exception as e:
        gc.warn("data assets: %s" % e)
    swapped = {}
    for plan in PLANS:
        if plan.get("mode") == "2d":
            continue
        try:
            gc.level_sub().load_level(plan["map"])
            swapped[plan["map"]] = gc.swap_all(plan)
            gc.save_all()
        except Exception as e:
            gc.warn("swap %s: %s" % (plan["map"], e))
    try:
        gc.level_sub().load_level(PLANS[0]["map"])
    except Exception:
        pass
    ok = not [w for w in gc.REPORT["warnings"] if "failed" in w]
    gc.write_report({"ok": ok, "runtime": RUNTIME, "maps": [p["map"] for p in PLANS], "swapped": swapped,
                     "data_asset": str(data_asset.get_path_name()) if data_asset is not None else None,
                     "sounds": sorted(sounds), "art": sorted(ART), "seconds": round(time.time() - T0, 1),
                     "game": GAME.get("title")})
    gc.write_state(ok)
    gc.log("Stark World Engine build done: %d level(s), %d warning(s), %.1fs" % (len(PLANS), len(gc.REPORT["warnings"]),
                                                                    time.time() - T0))


try:
    main()
except Exception as _e:
    import traceback
    gc.write_report({"ok": False, "error": repr(_e), "trace": traceback.format_exc()})
    unreal.log_error("[StarkWorldEngine] build failed: %r" % (_e,))
    raise
