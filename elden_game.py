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

    def __init__(self, process_name: str = "eldenring.exe", arenas_path: str = "arenas.yaml"):
        self.mem = MemoryManager(process_name)
        if not self.mem.attach():
            raise RuntimeError(f"Failed to attach to {process_name}. Is the game running?")
        
        config_dir = os.path.dirname(arenas_path)
        addresses_path = os.path.join(config_dir, "addresses.yaml")
        
        self.mem.load_addresses(addresses_path)
        self.teleporter = TeleportManager(self.mem)
        self.arenas: Dict[int, Dict[str, Any]] = {}
        self._load_arenas(arenas_path)
        
        self.boss_entity_addr: Optional[int] = None
        logging.info("EldenRingGame API initialized.")

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
        """
        Scans memory for the boss NPC based on its character param ID.
        """
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
        """Returns the boss's current and maximum HP if the entity has been found."""
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

    def get_boss_position(self) -> Optional[Tuple[float, float, float]]:
        """Returns the boss's current X, Z, Y coordinates."""
        if not self.boss_entity_addr:
            return None
            
        try:
            comp_ptr = self.mem.read_longlong(self.boss_entity_addr + 0x190)
            if not comp_ptr: return None
            transform_ptr = self.mem.read_longlong(comp_ptr + 0x68)
            if not transform_ptr: return None

            x = self.mem.read_float(transform_ptr + 0x70)
            z = self.mem.read_float(transform_ptr + 0x74)
            y = self.mem.read_float(transform_ptr + 0x78)

            if x is not None and z is not None and y is not None:
                return x, z, y
        except Exception:
            return None
        return None

    def get_distance_to_boss(self) -> Optional[float]:
        """Calculates the Euclidean distance between the player and the boss."""
        player_pos = self.get_player_position()
        boss_pos = self.get_boss_position()
        if player_pos and boss_pos:
            return math.sqrt(sum([(a - b) ** 2 for a, b in zip(player_pos, boss_pos)]))
        return None

    def is_in_cutscene(self) -> bool:
        """Checks if the game is currently in a cutscene or loading screen."""
        _, value = self.mem.read_pointer("InCutscene")
        return value == 1

    def get_player_animation(self) -> Optional[int]:
        """Returns the player's current animation ID."""
        _, anim_id = self.mem.read_pointer("PlayerAnimation")
        return anim_id

    def get_player_stats(self) -> Optional[dict]:
        """Returns a dictionary of all primary player stats."""
        stats = {}
        _, hp = self.mem.read_pointer("PlayerHP")
        _, max_hp = self.mem.read_pointer("PlayerMaxHP")
        if hp is not None and max_hp is not None:
            stats['hp'], stats['max_hp'] = hp, max_hp
        return stats if stats else None

    def get_player_position(self) -> Optional[Tuple[float, float, float]]:
        """Returns the player's current X, Z, Y coordinates."""
        _, x = self.mem.read_pointer("xPlayer")
        _, z = self.mem.read_pointer("zPlayer")
        _, y = self.mem.read_pointer("yPlayer")
        if x is not None and z is not None and y is not None:
            return x, z, y
        return None

    def teleport_to_arena(self, arena_id: int) -> bool:
        """Teleports the player to the spawn point of a specific arena."""
        arena = self.arenas.get(arena_id)
        if not arena:
            logging.error(f"Arena ID '{arena_id}' not found in configuration.")
            return False
        
        spawn_coords = arena.get("player_spawn")
        if not spawn_coords:
            logging.error(f"Arena '{arena_id}' has no player_spawn coordinates defined.")
            return False
            
        x, y, z = spawn_coords.get("x"), spawn_coords.get("y"), spawn_coords.get("z")
        if x is None or y is None or z is None:
            logging.error(f"Arena '{arena_id}' has incomplete player_spawn coordinates.")
            return False
            
        logging.info(f"Teleporting player to arena '{arena.get('name', arena_id)}'...")
        return self.teleporter.teleport_to_coords(x, y, z)

    def teleport_boss(self, x: float, y: float, z: float) -> bool:
        """Teleports the currently tracked boss to a set of global coordinates."""
        if not self.boss_entity_addr:
            logging.error("Cannot teleport boss, no boss entity is being tracked.")
            return False

        logging.info(f"Teleporting boss to (X:{x:.2f}, Y:{y:.2f}, Z:{z:.2f})...")
        return self.teleporter.teleport_to_coords(x, y, z, entity_addr=self.boss_entity_addr)

    def close(self):
        logging.info("EldenRingGame API shutting down.")
