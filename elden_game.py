import logging
import yaml
import os
import math
from typing import Optional, Tuple, Dict, Any

from memory_manager import MemoryManager
from teleport import TeleportManager

class EldenRingGame:
    """
    Provides a high-level API to interact with the Elden Ring game,
    including dynamic boss detection and state tracking.
    """

    def __init__(self, config: dict, arenas_path: str = "arenas.yaml"):
        self.config = config
        self.mem = MemoryManager(self.config.get("PROCESS_NAME", "eldenring.exe"))
        if not self.mem.attach():
            raise RuntimeError(f"Failed to attach to {self.config.get('PROCESS_NAME', 'eldenring.exe')}. Is the game running?")
        
        config_dir = os.path.dirname(arenas_path)
        addresses_path = os.path.join(config_dir, "addresses.yaml")
        
        self.mem.load_addresses(addresses_path)
        self.teleporter = TeleportManager(self.mem)
        self.arenas: Dict[int, Dict[str, Any]] = {}
        self._load_arenas(arenas_path)
        
        self.boss_entity_addr: Optional[int] = None

        # Apply game patches on initialization
        self.set_unlimited_consumables(True)

        logging.info("EldenRingGame API initialized.")

    def set_unlimited_consumables(self, enabled: bool):
        """
        Patches the game memory to grant unlimited consumables using CHR_DBG_FLAGS.
        This is based on the user-provided script: `CHR_DBG_FLAGS+3: db 01`.
        """
        logging.info(f"Setting unlimited consumables to: {enabled}")
        chr_dbg_flags_addr = self.mem._get_static_var_address("ChrDbgFlags")

        if not chr_dbg_flags_addr:
            logging.error("Could not find address for CHR_DBG_FLAGS. Cannot set unlimited consumables.")
            return

        address_to_patch = chr_dbg_flags_addr + 3
        value_to_write = 1 if enabled else 0

        if self.mem.write_byte(address_to_patch, value_to_write):
            logging.info(f"Successfully wrote {value_to_write} to {hex(address_to_patch)} for unlimited consumables.")
        else:
            logging.error(f"Failed to write to {hex(address_to_patch)} for unlimited consumables.")

    def _load_arenas(self, file_path: str):
        """Loads arena configurations from the YAML file."""
        try:
            with open(file_path, "r") as f:
                arena_data = yaml.safe_load(f)
                for arena in arena_data.get("arenas", []):
                    self.arenas[arena["id"]] = arena
            logging.info(f"Loaded {len(self.arenas)} arenas from '{file_path}'.")
        except FileNotFoundError:
            logging.error(f"Arena configuration file not found at '{file_path}'.")
        except Exception as e:
            logging.error(f"Error loading arena configuration: {e}")

    def find_boss_entity(self, target_param_id: int) -> bool:
        world_chr_man = self.mem._get_address_from_config("WorldChrMan")
        if not world_chr_man:
            return False
        try:
            list_start_ptr = world_chr_man + 0x1F1B8
            list_end_ptr = world_chr_man + 0x1F1C0
            start_addr = self.mem.read_longlong(list_start_ptr)
            end_addr = self.mem.read_longlong(list_end_ptr)
            if not start_addr or not end_addr or start_addr >= end_addr:
                return False
            current_addr = start_addr
            while current_addr < end_addr:
                entity_ptr = self.mem.read_longlong(current_addr)
                if entity_ptr and entity_ptr > 0xFFFF:
                    param_id = self.mem.read_int(entity_ptr + 0x60)
                    if param_id == target_param_id:
                        self.boss_entity_addr = entity_ptr
                        logging.info(f"Boss with ParamID {target_param_id} found at {hex(entity_ptr)}")
                        return True
                current_addr += 8
        except Exception as e:
            logging.error(f"Error while scanning for boss entity: {e}")
        self.boss_entity_addr = None
        return False

    def get_boss_hp(self) -> Optional[Tuple[int, int]]:
        if not self.boss_entity_addr:
            return None
        try:
            comp_ptr = self.mem.read_longlong(self.boss_entity_addr + 0x190)
            if not comp_ptr: return None
            stats_ptr = self.mem.read_longlong(comp_ptr + 0x0)
            if not stats_ptr: return None
            current_hp = self.mem.read_int(stats_ptr + 0x138)
            max_hp = self.mem.read_int(stats_ptr + 0x13C)
            if current_hp is not None and max_hp is not None:
                return current_hp, max_hp
        except Exception:
            return None
        return None

    def set_boss_position(self, x: float, y: float, z: float):
        if not self.boss_entity_addr:
            return
        try:
            comp_ptr = self.mem.read_longlong(self.boss_entity_addr + 0x190)
            if not comp_ptr: return
            transform_ptr = self.mem.read_longlong(comp_ptr + 0x68)
            if not transform_ptr: return
            self.mem.write_float(transform_ptr + 0x70, x)
            self.mem.write_float(transform_ptr + 0x74, y)
            self.mem.write_float(transform_ptr + 0x78, z)
        except Exception as e:
            logging.error(f"Failed to set boss position: {e}")

    def get_entity_position(self, entity_addr: int) -> Optional[Tuple[float, float, float]]:
        """Gets the world coordinates of any game entity, handling the game's Y/Z axis swap."""
        if not entity_addr:
            return None
        try:
            comp_ptr = self.mem.read_longlong(entity_addr + 0x190)
            if not comp_ptr: return None
            transform_ptr = self.mem.read_longlong(comp_ptr + 0x68)
            if not transform_ptr: return None
            
            # Read coordinates based on memory layout (X, Z, Y)
            x = self.mem.read_float(transform_ptr + 0x70)
            z = self.mem.read_float(transform_ptr + 0x74) # This is the Z-axis (depth)
            y = self.mem.read_float(transform_ptr + 0x78) # This is the Y-axis (vertical)
            
            if x is not None and y is not None and z is not None:
                # Return in standard (X, Y, Z) order for calculations
                return x, y, z
        except Exception as e:
            logging.error(f"Exception in get_entity_position for address {hex(entity_addr)}: {e}")
        return None

    def get_distance_to_boss(self) -> Optional[float]:
        player_pos = self.get_player_position()
        boss_pos = self.get_entity_position(self.boss_entity_addr)
        
        if not player_pos or not boss_pos:
            return None
            
        distance = math.sqrt(sum([(a - b) ** 2 for a, b in zip(player_pos, boss_pos)]))
        return distance
    
    def is_in_cutscene(self) -> bool:
        _, value = self.mem.read_pointer("InCutscene")
        return value == 1

    def set_invisibility(self, enabled: bool):
        INVISIBILITY_FLAG = 0x400
        current_flags = self.mem.read_static_var("ChrDbgFlags")
        if current_flags is None:
            logging.error("Could not read ChrDbgFlags to set invisibility.")
            return
        if enabled:
            new_flags = current_flags | INVISIBILITY_FLAG
        else:
            new_flags = current_flags & ~INVISIBILITY_FLAG
        self.mem.write_static_var("ChrDbgFlags", new_flags)

    def get_player_animation(self) -> Optional[int]:
        _, anim_id = self.mem.read_pointer("PlayerAnimation")
        return anim_id

    def get_player_stats(self) -> Optional[dict]:
        stats = {}
        _, hp = self.mem.read_pointer("PlayerHP")
        _, max_hp = self.mem.read_pointer("PlayerMaxHP")
        if hp is not None and max_hp is not None:
            stats['hp'], stats['max_hp'] = hp, max_hp
        return stats if stats else None

    def set_player_hp(self, value: int):
        self.mem.write_pointer("PlayerHP", value)

    def set_boss_hp(self, value: int):
        if not self.boss_entity_addr:
            return
        try:
            comp_ptr = self.mem.read_longlong(self.boss_entity_addr + 0x190)
            if not comp_ptr: return
            stats_ptr = self.mem.read_longlong(comp_ptr + 0x0)
            if not stats_ptr: return
            self.mem.write_int(stats_ptr + 0x138, value)
        except Exception as e:
            logging.error(f"Failed to set boss HP: {e}")

    def set_player_animation(self, value: int):
        self.mem.write_pointer("PlayerAnimation", value)

    def set_player_animation_override(self, value: int):
        self.mem.write_pointer("PlayerAnimationOverride", value)

    def get_player_position(self) -> Optional[Tuple[float, float, float]]:
        try:
            _, x = self.mem.read_pointer("xPlayer")
            _, y = self.mem.read_pointer("yPlayer")
            _, z = self.mem.read_pointer("zPlayer")
            if x is not None and y is not None and z is not None:
                logging.debug("Player position found via direct pointers.")
                return x, y, z
        except Exception as e:
            logging.error(f"Error getting player position via direct pointers: {e}")

        logging.error("Failed to get player position.")
        return None

    def set_player_angle(self, cos_z: float, sin_z: float):
        self.mem.write_pointer("PlayerAngleCosZ", cos_z)
        self.mem.write_pointer("PlayerAngleSinZ", sin_z)

    def teleport_to_arena(self, arena_id: int) -> bool:
        arena = self.arenas.get(arena_id)
        if not arena:
            logging.error(f"Arena ID '{arena_id}' not found in configuration.")
            return False
        spawn_coords = arena.get("player_spawn")
        if not spawn_coords:
            logging.error(f"Arena '{arena_id}' has no player_spawn coordinates defined.")
            return False
        x = spawn_coords.get("x")
        y = spawn_coords.get("y")
        z = spawn_coords.get("z")
        if x is None or y is None or z is None:
            logging.error(f"Arena '{arena_id}' has incomplete player_spawn coordinates.")
            return False
        logging.info(f"Teleporting to arena '{arena.get('name', arena_id)}'...")
        return self.teleporter.teleport_to_coords(x, y, z)

    def close(self):
        self.set_unlimited_consumables(False)
        logging.info("EldenRingGame API shutting down.")
