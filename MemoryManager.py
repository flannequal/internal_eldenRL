import ctypes
import os
import time
import logging
from typing import Optional, Dict, Any, Tuple
import yaml
import pymem
import pymem.ressources.kernel32 as k32


class MemoryManager:
    """Manages low-level memory operations, AOB scanning, and pointer path resolution.
    This class is game-agnostic and only deals with raw memory access.
    """

    def __init__(self, process_name: str = "eldenring.exe", addresses_config_path: str = os.path.join("config", "addresses.yaml")):
        self.process_name = process_name
        self.addresses_config_path = addresses_config_path
        self.attached = False
        self._last_attach_attempt = 0.0
        self._pm: Optional[pymem.Pymem] = None
        self._module = None

        # Config caches for generic memory access (bases and pointer chains)

        self._bases_static: Dict[str, int] = {}
        self._aob_patterns: Dict[str, str] = {}
        self._addresses: Dict[str, Any] = {}

        self._load_configs()

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

    def _load_configs(self):
        """Loads configurations from YAML. Stores RVAs as integers."""
        logging.info(
            f"Loading memory configurations from {self.addresses_config_path}...")
        addresses_yaml = self._safe_load_yaml(self.addresses_config_path)

        self._bases_static = addresses_yaml.get("bases_static", {})

        self._aob_patterns = addresses_yaml.get("bases_aob", {})
        self._addresses = addresses_yaml.get("addresses", {})

    def _parse_aob_pattern(self, aob_pattern_str: str):
        """
        Parse a human AOB string into (pattern_bytes, mask_bytes).
        Mask contains 1 for concrete bytes, 0 for wildcards.
        Accepts patterns like:
        "48 83 3D ?? ?? ?? ?? 00 48"
        "C3 ?? ?? ???????? 57"
        "48??3D ?? 00"
        with or without leading "AOB:".
        """
        s = str(aob_pattern_str).strip()
        if not s:
            return b"", bytearray()

        if s.upper().startswith("AOB:"):
            s = s[4:].strip()

        parts = s.split()
        pat = bytearray()
        mask = bytearray()

        for part in parts:
            part = part.strip()
            if not part:
                continue

            # if it's all question marks (like "????" or "??????"), treat as multiple wildcards
            if set(part) == {"?"}:
                count = max(1, len(part) // 2)
                for _ in range(count):
                    pat.append(0x00)
                    mask.append(0)
                continue

            # otherwise iterate two chars at a time to handle tokens like "48??3D" or maybe malformed spacing
            i = 0
            if len(part) % 2 == 1:
                part = "?" + part
            while i < len(part):
                pair = part[i:i+2]
                if pair == "??" or pair == "?":
                    pat.append(0x00)
                    mask.append(0)
                else:
                    try:
                        pat.append(int(pair, 16))
                        mask.append(1)
                    except ValueError:
                        # if something weird appears, treat as wildcard
                        pat.append(0x00)
                        mask.append(0)
                i += 2

        return bytes(pat), mask

    def _find_pattern_in_buffer(self, buf: bytes, pat: bytes, mask: bytearray) -> int:
        """Return offset of first match or -1. Simple byte-by-byte scan with mask."""
        if not pat or len(buf) < len(pat):
            return -1
        plen = len(pat)
        # naive scan (ok for module-sized scans; can be chunked/optimized later)
        last = len(buf) - plen + 1
        for i in range(last):
            # small optimization: compare first non-wildcard byte quickly if exists
            match = True
            for j in range(plen):
                if mask[j] and buf[i + j] != pat[j]:
                    match = False
                    break
            if match:
                return i
        return -1

    def _scan_aob(self, aob_pattern_str: str) -> Optional[int]:
        """
        Robust AOB scanner:
        - Parses AOB string (handles ?? and runs of ?)
        - Tries main EXE module and GameAssembly.dll by default
        - Reads module memory and does wildcard-aware search
        """
        if not self.attached or not self._pm:
            logging.warning("Cannot scan AOB: not attached to process.")
            return None

        pattern_bytes, mask = self._parse_aob_pattern(aob_pattern_str)
        if not pattern_bytes:
            logging.warning(f"Empty/invalid AOB pattern: '{aob_pattern_str}'")
            return None

        modules_to_try = []
        if getattr(self, "_module", None):
            modules_to_try.append(self._module)

        # try:
        #     all_mods = self._pm.list_modules()
        #     preferred = {"gameassembly.dll", self.process_name.lower()}
        #     # add preferred modules first if present
        #     for mod in all_mods:
        #         name = getattr(mod, "name", "").lower()
        #         if name in preferred and mod not in modules_to_try:
        #             modules_to_try.append(mod)
        # except Exception as e:
        #     logging.debug(f"Could not list modules: {e}")

        for mod in modules_to_try:
            try:
                base = mod.lpBaseOfDll
                size = mod.SizeOfImage
            except Exception:
                logging.debug(
                    f"Module object missing attributes, skipping: {mod}")
                continue

            logging.debug(
                f"Scanning module {getattr(mod, 'name', str(mod))} at {hex(base)} size {hex(size)} for pattern '{aob_pattern_str}'"
            )

            try:
                # read entire module region (might be large; if you prefer chunked scanning do that)
                buf = self._pm.read_bytes(base, size)
            except Exception as e:
                logging.debug(
                    f"Failed to read module memory {getattr(mod, 'name', None)}: {e}")
                continue

            offset = self._find_pattern_in_buffer(buf, pattern_bytes, mask)
            if offset != -1:
                found_addr = base + offset
                logging.info(
                    f"AOB Scan found '{aob_pattern_str}' in {getattr(mod, 'name', None)} at {hex(found_addr)}")
                return found_addr

            logging.debug(
                f"Pattern not found in module {getattr(mod, 'name', None)}")

        logging.warning(f"AOB Scan failed for pattern: '{aob_pattern_str}'")
        return None

    def attach(self) -> bool:
        """Attaches to the process and prepares all base addresses."""
        if self.attached and self._pm: return True
        if time.time() - self._last_attach_attempt < 2.0: return False
        self._last_attach_attempt = time.time()
        try:
            self._pm = pymem.Pymem(self.process_name)
            self._module = pymem.process.module_from_name(self._pm.process_handle, self.process_name)
            if not self._module:
                logging.error(f"Could not find module '{self.process_name}'.")
                return False

            self.attached = True
            module_base = self._module.lpBaseOfDll
            
            # This holds absolute addresses of STATIC POINTERS (from RVAs)
            self._static_pointer_addrs = {}
            for name, rva in self._bases_static.items():
                self._static_pointer_addrs[name] = module_base + rva
            
            # This holds DIRECT addresses (from AOB scans)
            self._direct_addrs = {}
            for name, aob_pattern in self._aob_patterns.items():
                self._direct_addrs[name] = self._scan_aob(aob_pattern)
            
            logging.info("All base addresses prepared.")
            return True
        except Exception as e:
            logging.error(f"Failed to attach to process: {e}")
            return False

    def detach(self) -> None:
        if self._pm:
            try:
                self._pm.close_process()
            except Exception as e:
                logging.error(f"Error closing process: {e}")
        self.attached = False
        self._pm = None
        self._module = None

    def read_bytes(self, address: int, length: int) -> Optional[bytes]:
        """Safely reads raw bytes from memory, returning None on error."""
        if not self.attached or not self._pm:
            return None
        try:
            return self._pm.read_bytes(address, length)
        except pymem.exception.MemoryReadError as e:
            logging.error(
                f"MemoryReadError: Could not read memory at: {hex(address)}, length: {length} - {e}"
            )
            return None
        except Exception as e:
            logging.error(
                f"Unexpected error reading bytes at {hex(address)}: {e}")
            return None

    def write_bytes(self, address: int, data: bytes) -> bool:
        """Safely writes raw bytes to memory, returning True on success."""
        if not self.attached or not self._pm:
            return False
        try:
            self._pm.write_bytes(address, data, len(data))
            return True
        except pymem.exception.MemoryWriteError as e:
            logging.error(
                f"MemoryWriteError: Could not write memory at: {hex(address)}, length: {len(data)} - {e}"
            )
            return False
        except Exception as e:
            logging.error(
                f"Unexpected error writing bytes at {hex(address)}: {e}")
            return False

    def read_int(self, address: int) -> Optional[int]:
        return self._read_typed_value(address, "int")

    def write_int(self, address: int, value: int) -> bool:
        if not self.attached or not self._pm:
            return False
        try:
            self._pm.write_int(address, value)
            return True
        except Exception as e:
            logging.error(f"Failed to write int to {hex(address)}: {e}")
            return False

    def read_float(self, address: int) -> Optional[float]:
        return self._read_typed_value(address, "float")

    def write_float(self, address: int, value: float) -> bool:
        if not self.attached or not self._pm:
            return False
        try:
            self._pm.write_float(address, value)
            return True
        except Exception as e:
            logging.error(f"Failed to write float to {hex(address)}: {e}")
            return False

    def read_longlong(self, address: int) -> Optional[int]:
        return self._read_typed_value(address, "longlong")

    def write_longlong(self, address: int, value: int) -> bool:
        if not self.attached or not self._pm:
            return False
        try:
            self._pm.write_longlong(address, value)
            return True
        except Exception as e:
            logging.error(f"Failed to write longlong to {hex(address)}: {e}")
            return False

    def allocate(self, size: int) -> Optional[int]:
        if not self.attached or not self._pm:
            return None
        try:
            return self._pm.allocate(size)
        except Exception as e:
            logging.error(f"Failed to allocate memory of size {size}: {e}")
            return None

    def free(self, address: int) -> bool:
        if not self.attached or not self._pm:
            return False
        try:
            self._pm.free(address)
            return True
        except Exception as e:
            logging.error(f"Failed to free memory at {hex(address)}: {e}")
            return False

        
    def execute_shellcode(self, shellcode: bytes) -> bool:
        """
        The definitive method to execute shellcode.
        This manually allocates memory, writes the shellcode, creates a remote
        thread using the direct WinAPI call, waits for it, and cleans up.
        This bypasses the buggy high-level pymem functions.
        """
        if not self.attached or not self._pm:
            logging.error("Cannot execute shellcode, not attached.")
            return False

        shellcode_addr = None
        try:
            # 1. Allocate memory for the shellcode inside the game
            shellcode_addr = self.allocate(len(shellcode))
            if not shellcode_addr:
                logging.error("Failed to allocate memory for shellcode.")
                return False

            # 2. Write the shellcode to the allocated memory
            if not self.write_bytes(shellcode_addr, shellcode):
                logging.error("Failed to write shellcode to allocated memory.")
                return False

            # 3. Execute the shellcode in a new thread
            logging.info(f"Executing shellcode at remote address {hex(shellcode_addr)}")
            thread_handle = k32.CreateRemoteThread(
                self._pm.process_handle,
                None,
                0,
                shellcode_addr, # The address of our shellcode
                None,
                0,
                None
            )
            
            if not thread_handle:
                error_code = ctypes.windll.kernel32.GetLastError()
                logging.error(f"CreateRemoteThread failed, GetLastError={error_code:#x}")
                return False

            # 4. Wait for the thread to finish executing
            k32.WaitForSingleObject(thread_handle, -1) # -1 means wait indefinitely
            k32.CloseHandle(thread_handle) # Clean up the thread handle
            
            logging.info("Remote thread executed successfully.")
            return True

        except Exception as e:
            logging.error(f"An exception occurred during shellcode execution: {e}")
            return False
            
        finally:
            # 5. ALWAYS free the memory we allocated
            if shellcode_addr:
                self.free(shellcode_addr)


    def _read_ptr_value(self, addr: int) -> Optional[int]:
        """Read an unsigned pointer-sized value (8 bytes) from addr. Return None on failure."""
        try:
            data = self._pm.read_bytes(addr, 8)
            return int.from_bytes(data, "little", signed=False)
        except Exception as e:
            logging.debug(
                f"_read_ptr_value: failed to read 8 bytes at {hex(addr)}: {e}")
            return None

    def _read_typed_value(self, addr: int, type_name: str):
        """
        Read a value at `addr` according to type_name.
        Supported: 'int' (32-bit signed), 'uint' (32-bit unsigned), 'int64', 'uint64',
                'float' (32-bit), 'double' (64-bit), 'bool', 'bytes:<len>'
        Returns Python value or None on failure.
        """
        try:
            if type_name is None:
                # default: read pointer-sized integer
                val = self._read_ptr_value(addr)
                return val

            t = str(type_name).lower()
            if t == "int":
                data = self._pm.read_bytes(addr, 4)
                return int.from_bytes(data, "little", signed=True)
            if t == "uint":
                data = self._pm.read_bytes(addr, 4)
                return int.from_bytes(data, "little", signed=False)
            if t == "int64" or t == "long" or t == "longlong":
                data = self._pm.read_bytes(addr, 8)
                return int.from_bytes(data, "little", signed=True)
            if t == "uint64":
                data = self._pm.read_bytes(addr, 8)
                return int.from_bytes(data, "little", signed=False)
            if t == "float":
                import struct
                data = self._pm.read_bytes(addr, 4)
                return struct.unpack("<f", data)[0]
            if t == "double":
                import struct
                data = self._pm.read_bytes(addr, 8)
                return struct.unpack("<d", data)[0]
            if t == "bool":
                data = self._pm.read_bytes(addr, 1)
                return bool(int.from_bytes(data, "little"))
            if t.startswith("bytes:"):
                try:
                    length = int(t.split(":", 1)[1])
                except Exception:
                    length = 16
                return self._pm.read_bytes(addr, length)
            # fallback: try pointer-sized
            return self._read_ptr_value(addr)
        except Exception as e:
            logging.debug(
                f"_read_typed_value: failed to read {type_name} at {hex(addr)}: {e}")
            return None

    def _parse_offset(self, off):
        """Convert offset expressed as int or hex string into int."""
        if isinstance(off, int):
            return off
        if isinstance(off, str):
            s = off.strip().lower()
            # allow formats like "0x10ef8" or "10ef8"
            if s.startswith("0x"):
                return int(s, 16)
            try:
                return int(s, 16)
            except ValueError:
                try:
                    return int(s)
                except ValueError:
                    logging.warning(f"Invalid offset format: {off}")
                    return None
        logging.warning(f"Unsupported offset type: {type(off)}")
        return None

    def _follow_pointer_chain(self, base_addr: int, offsets: list[int]) -> Optional[int]:
        """
        Follows a pointer chain to resolve the final memory address.
        This function uses the proven logic from the standalone test script.
        """
        if not self.attached or not self._pm:
            return None

        addr = base_addr

        for i, offset in enumerate(offsets[:-1]):
            try:
                addr = self._pm.read_longlong(addr + offset)
                if addr == 0:
                    logging.warning(
                        f"Pointer chain resolving to NULL at step {i} (offset {hex(offset)})")
                    return None
            except Exception as e:
                logging.error(
                    f"Failed to read pointer in chain at step {i} (address {hex(addr + offset)}): {e}")
                return None

        # Add the final offset to get the address of the actual value
        return addr + offsets[-1]
    
    
    def read_pointer(self, address: int) -> Optional[int]:
        """
        NEW METHOD: Reads an 8-byte value and interprets it as a 64-bit
        unsigned integer, which is correct for memory addresses (pointers).
        """
        try:
            data = self._pm.read_bytes(address, 8)
            # Use signed=False to correctly handle high-memory addresses
            return int.from_bytes(data, "little", signed=False)
        except Exception:
            return None
        
        
    def resolve_address(self, path_key: str) -> Optional[int]:
        """The definitive, simple, and universal address resolver."""
        if not self.attached: return None

        if path_key in self._static_pointer_addrs:
            if path_key == "TeleportFunction":
                return self._static_pointer_addrs[path_key]
            
            return self.read_pointer(self._static_pointer_addrs[path_key])
        
        if path_key in self._direct_addrs:
            return self._direct_addrs[path_key]

        if path_key in self._addresses:
            path_info = self._addresses[path_key]
            base_name = path_info.get("base")
            if not base_name: return None
            
            start_address = self.resolve_address(base_name)
            if start_address is None: return None
            
            offsets = [int(o, 0) if isinstance(o, str) else int(o) for o in path_info.get("offsets", [])]
            if not offsets: return start_address
            
            return self._follow_pointer_chain(start_address, offsets)

        logging.warning(f"Could not resolve address for key: {path_key}")
        return None

    def read_value(self, path_key: str) -> Tuple[Optional[int], Any]:
        """
        NEW PUBLIC METHOD: Resolves a key and reads the value at the final address.
        """
        address = self.resolve_address(path_key)
        if address is None:
            return None, None

        path_info = self._addresses.get(path_key, {})
        value_type = path_info.get("type")

        if value_type == "bytes":
            length = path_info.get("length", 16)
            value = self.read_bytes(address, length)
        else:
            value = self._read_typed_value(address, value_type)

        logging.debug(
            f"read_value: '{path_key}' -> {hex(address)}, value={value} (type={value_type})")
        return address, value
