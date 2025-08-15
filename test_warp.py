import pymem
import struct
import ctypes
from pymem.ressources import kernel32, structure
import time

# --- CONFIGURATION: The correct data YOU found ---
PROCESS_NAME = "eldenring.exe"
WARP_FUNCTION_RVA = 0x599CD0 # Your RVA from the CALL instruction
CS_LUA_EVENT_MANAGER_RVA = 0x3D67E48 # Your RVA from the CMP instruction
TARGET_BONFIRE_ID = 31032950

def execute_fire_and_forget_shellcode(pm, shellcode: bytes) -> bool:
    """The definitive, isolated shellcode execution logic for asynchronous calls."""
    shellcode_addr = None
    try:
        shellcode_addr = pm.allocate(len(shellcode))
        pm.write_bytes(shellcode_addr, shellcode, len(shellcode))
        
        thread_handle = kernel32.CreateRemoteThread(pm.process_handle, None, 0, shellcode_addr, None, 0, None)
        
        if not thread_handle:
            print(f"  -> ERROR: CreateRemoteThread failed! GetLastError={ctypes.windll.kernel32.GetLastError():#x}")
            # We must free the memory if the thread creation failed
            if shellcode_addr: pm.free(shellcode_addr)
            return False
        
        # We don't wait for the thread. We close the handle immediately and let it run wild.
        kernel32.CloseHandle(thread_handle)
        
        # We keep the memory allocated for a short time to ensure the thread can finish executing from it.
        time.sleep(1.0) # Keep memory alive for 1 second
        return True

    finally:
        # After a delay, we clean up the memory.
        if shellcode_addr:
            pm.free(shellcode_addr)
            print("  -> Freed shellcode memory after delay.")

def main():
    print("--- The Definitive 'Fire and Forget' Warp Test ---")
    try:
        pm = pymem.Pymem(PROCESS_NAME)
        module = pymem.process.module_from_name(pm.process_handle, PROCESS_NAME)
    except Exception as e:
        print(f"ERROR: Could not attach to game: {e}")
        return

    # --- Step 1: Get all necessary pointers (this logic is now proven correct) ---
    final_warp_addr = module.lpBaseOfDll + WARP_FUNCTION_RVA
    cs_lua_manager_static_ptr_addr = module.lpBaseOfDll + CS_LUA_EVENT_MANAGER_RVA
    cs_lua_manager_runtime_addr = pm.read_longlong(cs_lua_manager_static_ptr_addr)
    script_imitation_ptr = pm.read_longlong(cs_lua_manager_runtime_addr + 0x18)
    proxy_ptr = pm.read_longlong(cs_lua_manager_runtime_addr + 0x08)
    
    if not all([final_warp_addr, cs_lua_manager_runtime_addr, script_imitation_ptr, proxy_ptr]):
        print("ERROR: Failed to resolve one of the required pointers. The game might not be fully loaded.")
        return

    warp_id_arg = TARGET_BONFIRE_ID - 1000

    # --- THE MINIMALIST "FIRE AND FORGET" SHELLCODE ---
    # No stack cleanup. No RET. Just the bare essentials.
    print("\nBuilding 'fire and forget' shellcode...")
    shellcode = (
        bytes([0x48, 0x83, 0xE4, 0xF0])              # and rsp, 0xFFFFFFFFFFFFFFF0 (Align stack)
        + bytes([0x48, 0x83, 0xEC, 0x48])            # sub rsp, 48h (Shadow store)
        + bytes([0x4D, 0x31, 0xC9])                  # xor r9, r9
        + bytes([0x48, 0xB9])                        # mov rcx, ...
        + struct.pack("<Q", script_imitation_ptr)   # ... Arg 1
        + bytes([0x48, 0xBA])                        # mov rdx, ...
        + struct.pack("<Q", proxy_ptr)               # ... Arg 2
        + bytes([0x41, 0xB8])                        # mov r8d, ...
        + struct.pack("<i", warp_id_arg)             # ... Arg 3
        + bytes([0x48, 0xB8])                        # mov rax, ...
        + struct.pack("<Q", final_warp_addr)         # ... Function Address
        + bytes([0xFF, 0xD0])                        # call rax
        # INTENTIONALLY OMITTED: No 'add rsp' and no 'ret'.
        # The thread will finish here, and the game engine will handle it.
    )

    print("Executing shellcode and letting it run...")
    success = execute_fire_and_forget_shellcode(pm, shellcode)

    if success:
        print("\n--- TEST COMPLETE ---")
        print("The thread was launched successfully. Check if the game warped without crashing.")
    else:
        print("\n--- TEST FAILED ---")

if __name__ == "__main__":
    main()