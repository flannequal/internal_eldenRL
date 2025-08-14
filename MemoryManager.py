import os
import time
import logging
from typing import Optional, Dict, Any
import yaml
import pymem
import pymem.pattern
import struct


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
        self._module = None  # Store the main module for pattern scanning

        # Config caches for generic memory access (bases and pointer chains)
        self._bases_static: Dict[str, int] = {} # Resolved static base addresses
        self._aob_patterns: Dict[str, str] = {} # AOB patterns to scan
        self._addresses: Dict[str, Any] = {}    # Pointer chain definitions from config

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
        logging.info(f"Loading memory configurations from {self.addresses_config_path}...")
        addresses_yaml = self._safe_load_yaml(self.addresses_config_path)

        self._bases_static = {}
        self._aob_patterns = {}
        self._addresses = {}

        # Load static addresses
        for name, value in addresses_yaml.get("bases_static", {}).items():
            try:
                self._bases_static[name] = int(str(value), 16)
            except ValueError:
                logging.warning(
                    f"Could not convert '{value}' to a base address for '{name}'."
                )

        # Load AOB patterns
        for name, pattern in addresses_yaml.get("bases_aob", {}).items():
            if isinstance(pattern, str):
                self._aob_patterns[name] = pattern.strip()
            else:
                logging.warning(
                    f"Invalid AOB pattern type for '{name}': {type(pattern)}"
                )
        
        # Load generic pointer chain definitions
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
            # if odd length, try to salvage by prepending a '?' to first nibble (rare)
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

        # Parse pattern
        pattern_bytes, mask = self._parse_aob_pattern(aob_pattern_str)
        if not pattern_bytes:
            logging.warning(f"Empty/invalid AOB pattern: '{aob_pattern_str}'")
            return None

        # Modules to try (main module first, then common DLL where game logic resides)
        modules_to_try = []
        if getattr(self, "_module", None):
            modules_to_try.append(self._module)

        # Try GameAssembly.dll and a few other common names (extend as needed)
        try:
            all_mods = pymem.process.list_modules(self._pm.process_handle)
            # preferred module names (lowercase)
            preferred = {"gameassembly.dll", self.process_name.lower()}
            # add preferred modules first if present
            for mod in all_mods:
                name = getattr(mod, "name", "").lower()
                if name in preferred and mod not in modules_to_try:
                    modules_to_try.append(mod)
            # fallback: append all modules (if earlier tries fail you may want to expand search)
        except Exception as e:
            logging.debug(f"Could not list modules: {e}")

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
        if self.attached and self._pm:
            return True
        if time.time() - self._last_attach_attempt < 2.0:
            return False
        self._last_attach_attempt = time.time()

        try:
            self._pm = pymem.Pymem(self.process_name)
            self._module = pymem.process.module_from_name(
                self._pm.process_handle, self.process_name
            )
            if not self._module:
                logging.error(f"Could not find module '{self.process_name}'.")
                self.detach()
                return False

            logging.info(f"Module {self._module.name} found at {hex(self._module.lpBaseOfDll)} "
                         f"size {hex(self._module.SizeOfImage)}")

            self.attached = True
            logging.info(
                f"Successfully attached to process '{self.process_name}' (PID: {self._pm.process_id})."
            )

            # Perform AOB scans on attach and cache results
            for name, aob_pattern in self._aob_patterns.items():
                # Only scan if not already a static address (e.g., if it's explicitly defined in bases_static)
                if name not in self._bases_static: 
                    resolved_addr = self._scan_aob(aob_pattern)
                    if resolved_addr:
                        self._bases_static[name] = resolved_addr # Cache the resolved address

            return True
        except pymem.exception.ProcessNotFound:
            logging.warning(
                f"Process '{self.process_name}' not found. Is the game running?"
            )
            return False
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

    def create_remote_process(self, address: int) -> bool:
        """Executes shellcode at the given address in a remote thread."""
        if not self.attached or not self._pm:
            return False
        try:
            self._pm.create_remote_thread(address)
            return True
        except Exception as e:
            logging.error(f"Failed to create remote thread at {hex(address)}: {e}")
            return False


    # --- helpers --------------------------------------------------------------

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

# --- pointer-chain follower ----------------------------------------------

    def _follow_pointer_chain(self, base_addr: int, offsets: list[int]) -> Optional[int]:
        """Given base address and list of offsets (ints), follow pointer chain and return final address."""
        addr = base_addr
        for i, off in enumerate(offsets):
            if addr is None:
                logging.debug(
                    f"_follow_pointer_chain: addr became None at step {i}")
                return None
            target = addr + off
            # When offsets include a final 0 which means "addr + 0" and no deref, we still read pointer at that address
            # For the last offset in the chain, it's typically an offset to the value, not another pointer.
            # So, only dereference if it's not the *last* offset.
            # Correction: The original code always dereferences. We should keep that behavior.
            # The last offset is part of the chain leading to a pointer, not necessarily the final value.
            ptr = self._read_ptr_value(target)
            if ptr is None:
                logging.debug(
                    f"_follow_pointer_chain: failed to read pointer at {hex(target)} (step {i})")
                return None
            logging.debug(
                f"_follow_pointer_chain: step {i}: read {hex(ptr)} from {hex(target)}")
            addr = ptr
        return addr

# --- main resolver/reader -----------------------------------------------

    def _resolve_pointer_path(self, path_key: str, _visited: Optional[set] = None) -> Optional[int]:
        """
        Resolve the name `path_key` to a numeric address.
        Supports:
        - static bases in self._bases_static (already parsed ints)
        - aob patterns in self._aob_patterns (scanned)
        - pointer-chain dicts under self._addresses (with keys: base, offsets)
        Prevents recursion loops with _visited set.
        """
        if not self.attached or not self._pm:
            return None

        if _visited is None:
            _visited = set()
        if path_key in _visited:
            logging.warning(
                f"_resolve_pointer_path: recursive reference detected for '{path_key}'")
            return None
        _visited.add(path_key)

        # 1) direct static base
        bases = self._bases_static
        if path_key in bases:
            logging.debug(
                f"_resolve_pointer_path: '{path_key}' found in bases_static -> {hex(bases[path_key])}")
            return bases[path_key]

        # This method's logic should generally remain unchanged, but ensuring correct use of _aob_scans cache
        # 1) direct static base
        bases = self._bases_static
        if path_key in bases:
            logging.debug(
                f"_resolve_pointer_path: '{path_key}' found in bases_static -> {hex(bases[path_key])}")
            return bases[path_key]

        # 2) look in addresses table for pointer-chain entry or a direct AOB definition
        path_info = self._addresses.get(path_key) # Check in general addresses
        
        # If not found in addresses, try AOB patterns directly
        aobs = self._aob_patterns
        if path_key in aobs:
            if path_key not in self._aob_scans:
                self._aob_scans[path_key] = self._scan_aob(aobs[path_key])
            addr = self._aob_scans[path_key]
            logging.debug(
                f"_resolve_pointer_path: '{path_key}' found in aob_patterns (scanned) -> {addr if addr is None else hex(addr)}")
            return addr

        if path_info is None:
            logging.debug(
                f"_resolve_pointer_path: '{path_key}' not in addresses table, static bases, or AOB patterns")
            return None

        # If the config has a plain integer or hex string (e.g., direct address)
        if isinstance(path_info, int):
            return path_info
        if isinstance(path_info, str):
            s = path_info.strip()
            if s.upper().startswith("AOB:"):
                # If it's an AOB string *within* the addresses block, treat it like a normal AOB pattern
                # This ensures it gets cached properly under _aob_scans if its key is used directly.
                aob_key_for_cache = f"AOB_STR_IN_ADDR:{path_key}" # Unique key for this case
                if aob_key_for_cache not in self._aob_scans:
                    self._aob_scans[aob_key_for_cache] = self._scan_aob(s)
                addr = self._aob_scans[aob_key_for_cache]
                logging.debug(
                    f"_resolve_pointer_path: '{path_key}' found as direct AOB string (scanned) -> {addr if addr is None else hex(addr)}")
                return addr
            try:
                return int(s, 16)
            except ValueError:
                # try treat as reference to another key (recursive)
                return self._resolve_pointer_path(s, _visited)

        # If dict -> expect base + offsets (offsets optional)
        if isinstance(path_info, dict):
            base_spec = path_info.get("base") or path_info.get(
                "address") or path_info.get("module_base")
            offsets_spec = path_info.get(
                "offsets") or path_info.get("pointer_offsets") or []
            # resolve base_spec
            base_addr = None
            if isinstance(base_spec, int):
                base_addr = base_spec
            elif isinstance(base_spec, str):
                bs = base_spec.strip()
                if bs.upper().startswith("AOB:"):
                    # if base is an AOB string, scan it
                    # No specific cache for base AOBs, re-scan if needed or assume _aob_patterns covers it
                    base_addr = self._scan_aob(bs) 
                else:
                    # named base, hex string, or other key (recursive call)
                    try:
                        base_addr = int(bs, 16)
                    except ValueError:
                        # treat as named key (recursive call)
                        base_addr = self._resolve_pointer_path(bs, _visited)
            else:
                logging.warning(
                    f"_resolve_pointer_path: unsupported base_spec type for '{path_key}': {type(base_spec)}")
                return None

            if base_addr is None:
                logging.warning(
                    f"_resolve_pointer_path: base for '{path_key}' could not be resolved: {base_spec}")
                return None

            # parse offsets into ints
            offsets = []
            for o in offsets_spec:
                parsed = self._parse_offset(o)
                if parsed is None:
                    logging.warning(
                        f"_resolve_pointer_path: skipping invalid offset '{o}' for '{path_key}'")
                    continue
                offsets.append(parsed)

            if not offsets:
                # no offsets: base_addr is the final address
                logging.debug(
                    f"_resolve_pointer_path: '{path_key}' resolved to base {hex(base_addr)} (no offsets)")
                return base_addr

            # follow pointer chain
            final = self._follow_pointer_chain(base_addr, offsets)
            if final is None:
                logging.warning(
                    f"_resolve_pointer_path: failed to follow pointer chain for '{path_key}' (base {hex(base_addr)})")
            else:
                logging.debug(
                    f"_resolve_pointer_path: '{path_key}' resolved to {hex(final)}")
            return final

        logging.warning(
            f"_resolve_pointer_path: unsupported address format for '{path_key}' ({type(path_info)})")
        return None

    def get_address_value(self, path_key: str):
        """
        Resolve an address key from addresses.yaml and read the memory value
        using the 'type' field if present in the addresses config.
        Returns (resolved_addr, value) or (None, None) on failure.
        """
        addr = self._resolve_pointer_path(path_key)
        if addr is None:
            logging.debug(
                f"get_address_value: could not resolve address for '{path_key}'")
            return None, None

        # determine type from addresses table when available
        path_info = self._addresses.get(path_key, {}) # Use _addresses, not self.getattr
        desired_type = None
        if isinstance(path_info, dict):
            desired_type = path_info.get("type")
        val = self._read_typed_value(addr, desired_type)
        logging.debug(
            f"get_address_value: '{path_key}' -> {hex(addr)}, value={val} (type={desired_type})")
        return addr, val
