# memory_manager.py
import os
import struct
import yaml
from typing import Any, Dict, Optional, Tuple
import pymem
import pymem.process

class MemoryManager:
    """
    Minimal MemoryManager:
      - attach() / detach()
      - resolve_address(key) -> address (int) or None
      - read_value(key) -> (addr, value) where value type depends on YAML 'type'
      - read_int/read_float/read_longlong/read_bytes, write_bytes
      - memory_check() - iterate addresses and try reading
    """

    def __init__(self, process_name: str = "eldenring.exe", addresses_path: str = "config/addresses.yaml"):
        self.process_name = process_name
        self.addresses_path = addresses_path

        self.pm: Optional[pymem.Pymem] = None
        self.module_base: Optional[int] = None
        self.process_handle: Optional[int] = None

        # loaded YAML
        self.raw: Dict[str, Any] = {}
        self._bases_static = {}
        self._addresses = {}

        if os.path.exists(self.addresses_path):
            with open(self.addresses_path, "r", encoding="utf-8") as f:
                self.raw = yaml.safe_load(f) or {}
                self._bases_static = self.raw.get("bases_static", {}) or {}
                self._addresses = self.raw.get("addresses", {}) or {}

    # ---- attach / detach ----
    def attach(self) -> bool:
        try:
            self.pm = pymem.Pymem(self.process_name)
            # get module base for eldenring.exe
            module = pymem.process.module_from_name(self.pm.process_handle, self.process_name)
            self.module_base = module.lpBaseOfDll
            # keep raw handle for WinAPI calls if needed
            self.process_handle = int(self.pm.process_handle)
            return True
        except Exception as e:
            # minimal feedback
            print(f"[MemoryManager] attach failed: {e}")
            self.pm = None
            self.module_base = None
            self.process_handle = None
            return False

    def detach(self) -> None:
        try:
            if self.pm:
                self.pm.close_process()
        except Exception:
            pass
        self.pm = None
        self.module_base = None
        self.process_handle = None

    # ---- low-level read / write primitives ----
    def read_bytes(self, addr: int, size: int) -> Optional[bytes]:
        if not self.pm:
            return None
        try:
            return self.pm.read_bytes(addr, size)
        except Exception:
            return None

    def write_bytes(self, addr: int, data: bytes) -> bool:
        if not self.pm:
            return False
        try:
            self.pm.write_bytes(addr, data, len(data))
            return True
        except Exception:
            return False

    def read_int(self, addr: int) -> Optional[int]:
        b = self.read_bytes(addr, 4)
        if not b or len(b) < 4:
            return None
        return struct.unpack("<i", b)[0]

    def read_u32(self, addr: int) -> Optional[int]:
        b = self.read_bytes(addr, 4)
        if not b or len(b) < 4:
            return None
        return struct.unpack("<I", b)[0]

    def read_float(self, addr: int) -> Optional[float]:
        b = self.read_bytes(addr, 4)
        if not b or len(b) < 4:
            return None
        return struct.unpack("<f", b)[0]

    def read_longlong(self, addr: int) -> Optional[int]:
        b = self.read_bytes(addr, 8)
        if not b or len(b) < 8:
            return None
        return struct.unpack("<Q", b)[0]

    # ---- address resolver (supports bases_static and recursive address bases) ----
    def resolve_address(self, key: str) -> Optional[int]:
        """
        Resolve an address by key in addresses.yaml.
        Semantics:
          - if the entry.base refers to a bases_static key, start at (module_base + base_offset).
          - if entry.base refers to another address key, resolve that recursively.
          - offsets: list of ints (hex strings allowed). Implementation:
              addr = base_addr + offsets[0]
              for each subsequent offset in offsets[1:]:
                  ptr = read_longlong(addr)
                  addr = ptr + offset
              return addr
        If offsets is a single element, the returned address is module_base + offset (no deref).
        """
        if self.pm is None or self.module_base is None:
            return None
        if key not in self._addresses:
            return None
        entry = self._addresses[key]
        base_ref = entry.get("base")
        offsets = entry.get("offsets", [])
        # parse offsets
        offs = []
        for o in offsets:
            if isinstance(o, str) and o.lower().startswith("0x"):
                offs.append(int(o, 16))
            else:
                offs.append(int(o))

        # determine base address
        if isinstance(base_ref, str) and base_ref in self._bases_static:
            base_offset = self._bases_static[base_ref]
            base_addr = self.module_base + int(base_offset)
        elif isinstance(base_ref, str) and base_ref in self._addresses:
            # recursive resolve: the base is another named address (that returns an address, not value)
            base_addr = self.resolve_address(base_ref)
            if base_addr is None:
                return None
        else:
            # unknown base type - fail
            return None

        if not offs:
            return base_addr

        # first step: module_base/base + offs[0]
        addr = base_addr + offs[0]

        # if only one offset, return addr (no deref)
        for o in offs[1:]:
            ptr = self.read_longlong(addr)
            if ptr is None:
                return None
            addr = ptr + o
        return addr

    # ---- read_value convenience: returns (addr, value) ----
    def read_value(self, key: str) -> Tuple[Optional[int], Optional[Any]]:
        """
        Read a value for the given address key according to YAML 'type'.
        Returns (resolved_addr, value)
        Supported types: int, float, bytes (needs length), ptr
        """
        if key not in self._addresses:
            return None, None
        entry = self._addresses[key]
        typ = entry.get("type", "int")
        length = entry.get("length")
        addr = self.resolve_address(key)
        if not addr:
            return None, None
        if typ == "int":
            return addr, self.read_int(addr)
        if typ == "u32":
            return addr, self.read_u32(addr)
        if typ == "float":
            return addr, self.read_float(addr)
        if typ == "ptr":
            return addr, self.read_longlong(addr)
        if typ == "bytes":
            if not length:
                return addr, None
            return addr, self.read_bytes(addr, int(length))
        # fallback: raw bytes 4
        return addr, self.read_bytes(addr, 4)

    # ---- memory check utility ----
    def memory_check(self) -> Dict[str, Dict[str, Any]]:
        """
        Attempt to read each declared address and report success/failure + sample value.
        Returns dict keyed by address key with {'ok':bool, 'addr':hex or None, 'value':...}
        """
        results = {}
        for k in self._addresses.keys():
            addr = None
            value = None
            try:
                addr = self.resolve_address(k)
                if addr:
                    _, value = self.read_value(k)
                    results[k] = {"ok": True, "addr": hex(addr), "value": value}
                else:
                    results[k] = {"ok": False, "addr": None, "value": None}
            except Exception as e:
                results[k] = {"ok": False, "addr": hex(addr) if addr else None, "value": None, "error": str(e)}
        return results
