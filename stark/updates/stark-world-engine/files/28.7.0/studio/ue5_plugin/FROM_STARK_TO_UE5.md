## From Stark World Engine to Unreal Engine 5

**Status, plainly:** the Unreal bridge has passed every check we can run without Unreal: unit tests, a fake-Unreal
run of every editor script, and a static check of the C++ plugin. **We have not yet opened it in a real Unreal Engine 5
install.** Until that test is done, treat this path as a preview. The Godot 4 path is the one we have verified end to end.

### What you need
- Unreal Engine **5.4 or newer**, installed through the Epic Games Launcher (free; Epic's licence terms apply).
- Nothing else for a normal buyer: the Stark World Engine Runtime plugin ships **prebuilt** for each supported engine version, so you
  do not need Visual Studio or a C++ compiler. If your engine version has no prebuilt plugin yet, the project still opens
  and builds the level; gameplay then needs a one-time compile (Visual Studio 2022, "Game development with C++").

### One click
In Stark World Engine press **Open in Unreal Engine**. Studios finds your newest UE 5.4+ install, writes the project and
opens it. On the first open the project builds itself (this takes a few minutes; later opens are instant):

- a World Partition map per level, with Landscape terrain (heights match your Stark World Engine world exactly) and an automatic
  landscape material (grass / rock on slopes / sand by the water / snow up high)
- Sky Atmosphere, Volumetric Clouds, Exponential Height Fog, a sun set to your time of day, Lumen lighting and Virtual
  Shadow Maps
- a water surface (using the Water plugin's lake material when the plugin is on)
- trees, rocks and grass as Nanite instanced foliage, plus a PCG graph you can tweak
- every NPC, enemy, item, chest, door, portal and checkpoint as a working gameplay actor
- your quests, dialogue, items, enemies and levels as **Data Assets** you can edit in the editor
- sounds synthesized from your Stark World Engine sound settings

Press **Play**: walk, talk, take quests, fight, pick things up, travel through portals, save and load.
**Stark World Engine > Rebuild from Stark World Engine** rebuilds after you change the world in Studios; it never overwrites the swap lists you
edited.

### What carries over exactly
Quests (collect / defeat / talk / reach / escort, chained and final), dialogue with conditions and actions, items and
equipment, enemy kinds and difficulty, XP and levels, abilities, gold, checkpoints, portals between levels, the save
format, the terrain shape, time of day and mood colours.

### What is different or up to you
- **Art.** Stark World Engine proxies (simple shapes) stand in for art. Swap them for your own models, Fab or Quixel Megascans
  assets in **Content/Python/proxy_swap_map.csv**, or set *Art Mesh* / *Visual Class* on any actor. Then run
  **Stark World Engine > Swap proxies for real assets**. Assets you imported into Stark World Engine (glTF) come across through Interchange,
  with their credits in CREDITS.md.
- **Characters.** NPCs have a *Visual Class* slot that is ready for MetaHumans (see metahuman_slots.csv). MetaHumans are
  optional and are made with Epic's own tools under Epic's terms.
- **2.5D (side-view) chapters** inside a 3D game become blocky 2.5D levels. A whole 2D game exports to Godot or the
  HTML5 cartridge, not to Unreal.
- **Weather particles** (rain / snow) are not built automatically in Unreal; add a Niagara system where you want one.
- **Packaging** a game for players uses Unreal's own Package Project. Packaging may need Visual Studio, depending on
  your engine setup.
- The look depends on your art and your Unreal settings. Stark World Engine gives you a playable, well-lit starting point; it does
  not make your game look like a big-studio release.

### Child safety
Every export passes the Stark World Engine child-safety checker first. Worlds where a child or teen character is an enemy, a
combat target, captured or romanced are refused. Inside Unreal the runtime also never lets a child or teen take damage
or be targeted, even if the data is edited by hand.

### If something goes wrong
- *"Unreal Engine not found"*: install UE 5.4+ from the Epic Games Launcher, then press the button again, or use
  **Open in Godot** instead.
- The build log is in **Saved/Stark/build_report.json** inside the project.
- To rebuild from the command line, run **BUILD_LEVEL_HEADLESS.bat** in the project folder.

Unreal and Unreal Engine are trademarks of Epic Games, Inc. Stark World Engine is not affiliated with or endorsed by Epic Games.
