from typing import List, Dict, Optional
import os
import time
import logging
import struct
import math
from typing import List, Tuple, Optional, Dict, Any
import yaml

from MemoryManager import MemoryManager


class EldenRingGame:
    """interface providing a high-level API for game state and actions.
    It uses MemoryManager for low-level memory access and abstracts away pointer chains.
    """

    def __init__(self, process_name: str = "eldenring.exe", config: Dict[str, Any] = None):
        if config is None:
            config = {}

        self.process_name = process_name
        self.mem = MemoryManager(process_name=process_name)

        if not self.mem.attach():
            logging.error(
                "Failed to attach to Elden Ring process. Ensure the game is running.")
            raise RuntimeError(
                "Failed to initialize EldenRingGame: MemoryManager attachment failed.")

        self.BOSS = int(config.get("BOSS", 1))
        self._player_max_hp_val: Optional[int] = None

        self._arena_meta_db: Dict[int, Dict[str, Any]] = {}
        self._bonfires_db: Dict[str, int] = {}
        self._wcm_offsets: Dict[str, int] = {}
        self._char_offsets: Dict[str, int] = {}

        self._load_game_configs()

        self._boss_param_id: Optional[int] = None
        self._boss_stats_addr: int = 0
        self._boss_comp_addr: int = 0
        self._boss_transform_addr: int = 0
        self._boss_last_resolve: float = 0.0
        self._boss_resolve_retry_sec: float = 1.
        

    def _safe_load_yaml(self, path: str) -> Dict[str, Any]:
        if not os.path.isfile(path):
            logging.warning(f"YAML config not found at: {path}")
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logging.error(f"Failed to load or parse YAML at {path}: {e}")
            return {}

    def _load_game_configs(self):
        logging.info("Loading game-specific configurations...")
        arena_data = self._safe_load_yaml(
            os.path.join("config", "arenas.yaml"))
        for entry in arena_data.get("arenas", []):
            if "id" in entry:
                self._arena_meta_db[int(entry["id"])] = entry

        bonfire_data = self._safe_load_yaml(
            os.path.join("config", "bonfires.yaml"))
        if isinstance(bonfire_data, dict):
            self._bonfires_db = {str(k): int(v)
                                 for k, v in bonfire_data.items()}

        addresses_yaml = self._safe_load_yaml(
            os.path.join("config", "addresses.yaml"))
        self._wcm_offsets = addresses_yaml.get("worldchrman", {})
        self._char_offsets = addresses_yaml.get("character", {})

    def close(self):
        self.mem.detach()
        logging.info("EldenRingGame closed: detached from process.")

    @property
    def player_hp(self) -> Optional[float]:
        addr, current_hp = self.mem.read_value("PlayerHP")
        if not addr or current_hp is None:
            return None
        _, max_hp = self.mem.read_value("PlayerMaxHP")
        if max_hp is None or max_hp <= 0:
            return None

        self._player_max_hp_val = max_hp
        return max(0.0, min(1.0, current_hp / max_hp))

    @property
    def player_max_hp(self) -> Optional[int]:
        """Returns the raw integer value of player's maximum HP."""
        if self._player_max_hp_val is None:
            _, max_hp = self.mem.read_value("PlayerMaxHP")
            if max_hp is not None:
                self._player_max_hp_val = max_hp
        return self._player_max_hp_val

    @property
    def player_stamina(self) -> Optional[float]:
        addr, current_sp = self.mem.read_value("PlayerSP")
        if not addr or current_sp is None: return None
        _, max_sp = self.mem.read_value("PlayerMaxSP")
        if max_sp is None or max_sp <= 0:
            return None
        return max(0.0, min(1.0, current_sp / max_sp))

    @property
    def player_position(self) -> Optional[Tuple[float, float, float]]:
        addr, player_xyz_bytes = self.mem.read_value("PlayerXYZA")
        if not addr or player_xyz_bytes is None or len(player_xyz_bytes) < 12:
            return None
        try:
            x, y, z = struct.unpack("<fff", player_xyz_bytes[:12])
            return (x, y, z)
        except Exception as e:
            logging.error(f"Error unpacking player position: {e}")
            return None

    @property
    def player_flask_count(self) -> Optional[int]:
        try:
            inventory_items = self.get_inventory_items()
            if not inventory_items:
                return 0
            FLASK_IDS = set(range(1000, 1026))
            return sum(item["quantity"] for item in inventory_items if item["id"] in FLASK_IDS)
        except Exception as e:
            logging.error(f"Failed to get player flask count: {e}")
            return 0

    @property
    def boss_animation_id(self) -> Optional[int]:
        """Returns the current animation ID of the boss."""
        if not self._boss_comp_addr:
            return None

        # This offset is typically from the character's base/component address
        anim_id_addr = self._boss_comp_addr + \
            self._char_offsets.get("animation_id_off", 0)
        anim_id = self.mem.read_int(anim_id_addr)
        return anim_id

    @property
    def boss_is_staggered(self) -> bool:
        _, staggered_flag_val = self.mem.read_value("BossStaggerFlag")  #placeholder  - there is not boss stagger read yet
        return bool(staggered_flag_val and staggered_flag_val > 0)

    def read_last_grace(self) -> int:
        addr, grace_id = self.mem.read_value("LastGrace")
        return grace_id if grace_id is not None else -1
    
    def _write_last_grace(self, grace_id: int):
        addr, _ = self.mem.resolve_address("LastGrace")
        if not addr:
            return False
        return self.mem.write_int(addr, grace_id)

    @property
    def allow_player_death(self) -> Optional[bool]:
        """Reads the flag that allows/prevents player death."""
        addr, val = self.mem.read_value("AllowPlayerDeath")
        if val is None:
            return None
        # In the game's memory, 0 means death is allowed. 1 means it is prevented.
        return val == 0

    @allow_player_death.setter
    def allow_player_death(self, enabled: bool):
        """Sets the flag that allows/prevents player death."""
        addr = self.mem.resolve_address("AllowPlayerDeath")
        if not addr:
            logging.error("Could not resolve AllowPlayerDeath address to write.")
            return
        # If enabled (death is allowed), write 0. If disabled, write 1.
        value_to_write = 0 if enabled else 1
        self.mem.write_int(addr, value_to_write)

    @property
    def player_gravity(self) -> Optional[bool]:
        """Reads the player's gravity flag (bit 6)."""
        addr, val = self.mem.read_value("PlayerGravity")
        if val is None:
            return None
        # Gravity is controlled by the 6th bit of this integer.
        return (val & (1 << 6)) != 0

    @player_gravity.setter
    def player_gravity(self, enabled: bool):
        """Sets the player's gravity flag (bit 6)."""
        addr = self.mem.resolve_address("PlayerGravity")
        if not addr:
            logging.error("Could not resolve PlayerGravity address to write.")
            return
        self.mem.write_bit(addr, 6, enabled)

    @player_position.setter
    def player_position(self, pos: Tuple[float, float, float]):
        """Writes the player's XYZ coordinates directly to memory."""
        addr = self.mem.resolve_address("PlayerXYZA")
        if not addr:
            logging.error("Could not resolve PlayerXYZA address to write position.")
            return
        try:
            x, y, z = pos
            # Write coordinates as three separate float values
            self.mem.write_bytes(addr, struct.pack("<fff", x, y, z))
            logging.info(f"Set player position to ({x:.2f}, {y:.2f}, {z:.2f})")
        except Exception as e:
            logging.error(f"Error writing player position: {e}")

    def teleport_player(self, x: float, y: float, z: float):
        """
        Safely teleports the player to the given coordinates by disabling death and gravity,
        writing the new coordinates, and then re-enabling them.
        """
        logging.info(f"Initiating safe teleport to ({x:.2f}, {y:.2f}, {z:.2f})...")

        # 1. Store original states and disable flags
        original_death_allowed = self.allow_player_death
        original_gravity_enabled = self.player_gravity
        
        logging.debug("Disabling player death and gravity for teleport.")
        self.allow_player_death = False
        self.player_gravity = False

        # Give the game a moment to process the flag changes
        time.sleep(0.05)

        # 2. Set the new position
        self.player_position = (x, y, z)

        # Wait for the position to 'settle' in the game world
        time.sleep(0.1)

        # 3. Restore original states
        logging.debug("Re-enabling player death and gravity.")
        if original_gravity_enabled is not None:
            self.player_gravity = original_gravity_enabled
        else:
            self.player_gravity = True  # Default to gravity ON if it couldn't be read

        if original_death_allowed is not None:
            self.allow_player_death = original_death_allowed
        else:
            self.allow_player_death = True # Default to death ALLOWED if it couldn't be read

        logging.info("Safe teleport complete.")

    def warp(self, bonfire_name_or_id: Any) -> bool:
        if not self.mem.attached:
            logging.error("Cannot warp, MemoryManager not attached to game.")
            return False

        target_bonfire_id = None
        if isinstance(bonfire_name_or_id, int):
            target_bonfire_id = bonfire_name_or_id
        elif isinstance(bonfire_name_or_id, str):
            target_bonfire_id = self._bonfires_db.get(bonfire_name_or_id)

        if target_bonfire_id is None:
            logging.error(f"Bonfire '{bonfire_name_or_id}' not found.")
            return False

        logging.info(f"Initiating warp to bonfire ID: {target_bonfire_id}")

        # --- Step 1: Get all necessary addresses using our reliable resolver ---
        lua_warp_addr = self.mem.resolve_address("WarpFunction")
        if not lua_warp_addr:
            logging.error("WarpFunction address not resolved.")
            return False

        cs_lua_event_manager_addr = self.mem.resolve_address("CSLuaEventManager")
        if not cs_lua_event_manager_addr:
            logging.error("CSLuaEventManager address not resolved.")
            return False


        # --- START OF FINAL FIX: Retry Loop ---
        max_retries = 10
        retry_delay = 0.2  # Wait 200ms between tries
        script_imitation_ptr = None
        proxy_ptr = None

        logging.info(f"Attempting to read Lua event pointers from base: {hex(cs_lua_event_manager_addr)}")

        script_imitation_ptr = self.mem.read_pointer(cs_lua_event_manager_addr + 0x18)
        proxy_ptr = self.mem.read_pointer(cs_lua_event_manager_addr + 0x08)

        warp_id_arg = target_bonfire_id - 1000

        shellcode = (
            bytes([0x48, 0x83, 0xEC, 0x48])              # sub rsp, 48h (Allocate stack space)
            + bytes([0x48, 0xB9])                        # mov rcx, ...
            + struct.pack("<Q", script_imitation_ptr)   # ... Arg 1
            + bytes([0x48, 0xBA])                        # mov rdx, ...
            + struct.pack("<Q", proxy_ptr)               # ... Arg 2
            + bytes([0x41, 0xB8])                        # mov r8d, ... (41 B8 is mov r8d, imm32)
            + struct.pack("<i", warp_id_arg)             # ... Arg 3 (as a 32-bit signed int)
            + bytes([0x48, 0xB8])                        # mov rax, ...
            + struct.pack("<Q", lua_warp_addr)           # ... the function to call
            + bytes([0xFF, 0xD0])                        # call rax
            + bytes([0x48, 0x83, 0xC4, 0x48])            # add rsp, 48h (Cleanup stack)
            + bytes([0xC3])                              # ret
        )

        logging.info( f"Injecting and executing CORRECT warp shellcode to call LuaWarp at {hex(lua_warp_addr)}")
        return self.mem.execute_shellcode(shellcode)
            

    def reset_arena(self, arena_id: int, **kwargs) -> None:
        if not self.mem.attached:
            logging.error( "Cannot reset arena, MemoryManager not attached to game.")
            return

        logging.info(f"Resetting to arena ID: {arena_id}")
        meta_entry = self._arena_meta_db.get(arena_id)
        if not meta_entry:
            logging.error(f"No metadata found for arena ID: {arena_id}. Cannot reset.")
            return

        bonfire_key = meta_entry.get("nearest_bonfire_key")
        if not bonfire_key:
            logging.error(f"Arena {arena_id} has no 'nearest_bonfire_key'. Cannot set context.")
            return

        target_bonfire_id = self._bonfires_db.get(bonfire_key)
        if not target_bonfire_id:
            logging.error(f"Bonfire key '{bonfire_key}' not found in bonfires.yaml.")
            return

        current_grace_id = self.read_last_grace()

        if current_grace_id != target_bonfire_id:
            logging.info(f"Current grace ID ({current_grace_id}) does not match target ({target_bonfire_id}). Initiating warp.")
            if not self.warp(target_bonfire_id):
                logging.error("Warp initiation failed. Cannot proceed with reset.")
                return

            logging.info("Waiting for warp to complete (loading screen)...")
            time.sleep(10)
            logging.info("Finished waiting for warp.")
        else:
            logging.info(f"Already at the correct bonfire ID: {target_bonfire_id}. No warp needed.")

        spawn = meta_entry.get("player_spawn", {})
        x, y, z = spawn.get("x", 0.0), spawn.get("y", 0.0), spawn.get("z", 0.0)
        #cos, sin = spawn.get("cos", 1.0), spawn.get("sin", 0.0)
        map_id = meta_entry.get("map_id")

        if not map_id:
            logging.error( f"No 'map_id' for arena {arena_id}. Cannot teleport.")
            return

        self.teleport_player(x, y, z)

        self._boss_param_id = meta_entry.get("boss", {}).get("char_param_id")
        if isinstance(self._boss_param_id, str) and ":" in self._boss_param_id:
            self._boss_param_id = int(self._boss_param_id.split(":")[0])

        logging.info(f"Set target boss Param ID to {self._boss_param_id} for this arena.")
        self._boss_stats_addr = 0
        self._boss_last_resolve = 0.0

    @property
    def boss_hp(self) -> Optional[float]:
        if not self.mem.attached:
            return None
        now = time.time()
        if not self._boss_stats_addr and (now - self._boss_last_resolve > self._boss_resolve_retry_sec):
            self._boss_last_resolve = now
            self._resolve_boss_stats_address()

        if self._boss_stats_addr:
            try:
                cur = self.mem.read_int(self._boss_stats_addr)
                mxx = self.mem.read_int(self._boss_stats_addr + 4)
                if cur is None or mxx is None or mxx <= 0:
                    self._boss_stats_addr = 0
                    return None
                return max(0.0, min(1.0, float(cur) / float(mxx)))
            except Exception:
                self._boss_stats_addr = 0
                return None
        return None

    def _resolve_boss_stats_address(self) -> None:
        """
        REWRITTEN: This method now correctly uses the MemoryManager's public API
        to find the true base address of WorldChrMan before scanning for the boss.
        """
        if not self.mem.attached or not self._boss_param_id:
            return
        
        wcm_ptr = self.mem.resolve_address("WorldChrMan")
        if not wcm_ptr:
            logging.warning(
                "Could not resolve WorldChrMan's true base address for boss scan.")
            return

        try:
            begin = self.mem.read_longlong( wcm_ptr + self._wcm_offsets.get("character_list_begin_off", 0))
            end = self.mem.read_longlong( wcm_ptr + self._wcm_offsets.get("character_list_end_off", 0))

            if begin is None or end is None or end <= begin:
                logging.warning("Character list begin/end not resolved or invalid.")
                return

            logging.info(f"Scanning for boss with Param ID {self._boss_param_id} in list from {hex(begin)} to {hex(end)}...")

            p = begin
            count = 0
            while p < end:
                count += 1
                ent = self.mem.read_longlong(p)
                p += 8
                if ent is None or ent < 0x10000:
                    continue

                # character parameter ID is at +0x60
                pid = self.mem.read_int(ent + 0x60)
                if pid != self._boss_param_id:
                    continue

                logging.info(f"Found boss with matching PID at entity address {hex(ent)} after {count} scans.")

                comp_off = self._char_offsets.get("comp_190_off", 0)
                comp = self.mem.read_longlong(ent + comp_off)
                if not comp:
                    logging.warning(f"Could not read component pointer from {hex(ent + comp_off)}")
                    continue

                stats_off = self._char_offsets.get("stats_qword_off", 0)
                stats = self.mem.read_longlong(comp + stats_off)
                if stats:
                    self._boss_stats_addr = stats
                    logging.info(f"Resolved boss stats address to {hex(stats)}")
                    self._boss_comp_addr = comp

                    transform_off = self._char_offsets.get("transform_68_off", 0)
                    self._boss_transform_addr = self.mem.read_longlong(
                        comp + transform_off)
                    logging.info(f"Resolved boss transform address to {hex(self._boss_transform_addr)}")
                    return 

            logging.warning(
                f"Finished scanning {count} entities. Boss with Param ID {self._boss_param_id} not found.")
        except Exception as e:
            logging.error(f"Error while scanning for boss entity: {e}")

    @property
    def boss_position(self) -> Optional[Tuple[float, float, float]]:
        if not self.mem.attached or not self._boss_transform_addr:
            return None
        try:
            pos_xyz_off = self._char_offsets.get("pos_xyz_off", 0)
            addr = self._boss_transform_addr + pos_xyz_off
            x = self.mem.read_float(addr)
            y = self.mem.read_float(addr + 4)
            z = self.mem.read_float(addr + 8)
            if x is None or y is None or z is None:
                return None
            return (x, y, z)
        except Exception as e:
            logging.error(f"Error reading boss position: {e}")
            return None

    @property
    def distance_to_boss(self) -> Optional[float]:
        player_pos = self.player_position
        boss_pos = self.boss_position
        if player_pos is None or boss_pos is None:
            return None
        try:
            return math.sqrt(sum([(a - b) ** 2 for a, b in zip(player_pos, boss_pos)]))
        except Exception as e:
            logging.error(f"Error calculating distance to boss: {e}")
            return None

    @property
    def find_item_in_player_inventory(
        self,
        mem,
        target_base_id: int,
        inv2_index: int = 0,
        *,
        equip_path_key: str = "EquipInventoryData_Player",
        game_data_man_key: str = "GameDataMan",
        equip_offset_from_playergame: int = 0x538,
    ) -> List[Dict]:
        """
        Search player's inventory for entries matching target_base_id.

        Args:
            mem: your memory class instance (must provide read_value, read_longlong, read_int, and _bases_static).
            target_base_id: the base item id to search for (low 28 bits).
            inv2_index: which sub-list to check (0 = player inventory).
            equip_path_key: address key in addresses.yaml that resolves to EquipInventoryData pointer (preferred).
            game_data_man_key: name in mem._bases_static containing the GameDataMan static address.
            equip_offset_from_playergame: offset inside PlayerGameData to read EquipInventoryData pointer (0x538 by your config).

        Returns:
            A list of dicts with keys:
            index, ga_handle, raw_itemid, type_code, base_id, quantity, entry_address
        """
        # Constants matching the Lua child script / your config
        ENTRY_SIZE = 0x18
        LIST_PTR_OFFSET = 0x10
        COUNT_OFFSET = 0x18
        KEY_OFFSET_STRIDE = 0x10
        FIELD_HANDLE = 0x00
        FIELD_RAW_ITEMID = 0x04
        FIELD_QUANTITY = 0x08

        matches: List[Dict] = []

        try:
            resolved_addr, resolved_val = self.mem.read_value(equip_path_key)
        except Exception:
            resolved_addr, resolved_val = None, None

        equip_inventory_data = None

        if resolved_val:
            equip_inventory_data = resolved_val

        if not equip_inventory_data:
            return matches

        # 2) Read inventory list pointer and reported count for the chosen inv2_index
        try:
            keyOffset = inv2_index * KEY_OFFSET_STRIDE
            inventory_list_ptr = mem.read_longlong(
                equip_inventory_data + LIST_PTR_OFFSET + keyOffset)
            inventory_num_reported = mem.read_int(
                equip_inventory_data + COUNT_OFFSET + keyOffset)
        except Exception:
            return matches

        if not inventory_list_ptr or (inventory_num_reported is None) or inventory_num_reported <= 0:
            return matches

        # 3) Iterate with a safe cap
        cap = min(max(inventory_num_reported, 0), 4096)
        for i in range(cap):
            entry_addr = inventory_list_ptr + i * ENTRY_SIZE
            try:
                ga_handle = mem.read_int(entry_addr + FIELD_HANDLE)
            except Exception:
                # reading failed (invalid memory); stop scanning
                break

            if ga_handle == 0:
                continue

            try:
                raw_itemid = mem.read_int(entry_addr + FIELD_RAW_ITEMID)
                qty = mem.read_int(entry_addr + FIELD_QUANTITY)
            except Exception:
                continue

            type_code = (raw_itemid & 0xF0000000) >> 28
            base_id = raw_itemid & 0x0FFFFFFF

            # match either by base_id (common) or exact raw id
            if base_id == target_base_id or raw_itemid == target_base_id:
                matches.append({
                    "index": i,
                    "ga_handle": ga_handle,
                    "raw_itemid": raw_itemid,
                    "type_code": type_code,
                    "base_id": base_id,
                    "quantity": qty,
                    "entry_address": entry_addr,
                })

            # stop early if we've already found as many as reported
            if len(matches) >= inventory_num_reported:
                break

        return matches

    def get_inventory_items(self, inv_index: int = 0) -> List[Dict]:
        """
        REWRITTEN: Returns a list of all items in the player's inventory.
        This now correctly uses the public API of MemoryManager.
        """
        items: List[Dict] = []

        ENTRY_SIZE = 0x18
        LIST_PTR_OFFSET = 0x10
        COUNT_OFFSET = 0x18
        KEY_OFFSET_STRIDE = 0x10
        FIELD_HANDLE = 0x00
        FIELD_RAW_ITEMID = 0x04
        FIELD_QUANTITY = 0x08

        _, equip_inventory_data = self.mem.read_value("EquipInventoryData_Player")
        if not equip_inventory_data:
            logging.warning("Could not resolve EquipInventoryData_Player pointer.")
            return items

        keyOffset = inv_index * KEY_OFFSET_STRIDE
        inventory_list_ptr = self.mem.read_longlong(
            equip_inventory_data + LIST_PTR_OFFSET + keyOffset)
        inventory_count_reported = self.mem.read_int(
            equip_inventory_data + COUNT_OFFSET + keyOffset)

        if not inventory_list_ptr or not inventory_count_reported or inventory_count_reported <= 0:
            return items

        # Iterate with a safe cap
        cap = min(inventory_count_reported, 4096)
        for i in range(cap):
            entry_addr = inventory_list_ptr + i * ENTRY_SIZE
            try:
                ga_handle = self.mem.read_int(entry_addr + FIELD_HANDLE)
                if ga_handle == 0:
                    continue

                raw_id = self.mem.read_int(entry_addr + FIELD_RAW_ITEMID)
                quantity = self.mem.read_int(entry_addr + FIELD_QUANTITY)

                type_code = (raw_id & 0xF0000000) >> 28
                base_id = raw_id & 0x0FFFFFFF

                items.append({
                    "id": base_id,
                    "raw_id": raw_id,
                    "quantity": quantity or 0,
                    "type_code": type_code,
                    "entry_address": entry_addr
                })
            except Exception:
                continue
        return items
