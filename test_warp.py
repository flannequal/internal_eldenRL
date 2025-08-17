import pymem
import struct
import ctypes
from pymem.ressources import kernel32 as k32
from pymem.ressources.structure import MEMORY_PROTECTION

# --- CONFIGURATION ---
PROCESS_NAME = "eldenring.exe"
WARP_FUNCTION_RVA = 0x599CD0
CS_LUA_EVENT_MANAGER_RVA = 0x3D67E48
TARGET_BONFIRE_ID = 31032950

# helper to get numeric protection constant safely
import pymem
import struct
import ctypes
from pymem.ressources import kernel32 as k32
from pymem.ressources.structure import MEMORY_PROTECTION

def get_remote_proc_addr(pm, module_name: str, local_func_ptr) -> int:
    """
    Compute remote process function address:
      remote_base + (local_func - local_base)
    Assumes the exported function has the same RVA in remote module (true for same module version).
    """
    # local module base for the function
    # use ctypes to get local module handle and function pointer
    # local_func_ptr should be an actual callable from ctypes (e.g., ctypes.windll.user32.MessageBoxA)
    #- get local module handle via ctypes:
    # find the module that contains the function by iterating loaded modules until func_ptr inside range
    import sys, ctypes.util

    func_addr = ctypes.cast(local_func_ptr, ctypes.c_void_p).value
    # try to obtain local module base by checking GetModuleHandleA for module_name
    local_module_handle = ctypes.windll.kernel32.GetModuleHandleA(module_name.encode('ascii'))
    if not local_module_handle:
        raise RuntimeError(f"Couldn't get local module handle for {module_name!r}")
    local_base = int(local_module_handle)
    # compute RVA
    rva = func_addr - local_base

    # get remote module
    remote_mod = pymem.process.module_from_name(pm.process_handle, module_name)
    if not remote_mod:
        raise RuntimeError(f"Remote module {module_name} not found")
    remote_addr = remote_mod.lpBaseOfDll + rva
    return remote_addr

def _prot_val(prot_enum):
    return getattr(prot_enum, "value", prot_enum)

def execute_safely(pm, shellcode: bytes, test_mode: bool=True) -> bool:
    """
    DEP-aware injector:
      - allocates memory
      - writes shellcode
      - sets RWX while writing/executing
      - appends a remote-call to ExitThread so the thread exits cleanly
      - creates remote thread, waits, restores protections, frees memory
    If test_mode==True, we will call MessageBoxA in the target process instead of your warp.
    """
    shellcode_addr = None
    thread_handle = None
    old_protect = ctypes.c_ulong(0)

    try:
        # Allocate
        size = len(shellcode) + 128  # extra space for appended ExitThread-call / small stub
        shellcode_addr = pm.allocate(size)
        if not shellcode_addr:
            print("-> ERROR: allocate failed")
            return False
        print(f"-> Allocated {size} bytes at {hex(shellcode_addr)}")

        # If test_mode: build a simple shellcode that calls MessageBoxA then ExitThread.
        if test_mode:
            # resolve remote address of user32.MessageBoxA and remote ExitThread
            # get local function pointers using ctypes
            local_msgbox = ctypes.windll.user32.MessageBoxA
            remote_msgbox = get_remote_proc_addr(pm, "user32.dll", local_msgbox)
            local_exit = ctypes.windll.kernel32.ExitThread
            remote_exit = get_remote_proc_addr(pm, "kernel32.dll", local_exit)

            print(f"-> remote MessageBoxA: {hex(remote_msgbox)}")
            print(f"-> remote ExitThread: {hex(remote_exit)}")

            # build a tiny shellcode:
            # align stack, allocate shadow space, push args and call MessageBoxA
            # RCX = hWnd (NULL)
            # RDX = lpText (we'll write text after the stub)
            # R8  = lpCaption (we'll write caption after the stub)
            # R9  = uType (0)
            # then call MessageBoxA (call RAX)
            text = b"TEST from injected thread\x00"
            caption = b"Injection Test\x00"

            # place text immediately after code
            code = bytearray()
            # align stack: and rsp, -16 ; sub rsp, 0x28
            code += bytes([0x48,0x83,0xE4,0xF0, 0x48,0x83,0xEC,0x28])
            # mov rdx, addr_text
            text_addr = shellcode_addr + len(code) + 8 + 8 + 8  # approximate, we will compute properly below
            # We'll compute precise offsets after we know lengths. For simplicity we will compute dynamically below.

            # Instead: construct code with placeholders and patch addresses.
            # mov rdx, imm64  (text)
            code += bytes([0x48, 0xBA]) + struct.pack("<Q", 0)  # placeholder for text ptr (rdx)
            # mov r8, imm64 (caption)
            code += bytes([0x49, 0xB8]) + struct.pack("<Q", 0)  # placeholder for caption (r8)
            # xor rcx, rcx (hWnd = NULL)
            code += bytes([0x48, 0x31, 0xC9])
            # mov r9d, 0
            code += bytes([0x41, 0xB9]) + struct.pack("<I", 0)
            # mov rax, remote_msgbox
            code += bytes([0x48, 0xB8]) + struct.pack("<Q", remote_msgbox)
            # call rax
            code += bytes([0xFF, 0xD0])
            # mov rax, remote_exit; xor rcx, rcx; call rax
            code += bytes([0x48, 0xB8]) + struct.pack("<Q", remote_exit)
            code += bytes([0x48, 0x31, 0xC9])
            code += bytes([0xFF, 0xD0])
            # add text and caption after code
            code += text + caption

            # patch the placeholders for text and caption addresses
            # text pointer offset = location of first placeholder + 2 (opcode size)
            # find offsets:
            # placeholder for text is at index where we put 0 for rdx (first occurrence)
            ph_text_index = code.find(b'\x48\xBA')  # start of mov rdx
            ph_text_addr_offset = ph_text_index + 2
            ph_caption_index = code.find(b'\x49\xB8')  # start of mov r8
            ph_caption_addr_offset = ph_caption_index + 2

            text_real_addr = shellcode_addr + len(code) - (len(text) + len(caption))
            caption_real_addr = text_real_addr + len(text)

            code[ph_text_addr_offset:ph_text_addr_offset+8] = struct.pack("<Q", text_real_addr)
            code[ph_caption_addr_offset:ph_caption_addr_offset+8] = struct.pack("<Q", caption_real_addr)

            final_code = bytes(code)

            pm.write_bytes(shellcode_addr, final_code, len(final_code))
            print("-> Wrote test MessageBox shellcode.")
            actual_code_len = len(final_code)
        else:
            # Normal mode: write provided shellcode (we will append ExitThread call below)
            pm.write_bytes(shellcode_addr, shellcode, len(shellcode))
            actual_code_len = len(shellcode)

        # compute remote ExitThread address so we can append a call to it (if not test_mode)
        local_exit = ctypes.windll.kernel32.ExitThread
        try:
            remote_exit = get_remote_proc_addr(pm, "kernel32.dll", local_exit)
        except Exception as e:
            print(f"-> WARNING: couldn't compute remote ExitThread addr: {e}")
            remote_exit = None

        if (not test_mode) and remote_exit:
            # append call-to-ExitThread to the area immediately after your shellcode
            tail = bytearray()
            # mov rax, remote_exit
            tail += bytes([0x48, 0xB8]) + struct.pack("<Q", remote_exit)
            # xor rcx, rcx
            tail += bytes([0x48, 0x31, 0xC9])
            # call rax
            tail += bytes([0xFF, 0xD0])
            # write tail to remote process
            pm.write_bytes(shellcode_addr + actual_code_len, bytes(tail), len(tail))
            print(f"-> Appended ExitThread-call at {hex(shellcode_addr + actual_code_len)}")
            total_used = actual_code_len + len(tail)
        else:
            total_used = actual_code_len

        # --- change protection to RX or RWX temporarily (RWX safer for write+exec)
        new_prot = _prot_val(MEMORY_PROTECTION.PAGE_EXECUTE_READWRITE)
        addr = ctypes.c_void_p(shellcode_addr)
        size_ct = ctypes.c_size_t(total_used)
        ok = k32.VirtualProtectEx(pm.process_handle, addr, size_ct, ctypes.c_ulong(new_prot), ctypes.byref(old_protect))
        if not ok:
            print(f"-> ERROR: VirtualProtectEx failed to set RX/RWX. GetLastError={ctypes.windll.kernel32.GetLastError():#x}")
            # still attempt to free and exit
            return False
        print(f"-> Set page exec RWX (old={hex(old_protect.value)})")

        # Create thread: start address = shellcode_addr
        thread_id = ctypes.c_ulong(0)
        thread_handle = k32.CreateRemoteThread(
            pm.process_handle,
            None,
            0,
            ctypes.c_void_p(shellcode_addr),
            None,
            0,
            ctypes.byref(thread_id)
        )
        if not thread_handle:
            err = ctypes.windll.kernel32.GetLastError()
            print(f"-> ERROR: CreateRemoteThread failed (err={err:#x})")
            # try to restore protection and free memory below
            return False

        print(f"-> Thread created TID={thread_id.value}. Waiting...")
        wait = k32.WaitForSingleObject(thread_handle, 0xFFFFFFFF)
        if wait == 0xFFFFFFFF:
            print(f"-> WARNING: WaitForSingleObject failed (GetLastError={ctypes.windll.kernel32.GetLastError():#x})")
        else:
            print("-> Thread finished / signalled.")

        # Close handle
        k32.CloseHandle(thread_handle)
        thread_handle = None

        # restore original protection (best-effort)
        if old_protect.value != 0:
            k32.VirtualProtectEx(pm.process_handle, addr, size_ct, ctypes.c_ulong(old_protect.value), ctypes.byref(ctypes.c_ulong(0)))
            print("-> Restored original protection (best-effort).")

        return True

    except Exception as e:
        print(f"-> EXCEPTION: {e}")
        return False

    finally:
        # cleanup
        try:
            if thread_handle:
                k32.CloseHandle(thread_handle)
        except Exception:
            pass
        try:
            if shellcode_addr:
                pm.free(shellcode_addr)
                print("-> Freed allocated memory.")
        except Exception:
            pass



def main():
    import pymem, binascii
    
    print("--- The Definitive DEP-Aware Warp Test ---")
    try:
        pm = pymem.Pymem(PROCESS_NAME)
        module = pymem.process.module_from_name(pm.process_handle, PROCESS_NAME)
    except Exception as e:
        print(f"ERROR: Could not attach to game: {e}")
        return

    final_warp_addr = module.lpBaseOfDll + WARP_FUNCTION_RVA
    cs_lua_manager_static_ptr_addr = module.lpBaseOfDll + CS_LUA_EVENT_MANAGER_RVA
    cs_lua_manager_runtime_addr = pm.read_longlong(cs_lua_manager_static_ptr_addr)
    script_imitation_ptr = pm.read_longlong(cs_lua_manager_runtime_addr + 0x18)
    proxy_ptr = pm.read_longlong(cs_lua_manager_runtime_addr + 0x08)



    if not all([final_warp_addr, cs_lua_manager_runtime_addr, script_imitation_ptr, proxy_ptr]):
        print("ERROR: Failed to resolve one of the required pointers.")
        return

    print("final_warp_addr:", hex(final_warp_addr))
    print(pm.read_bytes(final_warp_addr, 64).hex())

    print("cs_lua_manager_runtime_addr:", hex(cs_lua_manager_runtime_addr))
    print(pm.read_bytes(cs_lua_manager_runtime_addr, 128).hex())

    print("script_imitation_ptr:", hex(script_imitation_ptr))
    print(pm.read_bytes(script_imitation_ptr, 128).hex())

    print("proxy_ptr:", hex(proxy_ptr))
    print(pm.read_bytes(proxy_ptr, 128).hex())

    # Put this in your main() after resolving addresses
    import pymem, binascii
    def peek_qword(addr):
        try:
            return pm.read_longlong(addr)
        except Exception as e:
            return f"read error: {e}"

    def dump_ptr(pm, name, addr):
        print(f"{name}: {hex(addr)}")
        try:
            b = pm.read_bytes(addr, 8)
            print(f"  first 8 bytes: {binascii.hexlify(b)}")
        except Exception as e:
            print(f"  read failed: {e}")

    print("peek(final_warp_addr):", peek_qword(final_warp_addr))
    print("peek(cs_lua_manager_runtime_addr):", hex(pm.read_longlong(cs_lua_manager_runtime_addr)))
    print("peek(script_imitation_ptr):", hex(pm.read_longlong(script_imitation_ptr)))
    print("peek(proxy_ptr):", hex(pm.read_longlong(proxy_ptr)))

    def addr_in_module(pm, addr):
        """
        Returns the module name that contains the given address,
        or None if no module in the process contains it.
        """
        modules = pm.list_modules()
        for m in modules:
            base = m.lpBaseOfDll
            size = m.SizeOfImage
            name = getattr(m, "name", getattr(m, "szModule", None))
            if base <= addr < base + size:
                return name
        return None

    print("=== pointer sanity checks ===")
    for name, a in [
        ("final_warp_addr", final_warp_addr),
        ("cs_lua_manager_runtime_addr", cs_lua_manager_runtime_addr),
        ("script_imitation_ptr", script_imitation_ptr),
        ("proxy_ptr", proxy_ptr)
    ]:
        print(f"{name}: {hex(a)}")
        try:
            b = pm.read_bytes(a, 8)
            print(f"  first 8 bytes: {b.hex()}")
        except Exception as e:
            print(f"  read failed: {e}")

        mod = addr_in_module(pm, a)
        print(f"  -> located in module: {mod}")


    warp_id_arg = TARGET_BONFIRE_ID - 1000

    shellcode = (
        bytes([0x48, 0x83, 0xE4, 0xF0])
        + bytes([0x48, 0x83, 0xEC, 0x48])
        + bytes([0x4D, 0x31, 0xC9])
        + bytes([0x48, 0xB9]) + struct.pack("<Q", script_imitation_ptr)
        + bytes([0x48, 0xBA]) + struct.pack("<Q", proxy_ptr)
        + bytes([0x41, 0xB8]) + struct.pack("<i", warp_id_arg)
        + bytes([0x48, 0xB8]) + struct.pack("<Q", final_warp_addr)
        + bytes([0xFF, 0xD0])
        + bytes([0x48, 0x83, 0xC4, 0x48])
        + bytes([0xC3])
    )

    print("\nExecuting shellcode with proper memory protection...")
    success = execute_safely(pm, shellcode)

    if success:
        print("\n--- TEST COMPLETE ---")
        print("The script finished without errors. This should be the successful warp.")
    else:
        print("\n--- TEST FAILED ---")


if __name__ == "__main__":
    main()
