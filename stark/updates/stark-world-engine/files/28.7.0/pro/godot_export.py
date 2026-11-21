"""Stark World Engine -> Godot 4 bridge (Godot 4.2+, verified headless with Godot 4.7.2).

What it makes: a Godot 4 project that plays the whole Stark World Engine game - every level (3D levels and 2D chapters),
quests, branching dialogue, items and equipment, XP and abilities, enemies with the browser engine's AI, chests,
locked doors, portals, checkpoints and save slots - through the Stark World Engine Runtime addon (godot_addon/stark_runtime:
GDScript autoloads StarkGame, StarkInventory, StarkQuests, StarkDialogue, StarkSave, StarkUI). Every level is
a normal editable scene (main.tscn = level 1, levels/level_NN.tscn): terrain from the world's height field with a
splat shader, scenery as MultiMeshes with Inspector art slots, NPC / enemy / item / chest / door / portal /
checkpoint nodes you can move, retune or re-skin with glTF art.

Public API (studio_app delegates here):
    godot_project(world, library=None) -> {relative path: str} (bytes only for library art files)
    find_godot(...) / pick_godot(...)  -> installed Godot 4 editors, newest first
    open_in_godot(world, out_dir, ...) -> writes the project and opens it in the Godot editor (or plays it)
    open_godot_action(world, export_dir, tier) -> (http_status, body) for the studio's POST route
    download_godot(dest_dir, consent=True, ...) -> official Godot build (SHA-512 checked); only with the buyer's OK
"""
import hashlib
import io
import json
import math
import os
import re
import subprocess
import sys
import zipfile

import ue5_export as core

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON_DIR = os.path.join(HERE, 'godot_addon', 'stark_runtime')
MIN_GODOT = (4, 2)
RUNTIME = 'res://addons/stark_runtime'
AUTOLOADS = (('StarkGame', 'core/game.gd'), ('StarkInventory', 'core/inventory.gd'),
             ('StarkQuests', 'core/quests.gd'), ('StarkDialogue', 'core/dialogue.gd'),
             ('StarkSave', 'core/save.gd'), ('StarkUI', 'ui/stark_ui.gd'))
ENTITY_SCRIPTS = {'npc': 'actors/npc_3d.gd', 'enemy': 'actors/enemy_3d.gd', 'item': 'actors/pickup_3d.gd',
                  'crystal': 'actors/pickup_3d.gd', 'chest': 'actors/chest_3d.gd', 'door': 'actors/door_3d.gd',
                  'portal': 'actors/portal_3d.gd', 'checkpoint': 'actors/checkpoint_3d.gd'}
ENTITY_TYPES = {'npc': 'CharacterBody3D', 'enemy': 'CharacterBody3D', 'item': 'Area3D', 'crystal': 'Area3D',
                'chest': 'StaticBody3D', 'door': 'StaticBody3D', 'portal': 'Node3D', 'checkpoint': 'Node3D'}


def _c(rgb, a=1.0):
    return 'Color(%.3f, %.3f, %.3f, %.3f)' % (rgb[0], rgb[1], rgb[2], a)


def _mix(a, b, t):
    return [a[i] + (b[i] - a[i]) * t for i in range(3)]


def _norm(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def basis_facing(z_axis):
    """Godot basis whose +Z is z_axis (so the node looks along -z_axis). -> 9 numbers, row-major."""
    z = _norm(z_axis)
    up = [0.0, 1.0, 0.0] if abs(z[1]) < 0.99 else [1.0, 0.0, 0.0]
    x = _norm(_cross(up, z))
    y = _cross(z, x)
    return [x[0], y[0], z[0], x[1], y[1], z[1], x[2], y[2], z[2]]


def basis_yaw(rad):
    """Rotation about +Y (Godot convention: +x turns toward -z for positive angles), row-major."""
    c, s = math.cos(rad), math.sin(rad)
    return [c, 0.0, s, 0.0, 1.0, 0.0, -s, 0.0, c]


def xform(basis, origin):
    return 'Transform3D(' + ', '.join('%.4f' % v for v in list(basis) + list(origin)) + ')'


IDENT = [1, 0, 0, 0, 1, 0, 0, 0, 1]


def _node_name(s):
    return re.sub(r'[.:@/"%\s\\]+', '_', str(s))[:48] or 'Node'


def _q(s):
    """Godot text-resource string literal."""
    return json.dumps(str(s), ensure_ascii=False)


def _col_hex(h, a=1.0):
    return _c(core._rgb(h, [0.85, 0.6, 0.3]), a)


class _Scene:
    """Tiny .tscn writer: ext resources, sub resources, nodes; load_steps kept consistent."""

    def __init__(self):
        self.ext, self.subs, self.nodes = [], [], []

    def res(self, typ, path):
        for t, p, i in self.ext:
            if p == path:
                return i
        rid = '%d_%s' % (len(self.ext) + 1, re.sub(r'[^a-z0-9]+', '', os.path.basename(path).lower())[:10] or 'r')
        self.ext.append((typ, path, rid))
        return rid

    def render(self):
        ext = ''.join(f'[ext_resource type="{t}" path="{p}" id="{i}"]\n' for t, p, i in self.ext)
        return (f'[gd_scene load_steps={len(self.ext) + len(self.subs) + 1} format=3]\n\n' + ext + '\n'
                + '\n'.join(self.subs) + '\n' + '\n'.join(self.nodes))


def _art_type(path):
    ext = os.path.splitext(path)[1].lower()
    return 'PackedScene' if ext in core.MODEL_EXT else 'Texture2D'


def level_scene_path(li):
    return 'res://main.tscn' if li == 0 else 'res://levels/level_%02d.tscn' % li


def _level_file(li):
    return 'main.tscn' if li == 0 else 'levels/level_%02d.tscn' % li


# ---------------------------------------------------------------- project
def godot_project(world, library=None):
    """-> {relative path: text} for a Godot 4 project that plays the whole campaign (3D levels and 2D chapters).
    library: asset library folder / manifest (glTF 2.0 + JSON); its art replaces proxies (files come back as bytes)."""
    world = core.gate(world)                         # child-safety gate (stark_systems), fails closed
    name = re.sub(r'["\\\r\n]', '', str(world.get('name', 'World')))
    if not os.path.isdir(ADDON_DIR):
        raise RuntimeError('Stark World Engine Runtime addon missing next to godot_export.py (godot_addon/stark_runtime)')
    game = core.game_data(world)
    art = {'format': 'stark-assets/1', 'assets': [], 'classes': {}}
    files = {}
    credits = None
    if library is not None:
        afiles, art, credits = core.asset_files(world, library, dest='assets')
        files.update(afiles)
    for L in game['levels']:
        L['scene'] = level_scene_path(L['index'])
    game['assets'] = art
    by_id = {a['id']: a for a in art['assets']}
    classes = {cls: by_id[aid] for cls, aid in art.get('classes', {}).items() if aid in by_id}
    plans = core.build_plans(world)
    three_d = any(L['mode'] == '3d' for L in game['levels'])
    files.update({
        'project.godot': _project_file(name, game, three_d),
        'stark_game.json': json.dumps(game, separators=(',', ':')),
        'world.json': json.dumps(world, indent=1),
        'player.gd': ('extends "res://addons/stark_runtime/actors/player_3d.gd"\n'
                      '## Your hero. Stark World Engine writes this file once; add your own moves, animations or camera '
                      'tweaks here.\n'),
        'README_GODOT.md': _readme(world, game),
        'CREDITS.md': credits or ('# Art credits\n\n- No third-party art: every model is a Stark World Engine proxy shape. Free '
                                  'CC0 sources: Poly Haven, Kenney, Quaternius, ambientCG (check each licence).\n'),
        '.gitignore': '.godot/\n',
        'VERIFY_IN_GODOT.bat': _verify_bat(),
    })
    for L, plan in zip(game['levels'], plans):
        files[_level_file(L['index'])] = (_scene_2d(L) if L['mode'] == '2d'
                                         else _scene_3d(world, game, L, plan, classes))
    for rel, data in core._read_tree(ADDON_DIR, binary_ok=False).items():
        files[f'addons/stark_runtime/{rel}'] = data
    return files


def _project_file(name, game, three_d):
    base = core.BASE[game['levels'][0]['mood']]
    s = (f'; Engine configuration file.\nconfig_version=5\n\n[application]\n\nconfig/name="{name}"\n'
         'run/main_scene="res://main.tscn"\nconfig/features=PackedStringArray("4.2", "Forward Plus")\n\n'
         '[autoload]\n\n' + ''.join(f'{n}="*{RUNTIME}/{p}"\n' for n, p in AUTOLOADS) +
         '\n[display]\n\nwindow/size/viewport_width=1280\nwindow/size/viewport_height=720\n'
         'window/stretch/mode="canvas_items"\nwindow/stretch/aspect="expand"\n\n'
         '[editor_plugins]\n\nenabled=PackedStringArray("res://addons/stark_runtime/plugin.cfg")\n\n'
         '[layer_names]\n\n3d_physics/layer_1="world"\n3d_physics/layer_2="player"\n3d_physics/layer_3="enemies"\n'
         '3d_physics/layer_4="npcs"\n3d_physics/layer_5="triggers"\n\n'
         '[rendering]\n\n'
         f'environment/defaults/default_clear_color={_c(base["fog"])}\n'
         'renderer/rendering_method="forward_plus"\n')
    if three_d:
        s += ('anti_aliasing/quality/msaa_3d=2\n'
              'anti_aliasing/quality/use_taa=true\n'
              'lights_and_shadows/directional_shadow/size=8192\n'
              'lights_and_shadows/directional_shadow/soft_shadow_filter_quality=4\n'
              'lights_and_shadows/positional_shadow/soft_shadow_filter_quality=3\n'
              'environment/volumetric_fog/volume_size=128\n'
              'environment/volumetric_fog/volume_depth=128\n'
              'global_illumination/sdfgi/probe_ray_count=2\n'
              'textures/default_filters/anisotropic_filtering_level=4\n')
    return s


def _environment(sc, plan, L, classes):
    """WorldEnvironment + sun (same look as the original Stark World Engine export: SDFGI, SSAO, volumetric fog, glow)."""
    base, look, sun, weather = plan['base'], plan['look'], plan['sun'], plan['weather']
    wet = weather['type'] in ('rain', 'storm', 'snow', 'fog')
    fog_mul = {'rain': 1.6, 'snow': 1.4, 'fog': 2.2, 'storm': 2.0}.get(weather['type'], 1.0)
    elev = sun['elev'] if sun['night'] else max(sun['elev'], 16.0)
    top = _mix(base['fog'], [0.05, 0.12, 0.35], 0.5) if sun['night'] or sun['elev'] < 10 else \
        _mix(base['fog'], [0.25, 0.45, 0.85], 0.6)
    sky_asset = classes.get('sky')
    if sky_asset:
        rid = sc.res('Texture2D', 'res://' + sky_asset['file'])
        sc.subs.append(f'[sub_resource type="PanoramaSkyMaterial" id="skymat"]\npanorama = ExtResource("{rid}")\n')
    else:
        sc.subs.append('[sub_resource type="ProceduralSkyMaterial" id="skymat"]\n'
                       f'sky_top_color = {_c(top)}\nsky_horizon_color = {_c(base["fog"])}\n'
                       f'ground_bottom_color = {_c([c * 0.4 for c in base["ground"]])}\n'
                       f'ground_horizon_color = {_c(base["fog"])}\nsun_angle_max = 25.0\n'
                       f'sky_energy_multiplier = {0.6 if sun["night"] else 1.0:.2f}\n')
    sc.subs.append('[sub_resource type="Sky" id="sky"]\nsky_material = SubResource("skymat")\n')
    sat = look['sat'] * (0.85 if wet else 1.0)
    fog_d = look['fog'] * 0.12 * fog_mul
    vfog_d = look['fog'] * (0.6 if wet or sun['night'] else 0.45) * fog_mul
    sc.subs.append(
        '[sub_resource type="Environment" id="env"]\n'
        'background_mode = 2\nsky = SubResource("sky")\n'
        'ambient_light_source = 3\nreflected_light_source = 2\n'
        f'ambient_light_color = {_c(base["amb"])}\n'
        'tonemap_mode = 3\ntonemap_exposure = %.2f\ntonemap_white = 6.0\n' % (1.0 + look['ev_bias'] * 0.3)
        + 'ssao_enabled = true\nssao_intensity = 1.5\n'
        'sdfgi_enabled = true\nsdfgi_use_occlusion = true\nsdfgi_read_sky_light = true\n'
        'glow_enabled = true\nglow_intensity = %.2f\nglow_bloom = 0.0\nglow_hdr_threshold = 1.0\n' % look['bloom']
        + f'fog_enabled = true\nfog_light_color = {_c(base["fog"])}\nfog_density = {min(0.008, fog_d):.4f}\n'
        'fog_aerial_perspective = 0.4\nfog_sky_affect = 0.4\n'
        f'volumetric_fog_enabled = true\nvolumetric_fog_density = {min(0.03, vfog_d):.4f}\n'
        f'volumetric_fog_albedo = {_c(_mix(base["fog"], [1, 1, 1], 0.6))}\n'
        'volumetric_fog_anisotropy = 0.6\nvolumetric_fog_length = 96.0\n'
        f'adjustment_enabled = true\nadjustment_contrast = {look["con"]:.3f}\nadjustment_saturation = {sat:.3f}\n')
    sc.subs.append('[sub_resource type="CameraAttributesPractical" id="cam_attr"]\nauto_exposure_enabled = true\n'
                   'auto_exposure_scale = 0.4\nauto_exposure_speed = 0.8\n')
    e, az = math.radians(elev), math.radians(sun['azim'])
    to_sun = [-math.cos(e) * math.cos(az), math.sin(e), -math.cos(e) * math.sin(az)]
    energy = max(0.15, min(2.5, sun['lux'] / 4.0)) * (0.6 if weather['type'] in ('rain', 'storm') else 1.0)
    sc.nodes.append('[node name="Env" type="WorldEnvironment" parent="."]\nenvironment = SubResource("env")\n'
                    'camera_attributes = SubResource("cam_attr")\n')
    sc.nodes.append(f'[node name="Sun" type="DirectionalLight3D" parent="."]\n'
                    f'transform = {xform(basis_facing(to_sun), [0, 30, 0])}\nlight_color = {_c(sun["color"])}\n'
                    f'light_energy = {energy:.3f}\nlight_angular_distance = 0.5\nshadow_enabled = true\n'
                    'directional_shadow_mode = 2\ndirectional_shadow_max_distance = 250.0\n')


def _entity_node(sc, o, kind, classes):
    """One gameplay node (NPC, enemy, item, crystal, chest, door, portal, checkpoint) with its properties."""
    rid = sc.res('Script', f'{RUNTIME}/{ENTITY_SCRIPTS[kind]}')
    label = {'npc': 'NPC', 'item': 'Item'}.get(kind, kind.capitalize())
    extra = o.get('id') or o.get('item') or ''
    nm = _node_name(f'{label}_{o["i"]:03d}' + (f'_{extra}' if extra else ''))
    rot = 0.0 if kind in ('npc', 'enemy', 'item', 'crystal') else math.radians(-o.get('yaw', 0.0))
    y = o['y'] + (0.3 if kind in ('npc', 'enemy') else 0.0)
    lines = [f'[node name="{nm}" type="{ENTITY_TYPES[kind]}" parent="Gameplay"]',
             f'transform = {xform(basis_yaw(rot), [o["x"], y, o["z"]])}', f'script = ExtResource("{rid}")',
             f'object_index = {o["i"]}']
    if kind == 'npc':
        lines += [f'npc_id = {_q(o.get("id", ""))}', f'dialog_id = {_q(o.get("dialog", ""))}', f'age = {_q(o.get("age", "adult"))}',
                  f'display_name = {_q(o.get("name", "Villager"))}', f'color = {_col_hex(o.get("col") or "#d99a4d")}']
        if o.get('text'):
            lines.append(f'line = {_q(o["text"])}')
    elif kind == 'enemy':
        lines += [f'kind = {_q(o.get("kind", "grunt"))}', f'enemy_id = {_q(o.get("id", ""))}', f'age = {_q(o.get("age", "adult"))}',
                  f'display_name = {_q(o.get("name", ""))}', f'hp_override = {int(o.get("hp", 0))}',
                  f'patrol = {float(o.get("patrol", 5.0)):.2f}', f'size_scale = {float(o.get("s", 1.0)):.3f}']
        if o.get('col'):
            lines.append(f'color = {_col_hex(o["col"])}')
    elif kind in ('item', 'crystal'):
        lines += [f'item = {_q("crystal" if kind == "crystal" else o.get("item", "potion"))}',
                  f'count = {int(o.get("n", 1))}', f'crystal = {"true" if kind == "crystal" else "false"}']
    elif kind == 'chest':
        lines += [f'item = {_q(o.get("item", ""))}', f'count = {int(o.get("n", 1))}', f'gold = {int(o.get("gold", 0))}']
    elif kind == 'door':
        lines.append(f'key_item = {_q(o.get("key", "key"))}')
    elif kind == 'portal':
        lines += [f'target = {int(o.get("to", -1))}', f'lock_quest = {_q(o.get("lock", ""))}']
    a = classes.get('enemy:' + str(o.get('kind'))) if kind == 'enemy' else None
    a = a or classes.get(kind)
    if a and a['kind'] == 'model':
        lines += [f'visual_scene = ExtResource("{sc.res("PackedScene", "res://" + a["file"])}")',
                  f'visual_scale = {float(a.get("scale", 1.0)):.3f}']
    sc.nodes.append('\n'.join(lines) + '\n')


def _scene_3d(world, game, L, plan, classes):
    sc = _Scene()
    li = L['index']
    level = sc.res('Script', f'{RUNTIME}/world/level_3d.gd')
    sc.nodes.append(f'[node name="Level" type="Node3D"]\nscript = ExtResource("{level}")\nlevel_index = {li}\n')
    _environment(sc, plan, L, classes)
    t_rid = sc.res('Script', f'{RUNTIME}/world/terrain.gd')
    terr = [f'[node name="Terrain" type="StaticBody3D" parent="."]', f'script = ExtResource("{t_rid}")',
            f'level_index = {li}']
    for cls, slot in (('ground', 'layer_grass'), ('ground_rock', 'layer_rock'), ('ground_sand', 'layer_sand'),
                      ('ground_snow', 'layer_snow')):
        a = classes.get(cls)
        if a and a['kind'] == 'texture':
            terr.append(f'{slot} = ExtResource("{sc.res("Texture2D", "res://" + a["file"])}")')
    sc.nodes.append('\n'.join(terr) + '\n')
    s_rid = sc.res('Script', f'{RUNTIME}/world/scatter.gd')
    scat = [f'[node name="Scenery" type="Node3D" parent="."]', f'script = ExtResource("{s_rid}")', f'level_index = {li}']
    for cls in core.SCENERY_KINDS + ('grass',):
        a = classes.get(cls)
        if a and a['kind'] == 'model':
            scat.append(f'{cls}_scene = ExtResource("{sc.res("PackedScene", "res://" + a["file"])}")')
            if cls != 'grass':
                scat.append(f'{cls}_scale = {float(a.get("scale", 1.0)):.3f}')
    sc.nodes.append('\n'.join(scat) + '\n')
    if L['water'] is not None:
        w_rid = sc.res('Script', f'{RUNTIME}/world/water.gd')
        wcol = _mix(L['palette']['water'], plan['base']['fog'], 0.25)
        sc.nodes.append(f'[node name="Water" type="MeshInstance3D" parent="."]\n'
                        f'transform = {xform(IDENT, [0, round(float(L["water"]), 3), 0])}\nscript = ExtResource("{w_rid}")\n'
                        f'water_color = {_c(wcol, 0.82)}\nsize = {L["terrain"]["span"]:.1f}\n')
    sc.nodes.append('[node name="Gameplay" type="Node3D" parent="."]\n')
    for o in L['objects']:
        t = o['t']
        if t in core.SCENERY_KINDS:
            continue
        kind = 'crystal' if t == 'crystal' else t
        if kind in ENTITY_SCRIPTS:
            _entity_node(sc, o, kind, classes)
    sp = L['spawn']
    p_rid = sc.res('Script', 'res://player.gd')
    hero = [f'[node name="Player" type="CharacterBody3D" parent="."]',
            f'transform = {xform(IDENT, [sp["x"], sp["y"] + 0.3, sp["z"]])}', f'script = ExtResource("{p_rid}")']
    a = classes.get('player')
    if a and a['kind'] == 'model':
        hero += [f'visual_scene = ExtResource("{sc.res("PackedScene", "res://" + a["file"])}")',
                 f'visual_scale = {float(a.get("scale", 1.0)):.3f}']
    sc.nodes.append('\n'.join(hero) + '\n')
    sc.nodes.append('[node name="Shots" type="Node3D" parent="."]\n')
    for c in plan['cameras']:
        fwd = [c['target'][i] - c['pos'][i] for i in range(3)]
        fov = 2 * math.degrees(math.atan(12.0 / c['focal']))
        sc.nodes.append(f'[node name="{_node_name(c["name"])}" type="Camera3D" parent="Shots"]\n'
                        f'transform = {xform(basis_facing([-v for v in fwd]), c["pos"])}\nfov = {fov:.2f}\n')
    if plan['markers']:
        sc.nodes.append('[node name="Markers" type="Node3D" parent="."]\n')
        used = set()
        for m in plan['markers']:
            n = _node_name(m['label'])
            while n in used:
                n += '_'
            used.add(n)
            sc.nodes.append(f'[node name="{n}" type="Marker3D" parent="Markers"]\n'
                            f'transform = {xform(IDENT, [m["x"], m["y"] + 0.5, m["z"]])}\n'
                            f'metadata/kind = "{m["kind"]}"\nmetadata/gs_name = {json.dumps(m["name"])}\n')
    return sc.render()


def _scene_2d(L):
    sc = _Scene()
    rid = sc.res('Script', f'{RUNTIME}/world/level_2d.gd')
    tiles = ', '.join(_q(r) for r in L.get('tiles', []))
    sc.nodes.append(f'[node name="Level" type="Node2D"]\nscript = ExtResource("{rid}")\nlevel_index = {L["index"]}\n'
                    f'tiles = PackedStringArray({tiles})\n')
    return sc.render()


def _verify_bat():
    return ('@echo off\r\nrem Stark World Engine: plays this game headless with a scripted bot (every quest, every level) and\r\n'
            'rem prints PASS/FAIL. Needs Godot 4.2+ (set GODOT to godot.exe if it is not found).\r\nsetlocal\r\n'
            'set "G=%GODOT%"\r\nif not defined G for /f "delims=" %%i in (\'where godot 2^>nul\') do set "G=%%i"\r\n'
            'if not defined G for /r "%LOCALAPPDATA%\\Microsoft\\WinGet\\Packages" %%i in (Godot_v4*_console.exe) do set "G=%%i"\r\n'
            'if not defined G (echo Godot 4 not found. Set GODOT to godot.exe & pause & exit /b 1)\r\n'
            '"%G%" --headless --path "%~dp0." --import\r\n'
            '"%G%" --headless --path "%~dp0." --fixed-fps 60 --script res://addons/stark_runtime/tests/autoplay.gd '
            '-- --stark-no-title --stark-save-dir="%TEMP%\\stark_verify_saves"\r\n'
            'echo Exit code %ERRORLEVEL% (0 = PASS)\r\npause\r\n')


def _guide_text():
    p = os.path.join(HERE, 'godot_addon', 'FROM_STARK_TO_GODOT4.md')
    try:
        with open(p, encoding='utf-8') as f:
            return f.read()
    except OSError:
        return ''


def _readme(world, game):
    nl = len(game['levels'])
    n2 = sum(1 for L in game['levels'] if L['mode'] == '2d')
    return f"""# {world.get('name', 'World')} - Godot 4 project

Exported by Stark World Engine {core._version()}: {nl} level(s){f' ({n2} 2D)' if n2 else ''}, {len(game['quests'])} quest(s), {len(game['dialogs'])} dialogue(s), {len(game['npcs'])} named NPC(s).
Runs on the free Godot 4.2+ engine (MIT licence) with the Stark World Engine Runtime addon included.

## Play it
Godot 4.2 or newer (Forward+ renderer, needs a Vulkan/D3D12-capable GPU): Import > select `project.godot` >
Run (F5). WASD move, Space jump, J or left click attack, E talk / open / unlock, 1-4 pick an answer, H potion,
Shift dash, K whirl, F bolt, Z/C or right-mouse drag turn the camera, L quests, I bag, Esc menu (save slots).

`VERIFY_IN_GODOT.bat` plays the whole game headless with a bot (every quest, every level, save + load) and prints
PASS or FAIL - the same check Stark World Engine runs before shipping this exporter.

## What carries over
Every level with its terrain, water, mood, weather and time of day; every tree, rock, ruin, lamp and house where you
put them; NPCs with their dialogue trees; enemies with their kind, health and patrol; items, chests, locked doors,
portals (with quest locks) and checkpoints; quests, rewards, XP/levels, abilities, difficulty and save slots.
2D chapters play as the same tile platformer as in the studio.

{_guide_text()}"""


# ---------------------------------------------------------------- Godot discovery + launch
def _godot_version(exe, run=None):
    m = re.search(r'(\d+)\.(\d+)(?:\.(\d+))?', os.path.basename(exe).replace('Godot_v', ''))
    if m and os.path.basename(exe).lower().startswith('godot_v'):
        return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))
    try:
        out = (run or subprocess.run)([exe, '--version'], capture_output=True, text=True, timeout=20)
        m = re.search(r'(\d+)\.(\d+)(?:\.(\d+))?', out.stdout or '')
        return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)) if m else None
    except (OSError, subprocess.SubprocessError, AttributeError):
        return None


def find_godot(env=None, config_path=None, roots=None, run=None):
    """-> [{'exe', 'console', 'version', 'vt', 'source'}] newest first. Looks at STARK_GODOT_EDITOR / GODOT env vars,
    engine_paths.json {"godot_editor": "..."}, winget, Program Files, Steam, scoop, our own download folder and PATH."""
    env = os.environ if env is None else env
    cands = []
    for k in ('STARK_GODOT_EDITOR', 'GODOT'):
        if env.get(k):
            cands.append((env[k], 'override'))
    cfg = config_path or os.path.join(HERE, 'engine_paths.json')
    if os.path.isfile(cfg):
        try:
            with open(cfg, encoding='utf-8') as f:
                g = json.load(f).get('godot_editor')
            if g:
                cands.append((g, 'override'))
        except (OSError, ValueError, AttributeError):
            pass
    la = env.get('LOCALAPPDATA') or ''
    pf = env.get('ProgramFiles') or r'C:\Program Files'
    dirs = roots if roots is not None else [
        os.path.join(la, 'Microsoft', 'WinGet', 'Packages'), os.path.join(la, 'StarkWorldEngine', 'godot'),
        os.path.join(pf, 'Godot'), os.path.join(pf, 'Godot Engine'),
        os.path.join(env.get('ProgramFiles(x86)') or r'C:\Program Files (x86)', 'Steam', 'steamapps', 'common', 'Godot Engine'),
        os.path.join(env.get('USERPROFILE') or '', 'scoop', 'apps', 'godot', 'current')]
    for d in dirs:
        if not d or not os.path.isdir(d):
            continue
        for dp, dns, fns in os.walk(d):
            if dp.count(os.sep) - d.count(os.sep) > 3:
                dns[:] = []
            for fn in fns:
                low = fn.lower()
                if low.startswith('godot') and low.endswith('.exe') and 'mono' not in low:
                    cands.append((os.path.join(dp, fn), 'installed'))
    if roots is None:
        for p in (env.get('PATH') or '').split(os.pathsep):
            for exe in ('godot.exe', 'godot4.exe', 'godot'):
                fp = os.path.join(p, exe)
                if p and os.path.isfile(fp):
                    cands.append((fp, 'path'))
    out, seen = [], set()
    for exe, src in cands:
        key = os.path.normcase(os.path.abspath(exe))
        if key in seen or not os.path.isfile(exe):
            continue
        if '_console' in os.path.basename(exe).lower():
            gui = exe.replace('_console', '')
            if os.path.isfile(gui):
                continue                                 # the GUI build next to it is listed instead
        seen.add(key)
        v = _godot_version(exe, run)
        if not v or v[0] != 4:
            continue
        console = exe.replace('.exe', '_console.exe') if exe.endswith('.exe') else exe
        out.append({'exe': exe, 'console': console if os.path.isfile(console) else exe, 'version': '%d.%d.%d' % v,
                    'vt': v, 'source': src})
    out.sort(key=lambda e: (e['source'] == 'override', e['vt']), reverse=True)
    return out


def pick_godot(found=None, **kw):
    found = find_godot(**kw) if found is None else found
    ok = [e for e in found if e['vt'][:2] >= MIN_GODOT]
    return ok[0] if ok else None


GODOT_GUIDE = ('Godot 4 is not installed (it is free, open source, MIT licence, no account needed).\n'
               'Option 1: click "Download Godot for me" in Stark World Engine (official build from godotengine.org\'s GitHub '
               'releases, checked against the official SHA-512 list, about 60 MB, only after you agree).\n'
               'Option 2: install it yourself from https://godotengine.org/download (or: winget install GodotEngine.GodotEngine),\n'
               'then click "Open in Godot" again - Stark World Engine finds it by itself.')


def open_in_godot(world, out_dir, editor=None, mode='editor', launch=True, popen=None, library=None, **find_kw):
    """Write the Godot project to out_dir and open it: mode 'editor' (Godot editor, press F5) or 'play' (runs it).
    -> {'ok': True, 'project', 'exe', 'version', 'argv', 'pid'} or {'ok': False, 'error', 'guide'}."""
    if editor:
        if not os.path.isfile(editor):
            return {'ok': False, 'error': 'editor_missing', 'guide': f'{editor} does not exist.\n' + GODOT_GUIDE}
        v = _godot_version(editor) or (4, 2, 0)
        found = {'exe': editor, 'version': '%d.%d.%d' % v}
    else:
        found = pick_godot(**find_kw)
        if not found:
            return {'ok': False, 'error': 'godot_not_found', 'guide': GODOT_GUIDE, 'download': True}
    files = godot_project(world, library=library)
    os.makedirs(out_dir, exist_ok=True)
    core.write_project(files, out_dir, preserve=('player.gd',))
    proj = os.path.abspath(out_dir)
    argv = [found['exe'], '--path', proj] + (['-e'] if mode == 'editor' else [])
    res = {'ok': True, 'project': os.path.join(proj, 'project.godot'), 'exe': found['exe'], 'version': found['version'],
           'argv': argv, 'pid': None, 'launched': False, 'mode': mode}
    if launch:
        kw = {'cwd': proj, 'close_fds': True, 'stdin': subprocess.DEVNULL, 'stdout': subprocess.DEVNULL,
              'stderr': subprocess.DEVNULL}
        if sys.platform == 'win32':
            kw['creationflags'] = 0x00000008 | 0x00000200     # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        try:
            p = (popen or subprocess.Popen)(argv, **kw)
            res.update(pid=getattr(p, 'pid', None), launched=True)
        except OSError as e:
            return {'ok': False, 'error': 'launch_failed', 'guide': f'Could not start Godot: {e}'}
    return res


def open_godot_action(world, export_dir, tier='pro', **kw):
    """Pure hook for a POST endpoint -> (http_status, json_body). 402 tier, 404 no Godot (body has 'guide' and
    'download': true so the UI can offer download_godot), 200 opened."""
    if tier not in ('pro', 'studio'):
        return 402, {'ok': False, 'error': 'tier', 'guide': 'Open in Godot is part of the Pro and Studio tiers.'}
    try:
        world = core.gate(world)
    except ValueError as e:
        return 400, {'ok': False, 'error': 'child_safety', 'guide': str(e)}
    res = open_in_godot(world, export_dir, **kw)
    if res['ok']:
        return 200, res
    return {'godot_not_found': 404, 'editor_missing': 404, 'child_safety': 400}.get(res['error'], 500), res


# ---------------------------------------------------------------- optional: download the official Godot build
GODOT_VERSION = '4.7.2'
GODOT_RELEASES = 'https://github.com/godotengine/godot/releases/download'


def godot_download_urls(version=GODOT_VERSION):
    tag = f'{version}-stable'
    name = f'Godot_v{tag}_win64.exe.zip'
    return {'zip': f'{GODOT_RELEASES}/{tag}/{name}', 'sums': f'{GODOT_RELEASES}/{tag}/SHA512-SUMS.txt', 'name': name}


def download_godot(dest_dir, consent=False, version=GODOT_VERSION, opener=None, max_bytes=300 * 1024 * 1024):
    """Download the official Godot editor (MIT licence) from godotengine's GitHub releases, verify it against the
    release's official SHA512-SUMS.txt and unpack it into dest_dir. Requires consent=True (the buyer clicked
    "Download Godot for me"). opener(url) -> bytes is injectable for tests. -> {'ok', 'exe' | 'error'}."""
    if consent is not True:
        return {'ok': False, 'error': 'consent_required',
                'guide': 'Stark World Engine only downloads Godot after you agree (button "Download Godot for me").'}
    u = godot_download_urls(version)
    if opener is None:
        import urllib.request

        def opener(url):
            if not url.startswith(GODOT_RELEASES + '/'):          # official release downloads only
                raise ValueError('refusing a non-official download URL')
            with urllib.request.urlopen(url, timeout=120) as r:
                return r.read(max_bytes + 1)
    try:
        sums = opener(u['sums']).decode('utf-8', 'replace')
        want = None
        for line in sums.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[-1].lstrip('*') == u['name']:
                want = parts[0].lower()
        if not want or not re.fullmatch(r'[0-9a-f]{128}', want):
            return {'ok': False, 'error': 'no_checksum', 'guide': f'{u["name"]} is not listed in the official checksums.'}
        data = opener(u['zip'])
        if len(data) > max_bytes:
            return {'ok': False, 'error': 'too_big'}
        if hashlib.sha512(data).hexdigest() != want:
            return {'ok': False, 'error': 'checksum_mismatch', 'guide': 'The download does not match the official '
                                                                         'checksum; nothing was installed.'}
        os.makedirs(dest_dir, exist_ok=True)
        exe = None
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for info in z.infolist():
                base = os.path.basename(info.filename)
                if not base or '..' in info.filename.replace('\\', '/').split('/') or not base.lower().endswith('.exe'):
                    continue
                target = os.path.join(dest_dir, base)
                with z.open(info) as src, open(target, 'wb') as dst:
                    dst.write(src.read())
                if '_console' not in base:
                    exe = target
        if not exe:
            return {'ok': False, 'error': 'no_exe_in_zip'}
        return {'ok': True, 'exe': exe, 'version': version, 'sha512': want}
    except Exception as e:  # noqa: BLE001 - network / zip problems become a friendly status
        return {'ok': False, 'error': 'download_failed', 'guide': f'Could not download Godot: {e}'}
