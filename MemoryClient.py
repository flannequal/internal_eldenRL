import os
import time
import logging
from typing import Tuple, Optional, Dict, Any
import yaml
import pymem
import struct

class MemoryClient:
    """Memory client for Elden Ring using pymem for direct memory access and function calls."""

    def __init__(self, process_name: str = "eldenring.exe", **kwargs):
        self.process_name = process_name
        self.attached = False
        self._last_attach_attempt = 0.0
        self._pm: Optional[pymem.Pymem] = None

        # Config caches
        self._arena_meta_db: Dict[int, Dict[str, Any]] = {}
        self._bonfires_db: Dict[str, int] = {}
        self._addresses: Dict[str, Any] = {}
        self._bases_static: Dict[str, int] = {}
        self._wcm_offsets: Dict[str, int] = {}
        self._char_offsets: Dict[str, int] = {}
        
        # Runtime caches
        self._boss_param_id: Optional[int] = None
        self._boss_stats_addr: int = 0
        self._boss_comp_addr: int = 0
        self._boss_transform_addr: int = 0
        self._boss_last_resolve: float = 0.0
        self._boss_resolve_retry_sec: float = 1.0

        self._load_configs()

    def _safe_load_yaml(self, path: str) -> Dict[str, Any]:
        if not os.path.isfile(path):
            logging.warning(f"YAML config not found at: {path}")
            return {}
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logging.error(f"Failed to load or parse YAML at {path}: {e}")
            return {}

    def _load_configs(self):
        logging.info("Loading memory configurations...")
        arena_data = self._safe_load_yaml(os.path.join('config', 'arenas.yaml'))
        for entry in arena_data.get('arenas', []):
            if 'id' in entry:
                self._arena_meta_db[int(entry['id'])] = entry
        
        bonfire_data = self._safe_load_yaml(os.path.join('config', 'bonfires.yaml'))
        if isinstance(bonfire_data, dict):
            self._bonfires_db = {str(k): int(v) for k, v in bonfire_data.items()}

        addresses_yaml = self._safe_load_yaml(os.path.join('config', 'addresses.yaml'))
        self._addresses = addresses_yaml.get('addresses', {})
        self._bases_static = {k: int(str(v), 16) for k, v in addresses_yaml.get('bases_static', {}).items()}
        self._wcm_offsets = {k: int(str(v), 16) for k, v in addresses_yaml.get('worldchrman', {}).items()}
        self._char_offsets = {k: int(str(v), 16) for k, v in addresses_yaml.get('character', {}).items()}
        logging.info("Finished loading memory configurations.")

    def attach(self) -> bool:
        if self.attached and self._pm: return True
        if time.time() - self._last_attach_attempt < 2.0: return False
        self._last_attach_attempt = time.time()
        
        try:
            self._pm = pymem.Pymem(self.process_name)
            self.attached = True
            logging.info(f"Successfully attached to process '{self.process_name}' (PID: {self._pm.process_id}).")
            return True
        except pymem.exception.ProcessNotFound:
            logging.warning(f"Process '{self.process_name}' not found. Is the game running?")
            return False
        return False

    def detach(self) -> None:
        if self._pm: self._pm.close_process()
        self.attached = False
        self._pm = None

    def _resolve_pointer_path(self, path_key: str) -> Optional[int]:
        if not self.attached or not self._pm: return None
        path_info = self._addresses.get(path_key)
        if not path_info: return None
            
        try:
            base_ptr = self._bases_static.get(path_info['base'])
            if not base_ptr: return None
            
            addr = self._pm.read_longlong(self._pm.base_address + base_ptr)
            offsets = path_info['offsets']
            
            for i, offset in enumerate(offsets):
                if i < len(offsets) - 1:
                    addr = self._pm.read_longlong(addr + offset)
                else:
                    addr = addr + offset
            return addr
        except Exception:
            return None

    def read_player_hp(self) -> float:
        addr = self._resolve_pointer_path("PlayerHP")
        if not addr or not self._pm: return 0.0
        try:
            current_hp = self._pm.read_int(addr)
            max_hp = self._pm.read_int(addr + 4)
            if max_hp <= 0: return 0.0
            return max(0.0, min(1.0, current_hp / max_hp))
        except:
            return 0.0

    def read_player_stamina(self) -> float:
        addr = self._resolve_pointer_path("PlayerSP")
        if not addr or not self._pm: return 0.0
        try:
            current_sp = self._pm.read_int(addr)
            max_sp = self._pm.read_int(addr + 4)
            if max_sp <= 0: return 0.0
            return max(0.0, min(1.0, current_sp / max_sp))
        except:
            return 0.0

    def read_player_position(self) -> Tuple[float, float, float]:
        addr = self._resolve_pointer_path('PlayerXYZA')
        if addr and self._pm:
            try:
                x = self._pm.read_float(addr + 0x0)
                y = self._pm.read_float(addr + 0x4)
                z = self._pm.read_float(addr + 0x8)
                return (x, y, z)
            except Exception:
                pass
        return (0.0, 0.0, 0.0)

    def _write_last_grace(self, grace_id: int):
        addr = self._resolve_pointer_path('LastGrace')
        if addr and self._pm:
            try:
                self._pm.write_int(addr, grace_id)
                logging.info(f"Set Last Grace to ID: {grace_id} at address {hex(addr)}")
            except Exception as e:
                logging.error(f"Failed to write Last Grace: {e}")

    def reset_arena(self, arena_id: int, **kwargs) -> None:
        if not self.attached or not self._pm:
            logging.error("Cannot reset arena, not attached to game.")
            return

        logging.info(f"Resetting to arena ID: {arena_id}")
        meta_entry = self._arena_meta_db.get(arena_id)
        if not meta_entry:
            logging.error(f"No metadata found for arena ID: {arena_id}. Cannot reset.")
            return

        # 1. Set Bonfire Context
        bonfire_key = meta_entry.get('nearest_bonfire_key')
        if not bonfire_key:
            logging.error(f"Arena {arena_id} has no 'nearest_bonfire_key'. Cannot set context.")
            return
        
        bonfire_id = self._bonfires_db.get(bonfire_key)
        if not bonfire_id:
            logging.error(f"Bonfire key '{bonfire_key}' not found in bonfires.yaml.")
            return
            
        self._write_last_grace(bonfire_id)
        time.sleep(0.1) # Brief pause

        # 2. Execute Teleport with local coordinates
        spawn = meta_entry.get('player_spawn', {})
        x, y, z = spawn.get('x', 0.0), spawn.get('y', 0.0), spawn.get('z', 0.0)
        cos, sin = spawn.get('cos', 1.0), spawn.get('sin', 0.0)
        map_id = meta_entry.get('map_id')

        if not map_id:
            logging.error(f"No 'map_id' for arena {arena_id}. Cannot teleport.")
            return

        self._execute_teleport(x, y, z, cos, sin, map_id)

        # 3. Set Boss Target
        self._boss_param_id = meta_entry.get('boss', {}).get('char_param_id')
        if isinstance(self._boss_param_id, str) and ':' in self._boss_param_id:
            self._boss_param_id = int(self._boss_param_id.split(':')[0])
        
        logging.info(f"Set target boss Param ID to {self._boss_param_id} for this arena.")
        self._boss_stats_addr = 0
        self._boss_last_resolve = 0.0

    def _execute_teleport(self, x: float, y: float, z: float, cos: float, sin: float, map_id: int):
        if not self._pm: return
        
        teleport_func_addr = self._pm.base_address + self._bases_static['TeleportFunction']
        logging.info(f"Attempting to call teleport function at {hex(teleport_func_addr)}")

        # Buffer format: x, y, z, cos, sin, map_id
        coord_buffer = self._pm.allocate(32)
        self._pm.write_bytes(coord_buffer, struct.pack('fffffI', x, y, z, cos, sin, map_id), 24)

        shellcode = bytes([
            0x48, 0xB9, # MOV RCX, ...
        ]) + struct.pack('<Q', coord_buffer) + bytes([
            0x48, 0xB8, # MOV RAX, ...
        ]) + struct.pack('<Q', teleport_func_addr) + bytes([
            0xFF, 0xD0, # CALL RAX
            0xC3        # RET
        ])

        shellcode_addr = self._pm.allocate(len(shellcode))
        self._pm.write_bytes(shellcode_addr, shellcode, len(shellcode))

        logging.info(f"Executing teleport shellcode at {hex(shellcode_addr)}")
        try:
            self._pm.create_remote_thread(shellcode_addr)
            logging.info("Teleport function called successfully.")
        except Exception as e:
            logging.error(f"Failed to execute remote thread for teleport: {e}")
        finally:
            self._pm.free(shellcode_addr)
            self._pm.free(coord_buffer)

    def read_boss_hp(self) -> float:
        if not self.attached: return 1.0
        now = time.time()
        if not self._boss_stats_addr and (now - self._boss_last_resolve > self._boss_resolve_retry_sec):
            self._boss_last_resolve = now
            self._resolve_boss_stats_address()

        if self._boss_stats_addr and self._pm:
            try:
                cur = self._pm.read_int(self._boss_stats_addr)
                mxx = self._pm.read_int(self._boss_stats_addr + 4)
                if mxx > 0:
                    return max(0.0, min(1.0, float(cur) / float(mxx)))
            except Exception:
                pass
        return 1.0

    def _resolve_boss_stats_address(self) -> None:
        if not self._pm or not self._boss_param_id: return
        
        base_addr = self._bases_static.get('WorldChrMan')
        if not base_addr: return
        wcm_ptr = self._pm.read_longlong(self._pm.base_address + base_addr)
        if not wcm_ptr: return

        try:
            begin = self._pm.read_longlong(wcm_ptr + self._wcm_offsets['character_list_begin_off'])
            end = self._pm.read_longlong(wcm_ptr + self._wcm_offsets['character_list_end_off'])
            if not (begin and end and end > begin): return

            logging.info(f"Scanning for boss with Param ID {self._boss_param_id}...")
            p = begin
            count = 0
            while p < end:
                count += 1
                ent = self._pm.read_longlong(p)
                p += 8
                if not ent or ent < 0x10000: continue
                
                pid = self._pm.read_int(ent + 0x60)
                if pid != self._boss_param_id: continue
                
                logging.info(f"!!! Found boss with matching PID at entity address {hex(ent)} after {count} scans.")
                comp = self._pm.read_longlong(ent + self._char_offsets['comp_190_off'])
                if not comp: continue
                
                stats = self._pm.read_longlong(comp + self._char_offsets['stats_qword_off'])
                if stats:
                    self._boss_stats_addr = stats
                    logging.info(f"Resolved boss stats address to {hex(stats)}")
                    self._boss_comp_addr = comp
                    self._boss_transform_addr = self._pm.read_longlong(comp + self._char_offsets['transform_68_off'])
                    return
            logging.warning(f"Finished scanning {count} entities. Boss not found.")
        except Exception as e:
            logging.error(f"Error while scanning for boss entity: {e}")

    def read_boss_position(self) -> Optional[Tuple[float, float, float]]:
        if not self._pm or not self._boss_transform_addr: return None
        try:
            addr = self._boss_transform_addr + self._char_offsets['pos_xyz_off']
            x = self._pm.read_float(addr)
            y = self._pm.read_float(addr + 4)
            z = self._pm.read_float(addr + 8)
            return (x, y, z)
        except Exception:
            return None

    def read_distance_to_boss(self) -> Optional[float]:
        player_pos = self.read_player_position()
        boss_pos = self.read_boss_position()
        if player_pos is None or boss_pos is None: return None
        try:
            import math
            return math.sqrt(sum([(a - b) ** 2 for a, b in zip(player_pos, boss_pos)]))
        except Exception:
            return None
