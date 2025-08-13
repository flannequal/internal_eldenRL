# read_offsets_and_read_values.py
import json
import pymem
import struct
import time

def load_offsets(path):
    with open(path, 'r') as f:
        return json.load(f)

def get_module_base(pm, module_name="eldenring.exe"):
    mod = pymem.process.module_from_name(pm.process_handle, module_name)
    return mod.lpBaseOfDll, mod.SizeOfImage

def read_u64(pm, addr):
    return pm.read_ulonglong(addr)

def read_int(pm, addr):
    return pm.read_int(addr)

def read_float(pm, addr):
    return pm.read_float(addr)

if __name__ == "__main__":
    offsets = load_offsets("C:\\elden_offsets.json")  # match CE output path

    pm = pymem.Pymem("eldenring.exe")
    base, size = get_module_base(pm, "eldenring.exe")
    print("Module base:", hex(base))

    # Example: read GameDataMan pointer, then follow +0x8 then +0x3C to get Vigor
    game_data_offset = int(offsets["GameDataMan"], 16)
    gdm_addr = base + game_data_offset
    print("GameDataMan absolute:", hex(gdm_addr))

    # read pointer at GameDataMan (u64)
    ptr1 = read_u64(pm, gdm_addr + 0x0)   # sometimes the symbol itself is the pointer; adjust if needed
    # if the cheat table used [instr + disp] directly to point to data, you might not need first deref
    print("ptr1:", hex(ptr1))

    # follow the pointer chain you obtained in CE:
    ptr2 = read_u64(pm, ptr1 + 0x8)       # example chain: +0x8
    vigor_addr = ptr2 + 0x3C             # final offset to vigor
    vigor = read_int(pm, vigor_addr)
    print("Vigor (raw):", vigor)
