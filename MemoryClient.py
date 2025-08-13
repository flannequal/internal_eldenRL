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
        self._bases_static = {k: int(str(v), 16) for k, v in addresses_yaml.get('bases_static', {}).items() if isinstance(v, (int, str)) and not isinstance(v, str) or not v.startswith("AOB")}
        self._aob_scans = {k: v for k, v in addresses_yaml.get('bases_static', {}).items() if isinstance(v, str) and v.startswith("AOB")}
        self._wcm_offsets = {k: int(str(v), 16) for k, v in addresses_yaml.get('worldchrman', {}).items()}
        self._char_offsets = {k: int(str(v), 16) for k, v in addresses_yaml.get('character', {}).items()}
        logging.info("Finished loading memory configurations.")

    def _scan_aob(self, aob_pattern: str) -> Optional[int]:
        if not self.attached or not self._pm: return None
        try:
            # Remove spaces and convert to bytes
            aob_bytes = bytes.fromhex(aob_pattern.replace(" ", ""))
            # pymem's pattern scanner expects a specific format, let's assume it's handled internally or we adapt
            # For simplicity, let's assume a direct AOB scan function exists or we adapt the pattern
            # A common way is to convert to a format like "48 83 3D ?? ?? ?? ?? 00"
            
            # Let's try a simple adaptation for pymem's find_pattern
            # pymem expects a pattern string like "48 83 3D ?? ?? ?? ?? 00"
            pymem_pattern = " ".join(aob_pattern.split())
            
            address = self._pm.find_pattern(pymem_pattern)
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
            
            # Perform AOB scans on attach
            for name, aob in self._aob_scans.items():
                if name not in self._bases_static: # Only scan if not already a static address
                    self._bases_static[name] = self._scan_aob(aob)
            
            return True
        except pymem.exception.ProcessNotFound:
            logging.warning(f"Process '{self.process_name}' not found. Is the game running?")
            return False
        except Exception as e:
            logging.error(f"Failed to attach to process: {e}")
            return False

    def detach(self) -> None:
        if self._pm: self._pm.close_process()
        self.attached = False
        self._pm = None

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
            if base_addr is None:
                logging.warning(f"Base address for '{base_key}' not resolved.")
                return None
            
            # If base_addr is actually an AOB pattern string that hasn't been resolved yet
            if isinstance(base_addr, str) and base_addr.startswith("AOB"):
                resolved_addr = self._scan_aob(base_addr)
                if resolved_addr is None:
                    logging.warning(f"Failed to resolve AOB base for '{base_key}'.")
                    return None
                self._bases_static[base_key] = resolved_addr # Cache the resolved address
                base_addr = resolved_addr
            
            # If base_addr is still None after potential AOB scan, return None
            if base_addr is None:
                return None

            # If it's a direct address (not a pointer chain)
            if 'offsets' not in path_info or not path_info['offsets']:
                return base_addr

            # Pointer chain resolution
            addr = base_addr
            offsets = path_info['offsets']
            
            for i, offset in enumerate(offsets):
                if i < len(offsets) - 1:
                    addr = self._pm.read_longlong(addr + offset)
                else:
                    addr = addr + offset
            return addr
        except Exception as e:
            logging.error(f"Error resolving pointer path for '{path_key}': {e}")
            return None

    def read_player_hp(self) -> float:
        addr = self._resolve_pointer_path("PlayerHP")
        if not addr or not self._pm: return 0.0
        try:
            current_hp = self._pm.read_int(addr)
            max_hp = self._pm.read_int(addr + 4)
            if max_hp <= 0: return 0.0
            return max(0.0, min(1.0, current_hp / max_hp))
        except Exception as e:
            logging.error(f"Error reading player HP: {e}")
            return 0.0

    def read_player_stamina(self) -> float:
        addr = self._resolve_pointer_path("PlayerSP")
        if not addr or not self._pm: return 0.0
        try:
            current_sp = self._pm.read_int(addr)
            max_sp = self._pm.read_int(addr + 4)
            if max_sp <= 0: return 0.0
            return max(0.0, min(1.0, current_sp / max_sp))
        except Exception as e:
            logging.error(f"Error reading player stamina: {e}")
            return 0.0

    def read_player_position(self) -> Tuple[float, float, float]:
        addr = self._resolve_pointer_path('PlayerXYZA')
        if addr and self._pm:
            try:
                x = self._pm.read_float(addr + 0x0)
                y = self._pm.read_float(addr + 0x4)
                z = self._pm.read_float(addr + 0x8)
                return (x, y, z)
            except Exception as e:
                logging.error(f"Error reading player position: {e}")
                return (0.0, 0.0, 0.0)
        return (0.0, 0.0, 0.0)

    def _write_last_grace(self, grace_id: int):
        addr = self._resolve_pointer_path('LastGrace')
        if addr and self._pm:
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

        # Buffer format: x, y, z, cos, sin, map_id
        coord_buffer = self._pm.allocate(24) # 3 floats + 1 float + 1 float + 1 uint
        self._pm.write_bytes(coord_buffer, struct.pack('fffffI', x, y, z, cos, sin, map_id), 24)

        # Shellcode to call the teleport function
        # Arguments: CSLuaEventScriptImitation, CSLuaEventProxy, warpId-1000
        # For teleport, the arguments are likely different. Based on the .CEA script, it seems to be:
        # executeCodeEx(0, 100, LuaWarp_01, CSLuaEventScriptImitation, CSLuaEventProxy, warpId-1000)
        # This implies a specific calling convention. For a direct function call, we need to know its signature.
        # Assuming TeleportFunction takes (x, y, z, cos, sin, map_id) as arguments directly.
        
        # Let's construct a shellcode that calls TeleportFunction with the packed coordinates.
        # This is a simplified assumption. A more accurate shellcode would depend on the exact function signature.
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
        """
        Initiates a warp to a specified bonfire.
        Args:
            bonfire_name_or_id: The name (string) or ID (int) of the bonfire.
        Returns:
            True if the warp was initiated, False otherwise.
        """
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

        # 1. Find LuaWarp_01 address using AOB
        lua_warp_aob = "C3 ?? ?? ???????? 57 48 83 EC ?? 48 8B FA 44" # From Warp_code_TGA_dependency.CEA
        lua_warp_addr = self._scan_aob(lua_warp_aob)
        if not lua_warp_addr:
            logging.error("Could not find LuaWarp_01 address via AOB scan.")
            return False
        lua_warp_addr += 2 # As per the CEA script

        # 2. Get CSLuaEventManager, Proxy, and ScriptImitation addresses
        cs_lua_event_manager_addr = self._bases_static.get("CSLuaEventManager")
        if not cs_lua_event_manager_addr:
            logging.error("CSLuaEventManager address not resolved.")
            return False
        
        try:
            cs_lua_event_proxy = self._pm.read_longlong(cs_lua_event_manager_addr + 0x08)
            cs_lua_event_script_imitation = self._pm.read_longlong(cs_lua_event_manager_addr + 0x18)
        except Exception as e:
            logging.error(f"Failed to read CSLuaEventManager pointers: {e}")
            return False

        if not cs_lua_event_proxy or not cs_lua_event_script_imitation:
            logging.error("Failed to get CSLuaEventProxy or CSLuaEventScriptImitation.")
            return False

        # 3. Check for DLC bonfire and handle logic (simplified for now)
        # This part would need more specific DLC handling if required.
        # For now, we just pass the ID.
        
        # 4. Prepare arguments for the warp function
        # The warp function expects: CSLuaEventScriptImitation, CSLuaEventProxy, warpId - 1000
        warp_id_arg = target_bonfire_id - 1000

        # 5. Construct and execute shellcode to call the warp function
        # The shellcode needs to call lua_warp_addr with the arguments.
        # This is a generic shellcode for calling a function with specific arguments.
        # The exact assembly might vary based on calling conventions (e.g., x64 calling convention).
        # For x64, arguments are passed in RCX, RDX, R8, R9.
        
        # Allocate memory for arguments
        args_buffer = self._pm.allocate(24) # 3 arguments: 8 bytes each (pointers/long long)
        
        # Write arguments to the buffer
        self._pm.write_bytes(args_buffer, struct.pack('<Q', cs_lua_event_script_imitation), 8) # RCX
        self._pm.write_bytes(args_buffer + 8, struct.pack('<Q', cs_lua_event_proxy), 8)       # RDX
        self._pm.write_bytes(args_buffer + 16, struct.pack('<Q', warp_id_arg), 8)            # R8

        # Shellcode to call the function with arguments from the buffer
        shellcode = bytes([
            0x48, 0x83, 0xEC, 0x28, # SUB RSP, 0x28 (stack space for arguments if needed, adjust as necessary)
            0x49, 0xBE, # MOV R14, args_buffer
        ]) + struct.pack('<Q', args_buffer) + bytes([
            0x48, 0xB8, # MOV RAX, lua_warp_addr
        ]) + struct.pack('<Q', lua_warp_addr) + bytes([
            0xFF, 0xD0, # CALL RAX
            0x48, 0x83, 0xC4, 0x28, # ADD RSP, 0x28 (clean up stack)
            0xC3        # RET
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

        # 1. Set Bonfire Context
        bonfire_key = meta_entry.get('nearest_bonfire_key')
        if not bonfire_key:
            logging.error(f"Arena {arena_id} has no 'nearest_bonfire_key'. Cannot set context.")
            return
        
        target_bonfire_id = self._bonfires_db.get(bonfire_key)
        if not target_bonfire_id:
            logging.error(f"Bonfire key '{bonfire_key}' not found in bonfires.yaml.")
            return
            
        # 2. Check Current Location and Warp if Necessary
        current_grace_id = self.read_last_grace() # Need to implement read_last_grace
        
        if current_grace_id != target_bonfire_id:
            logging.info(f"Current grace ID ({current_grace_id}) does not match target ({target_bonfire_id}). Initiating warp.")
            if not self.warp(target_bonfire_id):
                logging.error("Warp initiation failed. Cannot proceed with reset.")
                return
            
            # 3. Wait for Load
            # This is a crucial step. The duration might need tuning.
            logging.info("Waiting for warp to complete (loading screen)...")
            time.sleep(10) # Adjust this sleep duration as needed for loading times
            logging.info("Finished waiting for warp.")
        else:
            logging.info(f"Already at the correct bonfire ID: {target_bonfire_id}. No warp needed.")

        # 4. Final Local Teleport to precise arena starting coordinates
        spawn = meta_entry.get('player_spawn', {})
        x, y, z = spawn.get('x', 0.0), spawn.get('y', 0.0), spawn.get('z', 0.0)
        cos, sin = spawn.get('cos', 1.0), spawn.get('sin', 0.0)
        map_id = meta_entry.get('map_id')

        if not map_id:
            logging.error(f"No 'map_id' for arena {arena_id}. Cannot teleport.")
            return

        self._execute_teleport(x, y, z, cos, sin, map_id)

        # 5. Set Boss Target
        self._boss_param_id = meta_entry.get('boss', {}).get('char_param_id')
        if isinstance(self._boss_param_id, str) and ':' in self._boss_param_id:
            self._boss_param_id = int(self._boss_param_id.split(':')[0])
        
        logging.info(f"Set target boss Param ID to {self._boss_param_id} for this arena.")
        self._boss_stats_addr = 0
        self._boss_last_resolve = 0.0

    def read_last_grace(self) -> int:
        """Reads the current LastGrace ID from memory."""
        addr = self._resolve_pointer_path('LastGrace')
        if addr and self._pm:
            try:
                return self._pm.read_int(addr)
            except Exception as e:
                logging.error(f"Failed to read LastGrace: {e}")
                return -1 # Indicate an error or unknown state
        return -1 # Indicate an error or unknown state

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
