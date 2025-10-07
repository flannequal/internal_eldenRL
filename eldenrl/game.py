import logging
import math
import os
from typing import Any, Dict, Optional, Tuple

import yaml

from eldenrl.memory_mngr import MemoryManager
from eldenrl.teleport import TeleportManager

logger = logging.getLogger(__name__)

CHR_LIST_START = 0x1F1B8
CHR_LIST_END = 0x1F1C0
CHR_PARAM_ID = 0x60
CHR_COMPONENT = 0x190
COMPONENT_STATS = 0x0
COMPONENT_TRANSFORM = 0x68
STATS_HP = 0x138
STATS_MAX_HP = 0x13C
TRANSFORM_X = 0x70
TRANSFORM_Z = 0x74
TRANSFORM_Y = 0x78
POINTER_SIZE = 8
MIN_VALID_POINTER = 0xFFFF


class EldenRingGame:

    def __init__(self, process_name: str = "eldenring.exe", arenas_path: str = "config/arenas.yaml"):
        self.mem = MemoryManager(process_name)
        if not self.mem.attach():
            raise RuntimeError(f"could not attach to {process_name}, is the game running?")

        config_dir = os.path.dirname(arenas_path)
        self.mem.load_addresses(os.path.join(config_dir, "addresses.yaml"))
        self.teleporter = TeleportManager(self.mem, os.path.join(config_dir, "locations.json"))

        self.arenas: Dict[int, Dict[str, Any]] = {}
        self._load_arenas(arenas_path)
        self.boss_entity_addr: Optional[int] = None

    def _load_arenas(self, file_path: str) -> None:
        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
            for arena in data.get("arenas", []):
                self.arenas[arena["id"]] = arena
            logger.info("loaded %d arenas from '%s'", len(self.arenas), file_path)
        except FileNotFoundError:
            logger.error("arena config not found at '%s'", file_path)
        except Exception as exc:
            logger.error("could not load arena config: %s", exc)

    def find_boss_entity(self, target_param_id: int) -> bool:
        world_chr_man = self.mem.resolve("WorldChrMan")
        if not world_chr_man:
            return False

        start_addr = self.mem.read_longlong(world_chr_man + CHR_LIST_START)
        end_addr = self.mem.read_longlong(world_chr_man + CHR_LIST_END)
        if not start_addr or not end_addr or start_addr >= end_addr:
            return False

        addr = start_addr
        while addr < end_addr:
            entity = self.mem.read_longlong(addr)
            if entity and entity > MIN_VALID_POINTER:
                if self.mem.read_int(entity + CHR_PARAM_ID) == target_param_id:
                    self.boss_entity_addr = entity
                    logger.info("boss %d found at %s", target_param_id, hex(entity))
                    return True
            addr += POINTER_SIZE

        self.boss_entity_addr = None
        return False

    def _boss_component(self, offset: int) -> Optional[int]:
        if not self.boss_entity_addr:
            return None
        component = self.mem.read_longlong(self.boss_entity_addr + CHR_COMPONENT)
        if not component:
            return None
        return self.mem.read_longlong(component + offset)

    def get_boss_hp(self) -> Optional[Tuple[int, int]]:
        stats = self._boss_component(COMPONENT_STATS)
        if not stats:
            return None

        hp = self.mem.read_int(stats + STATS_HP)
        max_hp = self.mem.read_int(stats + STATS_MAX_HP)
        if hp is None or max_hp is None:
            return None
        return hp, max_hp

    def get_boss_position(self) -> Optional[Tuple[float, float, float]]:
        transform = self._boss_component(COMPONENT_TRANSFORM)
        if not transform:
            return None

        coords = [self.mem.read_float(transform + offset)
                  for offset in (TRANSFORM_X, TRANSFORM_Z, TRANSFORM_Y)]
        if any(value is None for value in coords):
            return None
        return coords[0], coords[1], coords[2]

    def get_distance_to_boss(self) -> Optional[float]:
        player_pos = self.get_player_position()
        boss_pos = self.get_boss_position()
        if not player_pos or not boss_pos:
            return None
        return math.dist(player_pos, boss_pos)

    def is_in_cutscene(self) -> bool:
        _, value = self.mem.read_pointer("InCutscene")
        return value == 1

    def get_player_animation(self) -> Optional[int]:
        _, animation_id = self.mem.read_pointer("PlayerAnimation")
        return animation_id

    def get_player_stats(self) -> Optional[Dict[str, int]]:
        _, hp = self.mem.read_pointer("PlayerHP")
        _, max_hp = self.mem.read_pointer("PlayerMaxHP")
        if hp is None or max_hp is None:
            return None
        return {"hp": hp, "max_hp": max_hp}

    def get_player_position(self) -> Optional[Tuple[float, float, float]]:
        coords = [self.mem.read_pointer(name)[1] for name in ("xPlayer", "zPlayer", "yPlayer")]
        if any(value is None for value in coords):
            return None
        return coords[0], coords[1], coords[2]

    def teleport_to_arena(self, arena_id: int) -> bool:
        arena = self.arenas.get(arena_id)
        if not arena:
            logger.error("arena %s not in configuration", arena_id)
            return False

        spawn = arena.get("player_spawn") or {}
        x, z, y = spawn.get("x"), spawn.get("z"), spawn.get("y")
        if x is None or z is None or y is None:
            logger.error("arena %s has no complete player_spawn", arena_id)
            return False

        logger.info("teleporting to arena '%s'", arena.get("name", arena_id))
        return self.teleporter.teleport_to_coords(x, z, y)

    def close(self) -> None:
        logger.info("closing game interface")
