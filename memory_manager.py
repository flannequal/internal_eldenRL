import ctypes
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import pymem
import pymem.process
import yaml

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class MemoryManager:
    """
    Handles low-level memory operations for the Elden Ring process, including
    process attachment, pointer chain resolution, and reading/writing memory.
    """

    def __init__(self, process_name: str = "eldenring.exe"):
        self.process_name = process_name
        self.pm: Optional[pymem.Pymem] = None
        self.module_base: int = 0
        self.config: Dict[str, Any] = {}
        self.attached = False
        self._resolve_cache: Dict[str, Optional[int]] = {}

    def attach(self) -> bool:
        """
        Attaches to the game process and loads memory configurations.
        Returns True on success, False otherwise.
        """
        if self.attached:
            return True
        try:
            self.pm = pymem.Pymem(self.process_name)
            self.module_base = pymem.process.module_from_name(
                self.pm.process_handle, self.process_name
            ).lpBaseOfDll
            self.attached = True
            logging.info(f"Successfully attached to {self.process_name} (PID: {self.pm.process_id}).")
            return True
        except pymem.exception.ProcessNotFound:
            logging.error(f"Process '{self.process_name}' not found. Is the game running?")
            return False
        except Exception as e:
            logging.error(f"An unexpected error occurred while attaching: {e}")
            return False

    def load_addresses(self, file_path: str = "config/addresses.yaml"):
        """Loads memory addresses and pointer chains from a YAML file."""
        try:
            with open(file_path, "r") as f:
                self.config = yaml.safe_load(f)
            logging.info(f"Loaded memory addresses from '{file_path}'.")
            # Clear cache when new addresses are loaded
            self._resolve_cache = {}
        except FileNotFoundError:
            logging.error(f"Address configuration file not found at '{file_path}'.")
            self.config = {}
        except Exception as e:
            logging.error(f"Error loading address configuration: {e}")
            self.config = {}

    def _get_full_chain(self, name: str) -> Optional[List[int]]:
        """
        Helper to recursively build a full list of offsets from the static base RVA.
        """
        config = self.config.get("pointers", {}).get(name) or self.config.get("teleport", {}).get(name)
        
        if config:
            base_name = config.get("base")
            offsets = config.get("offsets", [])
            
            base_chain = self._get_full_chain(base_name)
            if base_chain is None:
                return None
            
            return base_chain + offsets

        if name in self.config.get("bases_static", {}):
            return [self.config["bases_static"][name]]
        
        return None

    def _get_address_from_config(self, name: str) -> Optional[int]:
        """
        REVISED 5: Final resolver implementing the confirmed logic from diagnostic "Method C".
        """
        if name in self._resolve_cache:
            return self._resolve_cache[name]

        full_chain = self._get_full_chain(name)
        if not full_chain:
            logging.error(f"Could not construct a full pointer chain for '{name}'.")
            self._resolve_cache[name] = None
            return None

        try:
            # The first element of the full chain is always the RVA.
            rva = full_chain[0]
            offsets = full_chain[1:]

            # 1. Read the initial pointer value from the static base address.
            addr = self.read_longlong(self.module_base + rva)
            if addr is None or addr == 0:
                logging.error(f"Chain '{name}': Failed to read initial pointer from base address {hex(self.module_base + rva)}")
                self._resolve_cache[name] = None
                return None

            # 2. Iterate through the rest of the offsets, applying the "add then dereference" pattern.
            for i, offset in enumerate(offsets):
                addr += offset
                # Don't dereference on the last step, as it's the final address of the value.
                if i < len(offsets) - 1:
                    addr = self.read_longlong(addr)
                    if addr is None or addr == 0:
                        logging.warning(f"Chain for '{name}' resolved to NULL while processing offset {hex(offset)}.")
                        self._resolve_cache[name] = None
                        return None
            
            self._resolve_cache[name] = addr
            return addr

        except Exception as e:
            logging.error(f"Exception while resolving chain for '{name}': {e}")
            self._resolve_cache[name] = None
            return None

    def read_pointer(self, name: str) -> Tuple[Optional[int], Any]:
        """
        Reads a value from a named pointer in the config.
        Returns the final address and the read value.
        """
        addr = self._get_address_from_config(name)
        if addr is None:
            return None, None

        # Determine the type of value to read
        config = self.config.get("pointers", {}).get(name, {}) or self.config.get("teleport", {}).get(name, {})
        value_type = config.get("type", "bytes")
        length = config.get("length", 8)

        if value_type == "int":
            return addr, self.read_int(addr)
        elif value_type == "float":
            return addr, self.read_float(addr)
        elif value_type == "longlong":
            return addr, self.read_longlong(addr)
        elif value_type == "bytes":
            return addr, self.read_bytes(addr, length)
        else:
            logging.warning(f"Unsupported value type '{value_type}' for pointer '{name}'.")
            return addr, None

    def write_pointer(self, name: str, value: Any) -> bool:
        """Writes a value to a named pointer in the config."""
        addr = self._get_address_from_config(name)
        if addr is None:
            return False

        config = self.config.get("pointers", {}).get(name, {}) or self.config.get("teleport", {}).get(name, {})
        value_type = config.get("type", "bytes")

        if value_type == "int":
            return self.write_int(addr, value)
        elif value_type == "float":
            return self.write_float(addr, value)
        elif value_type == "longlong":
            return self.write_longlong(addr, value)
        elif value_type == "bytes":
            return self.write_bytes(addr, value)
        else:
            logging.warning(f"Unsupported value type '{value_type}' for pointer '{name}'.")
            return False

    def read_teleport_coords(self) -> Optional[Tuple[float, float, float]]:
        """Reads the global X, Z, Y coordinates for teleporting."""
        x_addr = self._get_address_from_config("xGlobal")
        z_addr = self._get_address_from_config("zGlobal")
        y_addr = self._get_address_from_config("yGlobal")

        if not all([x_addr, z_addr, y_addr]):
            logging.error("Could not resolve all global coordinate addresses for teleport.")
            return None

        x = self.read_float(x_addr)
        z = self.read_float(z_addr)
        y = self.read_float(y_addr)

        if x is None or z is None or y is None:
            return None
        return x, z, y

    # --- Primitive Read/Write Operations ---
    def read_bytes(self, address: int, length: int) -> Optional[bytes]:
        if not self.attached or not self.pm: return None
        try:
            return self.pm.read_bytes(address, length)
        except Exception as e:
            logging.debug(f"Failed to read {length} bytes at {hex(address)}: {e}")
            return None
    
    def write_bytes(self, address: int, value: bytes) -> bool:
        if not self.attached or not self.pm: return False
        try:
            self.pm.write_bytes(address, value, len(value))
            return True
        except Exception as e:
            logging.debug(f"Failed to write {len(value)} bytes to {hex(address)}: {e}")
            return False
        
    def read_byte(self, address: int) -> Optional[int]:
        data = self.read_bytes(address, 1)
        return int.from_bytes(data, 'little') if data else None

    def read_int(self, address: int) -> Optional[int]:
        data = self.read_bytes(address, 4)
        return int.from_bytes(data, 'little', signed=True) if data else None

    def write_int(self, address: int, value: int) -> bool:
        return self.write_bytes(address, value.to_bytes(4, 'little', signed=True))

    def read_float(self, address: int) -> Optional[float]:
        data = self.read_bytes(address, 4)
        if not data: return None
        import struct
        return struct.unpack('<f', data)[0]

    def write_float(self, address: int, value: float) -> bool:
        import struct
        return self.write_bytes(address, struct.pack('<f', value))

    def read_longlong(self, address: int) -> Optional[int]:
        data = self.read_bytes(address, 8)
        return int.from_bytes(data, 'little') if data else None

    def write_longlong(self, address: int, value: int) -> bool:
        return self.write_bytes(address, value.to_bytes(8, 'little'))
        
    def allocate(self, size: int) -> Optional[int]:
        if not self.attached or not self.pm: return None
        try:
            return self.pm.allocate(size)
        except Exception as e:
            logging.error(f"Failed to allocate memory: {e}")
            return None

    def free(self, address: int) -> bool:
        if not self.attached or not self.pm: return False
        try:
            # pymem's free is a wrapper for VirtualFreeEx with MEM_RELEASE
            return self.pm.free(address)
        except Exception as e:
            logging.error(f"Failed to free memory at {hex(address)}: {e}")
            return False
