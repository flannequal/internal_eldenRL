import os
import time
import logging
from typing import Optional, Dict, Any
import yaml
import pymem


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

        # This dictionary will TEMPORARILY hold the Relative Virtual Addresses (RVAs)
        self._bases_static = addresses_yaml.get("bases_static", {})

        # Load other configs
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
        """Attaches to the process and calculates absolute pointer addresses."""
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
                logging.error(f"could not find module '{self.process_name}'.")
                self.detach()
                return False

            self.attached = True
            logging.info(
                f"successfully attached to process '{self.process_name}' (PID: {self._pm.process_id}).")

            module_base = self._module.lpBaseOfDll

            absolute_base_pointers = {}
            for name, rva in self._bases_static.items():
                absolute_base_pointers[name] = module_base + rva

            self._bases_static = absolute_base_pointers

            logging.debug(
                f"Correctly calculated 'WorldChrMan' pointer address to: {hex(self._bases_static.get('WorldChrMan', 0))}")

            # Initialize and perform AOB scans
            self._aob_scans = {}
            for name, aob_pattern in self._aob_patterns.items():
                resolved_addr = self._scan_aob(aob_pattern)
                if resolved_addr:
                    self._bases_static[name] = resolved_addr
                    self._aob_scans[name] = resolved_addr

            return True
        except pymem.exception.ProcessNotFound:
            logging.warning(f"Process '{self.process_name}' not found.")
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
            logging.error(
                f"Failed to create remote thread at {hex(address)}: {e}")
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

    def _follow_pointer_chain(self, base_addr: int, offsets: list[int]) -> Optional[int]:
        """
        Follows a pointer chain to resolve the final memory address.
        This function uses the proven logic from the standalone test script.
        """
        if not self.attached or not self._pm:
            return None

        addr = base_addr

        # Dereference all offsets except the last one
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

    def _resolve_pointer_path(self, path_key: str) -> Optional[int]:
        """Resolves an address key to its final, absolute memory address."""
        if not self.attached or not self._pm:
            return None

        path_info = self._addresses.get(path_key)
        if not isinstance(path_info, dict):
            logging.warning(
                f"Address key '{path_key}' not found or not a valid structure in config.")
            return None

        # step1 resolve the base name e.g WorldChrMan
        base_name = path_info.get("base")
        if not base_name:
            logging.warning(f"No 'base' specified for '{path_key}'")
            return None

        # Look up the absolute address of the static pointer (calculated in attach)
        static_pointer_addr = self._bases_static.get(base_name)
        if static_pointer_addr is None:
            logging.warning(
                f"Could not find the static pointer address for base '{base_name}'")
            return None

        try:
            # step 2 dereference the pointer to get the true base address
            true_base_addr = self._pm.read_longlong(static_pointer_addr)
            if true_base_addr == 0:
                logging.warning(f"Base pointer for '{base_name}' is NULL.")
                return None
        except Exception as e:
            logging.error(
                f"Failed to read/dereference base pointer for '{base_name}' at {hex(static_pointer_addr)}: {e}")
            return None

        # step 3 follow the offset chain
        offsets_spec = path_info.get("offsets", [])
        if not offsets_spec:
            return true_base_addr  # No offsets, return the dereferenced base

        offsets = [int(o, 0) if isinstance(o, str) else int(o)
                   for o in offsets_spec]

        return self._follow_pointer_chain(true_base_addr, offsets)

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
        # Use _addresses, not self.getattr
        path_info = self._addresses.get(path_key, {})
        desired_type = None
        if isinstance(path_info, dict):
            desired_type = path_info.get("type")
        val = self._read_typed_value(addr, desired_type)
        logging.debug(
            f"get_address_value: '{path_key}' -> {hex(addr)}, value={val} (type={desired_type})")
        return addr, val
