import pymem
import time

# --- Configuration: Directly from your addresses.yaml ---
PROCESS_NAME = "eldenring.exe"

# This is the Relative Virtual Address (RVA) for the static pointer to WorldChrMan
WORLDCHRMAN_RVA = 0x3D65F88

# These are the offsets to get to the Player's HP value
PLAYER_HP_OFFSETS = [0x10EF8, 0x0, 0x190, 0x0, 0x138]
PLAYER_MAX_HP_OFFSETS = [0x10EF8, 0x0, 0x190, 0x0, 0x13C]


def get_final_address(pm, base_address, offsets):
    """
    A simple, clear function to walk a pointer chain.
    """
    addr = base_address

    # Follow all pointers until the last offset
    # The last element in the list is a direct offset, not a pointer.
    for i, offset in enumerate(offsets[:-1]):
        try:
            addr = pm.read_longlong(addr + offset)
            print(
                f"    Step {i}: Reading pointer at {hex(addr + offset)} -> New Base: {hex(addr)}")
            if addr == 0:
                print(
                    f"    ERROR: Pointer at step {i} was NULL. Aborting chain.")
                return None
        except pymem.exception.MemoryReadError:
            print(
                f"    ERROR: Failed to read memory at step {i} (address: {hex(addr + offset)})")
            return None

    # Add the final offset to get the address of the value we want
    final_address = addr + offsets[-1]
    print(
        f"    Final Step: Adding last offset {hex(offsets[-1])} -> Final Address: {hex(final_address)}")
    return final_address


def main():
    print(f"Attempting to attach to '{PROCESS_NAME}'...")
    try:
        pm = pymem.Pymem(PROCESS_NAME)
        print(f"Successfully attached to process ID: {pm.process_id}")
    except pymem.exception.ProcessNotFound:
        print(f"'{PROCESS_NAME}' not found. Please make sure the game is running.")
        return

    # Get the base address of the main game module
    try:
        module_base = pymem.process.module_from_name(
            pm.process_handle, PROCESS_NAME).lpBaseOfDll
        print(
            f"\n[STEP 1] Found '{PROCESS_NAME}' module base address: {hex(module_base)}")
    except AttributeError:
        print(f"Could not find module '{PROCESS_NAME}'. Exiting.")
        return

    # Calculate the absolute address of the static pointer to WorldChrMan
    static_pointer_addr = module_base + WORLDCHRMAN_RVA
    print(
        f"[STEP 2] Calculated 'WorldChrMan' STATIC POINTER address: {hex(static_pointer_addr)}")

    # Dereference the static pointer to get the TRUE base address of WorldChrMan
    try:
        worldchrman_base_addr = pm.read_longlong(static_pointer_addr)
        print(
            f"[STEP 3] Read pointer at that address. TRUE 'WorldChrMan' BASE is: {hex(worldchrman_base_addr)}")
    except pymem.exception.MemoryReadError:
        print(
            f"  -> ERROR: Failed to read the pointer at {hex(static_pointer_addr)}. This is the root cause.")
        print("     This likely means the RVA in the config (0x3D65F88) is incorrect for your game version.")
        return

    print("\n--- Resolving PlayerHP ---")
    final_hp_address = get_final_address(
        pm, worldchrman_base_addr, PLAYER_HP_OFFSETS)

    if final_hp_address:
        try:
            current_hp = pm.read_int(final_hp_address)
            print(
                f"SUCCESS! PlayerHP Address: {hex(final_hp_address)} | Value: {current_hp}\n")
        except pymem.exception.MemoryReadError:
            print(
                f"ERROR: Could not read the final integer value at {hex(final_hp_address)}\n")

    print("--- Resolving PlayerMaxHP ---")
    final_max_hp_address = get_final_address(
        pm, worldchrman_base_addr, PLAYER_MAX_HP_OFFSETS)

    if final_max_hp_address:
        try:
            max_hp = pm.read_int(final_max_hp_address)
            print(
                f"SUCCESS! PlayerMaxHP Address: {hex(final_max_hp_address)} | Value: {max_hp}\n")
        except pymem.exception.MemoryReadError:
            print(
                f"ERROR: Could not read the final integer value at {hex(final_max_hp_address)}\n")


if __name__ == "__main__":
    main()
