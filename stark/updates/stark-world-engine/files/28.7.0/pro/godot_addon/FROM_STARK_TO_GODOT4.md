## From Stark World Engine to Godot 4

**Status, plainly:** this is the verified path. Every example world was exported and played from start to finish by a
scripted player in real Godot 4 (headless): every quest done, every level visited, save and load checked.

### What you need
- Godot **4.2 or newer** (free, MIT licence; we test with Godot 4.7.2). If you do not have it, Stark World Engine can download the official Godot
  build for you, but only after you say yes. The download is checked against Godot's published checksums.

### One click
Press **Open in Godot** in Stark World Engine. The project opens in the Godot editor; press **F5** to play.
**Project > Tools > Stark World Engine: rebuild terrain and scenery** refreshes the terrain and scenery after you edit them.

### What you get
- `main.tscn` (the first level) and `levels/level_NN.tscn`, real Godot scenes you can open and edit
- heightmap terrain with collision and a blended grass / rock / sand / snow shader
- trees, rocks, grass and lamps as MultiMesh scenery, water, sky, fog, glow and soft global lighting
- a player you control, NPCs who talk, enemies who fight, items, chests, locked doors, portals and checkpoints
- autoloads for the game rules: `StarkGame`, `StarkInventory`, `StarkQuests`, `StarkDialogue`, `StarkSave`, `StarkUI`
- 2D games export as side-view platformer scenes with the same quest and dialogue systems

### What carries over exactly
Quests, dialogue (conditions, actions, branches), items and equipment, enemy kinds and difficulty, XP, abilities,
gold, checkpoints, portals, saves, terrain shape, time of day, mood colours, weather and sounds.

### What is up to you
- **Art.** Proxies (simple shapes) stand in for art. Assets you imported into Stark World Engine (glTF, textures, HDRI skies) are
  copied in and used automatically. Otherwise drop a `.glb` or `.tscn` into an NPC's or enemy's *Visual Scene* slot,
  or into the art slots under the `Scenery` node. Credits go to `CREDITS.md`.
- **Export to players** uses Godot's own Project > Export with Godot's export templates.
- How good it looks depends on your art and settings. Stark World Engine gives you a playable, well-lit starting point.

### Child safety
Every export passes the Stark World Engine child-safety checker first. Inside Godot the runtime also keeps children and teens out of
combat, targeting, capture and romance, even if a scene or data file is edited by hand.

### Checking a project yourself
`VERIFY_IN_GODOT.bat` in the project folder runs the scripted playthrough and prints the result.
