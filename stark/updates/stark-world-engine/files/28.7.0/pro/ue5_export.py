"""Stark World Engine -> Unreal Engine 5 bridge (UE 5.4+).

What it makes: a UE5 project that carries the whole Stark World Engine game - every level (3D, and 2D chapters as 2.5D
side-scroller maps), quest, dialogue line, item, NPC, enemy, chest, door, portal, checkpoint and save slot - and is
playable in Play-In-Editor through the Stark World Engine Runtime plugin (ue5_plugin/StarkRuntime: data assets, a game-instance
subsystem for quests / dialogue / inventory / saves, an NPC component, an enemy AI controller). The editor Python
scripts (ue5_plugin/editor_scripts) build every level by themselves on the first editor start (registered as a
PythonScriptPlugin startup script): Landscape with an auto-material, instanced foliage, Water, Lumen, Virtual Shadow
Maps, Nanite, Sky Atmosphere, Volumetric Clouds, Exponential Height Fog, PCG scatter hooks, gameplay actors, imported
glTF art and the data assets. Fab / Megascans / MetaHuman stay optional upgrade slots (proxy_swap_map.csv,
metahuman_slots.csv).

Public API (studio_app delegates here):
    ue5_project(world, engine='5.4', with_binaries=False, library=None) -> {relative path: str | bytes}
        (str only unless with_binaries / library add binary files)
    game_data(world)                     -> engine-neutral game description (godot_export uses it too)
    build_plan(world, gameplay=False, level=0) -> engine-neutral visual plan of one level
    find_unreal(...) / pick_unreal(...)  -> installed UE5 editors, newest first
    open_in_unreal(world, out_dir, ...)  -> writes the project (+ prebuilt runtime) and launches the editor
    open_unreal_action(world, export_dir, tier) -> (http_status, body) for the studio's POST route

Honest status: the UE5 side is checked statically (JSON, C++ structure/macro checks, Python compile, runs against a
fake `unreal` module). It has NOT been opened in a real UE5 install yet; see ue5_plugin/VERIFY_UE5.md.
Nothing from Epic / Fab / Quixel is bundled or downloaded.
"""
import hashlib
import json
import math
import os
import re
import subprocess
import sys

MIN_UE = (5, 4)
TERRAIN_RES = 129
HALF = 48.0                 # browser engine: default half extent of a 3D level (metres)
MARGIN = 32.0               # exported terrain extends past the play area so the horizon is not a cliff
OBJ_KINDS = ('tree', 'ruin', 'rock', 'crystal', 'enemy', 'lamp')
GAMEPLAY_KINDS = ('house', 'npc', 'item', 'chest', 'door', 'portal', 'checkpoint')
UE_KINDS = OBJ_KINDS + GAMEPLAY_KINDS
OBJ_TYPES = UE_KINDS
SCENERY_KINDS = ('tree', 'rock', 'ruin', 'lamp', 'house')
STEP_TYPES = ('collect', 'defeat', 'talk', 'reach', 'escort')
ITEM_KINDS = ('quest', 'consumable', 'key', 'equip', 'treasure')
ENEMY_KINDS = ('grunt', 'archer', 'brute', 'wisp', 'boss')
HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.join(HERE, 'ue5_plugin')
RUNTIME_SRC = os.path.join(PLUGIN_DIR, 'StarkRuntime')
EDITOR_SCRIPTS = os.path.join(PLUGIN_DIR, 'editor_scripts')
PREBUILT_DIR = os.path.join(PLUGIN_DIR, 'prebuilt')
MAP_ROOT = '/Game/Stark/Maps'

# Mood base colours (sRGB 0..1), same values as studio_app.MOOD_PY so the module stands alone.
BASE = {
    'Bioluminescent Twilight': {'fog': [0.06, 0.09, 0.2], 'sun': [0.5, 0.6, 1.0], 'amb': [0.18, 0.2, 0.35],
                                'ground': [0.08, 0.16, 0.14], 'leaf': [0.1, 0.7, 0.6], 'stone': [0.3, 0.32, 0.4],
                                'fx': [0.5, 1.0, 0.8]},
    'Alpine Sunset': {'fog': [0.93, 0.62, 0.45], 'sun': [1.0, 0.7, 0.45], 'amb': [0.35, 0.3, 0.35],
                      'ground': [0.38, 0.5, 0.28], 'leaf': [0.13, 0.38, 0.2], 'stone': [0.55, 0.5, 0.5],
                      'fx': [1.0, 0.85, 0.4]},
    'Sub-Zero Aurora': {'fog': [0.05, 0.1, 0.16], 'sun': [0.6, 0.8, 1.0], 'amb': [0.25, 0.3, 0.4],
                        'ground': [0.85, 0.9, 0.95], 'leaf': [0.15, 0.3, 0.3], 'stone': [0.6, 0.7, 0.8],
                        'fx': [0.4, 1.0, 0.7]},
    'Crimson Citadel': {'fog': [0.3, 0.07, 0.06], 'sun': [1.0, 0.45, 0.3], 'amb': [0.3, 0.12, 0.12],
                        'ground': [0.22, 0.1, 0.09], 'leaf': [0.4, 0.08, 0.06], 'stone': [0.45, 0.2, 0.18],
                        'fx': [1.0, 0.45, 0.15]},
    'Sunken Ruins': {'fog': [0.03, 0.3, 0.38], 'sun': [0.5, 0.95, 0.9], 'amb': [0.15, 0.3, 0.32],
                     'ground': [0.55, 0.5, 0.35], 'leaf': [0.1, 0.5, 0.35], 'stone': [0.4, 0.5, 0.48],
                     'fx': [0.7, 1.0, 1.0]},
}
# Browser mood extras (studio_app ENGINE_JS MOODS): weather particles and water colour per mood.
MOOD_FX = {'Bioluminescent Twilight': 'fireflies', 'Alpine Sunset': 'pollen', 'Sub-Zero Aurora': 'snow',
           'Crimson Citadel': 'embers', 'Sunken Ruins': 'bubbles'}
MOOD_WATER = {'Bioluminescent Twilight': [0.05, 0.25, 0.35], 'Alpine Sunset': [0.15, 0.4, 0.55],
              'Sub-Zero Aurora': [0.1, 0.3, 0.45], 'Crimson Citadel': [0.35, 0.08, 0.05],
              'Sunken Ruins': [0.05, 0.4, 0.45]}

# Browser engine mood palettes (studio_app ENGINE_JS MOODS): leaf variants, sky, water, glow colour.
MOOD_PALETTE = {
    'Bioluminescent Twilight': {'fog': [0.06, 0.09, 0.2], 'sun': [0.5, 0.6, 1.0], 'amb': [0.18, 0.2, 0.35],
                                'ground': [0.08, 0.16, 0.14], 'stone': [0.3, 0.32, 0.4], 'fx': [0.5, 1.0, 0.8],
                                'leaf': [[0.1, 0.7, 0.6], [0.3, 0.4, 0.9], [0.6, 0.2, 0.8]], 'sky2': [0.02, 0.02, 0.08],
                                'zen': [0.02, 0.03, 0.12], 'water': [0.05, 0.25, 0.35], 'night0': 0.55},
    'Alpine Sunset': {'fog': [0.93, 0.62, 0.45], 'sun': [1.0, 0.7, 0.45], 'amb': [0.35, 0.3, 0.35],
                      'ground': [0.38, 0.5, 0.28], 'stone': [0.55, 0.5, 0.5], 'fx': [1.0, 0.85, 0.4],
                      'leaf': [[0.13, 0.38, 0.2], [0.2, 0.45, 0.25], [0.1, 0.3, 0.18]], 'sky2': [0.45, 0.35, 0.6],
                      'zen': [0.25, 0.35, 0.7], 'water': [0.15, 0.4, 0.55], 'night0': 0.0},
    'Sub-Zero Aurora': {'fog': [0.05, 0.1, 0.16], 'sun': [0.6, 0.8, 1.0], 'amb': [0.25, 0.3, 0.4],
                        'ground': [0.85, 0.9, 0.95], 'stone': [0.6, 0.7, 0.8], 'fx': [1.0, 1.0, 1.0],
                        'leaf': [[0.15, 0.3, 0.3], [0.2, 0.35, 0.4], [0.8, 0.9, 1.0]], 'sky2': [0.0, 0.02, 0.06],
                        'zen': [0.01, 0.03, 0.09], 'water': [0.1, 0.3, 0.45], 'night0': 0.6},
    'Crimson Citadel': {'fog': [0.3, 0.07, 0.06], 'sun': [1.0, 0.45, 0.3], 'amb': [0.3, 0.12, 0.12],
                        'ground': [0.22, 0.1, 0.09], 'stone': [0.45, 0.2, 0.18], 'fx': [1.0, 0.45, 0.15],
                        'leaf': [[0.4, 0.08, 0.06], [0.25, 0.1, 0.08], [0.55, 0.2, 0.1]], 'sky2': [0.08, 0.0, 0.02],
                        'zen': [0.12, 0.02, 0.04], 'water': [0.35, 0.08, 0.05], 'night0': 0.3},
    'Sunken Ruins': {'fog': [0.03, 0.3, 0.38], 'sun': [0.5, 0.95, 0.9], 'amb': [0.15, 0.3, 0.32],
                     'ground': [0.55, 0.5, 0.35], 'stone': [0.4, 0.5, 0.48], 'fx': [0.7, 1.0, 1.0],
                     'leaf': [[0.1, 0.5, 0.35], [0.2, 0.6, 0.3], [0.6, 0.3, 0.4]], 'sky2': [0.0, 0.08, 0.15],
                     'zen': [0.0, 0.12, 0.22], 'water': [0.05, 0.4, 0.45], 'night0': 0.15},
}


def palette(mood, amp=1.0):
    p = json.loads(json.dumps(MOOD_PALETTE.get(mood, MOOD_PALETTE[DEFAULT_MOOD])))
    g = p['ground']
    p['sand'] = [round(0.78 * 0.65 + g[0] * 0.35, 3), round(0.7 * 0.65 + g[1] * 0.35, 3), round(0.5 * 0.65 + g[2] * 0.35, 3)]
    p['snow'] = [0.92, 0.94, 0.97]
    p['snow_line'] = round(3.5 + 2.0 * amp, 2) if mood in ('Alpine Sunset', 'Sub-Zero Aurora') else 1000.0
    p['trunk'] = [0.36, 0.23, 0.14]
    return p


# Per-mood "look": sun (elevation/azimuth deg, lux), fog, grading, terrain character.
LOOK = {
    'Bioluminescent Twilight': dict(elev=6, azim=235, lux=2.5, sky=1.0, fog=0.045, falloff=0.3, vfog=2.0,
                                    ev_bias=-0.5, ev_min=-4.0, sat=1.15, con=1.08, gain=[0.94, 1.0, 1.08],
                                    vign=0.45, grain=0.08, bloom=0.9, amp=2.0, freq=1 / 30.0, edge=8.0),
    'Alpine Sunset': dict(elev=7, azim=260, lux=8.0, sky=1.0, fog=0.02, falloff=0.12, vfog=0.8, ev_bias=0.0,
                          ev_min=-2.0, sat=1.1, con=1.05, gain=[1.05, 1.0, 0.94], vign=0.35, grain=0.05,
                          bloom=0.7, amp=7.0, freq=1 / 45.0, edge=30.0),
    'Sub-Zero Aurora': dict(elev=4, azim=200, lux=1.8, sky=1.0, fog=0.03, falloff=0.2, vfog=1.2, ev_bias=-0.3,
                            ev_min=-4.0, sat=1.05, con=1.1, gain=[0.93, 1.0, 1.07], vign=0.4, grain=0.07,
                            bloom=1.0, amp=4.0, freq=1 / 40.0, edge=22.0),
    'Crimson Citadel': dict(elev=12, azim=300, lux=6.0, sky=1.0, fog=0.04, falloff=0.2, vfog=1.6, ev_bias=-0.2,
                            ev_min=-3.0, sat=1.12, con=1.12, gain=[1.08, 0.96, 0.92], vign=0.5, grain=0.07,
                            bloom=0.8, amp=3.5, freq=1 / 35.0, edge=18.0),
    'Sunken Ruins': dict(elev=55, azim=150, lux=9.0, sky=1.0, fog=0.05, falloff=0.25, vfog=2.2, ev_bias=0.2,
                         ev_min=-2.0, sat=1.1, con=1.04, gain=[0.94, 1.03, 1.03], vign=0.35, grain=0.05,
                         bloom=0.8, amp=2.5, freq=1 / 28.0, edge=12.0),
}
DEFAULT_MOOD = 'Bioluminescent Twilight'

# ---------------------------------------------------------------- gameplay tables (mirror studio_app ENGINE_JS)
# tests/test_exporters.py compares these with the browser engine source so the engines never drift apart.
ITEMS = {
    'crystal': {'name': 'Glow Crystal', 'kind': 'quest', 'col': '#7fffd0', 'desc': 'A humming shard of light.'},
    'potion': {'name': 'Healing Draught', 'kind': 'consumable', 'heal': 3, 'col': '#ff5577',
               'desc': 'Restores 3 HP. Hotkey H.'},
    'elixir': {'name': 'Grand Elixir', 'kind': 'consumable', 'heal': 99, 'col': '#ffcc33', 'desc': 'Restores all HP.'},
    'key': {'name': 'Old Key', 'kind': 'key', 'col': '#ffd84a', 'desc': 'Opens a locked door.'},
    'gem': {'name': 'Star Gem', 'kind': 'treasure', 'gold': 25, 'col': '#c78bff', 'desc': 'Worth 25 gold.'},
    'wood_sword': {'name': 'Driftwood Sword', 'kind': 'equip', 'slot': 'weapon', 'atk': 1, 'col': '#a0703a',
                   'desc': '+1 attack.'},
    'iron_blade': {'name': 'Iron Blade', 'kind': 'equip', 'slot': 'weapon', 'atk': 2, 'col': '#c8d0d8',
                   'desc': '+2 attack.'},
    'moon_blade': {'name': 'Moonsilver Blade', 'kind': 'equip', 'slot': 'weapon', 'atk': 4, 'col': '#b0e8ff',
                   'desc': '+4 attack.'},
    'leather': {'name': 'Leather Vest', 'kind': 'equip', 'slot': 'armor', 'def': 1, 'col': '#8a5a33',
                'desc': '+1 defence.'},
    'warden_plate': {'name': 'Warden Plate', 'kind': 'equip', 'slot': 'armor', 'def': 2, 'hp': 2, 'col': '#7a8aa0',
                     'desc': '+2 defence, +2 max HP.'},
    'swift_boots': {'name': 'Swift Boots', 'kind': 'equip', 'slot': 'boots', 'speed': 1.6, 'col': '#5fd3b5',
                    'desc': 'Run faster.'},
    'ember_charm': {'name': 'Ember Charm', 'kind': 'equip', 'slot': 'charm', 'atk': 1, 'hp': 1, 'col': '#ff7a33',
                    'desc': '+1 attack, +1 max HP.'},
}
ENEMY = {
    'grunt': {'name': 'Bog Slime', 'hp': 3, 'dmg': 1, 'speed': 2.6, 'sight': 14, 'xp': 10, 'gold': 2,
              'col': [0.75, 0.2, 0.35]},
    'archer': {'name': 'Thorn Archer', 'hp': 2, 'dmg': 1, 'speed': 2.3, 'sight': 18, 'xp': 15, 'gold': 3,
               'ranged': True, 'col': [0.35, 0.6, 0.25]},
    'brute': {'name': 'Stone Brute', 'hp': 8, 'dmg': 2, 'speed': 1.7, 'sight': 12, 'xp': 30, 'gold': 6,
              'col': [0.5, 0.45, 0.42]},
    'wisp': {'name': 'Bog Wisp', 'hp': 2, 'dmg': 1, 'speed': 3.6, 'sight': 16, 'xp': 12, 'gold': 2, 'fly': True,
             'col': [0.5, 0.8, 1.0]},
    'boss': {'name': 'Ancient Warden', 'hp': 40, 'dmg': 2, 'speed': 2.3, 'sight': 26, 'xp': 200, 'gold': 60,
             'boss': True, 'col': [0.55, 0.15, 0.6]},
}
DIFF = {'easy': {'hp': 0.7, 'dmg': 0.5}, 'normal': {'hp': 1, 'dmg': 1}, 'hard': {'hp': 1.5, 'dmg': 1.5}}
ABILITIES = [{'lvl': 2, 'key': 'Shift', 'name': 'Dash', 'cd': 1.2}, {'lvl': 3, 'key': 'K', 'name': 'Whirl', 'cd': 4},
             {'lvl': 4, 'key': 'F', 'name': 'Star Bolt', 'cd': 1.5}]
SFX = {
    'jump': {'wave': 'square', 'freq': 260, 'slide': 1.4, 'dur': 0.18, 'decay': 1.5, 'vol': 0.3, 'noise': 0},
    'coin': {'wave': 'square', 'freq': 880, 'slide': 0.6, 'dur': 0.2, 'decay': 1, 'vol': 0.25, 'noise': 0},
    'hit': {'wave': 'noise', 'freq': 200, 'slide': -0.5, 'dur': 0.22, 'decay': 2.5, 'vol': 0.55, 'noise': 0.7},
    'laser': {'wave': 'saw', 'freq': 1200, 'slide': -0.8, 'dur': 0.25, 'decay': 2, 'vol': 0.3, 'noise': 0},
    'boom': {'wave': 'noise', 'freq': 90, 'slide': -0.6, 'dur': 0.6, 'decay': 3, 'vol': 0.7, 'noise': 1},
    'power': {'wave': 'sine', 'freq': 330, 'slide': 2, 'dur': 0.45, 'decay': 1, 'vol': 0.4, 'noise': 0},
    'quest': {'wave': 'sine', 'freq': 520, 'slide': 0.5, 'dur': 0.5, 'decay': 0.8, 'vol': 0.35, 'noise': 0},
    'levelup': {'wave': 'square', 'freq': 392, 'slide': 1.0, 'dur': 0.7, 'decay': 0.7, 'vol': 0.3, 'noise': 0},
    'door': {'wave': 'saw', 'freq': 110, 'slide': -0.3, 'dur': 0.4, 'decay': 1.5, 'vol': 0.35, 'noise': 0.3},
    'portal': {'wave': 'sine', 'freq': 180, 'slide': 3, 'dur': 0.9, 'decay': 1, 'vol': 0.4, 'noise': 0.1},
    'talk': {'wave': 'square', 'freq': 660, 'slide': 0.1, 'dur': 0.06, 'decay': 1, 'vol': 0.15, 'noise': 0},
    'magic': {'wave': 'saw', 'freq': 700, 'slide': -0.5, 'dur': 0.35, 'decay': 1.5, 'vol': 0.25, 'noise': 0.1},
}
RULES = {'xp_base': 40, 'xp_pow': 1.45, 'interact_radius': 2.8, 'death_gold_keep': 0.9, 'crit_chance': 0.15,
         'walk_speed': 7.0, 'jump_speed': 8.5, 'gravity': 24.0, 'attack_reach': 2.5, 'attack_cooldown': 0.28,
         'deep_water': 1.3, 'step_up': 1.2}

# Proxy shapes (meters; size = full extent x, up, z; off = part centre relative to the object's ground point).
PROXIES = {
    'tree': [dict(part='Trunk', shape='cylinder', size=[0.45, 2.6, 0.45], off=[0, 1.3, 0], mat='trunk'),
             dict(part='Canopy', shape='cone', size=[2.6, 3.6, 2.6], off=[0, 3.6, 0], mat='leaf'),
             dict(part='Crown', shape='cone', size=[1.9, 2.8, 1.9], off=[0, 5.0, 0], mat='leaf')],
    'ruin': [dict(part='PillarA', shape='cube', size=[0.9, 3.4, 0.9], off=[-1.3, 1.7, 0], mat='stone'),
             dict(part='PillarB', shape='cube', size=[0.9, 2.1, 0.9], off=[1.3, 1.05, 0], mat='stone'),
             dict(part='Slab', shape='cube', size=[3.4, 0.5, 1.0], off=[0.2, 0.25, 1.4], mat='stone', tilt=6)],
    'rock': [dict(part='Boulder', shape='sphere', size=[1.8, 1.1, 1.4], off=[0, 0.35, 0], mat='rock'),
             dict(part='Pebble', shape='sphere', size=[0.8, 0.6, 0.7], off=[0.9, 0.2, 0.5], mat='rock')],
    'crystal': [dict(part='Shard', shape='cone', size=[0.45, 1.5, 0.45], off=[0, 0.75, 0], mat='crystal'),
                dict(part='ShardB', shape='cone', size=[0.3, 0.9, 0.3], off=[0.35, 0.4, 0.15], mat='crystal', tilt=18),
                dict(part='ShardC', shape='cone', size=[0.25, 0.7, 0.25], off=[-0.3, 0.3, -0.1], mat='crystal',
                     tilt=-22)],
    'enemy': [dict(part='Body', shape='sphere', size=[1.0, 1.2, 1.0], off=[0, 0.6, 0], mat='enemy')],
    'lamp': [dict(part='Post', shape='cylinder', size=[0.14, 2.4, 0.14], off=[0, 1.2, 0], mat='metal'),
             dict(part='Glow', shape='sphere', size=[0.42, 0.42, 0.42], off=[0, 2.55, 0], mat='glow')],
}
EMISSIVE = {'crystal': 6.0, 'glow': 12.0}

# UE5 stand-ins for gameplay objects (same conventions as PROXIES; first part = the object's main actor).
GAMEPLAY_PROXIES = {
    'house': [dict(part='Walls', shape='cube', size=[4.0, 2.6, 3.4], off=[0, 1.3, 0], mat='wall'),
              dict(part='Roof', shape='cone', size=[5.6, 2.0, 5.0], off=[0, 3.6, 0], mat='roof'),
              dict(part='Door', shape='cube', size=[0.9, 1.6, 0.1], off=[0, 0.8, 1.72], mat='trunk')],
    'npc': [dict(part='Body', shape='cylinder', size=[0.6, 1.0, 0.6], off=[0, 0.8, 0], mat='npc'),
            dict(part='CapLow', shape='sphere', size=[0.6, 0.6, 0.6], off=[0, 0.3, 0], mat='npc'),
            dict(part='CapHigh', shape='sphere', size=[0.6, 0.6, 0.6], off=[0, 1.3, 0], mat='skin')],
    'item': [dict(part='Gem', shape='sphere', size=[0.3, 0.45, 0.3], off=[0, 0.7, 0], mat='gem')],
    'chest': [dict(part='Box', shape='cube', size=[0.9, 0.55, 0.6], off=[0, 0.28, 0], mat='trunk'),
              dict(part='Band', shape='cube', size=[0.95, 0.12, 0.65], off=[0, 0.5, 0], mat='gold')],
    'door': [dict(part='Leaf', shape='cube', size=[2.6, 2.8, 0.3], off=[0, 1.4, 0], mat='trunk'),
             dict(part='JambL', shape='cube', size=[0.6, 3.0, 0.7], off=[-1.6, 1.5, 0], mat='stone'),
             dict(part='JambR', shape='cube', size=[0.6, 3.0, 0.7], off=[1.6, 1.5, 0], mat='stone'),
             dict(part='Lintel', shape='cube', size=[3.9, 0.5, 0.8], off=[0, 3.25, 0], mat='stone')],
    'portal': [dict(part='Veil', shape='cube', size=[2.6, 3.8, 0.06], off=[0, 1.95, 0], mat='veil'),
               dict(part='PillarL', shape='cube', size=[0.6, 4.0, 0.6], off=[-1.6, 2.0, 0], mat='stone'),
               dict(part='PillarR', shape='cube', size=[0.6, 4.0, 0.6], off=[1.6, 2.0, 0], mat='stone'),
               dict(part='Lintel', shape='cube', size=[3.8, 0.6, 0.7], off=[0, 4.2, 0], mat='stone')],
    'checkpoint': [dict(part='Pole', shape='cylinder', size=[0.1, 2.6, 0.1], off=[0, 1.3, 0], mat='metal'),
                   dict(part='Flag', shape='cube', size=[0.9, 0.55, 0.04], off=[0.48, 2.25, 0], mat='banner')],
}
GAMEPLAY_MATS = {'wall': [0.78, 0.7, 0.58], 'roof': [0.45, 0.2, 0.15], 'gold': [0.95, 0.75, 0.25],
                 'npc': [0.35, 0.45, 0.7], 'skin': [0.9, 0.72, 0.58], 'banner': [0.8, 0.18, 0.12]}
GAMEPLAY_EMISSIVE = {'gem': 5.0, 'veil': 8.0}

# What the buyer can drop in instead of each proxy (text hints only; nothing is bundled or downloaded).
SWAP_HINTS = {
    'tree': 'Fab: search "Megascans tree" or "European Beech / Black Alder" (Quixel, free with an Epic account)',
    'rock': 'Fab: search "Megascans rock" or "Nordic Beach Boulder" (Quixel, free with an Epic account)',
    'ruin': 'Fab: search "Megascans ruins" or "Medieval ruins pillar" (Quixel / community assets)',
    'crystal': 'Fab: search "crystal cluster" (check each asset licence)',
    'lamp': 'Fab: search "street lantern" or "medieval lamp post"',
    'enemy': 'A skeletal-mesh creature or a Blueprint child of StarkEnemyCharacter (keeps the AI and combat)',
    'house': 'Fab: search "medieval house" or "village cottage" (modular kits work best as a Blueprint)',
    'npc': 'A MetaHuman or any character Blueprint: set it per NPC in metahuman_slots.csv (keeps the dialogue)',
    'item': 'Fab: search "gem pickup" or "potion bottle" (the pickup logic stays on StarkInteractable)',
    'chest': 'Fab: search "treasure chest" or "wooden chest"',
    'door': 'Fab: search "castle gate" or "medieval wooden door"',
    'portal': 'Fab: search "magic portal" or "stone archway" (add a Niagara effect for the veil)',
    'checkpoint': 'Fab: search "banner flag" or "shrine"',
    'ground': 'Fab: search "Megascans surface grass / forest floor / snow"; assign a Material here (not a mesh)',
}


# ---------------------------------------------------------------- child-safety gate (stark_systems, QA-016 / P11)
GATE_MISSING = ('Export needs the child-safety checker (the stark_systems folder is missing or damaged). '
                'Reinstall Stark World Engine.')


def gate(world):
    """Every export passes stark_systems.integration.gate: -> the world with explicit ages and a child_safety stamp,
    or ValueError (ChildSafetyError) saying what to fix. Fails closed: no checker, no export."""
    try:
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        from stark_systems import integration as _gsi
    except Exception as e:  # noqa: BLE001
        raise ValueError(GATE_MISSING) from e
    return _gsi.gate(world)


def minors_of(world):
    cs = world.get('child_safety') if isinstance(world.get('child_safety'), dict) else {}
    return sorted(str(x) for x in (cs.get('minors') or []) if x)


def _age(o):
    return o.get('age') if o.get('age') in ('child', 'teen', 'adult') else 'adult'


# ---------------------------------------------------------------- helpers
def _version():
    try:
        import studio_app
        return studio_app.VERSION
    except Exception:
        return 'dev'


def slug(name):
    return re.sub(r'[^A-Za-z0-9]+', '_', str(name)).strip('_')[:60] or 'World'


def _f(v, default=0.0):
    if isinstance(v, bool):
        return default
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def _i(v, default=0):
    x = _f(v, None)
    return default if x is None else int(x)


def _rgb(v, default):
    """[r,g,b] (0..1 or 0..255) or '#rrggbb' -> [r,g,b] 0..1."""
    if isinstance(v, str) and re.fullmatch(r'#?[0-9a-fA-F]{6}', v.strip()):
        h = v.strip().lstrip('#')
        return [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    if isinstance(v, (list, tuple)) and len(v) >= 3:
        c = [_f(x) for x in v[:3]]
        if max(c) > 1.0:
            c = [x / 255.0 for x in c]
        return [min(1.0, max(0.0, x)) for x in c]
    return list(default)


def _hex(v, default='#dddddd'):
    if v is None or v == '':
        return default
    c = _rgb(v, None) if isinstance(v, (str, list, tuple)) else None
    if c is None:
        return default
    return '#%02x%02x%02x' % tuple(int(round(x * 255)) for x in c)


def _s(v, n=2000):
    return '' if v is None else str(v)[:n]


def mood_of(world):
    m = world.get('mood')
    return m if m in LOOK else DEFAULT_MOOD


def _hash01(ix, iz, seed):
    h = (ix * 73856093) ^ (iz * 19349663) ^ (seed * 83492791)
    h &= 0xffffffff
    h = ((h ^ (h >> 13)) * 1274126177) & 0xffffffff
    h ^= h >> 16
    return (h & 0xffff) / 65535.0


def _vnoise(x, z, seed):
    ix, iz = math.floor(x), math.floor(z)
    fx, fz = x - ix, z - iz
    sx, sz = fx * fx * (3 - 2 * fx), fz * fz * (3 - 2 * fz)
    a, b = _hash01(ix, iz, seed), _hash01(ix + 1, iz, seed)
    c, d = _hash01(ix, iz + 1, seed), _hash01(ix + 1, iz + 1, seed)
    return (a + (b - a) * sx) + ((c + (d - c) * sx) - (a + (b - a) * sx)) * sz


def _fbm(x, z, seed, octaves=4):
    t, amp, norm = 0.0, 1.0, 0.0
    for o in range(octaves):
        t += amp * (_vnoise(x, z, seed + o * 101) * 2 - 1)
        norm += amp
        x, z, amp = x * 2.03, z * 2.03, amp * 0.5
    return t / norm


def _smooth(e0, e1, x):
    t = min(1.0, max(0.0, (x - e0) / (e1 - e0)))
    return t * t * (3 - 2 * t)


def _resample(grid, res):
    """2D list (rows = z) -> flat res*res list via bilinear sampling."""
    rows, cols = len(grid), len(grid[0])
    out = []
    for iz in range(res):
        gz = iz / (res - 1) * (rows - 1)
        z0 = min(int(gz), rows - 2) if rows > 1 else 0
        tz = gz - z0 if rows > 1 else 0.0
        for ix in range(res):
            gx = ix / (res - 1) * (cols - 1)
            x0 = min(int(gx), cols - 2) if cols > 1 else 0
            tx = gx - x0 if cols > 1 else 0.0
            x1, z1 = min(x0 + 1, cols - 1), min(z0 + 1, rows - 1)
            a = grid[z0][x0] + (grid[z0][x1] - grid[z0][x0]) * tx
            b = grid[z1][x0] + (grid[z1][x1] - grid[z1][x0]) * tx
            out.append(a + (b - a) * tz)
    return out


# ---------------------------------------------------------------- terrain
def terrain_h(x, z, seed, amp):
    """Same height field as terrainH() in the browser engine (studio_app ENGINE_JS / studio_app.terrain_h)."""
    s = seed or 0
    v = (math.sin(x * 0.13 + s) * 0.6 + math.cos(z * 0.11 + s * 0.7) * 0.6 + math.sin((x + z) * 0.05 + s) * 0.8
         + math.cos(x * 0.045 - z * 0.06 + s * 0.4) * 0.9 + math.sin(x * 0.29 + z * 0.23 + s * 1.3) * 0.18)
    return amp * v * 0.55


def _user_heightmap(world):
    t = world.get('terrain') if isinstance(world.get('terrain'), dict) else {}
    hm = t.get('heightmap', world.get('heightmap'))
    if not isinstance(hm, list) or not hm:
        return None, t
    if not isinstance(hm[0], list):                         # flat list + width
        w = int(_f(t.get('width'), 0)) or int(round(math.sqrt(len(hm))))
        if w < 2 or len(hm) % w:
            return None, t
        hm = [hm[i:i + w] for i in range(0, len(hm), w)]
    try:
        grid = [[_f(v) for v in row] for row in hm]
    except TypeError:
        return None, t
    if len(grid) < 2 or len({len(r) for r in grid}) != 1 or len(grid[0]) < 2:
        return None, t
    flat = [v for r in grid for v in r]
    if 0.0 <= min(flat) and max(flat) <= 1.0:                # normalised -> meters
        scale = _f(t.get('height', t.get('amplitude', 12.0)), 12.0)
        grid = [[v * scale for v in r] for r in grid]
    return grid, t


def heightfield(world, span, res=TERRAIN_RES):
    """Legacy `terrain: {...}` dict worlds -> (flat res*res heights in metres, row-major [iz*res+ix], source)."""
    grid, t = _user_heightmap(world)
    if grid is not None:
        return [round(v, 3) for v in _resample(grid, res)], 'world'
    look = LOOK[mood_of(world)]
    if t.get('flat'):
        return [0.0] * (res * res), 'flat'
    amp = _f(t.get('amplitude'), look['amp'])
    seed = int(_f(t.get('seed', world.get('seed', 1)), 1))
    half, cell = span / 2.0, span / (res - 1)
    out = []
    for iz in range(res):
        z = -half + iz * cell
        for ix in range(res):
            x = -half + ix * cell
            r = math.hypot(x, z)
            n = _fbm(x * look['freq'], z * look['freq'], seed) * amp
            n *= _smooth(6.0, 16.0, r)                                  # flat spawn plateau
            n += look['edge'] * _smooth(half * 0.62, half, r) ** 2     # horizon hills
            out.append(round(n, 3))
    return out, 'procedural'


def sample(heights, res, span, x, z):
    half, cell = span / 2.0, span / (res - 1)
    gx = min(max((x + half) / cell, 0.0), res - 1.0001)
    gz = min(max((z + half) / cell, 0.0), res - 1.0001)
    x0, z0 = int(gx), int(gz)
    tx, tz = gx - x0, gz - z0
    h = lambda i, j: heights[j * res + i]
    a = h(x0, z0) + (h(x0 + 1, z0) - h(x0, z0)) * tx
    b = h(x0, z0 + 1) + (h(x0 + 1, z0 + 1) - h(x0, z0 + 1)) * tx
    return a + (b - a) * tz


def terrain_spec(L, reach=0.0):
    """-> how a 3D level's ground is shaped. 'stark': the browser height field (exact gameplay match) plus a
    horizon rise outside the play area; 'grid': legacy `terrain: {heightmap ...}` dict worlds (heights listed)."""
    t = L.get('terrain')
    if isinstance(t, dict):
        span = _f(t.get('size'), 0.0) or min(1000.0, max(140.0, 2 * reach + 60.0))
        span = float(math.ceil(span / 8.0) * 8)
        heights, source = heightfield(L, span)
        return {'kind': 'grid', 'span': span, 'res': TERRAIN_RES, 'heights': heights, 'source': source}
    amp = 1.0 if t is None or isinstance(t, (bool, str, list)) else min(6.0, max(0.0, _f(t, 1.0)))
    size = min(128.0, max(24.0, _f(L.get('size'), HALF) or HALF))
    seed = _f(L.get('seed'), 1.0) or 1.0
    return {'kind': 'stark', 'seed': seed, 'amp': amp, 'size': size, 'margin': MARGIN, 'edge': round(6.0 + 2.0 * amp, 3),
            'span': 2.0 * (size + MARGIN), 'source': 'stark'}


def spec_height(spec, x, z):
    if spec['kind'] == 'grid':
        return sample(spec['heights'], spec['res'], spec['span'], x, z)
    h = terrain_h(x, z, spec['seed'], spec['amp'])
    d = max(abs(x), abs(z)) - spec['size']
    if d > 0:
        t = min(1.0, d / spec['margin'])
        h += spec['edge'] * t * t * (3 - 2 * t)
    return h


def spec_grid(spec, res=TERRAIN_RES):
    """-> flat res*res list of heights over the spec's span (row-major [iz*res+ix], x and z from -span/2)."""
    if spec['kind'] == 'grid' and spec['res'] == res:
        return list(spec['heights'])
    span = spec['span']
    half, cell = span / 2.0, span / (res - 1)
    return [round(spec_height(spec, -half + ix * cell, -half + iz * cell), 3) for iz in range(res) for ix in range(res)]


def parse_time_of_day(v):
    """number (0-24), 'HH:MM', or dawn/morning/noon/afternoon/dusk/sunset/night -> hours or None."""
    names = {'dawn': 6.5, 'sunrise': 6.5, 'morning': 9.0, 'noon': 12.0, 'midday': 12.0, 'afternoon': 15.5,
             'dusk': 18.3, 'sunset': 18.0, 'evening': 19.5, 'night': 23.0, 'midnight': 0.0}
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v) % 24.0
    if isinstance(v, str):
        s = v.strip().lower()
        if s in names:
            return names[s]
        m = re.fullmatch(r'(\d{1,2}):(\d{2})', s)
        if m:
            return (int(m.group(1)) + int(m.group(2)) / 60.0) % 24.0
    return None


def _hour_of(world):
    h = parse_time_of_day(world.get('time_of_day'))
    day = world.get('day') if isinstance(world.get('day'), dict) else {}
    if h is None and day.get('start') is not None:
        st = _f(day.get('start'), None)
        h = None if st is None else (st % 1.0) * 24.0
    return h


def sun_for(world):
    mood = mood_of(world)
    look, base = LOOK[mood], BASE[mood]
    h = _hour_of(world)
    sun = {'elev': float(look['elev']), 'azim': float(look['azim']), 'lux': look['lux'], 'color': base['sun'],
           'night': False, 'hour': h}
    if h is not None:
        if 6.0 <= h <= 18.0:
            e = 65.0 * math.sin(math.pi * (h - 6.0) / 12.0)
            sun['elev'] = max(3.0, e)
            sun['azim'] = (90.0 + (h - 6.0) * 15.0) % 360.0
            sun['lux'] = round(2.0 + 8.0 * min(1.0, e / 30.0), 2)
            warm = 1.0 - min(1.0, e / 25.0)
            sun['color'] = [1.0, round(0.95 - 0.3 * warm, 3), round(0.9 - 0.5 * warm, 3)]
        else:                                                            # moonlight
            sun.update(elev=28.0, azim=(90.0 + (h - 18.0) * 15.0) % 360.0, lux=0.35,
                       color=[0.55, 0.65, 1.0], night=True)
    return sun


def _weather(world):
    w = world.get('weather')
    if isinstance(w, str):
        t = w.lower()
        if t == 'auto':
            t = MOOD_FX.get(mood_of(world), 'clear')
        return {'type': t, 'intensity': 0.6}
    if isinstance(w, dict):
        return {'type': str(w.get('type', 'clear')).lower(), 'intensity': _f(w.get('intensity'), 0.6)}
    return {'type': MOOD_FX.get(mood_of(world), 'clear') if 'weather' not in world else 'clear', 'intensity': 0.4}


def _named_points(world, key):
    out = []
    v = world.get(key)
    if isinstance(v, dict):
        v = list(v.values())
    if not isinstance(v, list):
        return out
    for i, it in enumerate(v):
        if not isinstance(it, dict):
            continue
        name = str(it.get('name') or it.get('id') or it.get('title') or f'{key}_{i + 1}')
        pos = it.get('pos') if isinstance(it.get('pos'), (list, tuple)) else None
        x = _f(it.get('x', pos[0] if pos and len(pos) > 0 else 0.0))
        z = _f(it.get('z', pos[-1] if pos and len(pos) > 1 else 0.0))
        out.append({'name': name, 'x': x, 'z': z, 'data': it})
    return out


def _clean(name):
    return re.sub(r'[^A-Za-z0-9_]+', '_', name).strip('_')[:40] or 'Item'


def yaw_of(o, default=0.0):
    """Object heading in plan degrees. Plan yaw turns +x toward +z (Godot uses -yaw about +Y; UE adds 90, see
    editor_scripts/stark_common.py). 'yaw'/'ry' are already plan degrees. studio_app's 'rot' is RADIANS in the
    preview's convention (rotXZ / vertex shader: +x turns toward -z), so plan yaw = -degrees(rot)."""
    if 'yaw' in o or 'ry' in o:
        return _f(o.get('yaw', o.get('ry')), default)
    if 'rot' in o:
        return -math.degrees(_f(o.get('rot'), 0.0))
    return default


# ---------------------------------------------------------------- levels + engine-neutral game data
def levels_of(world):
    """Level 0 is the world itself; world['levels'] are the next chapters (studio_app schema v2)."""
    out = [world]
    for L in world.get('levels') or []:
        if isinstance(L, dict):
            out.append(L)
    return out


def level_info(L, li=0):
    mode = '2d' if L.get('mode') == '2d' else '3d'
    mood = L.get('mood') if L.get('mood') in LOOK else DEFAULT_MOOD
    w = L.get('water')
    water = None if w is None or w == '' or isinstance(w, bool) else _f(w, None)
    day = L.get('day') if isinstance(L.get('day'), dict) else {}
    sp = L.get('spawn') if isinstance(L.get('spawn'), dict) else {}
    has_spawn = sp.get('x') is not None
    weather = L.get('weather') if isinstance(L.get('weather'), str) else 'auto'
    return {'index': li, 'name': _s(L.get('name') or f'Level {li + 1}', 120), 'mode': mode, 'mood': mood,
            'story': _s(L.get('story'), 4000), 'seed': _f(L.get('seed'), 1.0) or 1.0,
            'size': min(128.0, max(24.0, _f(L.get('size'), HALF) or HALF)),
            'water': water, 'weather': weather, 'fx': MOOD_FX[mood] if weather in ('auto', '') else weather,
            'day': {'start': _f(day.get('start'), None) if day.get('start') is not None else None,
                    'len': max(0.0, _f(day.get('len'), 0.0))},
            'spawn': {'x': _f(sp.get('x')) if has_spawn else 0.0, 'z': _f(sp.get('z')) if has_spawn else 0.0}}


def _norm_item(iid, it):
    kind = it.get('kind', 'quest') if it.get('kind', 'quest') in ITEM_KINDS else 'quest'
    return {'id': iid, 'name': _s(it.get('name') or iid.replace('_', ' '), 80), 'kind': kind,
            'slot': _s(it.get('slot'), 16) if kind == 'equip' else '', 'heal': _i(it.get('heal')),
            'atk': _i(it.get('atk')), 'def': _i(it.get('def')), 'hp': _i(it.get('hp')),
            'speed': _f(it.get('speed'), 0.0), 'gold': _i(it.get('gold')), 'col': _hex(it.get('col'), '#dddddd'),
            'desc': _s(it.get('desc'), 300)}


def _norm_cond(c):
    if not isinstance(c, dict):
        return None
    out = {k: str(c[k]) for k in ('has', 'lacks', 'done', 'active', 'notStarted', 'flag') if c.get(k)}
    if c.get('n') is not None:
        out['n'] = max(1, _i(c.get('n'), 1))
    if c.get('minLevel') is not None:
        out['minLevel'] = _i(c.get('minLevel'), 0)
    return out


def _norm_act(a):
    if not isinstance(a, dict):
        return {}
    out = {k: str(a[k]) for k in ('start', 'complete', 'advance', 'take', 'flag') if a.get(k)}
    g = a.get('give')
    give = [str(x) for x in (g if isinstance(g, list) else [g] if g else []) if x]
    if give:
        out['give'] = give
    if a.get('take'):
        out['n'] = max(1, _i(a.get('n'), 1))
    for k in ('gold', 'xp'):
        if _i(a.get(k)):
            out[k] = _i(a.get(k))
    for k in ('heal', 'win'):
        if a.get(k):
            out[k] = True
    return out


def _norm_dialog(did, d):
    nodes = {}
    src = d.get('nodes') if isinstance(d.get('nodes'), dict) else {}
    for nid, n in src.items():
        if not isinstance(n, dict):
            continue
        choices = []
        for c in n.get('choices') or []:
            if isinstance(c, dict):
                choices.append({'text': _s(c.get('text') or '...', 300), 'goto': _s(c.get('goto'), 64),
                                'end': bool(c.get('end')), 'if': _norm_cond(c.get('if')), 'do': _norm_act(c)})
        nodes[str(nid)] = {'speaker': _s(n.get('speaker'), 80), 'text': _s(n.get('text'), 2000),
                           'next': _s(n.get('next'), 64), 'do': _norm_act(n.get('do')), 'choices': choices}
    start = str(d.get('start')) if d.get('start') in nodes else (next(iter(nodes)) if nodes else '')
    branches = [{'if': _norm_cond(b.get('if')), 'node': _s(b.get('node'), 64)}
                for b in d.get('branches') or [] if isinstance(b, dict)]
    return {'id': did, 'start': start, 'branches': branches, 'nodes': nodes}


def _norm_quest(q, li):
    steps = []
    for s in q.get('steps') or []:
        if not isinstance(s, dict) or s.get('type') not in STEP_TYPES:
            continue
        lv = s.get('level')
        steps.append({'type': s['type'], 'item': _s(s.get('item'), 64), 'kind': _s(s.get('kind'), 16),
                      'id': _s(s.get('id'), 64), 'npc': _s(s.get('npc'), 64), 'count': max(1, _i(s.get('count'), 1)),
                      'x': _f(s.get('x')), 'z': _f(s.get('z')), 'r': _f(s.get('r'), 0.0) or 3.0,
                      'label': _s(s.get('label'), 120), 'level': -1 if lv is None or lv == '' else _i(lv, -1),
                      'text': _s(s.get('text'), 300), 'consume': bool(s.get('consume'))})
    rw = q.get('reward') if isinstance(q.get('reward'), dict) else {}
    ri = rw.get('items') if isinstance(rw.get('items'), list) else ([rw['item']] if rw.get('item') else [])
    return {'id': str(q['id']), 'title': _s(q.get('title') or q['id'], 120), 'desc': _s(q.get('desc'), 1000),
            'giver': _s(q.get('giver'), 64), 'auto': bool(q.get('auto')), 'final': bool(q.get('final')),
            'next': _s(q.get('next'), 64), 'level': li, 'steps': steps,
            'reward': {'xp': max(0, _i(rw.get('xp'))), 'gold': max(0, _i(rw.get('gold'))),
                       'items': [str(x) for x in ri if x]}}


def _norm_obj(o, i, mode, spec):
    t = o.get('t')
    x, z = _f(o.get('x'), None), _f(o.get('z'), None)
    if t not in OBJ_TYPES or x is None or z is None:
        return None
    d = {'i': i, 't': t, 'x': round(x, 3), 'z': round(z, 3), 's': round(min(20.0, max(0.05, _f(o.get('s'), 1.0) or 1.0)), 3)}
    if mode == '3d':
        d['y'] = round(spec_height(spec, x, z), 3)
        d['yaw'] = round(yaw_of(o, 0.0) % 360.0, 2)
    if o.get('asset'):
        d['asset'] = _s(o.get('asset'), 64)
    if t in ('npc', 'enemy'):
        d['age'] = _age(o)
    if t == 'enemy':
        d.update(kind=o.get('kind') if o.get('kind') in ENEMY_KINDS else 'grunt', id=_s(o.get('id'), 64),
                 name=_s(o.get('name'), 80), hp=max(0, _i(o.get('hp'))),
                 patrol=5.0 if o.get('patrol') is None else max(0.0, _f(o.get('patrol'), 5.0)),
                 col=_hex(o.get('col'), ''))
    elif t == 'npc':
        d.update(id=_s(o.get('id'), 64), name=_s(o.get('name') or o.get('id') or 'Villager', 80),
                 dialog=_s(o.get('dialog'), 64), col=_hex(o.get('col'), '#d99a4d'), text=_s(o.get('text'), 600))
    elif t == 'item':
        d.update(item=_s(o.get('item') or 'potion', 64), n=max(1, _i(o.get('n'), 1)))
    elif t == 'chest':
        d.update(item=_s(o.get('item'), 64), n=max(1, _i(o.get('n'), 1)), gold=max(0, _i(o.get('gold'))))
    elif t == 'door':
        d.update(key=_s(o.get('key') or 'key', 64))
    elif t == 'portal':
        to = o.get('to')
        d.update(to=-1 if to is None or to == 'next' else _i(to, -1), lock=_s(o.get('lock'), 64))
    if o.get('label'):
        d['label'] = _s(o.get('label'), 80)
    return d


def norm_level(L, li):
    info = level_info(L, li)
    spec = terrain_spec(L, _reach(L)) if info['mode'] == '3d' else None
    objs = [d for d in (_norm_obj(o, i, info['mode'], spec) for i, o in enumerate(L.get('objects') or [])
                        if isinstance(o, dict)) if d]
    out = dict(info, objects=objs, palette=palette(info['mood'], (spec or {}).get('amp', 1.0)))
    if info['mode'] == '2d':
        tiles = L.get('tiles') if isinstance(L.get('tiles'), list) else []
        out['tiles'] = [str(r) for r in tiles if isinstance(r, str)]
    else:
        out['terrain'] = spec
        out['spawn']['y'] = round(spec_height(spec, out['spawn']['x'], out['spawn']['z']), 3)
    return out


def _reach(L):
    objs = [o for o in (L.get('objects') or []) if isinstance(o, dict)]
    return max([abs(_f(o.get('x'))) for o in objs] + [abs(_f(o.get('z'))) for o in objs] + [10.0])


def save_key(world):
    """The browser engine's save-slot fingerprint (Game.prototype.key): same name + same level layout."""
    parts = []
    for L in levels_of(world):
        seed = L.get('seed')
        objs = ','.join(str(o.get('t') if isinstance(o, dict) else 'undefined') + str((o.get('id') if isinstance(o, dict) else '') or '')
                        for o in (L.get('objects') or []))
        tiles = ''.join(L['tiles']) if isinstance(L.get('tiles'), list) else ''
        parts.append(f"{L.get('mode') or ''}|{seed if seed else ''}|{objs}|{tiles}")
    s = '#'.join(parts)
    h = 2166136261
    data = s.encode('utf-16-le')
    for k in range(0, len(data), 2):
        h ^= data[k] | (data[k + 1] << 8)
        h = (h * 16777619) & 0xffffffff
    digits, out = '0123456789abcdefghijklmnopqrstuvwxyz', ''
    while True:
        h, r = divmod(h, 36)
        out = digits[r] + out
        if not h:
            break
    return out


def game_data(world):
    """Engine-neutral description of the whole campaign. Godot reads it as stark_game.json; UE reads the
    UE-shaped copy (ue_game_json). Rules, numbers and text are exactly the browser engine's."""
    levels = levels_of(world)
    items = {k: _norm_item(k, v) for k, v in ITEMS.items()}
    dialogs, quests, npcs = {}, [], {}
    for li, L in enumerate(levels):
        its = L.get('items') if isinstance(L.get('items'), dict) else {}
        for k, v in its.items():
            if isinstance(v, dict):
                items[str(k)] = _norm_item(str(k), v)
        ds = L.get('dialogs') if isinstance(L.get('dialogs'), dict) else {}
        for k, d in ds.items():
            if isinstance(d, dict):
                dialogs[str(k)] = _norm_dialog(str(k), d)
        for q in L.get('quests') or []:
            if isinstance(q, dict) and q.get('id'):
                quests.append(_norm_quest(q, li))
        for o in L.get('objects') or []:
            if isinstance(o, dict) and o.get('t') == 'npc' and o.get('id') and str(o['id']) not in npcs:
                npcs[str(o['id'])] = {'id': str(o['id']), 'name': _s(o.get('name') or o['id'], 80),
                                      'dialog': _s(o.get('dialog'), 64), 'text': _s(o.get('text'), 600),
                                      'col': _hex(o.get('col'), '#d99a4d'), 'level': li, 'age': _age(o)}
    pl = world.get('player') if isinstance(world.get('player'), dict) else {}
    sfx = {k: dict(v) for k, v in SFX.items()}
    for k, v in (world.get('sfx') or {}).items() if isinstance(world.get('sfx'), dict) else ():
        if isinstance(v, dict):
            sfx[str(k)] = {kk: v[kk] for kk in ('wave', 'freq', 'slide', 'dur', 'decay', 'vol', 'noise', 'seed') if kk in v}
    diff = world.get('difficulty') if world.get('difficulty') in DIFF else 'normal'
    return {
        'format': 'stark-game/1', 'generator': f'Stark World Engine {_version()}',
        'title': _s(world.get('name') or 'Untitled Adventure', 120), 'author': _s(world.get('author') or 'you', 80),
        'story': _s(world.get('story'), 4000), 'difficulty': diff, 'save_key': save_key(world),
        'player': {'hp': max(1, _i(pl.get('hp'), 6) or 6), 'col': _hex(pl.get('col'), '#2e8c9e'),
                   'items': [str(x) for x in (pl.get('items') or []) if x] if isinstance(pl.get('items'), list) else []},
        'rules': dict(RULES), 'items': items, 'enemies': {k: dict(v) for k, v in ENEMY.items()},
        'abilities': [dict(a) for a in ABILITIES], 'diff': {k: dict(v) for k, v in DIFF.items()}, 'sfx': sfx,
        'quests': quests, 'dialogs': dialogs, 'npcs': npcs,
        'levels': [norm_level(L, li) for li, L in enumerate(levels)],
        # stark_systems CHILD_SAFETY.md bridge mirror: ids of child / teen characters. The runtimes never let them be
        # damaged, targeted, captured or romanced.
        'child_safety': {'minors': sorted(set(minors_of(world)) | {k for k, n in npcs.items() if n['age'] != 'adult'}),
                         'policy': str((world.get('child_safety') or {}).get('policy', ''))
                         if isinstance(world.get('child_safety'), dict) else ''},
    }


def _lin(c):
    return round(c ** 2.2, 5)


def _ue_col(h, default='#dddddd'):
    r, g, b = _rgb(h or default, _rgb(default, [1, 1, 1]))
    return {'R': _lin(r), 'G': _lin(g), 'B': _lin(b), 'A': 1.0}


def _ue_cond(c):
    c = c or {}
    return {'Has': c.get('has', ''), 'N': c.get('n', 1), 'Lacks': c.get('lacks', ''), 'Done': c.get('done', ''),
            'Active': c.get('active', ''), 'NotStarted': c.get('notStarted', ''), 'Flag': c.get('flag', ''),
            'MinLevel': c.get('minLevel', 0)}


def _ue_act(a):
    a = a or {}
    return {'Start': a.get('start', ''), 'Complete': a.get('complete', ''), 'Advance': a.get('advance', ''),
            'Give': a.get('give', []), 'Take': a.get('take', ''), 'TakeCount': a.get('n', 1), 'Gold': a.get('gold', 0),
            'Xp': a.get('xp', 0), 'Flag': a.get('flag', ''), 'Heal': bool(a.get('heal')), 'Win': bool(a.get('win'))}


def map_name(li):
    return 'GS_Level_%02d' % li


def ue_game_json(game):
    """game_data() reshaped for the C++ USTRUCTs in StarkTypes.h (FJsonObjectConverter matches property names)."""
    def obj(o):
        return {'Index': o['i'], 'Type': o['t'], 'X': o['x'], 'Y': o.get('y', 0.0), 'Z': o['z'], 'Scale': o['s'],
                'Yaw': o.get('yaw', 0.0), 'Kind': o.get('kind', ''), 'Id': o.get('id', ''), 'Name': o.get('name', ''),
                'Dialog': o.get('dialog', ''), 'Item': o.get('item', ''), 'Count': o.get('n', 1), 'Gold': o.get('gold', 0),
                'Key': o.get('key', ''), 'To': o.get('to', -1), 'Lock': o.get('lock', ''), 'Hp': o.get('hp', 0),
                'Patrol': o.get('patrol', 5.0), 'Color': _ue_col(o.get('col') or '#d99a4d'), 'Text': o.get('text', ''),
                'Asset': o.get('asset', ''), 'Age': o.get('age', 'adult')}
    levels = []
    for L in game['levels']:
        t = L.get('terrain') or {}
        levels.append({'Index': L['index'], 'Name': L['name'], 'Mode': L['mode'], 'Mood': L['mood'],
                       'Story': L['story'], 'MapName': map_name(L['index']), 'Seed': L['seed'], 'Size': L['size'],
                       'Amp': t.get('amp', 0.0), 'TerrainKind': t.get('kind', ''), 'Margin': t.get('margin', MARGIN),
                       'Edge': t.get('edge', 0.0), 'HasWater': L['water'] is not None,
                       'Water': L['water'] if L['water'] is not None else 0.0, 'Weather': L['fx'],
                       'DayStart': L['day']['start'] if L['day']['start'] is not None else -1.0,
                       'DayLength': L['day']['len'], 'SpawnX': L['spawn']['x'], 'SpawnZ': L['spawn']['z'],
                       'SpawnY': L['spawn'].get('y', 0.0), 'Objects': [obj(o) for o in L['objects']],
                       'Tiles': L.get('tiles', [])})
    dialogues = []
    for d in game['dialogs'].values():
        nodes = []
        for nid, n in d['nodes'].items():
            nodes.append({'Id': nid, 'Speaker': n['speaker'], 'Text': n['text'], 'Next': n['next'], 'Action': _ue_act(n['do']),
                          'Choices': [{'Text': c['text'], 'Goto': c['goto'], 'End': c['end'], 'HasRequires': c['if'] is not None,
                                       'Requires': _ue_cond(c['if']), 'Action': _ue_act(c['do'])} for c in n['choices']]})
        dialogues.append({'Id': d['id'], 'Start': d['start'], 'Nodes': nodes,
                          'Branches': [{'HasRequires': b['if'] is not None, 'Requires': _ue_cond(b['if']), 'Node': b['node']}
                                       for b in d['branches']]})
    return {
        'Title': game['title'], 'Author': game['author'], 'Story': game['story'], 'SaveKey': game['save_key'],
        'Minors': game['child_safety']['minors'],
        'Rules': {'PlayerHp': game['player']['hp'], 'PlayerColor': _ue_col(game['player']['col']),
                  'StartItems': game['player']['items'], 'Difficulty': game['difficulty'],
                  'XpBase': game['rules']['xp_base'], 'XpPow': game['rules']['xp_pow'],
                  'InteractRadius': game['rules']['interact_radius'], 'DeathGoldKeep': game['rules']['death_gold_keep'],
                  'CritChance': game['rules']['crit_chance'],
                  'Abilities': [{'Name': a['name'], 'Level': a['lvl'], 'Cooldown': a['cd'], 'Key': a['key']}
                                for a in game['abilities']],
                  'Difficulties': [{'Name': k, 'HpMul': v['hp'], 'DmgMul': v['dmg']} for k, v in game['diff'].items()]},
        'Items': [{'Id': k, 'Name': v['name'], 'Kind': v['kind'], 'Slot': v['slot'], 'Heal': v['heal'], 'Atk': v['atk'],
                   'Def': v['def'], 'Hp': v['hp'], 'Gold': v['gold'], 'Speed': v['speed'], 'Color': _ue_col(v['col']),
                   'Desc': v['desc']} for k, v in game['items'].items()],
        'Enemies': [{'Kind': k, 'Name': v['name'], 'Hp': v['hp'], 'Dmg': v['dmg'], 'Speed': v['speed'], 'Sight': v['sight'],
                     'Xp': v['xp'], 'Gold': v['gold'], 'Ranged': bool(v.get('ranged')), 'Fly': bool(v.get('fly')),
                     'Boss': bool(v.get('boss')), 'Color': _ue_col('#%02x%02x%02x' % tuple(int(c * 255) for c in v['col']))}
                    for k, v in game['enemies'].items()],
        'Quests': [{'Id': q['id'], 'Title': q['title'], 'Desc': q['desc'], 'Giver': q['giver'], 'Auto': q['auto'],
                    'Final': q['final'], 'Next': q['next'], 'Level': q['level'],
                    'Steps': [{'Type': s['type'], 'Item': s['item'], 'Kind': s['kind'], 'Id': s['id'], 'Npc': s['npc'],
                               'Count': s['count'], 'X': s['x'], 'Z': s['z'], 'R': s['r'], 'Label': s['label'],
                               'Level': s['level'], 'Text': s['text'], 'Consume': s['consume']} for s in q['steps']],
                    'Reward': {'Xp': q['reward']['xp'], 'Gold': q['reward']['gold'], 'Items': q['reward']['items']}}
                   for q in game['quests']],
        'Dialogues': dialogues,
        'Npcs': [{'Id': n['id'], 'Name': n['name'], 'Dialog': n['dialog'], 'Text': n['text'], 'Color': _ue_col(n['col']),
                  'Level': n['level'], 'Age': n['age']} for n in game['npcs'].values()],
        'Levels': levels,
    }


# ---------------------------------------------------------------- asset library (glTF 2.0 + JSON manifest)
ASSET_CLASSES = UE_KINDS + ('ground', 'ground_rock', 'ground_sand', 'ground_snow', 'sky', 'grass')
OK_LICENCES = re.compile(r'^(cc0|cc[- ]?by(?![- ]?nc)(?![- ]?nd)|mit|public domain|own|my own|original)', re.I)
MODEL_EXT = ('.glb', '.gltf')
TEXTURE_EXT = ('.png', '.jpg', '.jpeg')
HDRI_EXT = ('.hdr', '.exr')


def load_library(library):
    """library: a folder holding stark_assets.json (or the manifest path, or an already-loaded dict/list).
    Manifest: {"format": "stark-assets/1", "assets": [{id, file, licence, credit, scale, pivot, class, kind}]}.
    Also accepts a bare list and the staging fields (asset -> id, authors -> credit, license -> licence).
    -> {'root': folder or None, 'assets': [normalised entries], 'skipped': [reasons]}"""
    root, data = None, library
    if isinstance(library, str):
        p = library
        if os.path.isdir(p):
            root, p = p, os.path.join(p, 'stark_assets.json')
            if not os.path.isfile(p) and os.path.isfile(os.path.join(root, 'library.json')):
                p = os.path.join(root, 'library.json')          # Stark World Engine's own My_Assets folder
        else:
            root = os.path.dirname(os.path.abspath(p))
        with open(p, encoding='utf-8') as f:
            data = json.load(f)
    entries = data.get('assets', []) if isinstance(data, dict) else data if isinstance(data, list) else []
    assets, skipped, seen = [], [], set()
    for e in entries:
        if not isinstance(e, dict):
            continue
        aid = _clean(str(e.get('id') or e.get('asset') or ''))
        rel = str(e.get('file') or '').replace('\\', '/')
        lic = str(e.get('licence') or e.get('license') or '').strip()
        if rel.startswith('lib:'):                               # My_Assets: lib:<id>/<file> = My_Assets/<id>/<file>
            rel = rel[4:]
        credit = e.get('credit')
        if not credit and isinstance(e.get('authors'), dict):
            credit = ', '.join(f'{k} ({v})' for k, v in e['authors'].items())
        credit = _s(credit or e.get('pack') or '', 300)
        why = None
        if not aid or aid in seen:
            why = 'missing or duplicate id'
        elif not rel or rel.startswith('/') or re.match(r'^[A-Za-z]:', rel) or '..' in rel.split('/'):
            why = 'file must be a relative path inside the library'
        elif not OK_LICENCES.match(lic):
            why = f'licence "{lic or "unknown"}" is not on the allow list (CC0, CC-BY, MIT, own work)'
        elif root and not os.path.isfile(os.path.join(root, *rel.split('/'))):
            why = 'file not found'
        ext = os.path.splitext(rel)[1].lower()
        kind = e.get('kind') or ('model' if ext in MODEL_EXT else 'hdri' if ext in HDRI_EXT else
                                 'texture' if ext in TEXTURE_EXT else 'other')
        if why is None and kind == 'other':
            why = 'unsupported file type (use glTF 2.0 .glb/.gltf, .png/.jpg textures or .hdr skies)'
        if why:
            skipped.append(f'{aid or rel}: {why}')
            continue
        seen.add(aid)
        piv = e.get('pivot', 'bottom')
        if not (piv in ('bottom', 'center') or (isinstance(piv, list) and len(piv) == 3)):
            piv = 'bottom'
        maps = e.get('maps') if isinstance(e.get('maps'), dict) else {}
        maps = {k: str(v).replace('\\', '/') for k, v in maps.items()
                if isinstance(v, str) and '..' not in v.split('/') and not v.startswith('/') and k in
                ('normal', 'roughness', 'ao', 'displacement', 'arm', 'metallic')}
        assets.append({'id': aid, 'file': rel, 'kind': kind, 'class': str(e.get('class') or e.get('replaces') or ''),
                       'licence': lic, 'credit': credit, 'source': _s(e.get('source') or e.get('page') or e.get('url'), 300),
                       'scale': _f(e.get('scale'), 1.0) or 1.0, 'pivot': piv, 'maps': maps})
    return {'root': root, 'assets': assets, 'skipped': skipped}


def pick_assets(world, lib):
    """-> {gs class: asset} + per-object overrides {asset id: asset}. world['assets'] = {class: asset id} picks;
    otherwise the first library asset tagged with that class is used. Objects may name their own 'asset'."""
    if not lib or not lib.get('assets'):
        return {}, {}
    by_id = {a['id']: a for a in lib['assets']}
    by_id.update({_clean(str(k)): v for k, v in list(by_id.items())})
    chosen = {}
    for a in lib['assets']:
        if a['class'] in ASSET_CLASSES and a['class'] not in chosen:
            chosen[a['class']] = a
    wa = world.get('assets') if isinstance(world.get('assets'), dict) else {}
    for cls, aid in wa.items():
        if _clean(str(aid)) in by_id:
            chosen[str(cls)] = by_id[_clean(str(aid))]
    per_obj = {}
    for L in levels_of(world):
        for o in L.get('objects') or []:
            if isinstance(o, dict) and o.get('asset') and _clean(str(o['asset'])) in by_id:
                per_obj[o['asset']] = by_id[_clean(str(o['asset']))]
    return chosen, per_obj


def asset_files(world, library, dest='assets'):
    """-> ({export path: bytes}, manifest dict, credits markdown) for every library asset the world uses.
    Only allow-listed licences are copied; paths stay relative (never an absolute user path)."""
    lib = library if isinstance(library, dict) and 'assets' in library and 'root' in library else load_library(library)
    chosen, per_obj = pick_assets(world, lib)
    used = {a['id']: a for a in list(chosen.values()) + list(per_obj.values())}
    files, entries = {}, []
    for a in used.values():
        rels = [a['file']] + list(a['maps'].values())
        if a['file'].lower().endswith('.gltf') and lib['root']:
            rels += _gltf_deps(os.path.join(lib['root'], *a['file'].split('/')), a['file'])
        for rel in rels:
            if lib['root']:
                p = os.path.join(lib['root'], *rel.split('/'))
                if os.path.isfile(p):
                    with open(p, 'rb') as f:
                        files[f'{dest}/{rel}'] = f.read()
        entries.append({'id': a['id'], 'file': f'{dest}/{a["file"]}', 'kind': a['kind'], 'class': a['class'],
                        'scale': a['scale'], 'pivot': a['pivot'], 'licence': a['licence'], 'credit': a['credit'],
                        'maps': {k: f'{dest}/{v}' for k, v in a['maps'].items()}})
    classes = {cls: a['id'] for cls, a in chosen.items()}
    manifest = {'format': 'stark-assets/1', 'assets': entries, 'classes': classes}
    lines = ['# Art credits', '', 'Every third-party file in this project, with its licence. Keep this file when you ship.', '']
    for a in sorted(used.values(), key=lambda a: a['id']):
        lines.append(f"- **{a['id']}** (`{a['file']}`): {a['credit'] or 'unknown author'} - {a['licence']}"
                     + (f" - {a['source']}" if a['source'] else ''))
    if not used:
        lines.append('- No third-party art: every model is a Stark World Engine proxy shape.')
    return files, manifest, '\n'.join(lines) + '\n'


def _gltf_deps(path, rel):
    """External buffers/images a .gltf references (relative to it)."""
    try:
        with open(path, encoding='utf-8') as f:
            g = json.load(f)
    except (OSError, ValueError):
        return []
    base = rel.rsplit('/', 1)[0] + '/' if '/' in rel else ''
    out = []
    for k in ('buffers', 'images'):
        for b in g.get(k) or []:
            u = b.get('uri') if isinstance(b, dict) else None
            if isinstance(u, str) and not u.startswith('data:') and '..' not in u.split('/') and not u.startswith('/') \
                    and ':' not in u:
                out.append(base + u)
    return out


# ---------------------------------------------------------------- visual plan (one level)
def build_plan(world, gameplay=False, level=0):
    """Engine-neutral, JSON-serialisable description of one level's 3D scene (meters, y up, x/z ground plane).
    gameplay=True also places houses, NPCs, items, chests, doors, portals and checkpoints (GAMEPLAY_KINDS) with
    their proxies/materials and a light per portal; the default leaves them out."""
    levels = levels_of(world)
    L = levels[level] if 0 <= level < len(levels) else world
    mood = mood_of(L)
    base, look = BASE[mood], LOOK[mood]
    kinds = UE_KINDS if gameplay else OBJ_KINDS
    objs = [(i, o) for i, o in enumerate(L.get('objects') or []) if isinstance(o, dict) and o.get('t') in kinds]
    # legacy marker lists (npcs/items/portals/quests with x/z or pos); v2 item definitions and quests have no position
    markers_src = [(k, p) for k in ('npcs', 'items', 'portals', 'quests') for p in _named_points(L, k)
                   if any(key in p['data'] for key in ('x', 'z', 'pos'))] if level == 0 else []
    reach = max([abs(_f(o.get('x'))) for _, o in objs] + [abs(_f(o.get('z'))) for _, o in objs]
                + [max(abs(p['x']), abs(p['z'])) for _, p in markers_src] + [10.0])
    spec = terrain_spec(L, reach)
    span, res = spec['span'], TERRAIN_RES
    heights = spec_grid(spec, res)
    gy = lambda x, z: round(spec_height(spec, x, z), 3)
    seed = int(_f(L.get('seed'), 1))

    objects, counts = [], {}
    for idx, o in objs:
        x, z = _f(o.get('x')), _f(o.get('z'))
        counts[o['t']] = counts.get(o['t'], 0) + 1
        i = counts[o['t']]
        yaw = yaw_of(o, 0.0 if o['t'] in GAMEPLAY_KINDS else _hash01(i, len(objects), seed) * 360.0)
        objects.append({'cls': o['t'], 'i': i, 'oi': idx, 'x': round(x, 3), 'z': round(z, 3),
                        'y': round(gy(x, z) - 0.08, 3),
                        's': round(min(10.0, max(0.1, _f(o.get('s'), 1.0))), 3), 'yaw': round(yaw % 360.0, 1)})

    lights = []
    for ob in objects:
        if ob['cls'] == 'lamp':
            lights.append({'label': f'GS_LampLight_{ob["i"]:03d}', 'type': 'point', 'x': ob['x'], 'z': ob['z'],
                           'y': round(ob['y'] + 2.55 * ob['s'], 3), 'color': base['fx'], 'intensity': 12.0,
                           'radius': 14.0, 'shadows': sum(1 for L2 in lights if L2['shadows']) < 8,
                           'ground': ob['y']})
        elif ob['cls'] == 'crystal':
            lights.append({'label': f'GS_CrystalLight_{ob["i"]:03d}', 'type': 'point', 'x': ob['x'], 'z': ob['z'],
                           'y': round(ob['y'] + 0.9 * ob['s'], 3), 'color': base['fx'], 'intensity': 4.0,
                           'radius': 7.0, 'shadows': False, 'ground': ob['y']})
        elif ob['cls'] == 'portal':
            lights.append({'label': f'GS_PortalLight_{ob["i"]:03d}', 'type': 'point', 'x': ob['x'], 'z': ob['z'],
                           'y': round(ob['y'] + 2.0 * ob['s'], 3), 'color': base['fx'], 'intensity': 10.0,
                           'radius': 10.0, 'shadows': False, 'ground': ob['y']})
    for i, Lt in enumerate((L.get('lights') or []) if level == 0 else [], 1):
        if not isinstance(Lt, dict):
            continue
        x, z = _f(Lt.get('x')), _f(Lt.get('z'))
        lights.append({'label': f'GS_Light_{i:03d}', 'type': 'spot' if Lt.get('type') == 'spot' else 'point',
                       'x': x, 'z': z, 'y': round(gy(x, z) + _f(Lt.get('y', Lt.get('height')), 3.0), 3),
                       'color': _rgb(Lt.get('color'), base['fx']), 'intensity': _f(Lt.get('intensity'), 10.0),
                       'radius': _f(Lt.get('radius'), 12.0), 'shadows': bool(Lt.get('shadows', True)),
                       'ground': gy(x, z)})

    markers = []
    for kind, p in markers_src:
        label = {'npcs': 'NPC', 'items': 'Item', 'portals': 'Portal', 'quests': 'Quest'}[kind]
        markers.append({'kind': label, 'label': f'GS_{label}_{_clean(p["name"])}', 'name': p['name'],
                        'x': round(p['x'], 3), 'z': round(p['z'], 3), 'y': gy(p['x'], p['z']),
                        'data': json.loads(json.dumps(p['data'], default=str))})

    info = level_info(L, level)
    sp = world.get('player') if level == 0 and isinstance(world.get('player'), dict) and \
        world['player'].get('x') is not None else info['spawn']
    sx, sz = _f(sp.get('x')), _f(sp.get('z'))
    spawn = {'x': sx, 'z': sz, 'y': gy(sx, sz)}

    def cam(name, pos, tgt, focal, aperture):
        return {'name': name, 'pos': [round(v, 3) for v in pos], 'target': [round(v, 3) for v in tgt],
                'focal': focal, 'aperture': aperture, 'ground': gy(pos[0], pos[2]), 'tground': gy(tgt[0], tgt[2])}
    centre = [0.0, gy(0, 0) + 2.0, 0.0]
    hc = min(span * 0.3, (spec.get('size') or span / 2) * 0.8)
    cams = [cam('GS_Shot_Hero', [-hc, gy(-hc, -hc) + 18.0, -hc], centre, 24.0, 8.0)]
    land = next((o for o in objects if o['cls'] == 'ruin'), None) or next(
        (o for o in objects if o['cls'] in ('crystal', 'lamp')), None)
    look_at = [land['x'], land['y'] + 1.5, land['z']] if land else centre
    back = [spawn['x'] - 7.0, spawn['y'] + 1.7, spawn['z'] - 7.0]
    cams.append(cam('GS_Shot_Ground', back, look_at, 35.0, 2.8))
    if land:
        p = [land['x'] + 6.0, 0.0, land['z'] + 6.0]
        p[1] = gy(p[0], p[2]) + 2.2
        cams.append(cam('GS_Shot_Landmark', p, [land['x'], land['y'] + 1.4, land['z']], 50.0, 2.0))

    mats = {'ground': base['ground'], 'trunk': [0.3, 0.2, 0.12], 'leaf': base['leaf'], 'stone': base['stone'],
            'rock': [c * 0.8 for c in base['stone']], 'crystal': base['fx'], 'enemy': [0.7, 0.12, 0.18],
            'metal': [0.15, 0.15, 0.17], 'glow': base['fx']}
    weather = _weather(L)
    if weather['type'] == 'snow':
        mats['ground'] = [min(1.0, c * 0.4 + 0.55) for c in mats['ground']]
    proxies, emissive = PROXIES, EMISSIVE
    if gameplay:
        mats.update(GAMEPLAY_MATS, gem=base['fx'], veil=base['fx'])
        proxies, emissive = dict(PROXIES, **GAMEPLAY_PROXIES), dict(EMISSIVE, **GAMEPLAY_EMISSIVE)
    terrain = {'span': span, 'res': res, 'source': spec['source'], 'heights': heights, 'kind': spec['kind']}
    for k in ('seed', 'amp', 'size', 'margin', 'edge'):
        if k in spec:
            terrain[k] = spec[k]
    return {
        'format': 2, 'generator': f'Stark World Engine {_version()}', 'name': str(L.get('name', 'World')), 'level': level,
        'map': f'{MAP_ROOT}/{map_name(level)}', 'mode': info['mode'],
        'slug': slug(L.get('name', 'World')), 'story': str(L.get('story', '')), 'mood': mood,
        'base': base, 'look': look, 'sun': sun_for(L), 'weather': weather, 'water': info['water'],
        'water_color': MOOD_WATER[mood], 'terrain': terrain,
        'objects': objects, 'counts': counts, 'lights': lights, 'markers': markers, 'spawn': spawn,
        'cameras': cams, 'materials': {k: [round(c, 4) for c in v] for k, v in mats.items()},
        'emissive': emissive, 'proxies': proxies,
        'extras': {k: L[k] for k in ('quests', 'npcs', 'items', 'portals') if k in L},
    }


def build_plans(world):
    """Visual plan of every level (2D levels get a plan too: the UE build lays their tiles out as a 2.5D map)."""
    out = []
    for li, L in enumerate(levels_of(world)):
        if L.get('mode') == '2d':
            info = level_info(L, li)
            out.append({'format': 2, 'level': li, 'mode': '2d', 'name': info['name'], 'mood': info['mood'],
                        'map': f'{MAP_ROOT}/{map_name(li)}', 'base': BASE[info['mood']], 'look': LOOK[info['mood']],
                        'sun': sun_for(L), 'weather': _weather(L), 'tiles': norm_level(L, li).get('tiles', []),
                        'water_color': MOOD_WATER[info['mood']]})
        else:
            out.append(build_plan(world, gameplay=True, level=li))
    return out


# ---------------------------------------------------------------- UE project files
def _uproject(world, engine='5.4', runtime=True):
    plugins = [{'Name': 'StarkRuntime', 'Enabled': bool(runtime)},
               {'Name': 'PythonScriptPlugin', 'Enabled': True},
               {'Name': 'EditorScriptingUtilities', 'Enabled': True},
               {'Name': 'PCG', 'Enabled': True},
               {'Name': 'Water', 'Enabled': True}]
    return json.dumps({
        'FileVersion': 3, 'EngineAssociation': engine, 'Category': '',
        'Description': str(world.get('story', ''))[:500],
        'Plugins': plugins,
    }, indent=2)


def _engine_ini(name, runtime=True):
    gm = ('GlobalDefaultGameMode=/Script/StarkRuntime.StarkGameMode\n' if runtime else '')
    return f"""; Generated by Stark World Engine - high-end UE5 rendering defaults + the Stark World Engine startup build.
; Rendering settings: https://dev.epicgames.com/documentation/en-us/unreal-engine/lumen-global-illumination-and-reflections-in-unreal-engine
; Python startup scripts: https://dev.epicgames.com/documentation/en-us/unreal-engine/scripting-the-unreal-editor-using-python
[/Script/EngineSettings.GameMapsSettings]
EditorStartupMap=/Game/Stark/Maps/GS_Level_00.GS_Level_00
GameDefaultMap=/Game/Stark/Maps/GS_Level_00.GS_Level_00
{gm}
[/Script/PythonScriptPlugin.PythonScriptPluginSettings]
; Builds every Stark World Engine level once on the first editor start (idempotent; menu Stark World Engine > Rebuild from Stark World Engine re-runs it).
+StartupScripts=stark_startup.py

[/Script/Engine.RendererSettings]
; Lumen global illumination + reflections (1 = Lumen)
r.DynamicGlobalIlluminationMethod=1
r.ReflectionMethod=1
r.Lumen.TraceMeshSDFs=1
r.GenerateMeshDistanceFields=True
; Virtual Shadow Maps
r.Shadow.Virtual.Enable=1
; Nanite
r.Nanite.ProjectEnabled=True
; Temporal Super Resolution (4 = TSR)
r.AntiAliasingMethod=4
; Physically based sky, exposure in EV100, bloom
r.SupportSkyAtmosphere=True
r.SupportSkyAtmosphereAffectsHeightFog=True
r.DefaultFeature.AutoExposure=True
r.DefaultFeature.AutoExposure.Method=0
r.DefaultFeature.AutoExposure.Bias=1.0
r.DefaultFeature.AutoExposure.ExtendDefaultLuminanceRange=True
r.DefaultFeature.Bloom=True
r.DefaultFeature.MotionBlur=True
r.DefaultFeature.LocalExposure.HighlightContrastScale=0.8
r.DefaultFeature.LocalExposure.ShadowContrastScale=0.8
r.AllowStaticLighting=False
r.VirtualTextures=True
r.CustomDepth=3
r.SkinCache.CompileShaders=True
; Hardware ray tracing (optional, needs a DX12 RT-capable GPU): set both to True and restart the editor.
r.RayTracing=False
r.Lumen.HardwareRayTracing=False

[/Script/WindowsTargetPlatform.WindowsTargetSettings]
DefaultGraphicsRHI=DefaultGraphicsRHI_DX12
-D3D12TargetedShaderFormats=PCD3D_SM5
+D3D12TargetedShaderFormats=PCD3D_SM6

[SystemSettings]
r.Tonemapper.Quality=5
r.Tonemapper.Sharpen=0.6
r.TSR.History.ScreenPercentage=200
r.Lumen.Reflections.HierarchicalScreenTraces.MaxIterations=50
r.VolumetricFog.GridPixelSize=8
r.VolumetricFog.GridSizeZ=128

[/Script/EngineSettings.GeneralProjectSettings]
ProjectName={name}
"""


def _game_ini(world):
    name = re.sub(r'[\r\n]', ' ', str(world.get('name', 'World')))
    return (f'[/Script/EngineSettings.GeneralProjectSettings]\nProjectName={name}\n'
            f'Description=Exported by Stark World Engine {_version()}\nCompanyName=\n\n'
            '[/Script/UnrealEd.ProjectPackagingSettings]\n'
            '; the runtime reads Content/Stark/Data/stark_game_ue.json when the data assets are missing\n'
            '+DirectoriesToAlwaysStageAsUFS=(Path="Stark/Data")\n')


def _swap_csv(plans):
    counts = {}
    for p in plans:
        for k, v in (p.get('counts') or {}).items():
            counts[k] = counts.get(k, 0) + v
    rows = ['gs_class,asset_path,scale,random_yaw,z_offset_cm,notes']
    for cls in ('tree', 'rock', 'ruin', 'crystal', 'lamp', 'enemy') + GAMEPLAY_KINDS + ('ground',):
        n = counts.get(cls, 0) if cls != 'ground' else len([p for p in plans if p.get('mode') != '2d'])
        hint = SWAP_HINTS[cls].replace(',', ';').replace('"', "'")
        rows.append(f'{cls},,1.0,{"1" if cls in ("tree", "rock", "crystal") else "0"},0,{n} placed - {hint}')
    return '\n'.join(rows) + '\n'


def _metahuman_csv(game):
    rows = ['npc_id,character_blueprint,notes']
    for n in game['npcs'].values():
        rows.append(f"{n['id']},,{n['name'].replace(',', ' ')} (level {n['level'] + 1}) - paste a MetaHuman or "
                    "character Blueprint path (Copy Reference); the Stark World Engine NPC component keeps the dialogue")
    return '\n'.join(rows) + '\n'


def _pcg_json(plans):
    hooks = []
    for p in plans:
        if p.get('mode') == '2d':
            continue
        c = p.get('counts') or {}
        hooks.append({'level': p['level'], 'map': p['map'], 'graph': '', 'enabled': True,
                      'density': {'grass': 0.08, 'bush': 0.012 + 0.0004 * c.get('tree', 0), 'pebble': 0.004},
                      'notes': 'Ambient scatter only. Creator-placed trees/rocks are placed exactly from world.json. '
                               'Put your own PCG graph path in "graph" to replace the Stark World Engine default graph.'})
    return json.dumps({'format': 1, 'hooks': hooks}, indent=1)


def _bat_find_ue():
    return r'''set "UE=%UE_EDITOR%"
if not defined UE for /d %%D in ("%ProgramFiles%\Epic Games\UE_5.*") do if exist "%%D\Engine\Binaries\Win64\UnrealEditor-Cmd.exe" set "UE=%%D\Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
if not defined UE (echo Unreal Engine 5.4+ not found. Install it free from the Epic Games Launcher, or set UE_EDITOR to UnrealEditor-Cmd.exe & pause & exit /b 1)
'''


TEXT_EXT = ('.h', '.cpp', '.cs', '.uplugin', '.ini', '.md', '.txt', '.json', '.py', '.modules', '.gd', '.gdshader',
            '.cfg', '.tscn', '.tres', '.svg', '.bat', '.ps1', '.csv')


def _read_tree(root, binary_ok):
    """-> {relative posix path: str | bytes} of every file under root (text for source, bytes for binaries)."""
    out = {}
    if not os.path.isdir(root):
        return out
    for dp, dns, fns in os.walk(root):
        dns[:] = sorted(d for d in dns if d not in ('__pycache__',) and not d.startswith('.'))
        for fn in sorted(fns):
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, root).replace(os.sep, '/')
            with open(p, 'rb') as f:
                data = f.read()
            if fn.endswith(TEXT_EXT):
                out[rel] = data.decode('utf-8')
            elif binary_ok:
                out[rel] = data
    return out


def _editor_script(name):
    with open(os.path.join(EDITOR_SCRIPTS, name), encoding='utf-8') as f:
        return f.read()


EDITOR_SCRIPT_NAMES = ('stark_common.py', 'stark_build_level.py', 'stark_startup.py', 'stark_swap_proxies.py',
                       'stark_screenshots.py', 'stark_pie_smoke.py', 'init_unreal.py')


def prebuilt_for(version, prebuilt_dir=None):
    """-> folder with verified prebuilt Stark World Engine Runtime binaries for UE '5.x', or None.
    ue5_plugin/prebuilt/UE_5.x/manifest.json lists sha256 of every file (written by build_binaries.ps1)."""
    d = os.path.join(prebuilt_dir or PREBUILT_DIR, f'UE_{version}')
    man = os.path.join(d, 'manifest.json')
    plug = os.path.join(d, 'StarkRuntime')
    if not (os.path.isfile(man) and os.path.isdir(plug)):
        return None
    try:
        with open(man, encoding='utf-8') as f:
            m = json.load(f)
        for rel, digest in (m.get('files') or {}).items():
            p = os.path.join(plug, *rel.split('/'))
            with open(p, 'rb') as fh:
                if hashlib.sha256(fh.read()).hexdigest() != digest:
                    return None
        dll = os.path.join(plug, 'Binaries', 'Win64', 'UnrealEditor-StarkRuntime.dll')
        return d if os.path.isfile(dll) and m.get('files') else None
    except (OSError, ValueError, AttributeError):
        return None


def detect_msvc(vswhere=None):
    """True when Visual Studio with the C++ toolset is installed (UE can then compile the runtime itself)."""
    vswhere = vswhere or os.path.join(os.environ.get('ProgramFiles(x86)') or r'C:\Program Files (x86)',
                                      'Microsoft Visual Studio', 'Installer', 'vswhere.exe')
    if not os.path.isfile(vswhere):
        return False
    try:
        out = subprocess.run([vswhere, '-latest', '-products', '*', '-requires',
                              'Microsoft.VisualStudio.Component.VC.Tools.x86.x64', '-property', 'installationPath'],
                             capture_output=True, text=True, timeout=20)
        return bool(out.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return False


def runtime_mode(engine='5.4', with_binaries=False, compiler=None, prebuilt_dir=None):
    """'prebuilt' (binaries copied: plays with nothing else installed), 'source' (UE compiles the plugin; needs
    Visual Studio C++) or 'disabled' (no binaries, no compiler: levels build as scenery, gameplay waits)."""
    if with_binaries and prebuilt_for(engine, prebuilt_dir):
        return 'prebuilt'
    if compiler is None:
        compiler = detect_msvc()
    return 'source' if compiler else 'disabled'


def ue5_project(world, engine='5.4', with_binaries=False, library=None, compiler=None, prebuilt_dir=None):
    """-> {relative path: text (or bytes for prebuilt binaries / art)}: a UE5 project that builds and plays the
    whole Stark World Engine game. with_binaries: copy the verified prebuilt runtime for `engine` (needs a bytes-capable writer).
    library: asset library folder / manifest (glTF 2.0 + JSON) whose art replaces proxies."""
    world = gate(world)                              # child-safety gate (stark_systems), fails closed
    if world.get('mode', '3d') != '3d':
        raise ValueError('UE5 export supports 3D worlds; use Godot 4 or the HTML5 cartridge for 2D worlds')
    if not os.path.isdir(RUNTIME_SRC) or not os.path.isdir(EDITOR_SCRIPTS):
        raise RuntimeError('Stark World Engine Runtime files are missing next to ue5_export.py (ue5_plugin/)')
    name = slug(world.get('name', 'World'))
    mode = runtime_mode(engine, with_binaries, compiler, prebuilt_dir)
    runtime_on = mode != 'disabled'
    game = game_data(world)
    plans = build_plans(world)
    files = {
        f'{name}.uproject': _uproject(world, engine, runtime_on),
        'Config/DefaultEngine.ini': _engine_ini(name, runtime_on),
        'Config/DefaultGame.ini': _game_ini(world),
        'Content/Python/world.json': json.dumps(world, indent=1),
        'Content/Python/stark_plan.json': json.dumps({'format': 2, 'levels': plans}, separators=(',', ':')),
        'Content/Python/proxy_swap_map.csv': _swap_csv(plans),
        'Content/Python/metahuman_slots.csv': _metahuman_csv(game),
        'Content/Python/pcg_hooks.json': _pcg_json(plans),
        'Content/Stark/Data/stark_game.json': json.dumps(game, separators=(',', ':')),
        'Content/Stark/Data/stark_game_ue.json': json.dumps(ue_game_json(game), indent=1),
        'BUILD_LEVEL_HEADLESS.bat': ('@echo off\r\nsetlocal\r\n' + _bat_find_ue().replace('\n', '\r\n')
                                     + f'"%UE%" "%~dp0{name}.uproject" -run=pythonscript '
                                       '-script="%~dp0Content\\Python\\stark_build_level.py" -unattended -nosplash '
                                       '-nop4\r\necho Done. Log: Saved\\Stark\\build_report.json\r\npause\r\n'),
    }
    for s in EDITOR_SCRIPT_NAMES:
        files[f'Content/Python/{s}'] = _editor_script(s)
    src = _read_tree(RUNTIME_SRC, binary_ok=False)
    for rel, data in src.items():
        if not rel.startswith(('Binaries/', 'Intermediate/')):
            files[f'Plugins/StarkRuntime/{rel}'] = data
    if mode == 'prebuilt':
        pre = _read_tree(os.path.join(prebuilt_for(engine, prebuilt_dir), 'StarkRuntime'), binary_ok=True)
        for rel, data in pre.items():
            if rel.startswith(('Binaries/', 'Intermediate/')) or rel == 'StarkRuntime.uplugin':
                files[f'Plugins/StarkRuntime/{rel}'] = data
    art = {'format': 'stark-assets/1', 'assets': [], 'classes': {}}
    credits = None
    if library is not None:
        afiles, art, credits = asset_files(world, library, dest='StarkAssets')
        files.update(afiles)
    files['Content/Python/stark_assets.json'] = json.dumps(art, indent=1)
    files['CREDITS.md'] = credits or ('# Art credits\n\n- No third-party art: every model is a Stark World Engine proxy shape or an '
                                      'engine primitive. Add Fab / Megascans / MetaHumans with your own Epic account.\n')
    files['README_UE5.md'] = _readme(world, name, plans, game, mode)
    return files


def _guide_text():
    p = os.path.join(PLUGIN_DIR, 'FROM_STARK_TO_UE5.md')
    try:
        with open(p, encoding='utf-8') as f:
            return f.read()
    except OSError:
        return ''


def _readme(world, name, plans, game, mode):
    nq, nd = len(game['quests']), len(game['dialogs'])
    nl = len(game['levels'])
    n2 = sum(1 for L in game['levels'] if L['mode'] == '2d')
    status = {
        'prebuilt': 'The Stark World Engine Runtime plugin is included prebuilt for this engine version: press Play and the game '
                    'runs - no compiler needed.',
        'source': 'The Stark World Engine Runtime plugin is included as C++ source. Unreal compiles it the first time you open the '
                  'project (Visual Studio 2022 with "Game development with C++" was found on this PC).',
        'disabled': 'The Stark World Engine Runtime plugin is included as C++ source but switched OFF: no prebuilt binaries for '
                    'this engine version were bundled and no C++ compiler was found. The levels still build '
                    '(landscape, sky, art, markers); to play quests/dialogue/combat either open the project from '
                    'Stark World Engine with "Open in Unreal Engine" (it adds the prebuilt runtime when available) or '
                    'install Visual Studio 2022 (C++) and set "Enabled": true for StarkRuntime in the .uproject.',
    }[mode]
    return f"""# {world.get('name', 'World')} - Unreal Engine 5 project

Exported by Stark World Engine {_version()}: {nl} level(s){f' ({n2} 2D chapter(s) as 2.5D side-scroller maps)' if n2 else ''}, {nq} quest(s), {nd} dialogue(s), {len(game['npcs'])} named NPC(s).

**Status: generated and checked by Stark World Engine's own tests; not yet opened in a real UE5 install by us.**
{status}

## Open it (nothing to click)
1. Install Unreal Engine 5.4 or newer from the Epic Games Launcher (free account). Stark World Engine never downloads it.
2. Double-click `{name}.uproject` (or use "Open in Unreal Engine" in Stark World Engine). On the first start the editor
   compiles shaders, then the Stark World Engine startup script builds every level by itself (`/Game/Stark/Maps/GS_Level_00`
   ...). Watch the Output Log for `[StarkWorldEngine]`. It only builds once; menu **Stark World Engine > Rebuild from Stark World Engine** re-runs.
3. Press **Play**. WASD move, Space jump, J or left mouse attack, E talk / open / unlock, 1-4 pick an answer,
   H potion, Shift dash, K whirl, F bolt, Z/C or right mouse turn the camera, L quests, I bag, Esc menu
   (save slots 1-3, load, autosave at checkpoints).

Headless build (no window): `BUILD_LEVEL_HEADLESS.bat` (set `UE_EDITOR` if the engine is not under Program Files).

## What carries over
- Every level, its mood, sky, time of day, weather, water and the exact terrain shape (same height formula as the
  browser engine, extended past the play area for a horizon).
- Every object at its exact place: trees/rocks/ruins/lamps/houses as instanced foliage, NPCs with their dialogue,
  enemies with their kind/health/patrol, items, chests, locked doors, portals (with their quest locks) and checkpoints.
- Quests, dialogue trees (conditions, branches, actions), items and equipment, XP/levels, abilities, difficulty,
  save slots + autosave - as data assets in `/Game/Stark/Data` read by the Stark World Engine Runtime plugin.

## Swap in real art (optional)
- `Content/Python/proxy_swap_map.csv`: per class (tree, rock, ...) a Fab / Megascans asset path (Copy Reference).
- `Content/Python/metahuman_slots.csv`: per NPC id a MetaHuman (or any character) Blueprint. The NPC keeps its
  dialogue because the Stark World Engine NPC component goes onto the new actor.
- `Content/Python/pcg_hooks.json`: PCG graph per level for ambient scatter (grass, bushes, pebbles).
- Then menu **Stark World Engine > Swap proxies for real assets** (or Rebuild). See "From Stark World Engine to Unreal Engine 5" below.

## Licensing
- Unreal Engine is free to download and use. Epic's standard EULA charges a 5% royalty only on gross revenue above
  USD 1,000,000 per product (see the Unreal Engine EULA at https://www.unrealengine.com/eula ; read it yourself, the
  terms are Epic's, not ours).
- Fab / Megascans / MetaHuman assets are licensed to you by Epic or their creators under your own account. Stark World Engine
  Studios does not bundle, redistribute or download any Epic, Fab or Megascans content.
- The Stark World Engine Runtime plugin may ship inside games you make (see Plugins/StarkRuntime/LICENSE_RUNTIME.md).
- Third-party art in this project: CREDITS.md.

## Files
- `Content/Python/world.json` - the Stark World Engine world (source of truth).
- `Content/Stark/Data/stark_game.json` / `stark_game_ue.json` - the whole game as data (the runtime falls back to
  it when the data assets are missing).
- `Content/Python/stark_plan.json` - terrain, placements, lights, cameras and look of every level.
- `Saved/Stark/build_report.json` - what the last build did, with any warnings.

---

{_guide_text()}"""


# ---------------------------------------------------------------- Unreal discovery + launch
def _ver_tuple(s):
    m = re.search(r'(\d+)\.(\d+)', str(s))
    return (int(m.group(1)), int(m.group(2))) if m else None


def _editor_version(root):
    bv = os.path.join(root, 'Engine', 'Build', 'Build.version')
    try:
        with open(bv, encoding='utf-8') as f:
            d = json.load(f)
        return (int(d['MajorVersion']), int(d['MinorVersion']))
    except (OSError, ValueError, KeyError, TypeError):
        return _ver_tuple(os.path.basename(os.path.normpath(root)).replace('UE_', ''))


def _editor_exe(root):
    return os.path.join(root, 'Engine', 'Binaries', 'Win64', 'UnrealEditor.exe')


def _registry_roots(registry=None):
    """HKLM\\SOFTWARE\\EpicGames\\Unreal Engine\\<ver>\\InstalledDirectory (launcher installs).
    registry: injectable {version: InstalledDirectory} for tests; None reads the real registry on Windows."""
    if registry is not None:
        return [(p, 'registry') for _, p in sorted(registry.items())]
    if sys.platform != 'win32':
        return []
    out = []
    try:
        import winreg
    except ImportError:
        return out
    for view in (0, getattr(winreg, 'KEY_WOW64_64KEY', 0)):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\EpicGames\Unreal Engine', 0,
                                winreg.KEY_READ | view) as k:
                i = 0
                while True:
                    try:
                        ver = winreg.EnumKey(k, i)
                    except OSError:
                        break
                    i += 1
                    try:
                        with winreg.OpenKey(k, ver) as kv:
                            p, _ = winreg.QueryValueEx(kv, 'InstalledDirectory')
                            out.append((str(p), 'registry'))
                    except OSError:
                        pass
        except OSError:
            pass
    return out


def find_unreal(program_files=None, launcher_dat=None, config_path=None, env=None, registry=None):
    """-> [{'version': '5.4', 'root': ..., 'editor': ..., 'cmd': ..., 'source': ...}] newest first.

    Looks in: STARK_UNREAL_EDITOR env var / engine_paths.json ({"unreal_editor": "...UnrealEditor.exe"}) next to
    this module, %ProgramFiles%\\Epic Games\\UE_5.*, the Epic launcher's LauncherInstalled.dat and the registry
    (HKLM\\SOFTWARE\\EpicGames\\Unreal Engine\\<ver>\\InstalledDirectory)."""
    env = os.environ if env is None else env
    roots = []
    override = env.get('STARK_UNREAL_EDITOR')
    cfg = config_path or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'engine_paths.json')
    if not override and os.path.isfile(cfg):
        try:
            with open(cfg, encoding='utf-8') as f:
                override = json.load(f).get('unreal_editor')
        except (OSError, ValueError, AttributeError):
            override = None
    if override:
        p = os.path.abspath(override)
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(p)))) if p.lower().endswith('.exe') else p
        roots.append((root, 'override'))
    pf = program_files or env.get('ProgramFiles') or r'C:\Program Files'
    epic = os.path.join(pf, 'Epic Games')
    if os.path.isdir(epic):
        for d in sorted(os.listdir(epic)):
            if d.upper().startswith('UE_5'):
                roots.append((os.path.join(epic, d), 'program_files'))
    dat = launcher_dat or os.path.join(env.get('ProgramData') or r'C:\ProgramData', 'Epic', 'UnrealEngineLauncher',
                                       'LauncherInstalled.dat')
    try:
        with open(dat, encoding='utf-8') as f:
            for it in json.load(f).get('InstallationList', []):
                if str(it.get('AppName', '')).upper().startswith('UE_5') and it.get('InstallLocation'):
                    roots.append((it['InstallLocation'], 'launcher'))
    except (OSError, ValueError, AttributeError):
        pass
    roots += _registry_roots(registry if (registry is not None or program_files is None) else {})
    out, seen = [], set()
    for root, src in roots:
        key = os.path.normcase(os.path.abspath(root))
        exe = _editor_exe(root)
        if key in seen or not os.path.isfile(exe):
            continue
        seen.add(key)
        v = _editor_version(root)
        if not v or v[0] != 5:
            continue
        out.append({'version': f'{v[0]}.{v[1]}', 'vt': v, 'root': root, 'editor': exe,
                    'cmd': os.path.join(root, 'Engine', 'Binaries', 'Win64', 'UnrealEditor-Cmd.exe'), 'source': src})
    out.sort(key=lambda e: (e['source'] == 'override', e['vt']), reverse=True)
    return out


def pick_unreal(found=None, **kw):
    found = find_unreal(**kw) if found is None else found
    ok = [e for e in found if e['vt'] >= MIN_UE]
    return ok[0] if ok else None


INSTALL_GUIDE = ('Unreal Engine 5 is not installed on this PC (it is free, but we cannot bundle it).\n'
                 '1. Install the free Epic Games Launcher from epicgames.com and sign in with your Epic account.\n'
                 '2. In the launcher: Unreal Engine > Library > + > install 5.4 or newer. Then click "Open in Unreal '
                 'Engine" again - Stark World Engine finds it by itself.\n'
                 'No Unreal? "Open in Godot" plays the same game in the free Godot 4 engine (no account needed).\n'
                 'Already installed somewhere else? Put {"unreal_editor": "<path to UnrealEditor.exe>"} in '
                 'engine_paths.json next to studio_app.py, or set STARK_UNREAL_EDITOR.')

PRESERVE = ('Content/Python/proxy_swap_map.csv', 'Content/Python/metahuman_slots.csv', 'Content/Python/pcg_hooks.json')


def write_project(files, out_dir, preserve=PRESERVE):
    written = []
    for rel, text in files.items():
        p = os.path.join(out_dir, *rel.split('/'))
        if rel in preserve and os.path.exists(p):
            continue
        os.makedirs(os.path.dirname(p), exist_ok=True)
        data = text if isinstance(text, bytes) else text.encode('utf-8')
        with open(p, 'wb') as f:
            f.write(data)
        written.append(rel)
    return written


def open_in_unreal(world, out_dir, editor=None, launch=True, popen=None, library=None, compiler=None,
                   prebuilt_dir=None, **find_kw):
    """Write the UE5 project to out_dir (with the prebuilt Stark World Engine Runtime for the found engine when available) and
    launch the editor detached; the project builds its levels by itself on first open (startup script).

    editor: path to UnrealEditor.exe (skips discovery). Returns a status dict:
      {'ok': True, 'uproject', 'editor', 'version', 'runtime', 'pid', 'argv', 'headless'} or
      {'ok': False, 'error', 'guide'}. Never downloads anything."""
    try:
        world = gate(world)
    except ValueError as e:
        return {'ok': False, 'error': 'child_safety', 'guide': str(e)}
    if world.get('mode', '3d') != '3d':
        return {'ok': False, 'error': '2d', 'guide': 'Unreal export is for 3D worlds; use Godot 4 or the HTML5 '
                                                     'cartridge for 2D worlds.'}
    if editor:
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(editor)))))
        v = _editor_version(root) or MIN_UE
        found = {'editor': editor, 'version': f'{v[0]}.{v[1]}',
                 'cmd': os.path.join(os.path.dirname(os.path.abspath(editor)), 'UnrealEditor-Cmd.exe')}
        if not os.path.isfile(editor):
            return {'ok': False, 'error': 'editor_missing', 'guide': f'{editor} does not exist.\n' + INSTALL_GUIDE}
    else:
        found = pick_unreal(**find_kw)
        if not found:
            return {'ok': False, 'error': 'unreal_not_found', 'guide': INSTALL_GUIDE}
    name = slug(world.get('name', 'World'))
    files = ue5_project(world, engine=found['version'], with_binaries=True, library=library, compiler=compiler,
                        prebuilt_dir=prebuilt_dir)
    mode = runtime_mode(found['version'], True, compiler, prebuilt_dir)
    os.makedirs(out_dir, exist_ok=True)
    write_project(files, out_dir)
    up = os.path.abspath(os.path.join(out_dir, f'{name}.uproject'))
    script = os.path.abspath(os.path.join(out_dir, 'Content', 'Python', 'stark_build_level.py'))
    argv = [found['editor'], up]
    res = {'ok': True, 'uproject': up, 'script': script, 'editor': found['editor'], 'version': found['version'],
           'runtime': mode, 'argv': argv, 'pid': None, 'launched': False,
           'headless': [found.get('cmd') or found['editor'], up, '-run=pythonscript', f'-script={script}',
                        '-unattended', '-nosplash', '-nop4']}
    if mode == 'disabled':
        res['note'] = ('Gameplay runtime is off: no prebuilt Stark World Engine Runtime for UE ' + found['version'] +
                       ' in this copy and no Visual Studio C++ found. The levels still build. '
                       'See README_UE5.md in the project.')
    if launch:
        kw = {'cwd': out_dir, 'close_fds': True, 'stdin': subprocess.DEVNULL, 'stdout': subprocess.DEVNULL,
              'stderr': subprocess.DEVNULL}
        if sys.platform == 'win32':
            kw['creationflags'] = 0x00000008 | 0x00000200     # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        try:
            proc = (popen or subprocess.Popen)(argv, **kw)
            res.update(pid=getattr(proc, 'pid', None), launched=True)
        except OSError as e:
            return {'ok': False, 'error': 'launch_failed', 'guide': f'Could not start Unreal: {e}'}
    return res


def open_unreal_action(world, export_dir, tier='pro', **kw):
    """Pure hook for a POST endpoint; returns (http_status, json_body).

    Wiring in studio_app.py: see exporters_PROPOSED_CHANGES.md (route /api/open_unreal + button).
    Status: 200 launched; 402 tier is not pro/studio; 400 2D world; 404 no UE5 found (body has 'guide')."""
    if tier not in ('pro', 'studio'):
        return 402, {'ok': False, 'error': 'tier', 'guide': 'Open in Unreal is part of the Pro and Studio tiers.'}
    try:
        world = gate(world)
    except ValueError as e:
        return 400, {'ok': False, 'error': 'child_safety', 'guide': str(e)}
    res = open_in_unreal(world, export_dir, **kw)
    if res['ok']:
        return 200, res
    return {'2d': 400, 'child_safety': 400, 'unreal_not_found': 404, 'editor_missing': 404}.get(res['error'], 500), res
