# tp_cli.py
import json
import os
import struct
import time
import sys
import ctypes
import ctypes.wintypes
import pymem
import pymem.process
import psutil

# WinAPI helpers for remote allocation / R/W (used when invoking TP)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
VirtualAllocEx = kernel32.VirtualAllocEx
VirtualAllocEx.argtypes = [ctypes.wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, ctypes.wintypes.DWORD, ctypes.wintypes.DWORD]
VirtualAllocEx.restype = ctypes.c_void_p
VirtualFreeEx = kernel32.VirtualFreeEx
VirtualFreeEx.argtypes = [ctypes.wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, ctypes.wintypes.DWORD]
VirtualFreeEx.restype = ctypes.wintypes.BOOL
ReadProcessMemory = kernel32.ReadProcessMemory
ReadProcessMemory.argtypes = [ctypes.wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
ReadProcessMemory.restype = ctypes.wintypes.BOOL
WriteProcessMemory = kernel32.WriteProcessMemory
WriteProcessMemory.argtypes = [ctypes.wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
WriteProcessMemory.restype = ctypes.wintypes.BOOL

MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
PAGE_READWRITE = 0x04
MEM_RELEASE = 0x8000

LOCATIONS_FILE = "locations.json"   # where named locations are saved

# -----------------------
# Basic process / module helpers
# -----------------------
def get_pid_by_name(name: str) -> int:
    for proc in psutil.process_iter(attrs=["pid", "name"]):
        if proc.info["name"] and proc.info["name"].lower() == name.lower():
            return proc.info["pid"]
    raise ProcessLookupError(f"Process '{name}' not found")

def get_module_base(pm: pymem.Pymem, module_name: str) -> int:
    mod = pymem.process.module_from_name(pm.process_handle, module_name)
    return mod.lpBaseOfDll

# -----------------------
# low-level read/write wrappers (uses pymem when convenient)
# -----------------------
def read_u64(pm: pymem.Pymem, addr: int) -> int:
    return struct.unpack("<Q", pm.read_bytes(addr, 8))[0]

def read_f32(pm: pymem.Pymem, addr: int) -> float:
    return struct.unpack("<f", pm.read_bytes(addr, 4))[0]

def write_f32_pm(pm: pymem.Pymem, addr: int, value: float) -> None:
    pm.write_bytes(addr, struct.pack("<f", float(value)), 4)

def write_int32_pm(pm: pymem.Pymem, addr: int, value: int) -> None:
    pm.write_bytes(addr, struct.pack("<i", int(value)), 4)

# -----------------------
# pointer resolver (single offset = no-deref; multiple offsets = deref chain)
# -----------------------
def resolve_address(pm: pymem.Pymem, module_base: int, offsets_list):
    offs = []
    for o in offsets_list:
        if isinstance(o, str) and o.lower().startswith("0x"):
            offs.append(int(o, 16))
        else:
            offs.append(int(o))
    addr = module_base + offs[0]
    for o in offs[1:]:
        ptr = read_u64(pm, addr)
        addr = ptr + o
    return addr

# -----------------------
# remote memory helpers (via WinAPI)
# -----------------------
def alloc_remote(handle, size=32) -> int:
    addr = VirtualAllocEx(handle, None, size, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
    if not addr:
        raise OSError("VirtualAllocEx failed")
    return int(addr)

def free_remote(handle, addr: int) -> None:
    if not VirtualFreeEx(handle, ctypes.c_void_p(addr), 0, MEM_RELEASE):
        raise OSError("VirtualFreeEx failed")

def write_remote(handle, addr: int, data: bytes) -> None:
    written = ctypes.c_size_t(0)
    ok = WriteProcessMemory(handle, ctypes.c_void_p(addr), data, len(data), ctypes.byref(written))
    if not ok or written.value != len(data):
        raise OSError(f"WriteProcessMemory failed/wrote {written.value} bytes")

def read_remote(handle, addr: int, size: int) -> bytes:
    buf = (ctypes.c_ubyte * size)()
    read = ctypes.c_size_t(0)
    ok = ReadProcessMemory(handle, ctypes.c_void_p(addr), ctypes.byref(buf), size, ctypes.byref(read))
    if not ok or read.value != size:
        raise OSError(f"ReadProcessMemory failed/read {read.value} bytes at 0x{addr:X}")
    return bytes(buf)

# -----------------------
# class that encapsulates teleport logic + saving/loading named locations
# -----------------------
class TeleportManager:
    def __init__(self, config_path="config.json"):
        if not os.path.exists(config_path):
            raise FileNotFoundError("create config.json first (see earlier messages)")
        with open(config_path, "r") as f:
            self.cfg = json.load(f)

        self.proc_name = self.cfg.get("process", "eldenring.exe")
        pid = get_pid_by_name(self.proc_name)
        print(f"[+] Found {self.proc_name} (PID {pid})")

        self.pm = pymem.Pymem()
        self.pm.open_process_from_id(pid)
        # also keep raw handle for WinAPI calls
        self.proc_handle = ctypes.wintypes.HANDLE(self.pm.process_handle)

        # resolve module bases
        self.module_bases = {}
        for mname, val in self.cfg.get("modules", {}).items():
            if val is None:
                mb = get_module_base(self.pm, mname)
                self.module_bases[mname] = mb
            else:
                self.module_bases[mname] = int(val, 16) if isinstance(val, str) else int(val)
            print(f"[+] Module {mname} base = 0x{self.module_bases[mname]:X}")

    # read the three global floats (same ones CE 'copypaste current coords' copies)
    def read_current_global_coords(self):
        xg_addr = self.resolve_symbol("xGlobalPtr")
        zg_addr = self.resolve_symbol("zGlobalPtr")
        yg_addr = self.resolve_symbol("yGlobalPtr")
        x = read_f32(self.pm, xg_addr)
        z = read_f32(self.pm, zg_addr)
        y = read_f32(self.pm, yg_addr)
        return x, z, y

    # prepare the 32-byte TPData buffer bytes exactly like CE: {float x, float z, float y, uint32 bonfire, padding...}
    def make_tpdata_bytes_from_coords(self, x, z, y, bonfire_default=0x3E213247):
        buf = struct.pack("<fffI", float(x), float(z), float(y), int(bonfire_default))
        if len(buf) < 32:
            buf += b"\x00" * (32 - len(buf))
        return buf

    def resolve_symbol(self, symbol_name: str) -> int:
        sym = self.cfg["symbols"][symbol_name]
        mod = sym["module"]
        offsets = sym["offsets"]
        base = self.module_bases[mod]
        return resolve_address(self.pm, base, offsets)

    # Save current coords to locations file
    def save_location(self, name: str):
        x, z, y = self.read_current_global_coords()
        tp_bytes = self.make_tpdata_bytes_from_coords(x, z, y)
        entry = {
            "x": x,
            "z": z,
            "y": y,
            "tpdata_hex": tp_bytes.hex()
        }
        locs = {}
        if os.path.exists(LOCATIONS_FILE):
            with open(LOCATIONS_FILE, "r") as f:
                locs = json.load(f)
        locs[name] = entry
        with open(LOCATIONS_FILE, "w") as f:
            json.dump(locs, f, indent=2)
        print(f"[+] Saved location '{name}': x={x} z={z} y={y}")

    def list_locations(self):
        if not os.path.exists(LOCATIONS_FILE):
            print("[*] No saved locations")
            return
        with open(LOCATIONS_FILE, "r") as f:
            locs = json.load(f)
        for k, v in locs.items():
            print(f"- {k}: x={v['x']} z={v['z']} y={v['y']}")

    def delete_location(self, name: str):
        if not os.path.exists(LOCATIONS_FILE):
            print("[!] No saved locations file")
            return
        with open(LOCATIONS_FILE, "r") as f:
            locs = json.load(f)
        if name not in locs:
            print("[!] name not found")
            return
        del locs[name]
        with open(LOCATIONS_FILE, "w") as f:
            json.dump(locs, f, indent=2)
        print(f"[+] Deleted location '{name}'")

    # The CE-like invocation flow: allocate TPData, write the saved bytes into TPData, then invoke the teleport
    def teleport_to_named(self, name: str):
        if not os.path.exists(LOCATIONS_FILE):
            raise SystemExit("No locations saved")
        with open(LOCATIONS_FILE, "r") as f:
            locs = json.load(f)
        if name not in locs:
            raise KeyError(f"Location '{name}' not found")
        entry = locs[name]
        tpdata_bytes = bytes.fromhex(entry["tpdata_hex"])

        # Resolve the pointer addresses we'll manipulate (player ptrs and globals + gravity)
        xPtrAddr = self.resolve_symbol("xPtrTp")
        zPtrAddr = self.resolve_symbol("zPtrTp")
        yPtrAddr = self.resolve_symbol("yPtrTp")
        xGlobAddr = self.resolve_symbol("xGlobalPtr")
        zGlobAddr = self.resolve_symbol("zGlobalPtr")
        yGlobAddr = self.resolve_symbol("yGlobalPtr")
        gravity_addr = self.resolve_symbol("gravityPtr")

        # Allocate remote TPData and write the bytes into it (CE style)
        remote_addr = alloc_remote(self.proc_handle, 32)
        try:
            write_remote(self.proc_handle, remote_addr, tpdata_bytes)

            # Read floats from remote TPData (mirror CE's InvokeTP reading TPData)
            b = read_remote(self.proc_handle, remote_addr, 16)
            x, z, y, bon = struct.unpack("<fffI", b[:16])

            # read current values from game pointers
            xPtrVal = read_f32(self.pm, xPtrAddr)
            zPtrVal = read_f32(self.pm, zPtrAddr)
            yPtrVal = read_f32(self.pm, yPtrAddr)
            xGlobVal = read_f32(self.pm, xGlobAddr)
            zGlobVal = read_f32(self.pm, zGlobAddr)
            yGlobVal = read_f32(self.pm, yGlobAddr)

            # disable gravity, write new floats, restore gravity
            write_int32_pm(self.pm, gravity_addr, 1)
            xNew = x - (xGlobVal - xPtrVal)
            zNew = z - (zGlobVal - zPtrVal)
            yNew = (y - (yGlobVal + yPtrVal)) * -1
            write_f32_pm(self.pm, xPtrAddr, xNew)
            write_f32_pm(self.pm, zPtrAddr, zNew)
            write_f32_pm(self.pm, yPtrAddr, yNew)
            time.sleep(5)
            write_int32_pm(self.pm, gravity_addr, 0)

            print(f"[+] Teleported to '{name}' (xNew={xNew} zNew={zNew} yNew={yNew})")
        finally:
            free_remote(self.proc_handle, remote_addr)

# -----------------------
# CLI
# -----------------------
def print_usage():
    print("Usage:")
    print("  python tp_cli.py save <name>       # save current location as <name>")
    print("  python tp_cli.py list              # list saved locations")
    print("  python tp_cli.py teleport <name>   # teleport to a saved location")
    print("  python tp_cli.py delete <name>     # delete a saved location")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)
    cmd = sys.argv[1].lower()
    tm = TeleportManager("config.json")
    if cmd == "save":
        if len(sys.argv) < 3:
            print("Provide name.")
            sys.exit(1)
        tm.save_location(sys.argv[2])
    elif cmd == "list":
        tm.list_locations()
    elif cmd == "delete":
        if len(sys.argv) < 3:
            print("Provide name.")
            sys.exit(1)
        tm.delete_location(sys.argv[2])
    elif cmd == "teleport":
        if len(sys.argv) < 3:
            print("Provide name.")
            sys.exit(1)
        tm.teleport_to_named(sys.argv[2])
    else:
        print_usage()
