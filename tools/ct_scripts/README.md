# Cheat Engine scripts

Reference material

These are the Cheat Engine scripts the memory work in `eldenrl/` was reverse
engineered from. They are extracted logic stemming from the CE tables

| Source | Scripts |
| --- | --- |
| Elden Ring All-in-One table by Hexinton | `hexinton_startup_enable.cea`, `addresses_export.lua`, `npc_manager.lua`, `targeted_enemy.lua`, `reset_all_bosses.cea`, `faster_respawn.cscript` |
| ER TGA table | `warp_script_tga.cea`, `warp_invoke_tga.cea`, `warp_code_tga_dependency.cea` |
| Derived from them| `aob_teleport.cea`, `copy_current_coords.cea`, `invoke_tp.cea`, `teleport_map_relative.cea` |

The tables themselves (`.ct`) are not here - u can find them publicly

`TeleportManager` reimplements `copy_current_coords.cea` through `xGlobal` / `zGlobal` / `yGlobal`, and
`teleport.py` does the coordinate arithmetic from `invoke_tp.cea`
