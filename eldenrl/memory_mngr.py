import logging
import struct
from typing import Any, Dict, List, Optional, Tuple

import pymem
import pymem.process
import yaml

logger = logging.getLogger(__name__)


class MemoryManager:

    def __init__(self, process_name: str = "eldenring.exe"):
        self.process_name = process_name
        self.pm: Optional[pymem.Pymem] = None
        self.module_base: int = 0
        self.config: Dict[str, Any] = {}
        self.attached = False
        self._resolve_cache: Dict[str, Optional[int]] = {}

    def attach(self) -> bool:
        if self.attached:
            return True
        try:
            self.pm = pymem.Pymem(self.process_name)
            self.module_base = pymem.process.module_from_name(
                self.pm.process_handle, self.process_name
            ).lpBaseOfDll
            self.attached = True
            logger.info("attached to %s (pid %s)", self.process_name, self.pm.process_id)
            return True
        except pymem.exception.ProcessNotFound:
            logger.error("process '%s' not found", self.process_name)
            return False
        except Exception as exc:
            logger.error("could not attach to %s: %s", self.process_name, exc)
            return False

    def load_addresses(self, file_path: str = "config/addresses.yaml") -> None:
        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                self.config = yaml.safe_load(handle) or {}
            logger.info("loaded addresses from '%s'", file_path)
        except FileNotFoundError:
            logger.error("address config not found at '%s'", file_path)
            self.config = {}
        except Exception as exc:
            logger.error("could not load address config: %s", exc)
            self.config = {}
        self._resolve_cache = {}

    def _pointer_config(self, name: Optional[str]) -> Dict[str, Any]:
        if not name:
            return {}
        return (self.config.get("pointers", {}).get(name)
                or self.config.get("teleport", {}).get(name)
                or {})

    def _full_chain(self, name: Optional[str]) -> Optional[List[int]]:
        pointer = self._pointer_config(name)
        if pointer:
            base_chain = self._full_chain(pointer.get("base"))
            if base_chain is None:
                return None
            return base_chain + pointer.get("offsets", [])
        if name in self.config.get("bases_static", {}):
            return [self.config["bases_static"][name]]
        return None

    def resolve(self, name: str) -> Optional[int]:
        if name in self._resolve_cache:
            return self._resolve_cache[name]

        chain = self._full_chain(name)
        if not chain:
            logger.error("no pointer chain defined for '%s'", name)
            self._resolve_cache[name] = None
            return None

        rva, offsets = chain[0], chain[1:]
        addr = self.read_longlong(self.module_base + rva)
        if not addr:
            logger.error("'%s': static base at %s is null", name, hex(self.module_base + rva))
            self._resolve_cache[name] = None
            return None

        for i, offset in enumerate(offsets):
            addr += offset
            if i < len(offsets) - 1:  # last offset lands on the value
                addr = self.read_longlong(addr)
                if not addr:
                    logger.warning("'%s': null link at offset %s", name, hex(offset))
                    self._resolve_cache[name] = None
                    return None

        self._resolve_cache[name] = addr
        return addr

    def read_pointer(self, name: str) -> Tuple[Optional[int], Any]:
        addr = self.resolve(name)
        if addr is None:
            return None, None

        pointer = self._pointer_config(name)
        value_type = pointer.get("type", "bytes")
        readers = {
            "byte": self.read_byte,
            "int": self.read_int,
            "float": self.read_float,
            "longlong": self.read_longlong,
        }
        if value_type == "bytes":
            return addr, self.read_bytes(addr, pointer.get("length", 8))
        if value_type in readers:
            return addr, readers[value_type](addr)

        logger.warning("unsupported type '%s' for pointer '%s'", value_type, name)
        return addr, None

    def write_pointer(self, name: str, value: Any) -> bool:
        addr = self.resolve(name)
        if addr is None:
            return False

        pointer = self._pointer_config(name)
        value_type = pointer.get("type", "bytes")
        writers = {
            "byte": self.write_byte,
            "int": self.write_int,
            "float": self.write_float,
            "longlong": self.write_longlong,
            "bytes": self.write_bytes,
        }
        if value_type in writers:
            return writers[value_type](addr, value)

        logger.warning("unsupported type '%s' for pointer '%s'", value_type, name)
        return False

    def read_teleport_coords(self) -> Optional[Tuple[float, float, float]]:
        addrs = [self.resolve(name) for name in ("xGlobal", "zGlobal", "yGlobal")]
        if not all(addrs):
            logger.error("could not resolve global coordinate pointers")
            return None

        coords = [self.read_float(addr) for addr in addrs]
        if any(value is None for value in coords):
            return None
        return coords[0], coords[1], coords[2]

    def read_bytes(self, address: int, length: int) -> Optional[bytes]:
        if not self.attached or not self.pm:
            return None
        try:
            return self.pm.read_bytes(address, length)
        except Exception as exc:
            logger.debug("read of %d bytes at %s failed: %s", length, hex(address), exc)
            return None

    def write_bytes(self, address: int, value: bytes) -> bool:
        if not self.attached or not self.pm:
            return False
        try:
            self.pm.write_bytes(address, value, len(value))
            return True
        except Exception as exc:
            logger.debug("write of %d bytes at %s failed: %s", len(value), hex(address), exc)
            return False

    def read_byte(self, address: int) -> Optional[int]:
        data = self.read_bytes(address, 1)
        return data[0] if data else None

    def write_byte(self, address: int, value: int) -> bool:
        return self.write_bytes(address, bytes([value & 0xFF]))

    def read_int(self, address: int) -> Optional[int]:
        data = self.read_bytes(address, 4)
        return int.from_bytes(data, "little", signed=True) if data else None

    def write_int(self, address: int, value: int) -> bool:
        return self.write_bytes(address, value.to_bytes(4, "little", signed=True))

    def read_float(self, address: int) -> Optional[float]:
        data = self.read_bytes(address, 4)
        return struct.unpack("<f", data)[0] if data else None

    def write_float(self, address: int, value: float) -> bool:
        return self.write_bytes(address, struct.pack("<f", value))

    def read_longlong(self, address: int) -> Optional[int]:
        data = self.read_bytes(address, 8)
        return int.from_bytes(data, "little") if data else None

    def write_longlong(self, address: int, value: int) -> bool:
        return self.write_bytes(address, value.to_bytes(8, "little"))
