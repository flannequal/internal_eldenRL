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
        self._aob_scans: Dict[str, int] = {} # Cache for AOB scan results
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
        
        self._bases_static = {}
        self._aob_scans = {}
        for name, value in addresses_yaml.get('bases_static', {}).items():
            if isinstance(value, str) and value.startswith("AOB"):
                self._aob_scans[name] = value
            elif isinstance(value, (int, str)): # Handle potential string representations of hex
                try:
                    # Ensure value is treated as a string before converting to int with base 16
                    self._bases_static[name] = int(str(value), 16)
                except ValueError:
                    logging.warning(f"Could not convert '{value}' to a base address for '{name}'.")
            else:
                logging.warning(f"Unexpected type for base address '{name}': {type(value)}")

        self._wcm_offsets = {k: int(str(v), 16) for k, v in addresses_yaml.get('worldchrman', {}).items()}
        self._char_offsets = {k: int(str(v), 16) for k, v in addresses_yaml.get('character', {}).items()}
        logging.info("Finished loading memory configurations.")

    def _scan_aob(self, aob_pattern: str) -> Optional[int]:
        if not self.attached or not self._pm: return None
        try:
            # Use pattern_scan instead of find_pattern
            pymem_pattern = " ".join(aob_pattern.split())
            address = self._pm.pattern_scan(pymem_pattern)
            if address:
                logging.info(f"AOB Scan found '{aob_pattern}' at: {hex(address)}")
                return address
            else:
                logging.warning(f"AOB Scan failed for pattern: '{aob_pattern}'")
                return None
        except Exception as e:
            logging.error(f"Error during AOB scan for '{aob_pattern}': {e}")
            return None

    def attach(self) -> bool:
        if self.attached and self._pm: return True
        if time.time() - self._last_attach_attempt < 2.0: return False
        self._last_attach_attempt = time.time()
        
        try:
            self._pm = pymem.Pymem(self.process_name)
            self.attached = True
            logging.info(f"Successfully attached to process '{self.process_name}' (PID: {self._pm.process_id}).")
            
            # Perform AOB scans on attach and cache results
            for name, aob in self._aob_scans.items():
                if name not in self._bases_static: # Only scan if not already a static address
                    resolved_addr = self._scan_aob(aob)
                    if resolved_addr:
                        self._bases_static[name] = resolved_addr # Cache the resolved address
            
            # Check if essential bases are resolved immediately after attachment and AOB scans
            if not self._check_essential_addresses():
                logging.error("Failed to resolve essential base addresses after attachment. Detaching.")
                self.detach()
                return False

            return True
        except pymem.exception.ProcessNotFound:
            logging.warning(f"Process '{self.process_name}' not found. Is the game running?")
            return False
        except Exception as e:
            logging.error(f"Failed to attach to process: {e}")
            return False

    def _check_essential_addresses(self) -> bool:
        """Checks if critical memory addresses are resolved."""
        if not self.attached:
            logging.error("MemoryClient is not attached.")
            return False
        
        critical_addresses = ["WorldChrMan", "CSLuaEventManager", "PlayerHP", "PlayerSP", "PlayerXYZA"]
        for addr_key in critical_addresses:
            if self._resolve_pointer_path(addr_key) is None:
                logging.error(f"Critical address '{addr_key}' could not be resolved.")
                return False
        logging.info("All essential memory addresses resolved successfully.")
        return True

    def detach(self) -> None:
        if self._pm:
            try:
                self._pm.close_process()
            except Exception as e:
                logging.error(f"Error closing process: {e}")
        self.attached = False
        self._pm = None

    def _read_memory(self, address: int, length: int, data_type: str = 'int') -> Any:
        """Safely reads memory, returning None on error."""
        if not self.attached or not self._pm:
            return None
        try:
            if data_type == 'int':
                return self._pm.read_int(address)
            elif data_type == 'longlong':
                return self._pm.read_longlong(address)
            elif data_type == 'float':
                return self._pm.read_float(address)
            elif data_type == 'bytes':
                return self._pm.read_bytes(address, length)
            else:
                logging.warning(f"Unsupported data type for memory read: {data_type}")
                return None
        except pymem.exception.MemoryReadError as e:
            logging.error(f"MemoryReadError: Could not read memory at: {hex(address)}, length: {length} - {e}")
            return None
        except Exception as e:
            logging.error(f"Unexpected error reading memory at {hex(address)}: {e}")
            return None

    def _resolve_pointer_path(self, path_key: str) -> Optional[int]:
        if not self.attached or not self._pm: return None
        
        path_info = self._addresses.get(path_key)
        if not path_info: 
            logging.warning(f"Address key '{path_key}' not found in config.")
            return None
            
        try:
            base_key = path_info.get('base')
            if not base_key:
                logging.warning(f"Base key not specified for '{path_key}'.")
                return None

            base_addr = self._bases_static.get(base_key)
            
            if base_addr is None and base_key in self._aob_scans:
                resolved_addr = self._scan_aob(self._aob_scans[base_key])
                if resolved_addr is None:
                    logging.warning(f"Failed to resolve AOB base for '{base_key}'.")
                    return None
                self._bases_static[base_key] = resolved_addr # Cache the resolved address
                base_addr = resolved_addr
            
            if base_addr is None:
                logging.warning(f"Base address for '{base_key}' could not be resolved.")
                return None

            if 'offsets' not in path_info or not path_info['offsets']:
                return base_addr

            addr = base_addr
            offsets = path_info['offsets']
            
            for i, offset in enumerate(offsets):
                if i < len(offsets) - 1:
                    next_addr = self._read_memory(addr + offset, 8, 'longlong')
                    if next_addr is None:
                        logging.warning(f"Failed to read pointer offset for '{path_key}' at {hex(addr + offset)}.")
                        return None
                    addr = next_addr
                else:
                    addr = addr + offset
            return addr
        except Exception as e:
            logging.error(f"Error resolving pointer path for '{path_key}': {e}")
            return None

    def read_player_hp(self) -> Optional[float]:
        addr = self._resolve_pointer_path("PlayerHP")
        if not addr: return None
        try:
            current_hp = self._read_memory(addr, 4, 'int')
            max_hp = self._read_memory(addr + 4, 4, 'int')
            if current_hp is None or max_hp is None or max_hp <= 0: return None
            return max(0.0, min(1.0, current_hp / max_hp))
        except Exception as e:
            logging.error(f"Error reading player HP: {e}")
            return None

    def read_player_stamina(self) -> Optional[float]:
        addr = self._resolve_pointer_path("PlayerSP")
        if not addr: return None
        try:
            current_sp = self._read_memory(addr, 4, 'int')
            max_sp = self._read_memory(addr + 4, 4, 'int')
            if current_sp is None or max_sp is None or max_sp <= 0: return None
            return max(0.0, min(1.0, current_sp / max_sp))
        except Exception as e:
            logging.error(f"Error reading player stamina: {e}")
            return None

    def read_player_position(self) -> Optional[Tuple[float, float, float]]:
        addr = self._resolve_pointer_path('PlayerXYZA')
        if not addr: return None
        try:
            x = self._read_memory(addr + 0x0, 4, 'float')
            y = self._read_memory(addr + 0x4, 4, 'float')
            z = self._read_memory(addr + 0x8, 4, 'float')
            if x is None or y is None or z is None: return None
            return (x, y, z)
        except Exception as e:
            logging.error(f"Error reading player position: {e}")
            return None

    def _write_last_grace(self, grace_id: int):
        addr = self._resolve_pointer_path('LastGrace')
        if not addr: return
        try:
            self._pm.write_int(addr, grace_id)
            logging.info(f"Set Last Grace to ID: {grace_id} at address {hex(addr)}")
        except Exception as e:
            logging.error(f"Failed to write Last Grace: {e}")

    def _execute_teleport(self, x: float, y: float, z: float, cos: float, sin: float, map_id: int):
        if not self._pm: return
        
        teleport_func_addr = self._resolve_pointer_path("TeleportFunction")
        if not teleport_func_addr:
            logging.error("TeleportFunction address not resolved.")
            return
        
        logging.info(f"Attempting to call teleport function at {hex(teleport_func_addr)}")

        coord_buffer = self._pm.allocate(24)
        self._pm.write_bytes(coord_buffer, struct.pack('fffffI', x, y, z, cos, sin, map_id), 24)

        shellcode = bytes([
            0x48, 0xB9, # MOV RCX, coord_buffer
        ]) + struct.pack('<Q', coord_buffer) + bytes([
            0x48, 0xB8, # MOV RAX, teleport_func_addr
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

    def warp(self, bonfire_name_or_id: Any) -> bool:
        if not self.attached or not self._pm:
            logging.error("Cannot warp, not attached to game.")
            return False

        target_bonfire_id = None
        if isinstance(bonfire_name_or_id, int):
            target_bonfire_id = bonfire_name_or_id
        elif isinstance(bonfire_name_or_id, str):
            target_bonfire_id = self._bonfires_db.get(bonfire_name_or_id)
        
        if target_bonfire_id is None:
            logging.error(f"Bonfire '{bonfire_name_or_id}' not found in bonfires.yaml.")
            return False

        logging.info(f"Initiating warp to bonfire ID: {target_bonfire_id}")

        lua_warp_aob = "C3 ?? ?? ???????? 57 48 83 EC ?? 48 8B FA 44"
        lua_warp_addr = self._scan_aob(lua_warp_aob)
        if not lua_warp_addr:
            logging.error("Could not find LuaWarp_01 address via AOB scan.")
            return False
        lua_warp_addr += 2

        cs_lua_event_manager_addr = self._bases_static.get("CSLuaEventManager")
        if not cs_lua_event_manager_addr:
            logging.error("CSLuaEventManager address not resolved.")
            return False
        
        try:
            cs_lua_event_proxy = self._read_memory(cs_lua_event_manager_addr + 0x08, 8, 'longlong')
            cs_lua_event_script_imitation = self._read_memory(cs_lua_event_manager_addr + 0x18, 8, 'longlong')
        except Exception as e:
            logging.error(f"Failed to read CSLuaEventManager pointers: {e}")
            return False

        if cs_lua_event_proxy is None or cs_lua_event_script_imitation is None:
            logging.error("Failed to get CSLuaEventProxy or CSLuaEventScriptImitation.")
            return False

        warp_id_arg = target_bonfire_id - 1000

        args_buffer = self._pm.allocate(24)
        self._pm.write_bytes(args_buffer, struct.pack('<Q', cs_lua_event_script_imitation), 8)
        self._pm.write_bytes(args_buffer + 8, struct.pack('<Q', cs_lua_event_proxy), 8)
        self._pm.write_bytes(args_buffer + 16, struct.pack('<Q', warp_id_arg), 8)

        shellcode = bytes([
            0x48, 0x83, 0xEC, 0x28,
            0x49, 0xBE,
        ]) + struct.pack('<Q', args_buffer) + bytes([
            0x48, 0xB8,
        ]) + struct.pack('<Q', lua_warp_addr) + bytes([
            0xFF, 0xD0,
            0x48, 0x83, 0xC4, 0x28,
            0xC3
        ])

        shellcode_addr = self._pm.allocate(len(shellcode))
        self._pm.write_bytes(shellcode_addr, shellcode, len(shellcode))

        logging.info(f"Executing warp shellcode at {hex(shellcode_addr)} to call LuaWarp at {hex(lua_warp_addr)}")
        try:
            self._pm.create_remote_thread(shellcode_addr)
            logging.info("Warp function called successfully.")
            return True
        except Exception as e:
            logging.error(f"Failed to execute remote thread for warp: {e}")
            return False
        finally:
            self._pm.free(shellcode_addr)
            self._pm.free(args_buffer)

    def reset_arena(self, arena_id: int, **kwargs) -> None:
        if not self.attached or not self._pm:
            logging.error("Cannot reset arena, not attached to game.")
            return

        logging.info(f"Resetting to arena ID: {arena_id}")
        meta_entry = self._arena_meta_db.get(arena_id)
        if not meta_entry:
            logging.error(f"No metadata found for arena ID: {arena_id}. Cannot reset.")
            return

        bonfire_key = meta_entry.get('nearest_bonfire_key')
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

        spawn = meta_entry.get('player_spawn', {})
        x, y, z = spawn.get('x', 0.0), spawn.get('y', 0.0), spawn.get('z', 0.0)
        cos, sin = spawn.get('cos', 1.0), spawn.get('sin', 0.0)
        map_id = meta_entry.get('map_id')

        if not map_id:
            logging.error(f"No 'map_id' for arena {arena_id}. Cannot teleport.")
            return

        self._execute_teleport(x, y, z, cos, sin, map_id)

        self._boss_param_id = meta_entry.get('boss', {}).get('char_param_id')
        if isinstance(self._boss_param_id, str) and ':' in self._boss_param_id:
            self._boss_param_id = int(self._boss_param_id.split(':')[0])
        
        logging.info(f"Set target boss Param ID to {self._boss_param_id} for this arena.")
        self._boss_stats_addr = 0
        self._boss_last_resolve = 0.0

    def read_last_grace(self) -> int:
        addr = self._resolve_pointer_path('LastGrace')
        if not addr: return -1
        grace_id = self._read_memory(addr, 4, 'int')
        return grace_id if grace_id is not None else -1

    def read_boss_hp(self) -> Optional[float]:
        if not self.attached: return None
        now = time.time()
        if not self._boss_stats_addr and (now - self._boss_last_resolve > self._boss_resolve_retry_sec):
            self._boss_last_resolve = now
            self._resolve_boss_stats_address()

        if self._boss_stats_addr and self._pm:
            try:
                cur = self._read_memory(self._boss_stats_addr, 4, 'int')
                mxx = self._read_memory(self._boss_stats_addr + 4, 4, 'int')
                if cur is None or mxx is None or mxx <= 0: return None
                return max(0.0, min(1.0, float(cur) / float(mxx)))
            except Exception:
                pass
        return None

    def _resolve_boss_stats_address(self) -> None:
        if not self._pm or not self._boss_param_id: return
        
        base_addr = self._bases_static.get('WorldChrMan')
        if not base_addr: return
        wcm_ptr = self._read_memory(self._pm.base_address + base_addr, 8, 'longlong')
        if not wcm_ptr: return

        try:
            begin = self._read_memory(wcm_ptr + self._wcm_offsets['character_list_begin_off'], 8, 'longlong')
            end = self._read_memory(wcm_ptr + self._wcm_offsets['character_list_end_off'], 8, 'longlong')
            if begin is None or end is None or end <= begin: return

            logging.info(f"Scanning for boss with Param ID {self._boss_param_id}...")
            p = begin
            count = 0
            while p < end:
                count += 1
                ent = self._read_memory(p, 8, 'longlong')
                p += 8
                if ent is None or ent < 0x10000: continue
                
                pid = self._read_memory(ent + 0x60, 4, 'int')
                if pid != self._boss_param_id: continue
                
                logging.info(f"!!! Found boss with matching PID at entity address {hex(ent)} after {count} scans.")
                comp = self._read_memory(ent + self._char_offsets['comp_190_off'], 8, 'longlong')
                if not comp: continue
                
                stats = self._read_memory(comp + self._char_offsets['stats_qword_off'], 8, 'longlong')
                if stats:
                    self._boss_stats_addr = stats
                    logging.info(f"Resolved boss stats address to {hex(stats)}")
                    self._boss_comp_addr = comp
                    self._boss_transform_addr = self._read_memory(comp + self._char_offsets['transform_68_off'], 8, 'longlong')
                    return
            logging.warning(f"Finished scanning {count} entities. Boss not found.")
        except Exception as e:
            logging.error(f"Error while scanning for boss entity: {e}")

    def read_boss_position(self) -> Optional[Tuple[float, float, float]]:
        if not self._pm or not self._boss_transform_addr: return None
        try:
            addr = self._boss_transform_addr + self._char_offsets['pos_xyz_off']
            x = self._read_memory(addr, 4, 'float')
            y = self._read_memory(addr + 4, 4, 'float')
            z = self._read_memory(addr + 8, 4, 'float')
            if x is None or y is None or z is None: return None
            return (x, y, z)
        except Exception as e:
            logging.error(f"Error reading boss position: {e}")
            return None

    def read_distance_to_boss(self) -> Optional[float]:
        player_pos = self.read_player_position()
        boss_pos = self.read_boss_position()
        if player_pos is None or boss_pos is None: return None
        try:
            import math
            return math.sqrt(sum([(a - b) ** 2 for a, b in zip(player_pos, boss_pos)]))
        except Exception as e:
            logging.error(f"Error calculating distance to boss: {e}")
            return None
