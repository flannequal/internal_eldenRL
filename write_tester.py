# WriteTester.py
# --- Includes the same MemoryManager and resolver functions as the logger ---
# ... (paste the MemoryManager and the get_stable_struct_addr/get_local_struct_addr functions here) ...

import pymem
import pymem.process
import time

class MemoryManager:
    """Verified working Memory Manager."""
    def __init__(self, process_name="eldenring.exe"): self.pm,self.base_address=None,None; self.connect(process_name)
    def connect(self, process_name):
        try: self.pm=pymem.Pymem(process_name); self.base_address=pymem.process.module_from_name(self.pm.process_handle,process_name).lpBaseOfDll; print(f"Connected to {process_name} @ 0x{self.base_address:X}")
        except pymem.exception.PymemError as e: print(f"Error connecting: {e}")
    def is_connected(self): return self.pm is not None
    def read_pointer(self, address): return self.pm.read_longlong(address) if address and address != 0 else 0
    def read_float(self, address): return self.pm.read_float(address) if address and address != 0 else 0.0
    def write_float(self, address, value): self.pm.write_float(address, float(value)); return True if address and address != 0 else False
    def read_int(self, address): return self.pm.read_int(address) if address and address != 0 else 0
    def write_int(self, address, value): self.pm.write_int(address, int(value)); return True if address and address != 0 else False
    

    def get_stable_struct_addr(self):
        p1 = self.mm.read_pointer(self.mm.base_address + self.WORLDCHRMAN_STATIC)
        if not p1: return 0
        p2 = self.mm.read_pointer(p1 + 0x10EF8)
        if not p2: return 0
        return self.mm.read_pointer(p2 + 0x0)

    def get_local_struct_addr(self):
        p1 = self.mm.read_pointer(self.mm.base_address + self.WORLDCHRMAN_STATIC)
        if not p1: return 0
        p2 = self.mm.read_pointer(p1 + 0x10EF8)
        if not p2: return 0
        p3 = self.mm.read_pointer(p2 + 0x0)
        if not p3: return 0
        p4 = self.mm.read_pointer(p3 + 0x190)
        if not p4: return 0
        return self.mm.read_pointer(p4 + 0x68)
    
        
class WriteTester:
    def __init__(self, mem_manager):
        self.mm = mem_manager

    def test_write_to_local(self, offset=5.0):
        """Adds an offset to the current LOCAL X coordinate."""
        print(f"\n--- Testing write to LOCAL coordinates (+{offset} to X) ---")
        local_addr = get_local_struct_addr() # Assume get_local_struct_addr is defined globally
        if not local_addr:
            print("Could not find local coords struct.")
            return

        current_x = self.mm.read_float(local_addr + 0x70)
        new_x = current_x + offset
        print(f"Current Local X: {current_x:.2f}. Writing new X: {new_x:.2f}")
        self.mm.write_float(local_addr + 0x70, new_x)
        print("Write complete. Check if the player moved.")

    def test_write_to_stable(self, offset=5.0):
        """Adds an offset to the current STABLE X coordinate."""
        print(f"\n--- Testing write to STABLE coordinates (+{offset} to X) ---")
        stable_addr = get_stable_struct_addr() # Assume get_stable_struct_addr is defined globally
        if not stable_addr:
            print("Could not find stable coords struct.")
            return
            
        current_x = self.mm.read_float(stable_addr + 0x6C4)
        new_x = current_x + offset
        print(f"Current Stable X: {current_x:.2f}. Writing new X: {new_x:.2f}")
        self.mm.write_float(stable_addr + 0x6C4, new_x)
        print("Write complete. Check if the player moved.")

if __name__ == "__main__":
    mm = MemoryManager()
    if mm.is_connected():
        # Make the resolver functions accessible for the tester class
        def get_stable_struct_addr():
            p1 = mm.read_pointer(mm.base_address + 0x3D65F88)
            if not p1: return 0
            p2 = mm.read_pointer(p1 + 0x10EF8)
            if not p2: return 0
            return mm.read_pointer(p2 + 0x0)
            
        def get_local_struct_addr():
            p1 = mm.read_pointer(mm.base_address + 0x3D65F88)
            if not p1: return 0
            p2 = mm.read_pointer(p1 + 0x10EF8)
            if not p2: return 0
            p3 = mm.read_pointer(p2 + 0x0)
            if not p3: return 0
            p4 = mm.read_pointer(p3 + 0x190)
            if not p4: return 0
            return mm.read_pointer(p4 + 0x68)
            
        tester = WriteTester(mm)
        
        print("Starting write tests in 5 seconds...")
        time.sleep(5)
        
        # Test 1: Write to Local
        tester.test_write_to_local()
        
        print("\nPrepare for the next test. Rest at a grace to reset your position.")
        print("Waiting 10 seconds...")
        time.sleep(10)
        
        # Test 2: Write to Stable
        tester.test_write_to_stable()