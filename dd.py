import logging
import pymem
import pymem.process
from typing import List, Optional

# --- Configuration ---
PROCESS_NAME = "eldenring.exe"
LOGGING_FORMAT = '%(asctime)s - %(levelname)s - %(message)s'

# Pointer chains taken directly from the user-provided .CEA files.
# These are the ground truth we will test against.
CHAINS_TO_TEST = {
    "xPlayer": {
        "base": "WorldChrMan",
        "rva": 0x3D65F88,
        "offsets": [0x10EF8, 0x0, 0x190, 0x68, 0x70]
    },
    "xGlobal": {
        "base": "NetManImp",
        "rva": 0x3D5AE60,
        "offsets": [0x80, 0xE0, 0x80, 0x20, 0x98, 0x28]
    }
}

# --- Memory Reading Helpers ---

def read_longlong(pm: pymem.Pymem, address: int) -> Optional[int]:
    """Safely reads a 64-bit integer (pointer)."""
    try:
        data = pm.read_bytes(address, 8)
        return int.from_bytes(data, 'little')
    except Exception:
        return None

def read_float(pm: pymem.Pymem, address: int) -> Optional[float]:
    """Safely reads a 32-bit float."""
    try:
        data = pm.read_bytes(address, 4)
        import struct
        return struct.unpack('<f', data)[0]
    except Exception:
        return None

# --- Pointer Resolution Test Methods ---

def method_a(pm: pymem.Pymem, base_addr: int, offsets: List[int], chain_name: str) -> Optional[int]:
    """
    Method A: The logic from the original `tp_cli.py`.
    1. Start with `addr = module_base + rva`.
    2. Loop: `addr = read_longlong(addr) + next_offset`.
    """
    logging.info(f"--- Testing Method A for '{chain_name}' ---")
    addr = base_addr
    logging.info(f"Initial Address (Module Base + RVA): {hex(addr)}")
    
    try:
        for i, offset in enumerate(offsets):
            ptr_val = read_longlong(pm, addr)
            if ptr_val is None or ptr_val == 0:
                logging.error(f"  Step {i+1}: FAILED to read valid pointer from {hex(addr)}")
                return None
            logging.info(f"  Step {i+1}: Read {hex(ptr_val)} from {hex(addr)}")
            
            addr = ptr_val + offset
            logging.info(f"  Step {i+1}: Added offset {hex(offset)} -> New Address: {hex(addr)}")
        
        logging.info(f"Method A Final Address: {hex(addr)}")
        return addr
    except Exception as e:
        logging.error(f"Method A crashed: {e}")
        return None

def method_b(pm: pymem.Pymem, base_addr: int, offsets: List[int], chain_name: str) -> Optional[int]:
    """
    Method B: A common incorrect variation.
    1. Start with `addr = module_base + rva`.
    2. Loop: `addr = read_longlong(addr + next_offset)`.
    """
    logging.info(f"--- Testing Method B for '{chain_name}' ---")
    addr = base_addr
    logging.info(f"Initial Address (Module Base + RVA): {hex(addr)}")
    
    try:
        for i, offset in enumerate(offsets):
            read_addr = addr + offset
            ptr_val = read_longlong(pm, read_addr)
            if ptr_val is None or ptr_val == 0:
                logging.error(f"  Step {i+1}: FAILED to read valid pointer from {hex(read_addr)}")
                return None
            logging.info(f"  Step {i+1}: Read {hex(ptr_val)} from {hex(read_addr)} (addr + offset)")
            addr = ptr_val
        
        logging.info(f"Method B Final Address: {hex(addr)}")
        return addr
    except Exception as e:
        logging.error(f"Method B crashed: {e}")
        return None

def method_c(pm: pymem.Pymem, base_addr: int, offsets: List[int], chain_name: str) -> Optional[int]:
    """
    Method C: Another variation.
    1. Start with `addr = read_longlong(module_base + rva)`.
    2. Loop: `addr = read_longlong(addr) + next_offset`.
    """
    logging.info(f"--- Testing Method C for '{chain_name}' ---")
    try:
        addr = read_longlong(pm, base_addr)
        if addr is None or addr == 0:
            logging.error(f"  Step 0: FAILED to read initial pointer from {hex(base_addr)}")
            return None
        logging.info(f"Initial Pointer Value (from {hex(base_addr)}): {hex(addr)}")

        for i, offset in enumerate(offsets):
            addr += offset
            logging.info(f"  Step {i+1}: Added offset {hex(offset)} -> New Address: {hex(addr)}")
            
            # Don't read on the last step, as it's the final address
            if i < len(offsets) - 1:
                ptr_val = read_longlong(pm, addr)
                if ptr_val is None or ptr_val == 0:
                    logging.error(f"  Step {i+1}: FAILED to read valid pointer from {hex(addr)}")
                    return None
                logging.info(f"  Step {i+1}: Read {hex(ptr_val)} from {hex(addr)}")
                addr = ptr_val

        logging.info(f"Method C Final Address: {hex(addr)}")
        return addr
    except Exception as e:
        logging.error(f"Method C crashed: {e}")
        return None

# --- Main Execution ---

def run_diagnostic():
    """Main function to run all diagnostic tests."""
    logging.basicConfig(level=logging.INFO, format=LOGGING_FORMAT)
    
    try:
        pm = pymem.Pymem(PROCESS_NAME)
        module_base = pymem.process.module_from_name(pm.process_handle, PROCESS_NAME).lpBaseOfDll
        logging.info(f"Attached to {PROCESS_NAME}. Module base: {hex(module_base)}")
    except pymem.exception.ProcessNotFound:
        logging.error(f"'{PROCESS_NAME}' not found. Please ensure the game is running.")
        return

    for name, data in CHAINS_TO_TEST.items():
        print("\n" + "="*50)
        logging.info(f"STARTING TESTS FOR POINTER CHAIN: '{name}'")
        print("="*50)
        
        # The initial address is always the module base plus the RVA.
        initial_base_address = module_base + data['rva']
        
        # --- Run Method A ---
        final_addr_a = method_a(pm, initial_base_address, data['offsets'], name)
        if final_addr_a:
            value = read_float(pm, final_addr_a)
            logging.info(f"Method A Success! Final Value at {hex(final_addr_a)}: {value}\n")
        else:
            logging.error("Method A Failed.\n")

        # --- Run Method B ---
        final_addr_b = method_b(pm, initial_base_address, data['offsets'], name)
        if final_addr_b:
            value = read_float(pm, final_addr_b)
            logging.info(f"Method B Success! Final Value at {hex(final_addr_b)}: {value}\n")
        else:
            logging.error("Method B Failed.\n")
            
        # --- Run Method C ---
        final_addr_c = method_c(pm, initial_base_address, data['offsets'], name)
        if final_addr_c:
            value = read_float(pm, final_addr_c)
            logging.info(f"Method C Success! Final Value at {hex(final_addr_c)}: {value}\n")
        else:
            logging.error("Method C Failed.\n")

    logging.info("Diagnostic script finished.")

if __name__ == "__main__":
    run_diagnostic()
