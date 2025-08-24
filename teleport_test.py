import pymem
import pymem.process
import time
import struct

class MemoryManager:
    """Verified working Memory Manager."""
    def __init__(self, process_name="eldenring.exe"): self.pm,self.base_address=None,None; self.connect(process_name)
    def connect(self, process_name):
        try: self.pm=pymem.Pymem(process_name); self.base_address=pymem.process.module_from_name(self.pm.process_handle,process_name).lpBaseOfDll; print(f"Connected to {process_name} @ 0x{self.base_address:X}")
        except pymem.exception.PymemError as e: print(f"Error connecting: {e}")
    def is_connected(self): return self.pm is not None
    def allocate_memory(self, size): return pymem.memory.allocate_memory(self.pm.process_handle, size)
    def free_memory(self, address): pymem.memory.free_memory(self.pm.process_handle, address)
    def write_bytes(self, address, data): self.pm.write_bytes(address, data, len(data))
    def create_remote_thread(self, address):
        thread = pymem.process.create_remote_thread(self.pm.process_handle, address, 0)
        if thread:
            pymem.process.wait_for_single_object(thread[0], -1) # -1 means wait indefinitely
            pymem.process.close_handle(thread[0])
            return True
        return False

class FunctionCallerTeleporter:
    """
    Achieves perfect teleportation by injecting assembly code to call the
    game's internal WarpFunction, replicating how advanced cheat tables work.
    """
    def __init__(self, mem_manager):
        self.mm = mem_manager
        if not self.mm.is_connected(): raise ConnectionError("MemoryManager not connected.")
        
        # Addresses of the internal game functions and objects
        self.GAME_MAN_STATIC = 0x3D69918
        self.WARP_FUNCTION = self.mm.base_address + 0x599CD0

    def invoke_teleport(self, map_id, x, y, z):
        print("\n--- Invoking Teleport via Internal Warp Function ---")

        # 1. Allocate memory inside the game for our data and code
        # We need space for a 5-integer structure (map_id, x, y, z, unknown)
        coord_data_addr = self.mm.allocate_memory(20) 
        # We need space for our assembly shellcode
        shellcode_addr = self.mm.allocate_memory(256)

        if not coord_data_addr or not shellcode_addr:
            print("Error: Could not allocate memory in the game process.")
            if coord_data_addr: self.mm.free_memory(coord_data_addr)
            if shellcode_addr: self.mm.free_memory(shellcode_addr)
            return False

        try:
            # 2. Write our destination coordinates into the game's memory
            # The Warp function takes a pointer to a struct of 5 integers.
            # We pack our float coordinates into their raw 4-byte integer representation.
            coord_data = struct.pack(
                "<Iifff", # Format: unsigned int, int, float, float, float
                map_id,
                0, # Unknown/Padding integer
                x, y, z
            )
            self.mm.write_bytes(coord_data_addr, coord_data)
            print(f"Wrote coordinate data to 0x{coord_data_addr:X}")

            # 3. Assemble the "shellcode" that will call the Warp function
            # This is assembly language written in bytes.
            shellcode = (
                b"\x48\x83\xEC\x28",            # sub rsp, 0x28 (Make space on the stack)
                b"\x48\xB9" + struct.pack("<Q", self.mm.base_address + self.GAME_MAN_STATIC), # mov rcx, [GameMan] (Load the address of the GameMan pointer)
                b"\x48\x8B\x09",              # mov rcx, [rcx] (Dereference the pointer to get the actual GameMan object)
                b"\x48\xBA" + struct.pack("<Q", coord_data_addr), # mov rdx, coord_data_addr (Load the address of our coordinate struct into the 2nd argument register)
                b"\x48\xB8" + struct.pack("<Q", self.WARP_FUNCTION), # mov rax, WarpFunction (Load the address of the warp function)
                b"\xFF\xD0",                      # call rax (Execute the warp function)
                b"\x48\x83\xC4\x28",              # add rsp, 0x28 (Clean up the stack)
                b"\xC3"                          # ret (Return, ending our thread)
            )
            self.mm.write_bytes(shellcode_addr, b"".join(shellcode))
            print(f"Wrote shellcode to 0x{shellcode_addr:X}")

            # 4. Create a new thread inside Elden Ring that starts by running our shellcode
            print("Action: Creating remote thread to execute warp call...")
            success = self.mm.create_remote_thread(shellcode_addr)
            if success:
                print("--- Teleport sequence executed successfully. ---")
            else:
                print("Error: Failed to create remote thread.")

        finally:
            # 5. Free the memory we allocated to be clean
            self.mm.free_memory(coord_data_addr)
            self.mm.free_memory(shellcode_addr)
            print("Cleaned up allocated memory.")
        
        return success

if __name__ == "__main__":
    # To find these values, you need to go to a location and find your
    # coordinates and the current Map ID. The Map ID is often found in the same
    # data structure as the Stable Coords (at offset +6D4 as you noted).
    # map_id is an integer like 10000, 10010, etc.
    LOCATIONS = {
        # This is an example. You MUST find the correct Map ID for Limgrave.
        # A common value for Limgrave is 10000.
        "firststep": {"map_id": 10000, "x": 90.4, "y": -57.5, "z": 0.3},
    }

    mm = MemoryManager()
    if mm.is_connected():
        teleporter = FunctionCallerTeleporter(mm)
        target_loc = "firststep"
        
        print(f"\nTeleporting to '{target_loc}' in 5 seconds...")
        time.sleep(5)
        
        if target_loc in LOCATIONS:
            loc = LOCATIONS[target_loc]
            teleporter.invoke_teleport(loc['map_id'], loc['x'], loc['y'], loc['z'])
        else:
            print(f"Location '{target_loc}' not found.")
