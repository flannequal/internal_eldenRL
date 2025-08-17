import pymem
import struct
import time
import logging

# --- Configuration ---
# Set up basic logging to see the script's progress.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# The name of the game's process.
PROCESS_NAME = "eldenring.exe"

# RVA (Relative Virtual Address) for WorldChrMan. This is a static offset
# from the game's main module base address.
WORLDCHRMAN_RVA = 0x3D65F88

# Pointer chains (offsets) from the resolved WorldChrMan address.
# These chains navigate through memory to find the desired values.
PLAYER_BASE_OFFSETS = [0x10EF8, 0x0]
PLAYER_XYZ_OFFSETS = PLAYER_BASE_OFFSETS + [0x190, 0x68, 0x70]
PLAYER_GRAVITY_OFFSETS = PLAYER_BASE_OFFSETS + [0x190, 0x68, 0x1D3]
ALLOW_PLAYER_DEATH_OFFSETS = PLAYER_BASE_OFFSETS + [0x190, 0x0, 0x19B]

# Target coordinates for the teleport (Beastman Arena from your config).
# You can change these values to teleport to a different location.
TARGET_X = -3.797457933
TARGET_Y = -7.21598196 # In-game height coordinate
TARGET_Z = 2.266977549


class TeleportationError(Exception):
    """Custom exception for teleportation failures."""
    pass


class EldenRingMemory:
    """A simplified memory manager for handling Elden Ring's process memory."""

    def __init__(self, process_name: str):
        """Attaches to the game process and gets the base address."""
        self.pm = None
        try:
            self.pm = pymem.Pymem(process_name)
            self.module_base = pymem.process.module_from_name(
                self.pm.process_handle, process_name
            ).lpBaseOfDll
            logging.info(f"Successfully attached to {process_name} (PID: {self.pm.process_id})")
            logging.info(f"Module base address: {hex(self.module_base)}")
        except pymem.exception.ProcessNotFound:
            logging.error(f"Process '{process_name}' not found. Please ensure the game is running.")
            raise

    def resolve_pointer_chain(self, base_address: int, offsets: list[int]) -> int:
        """Follows a chain of pointers to find the final memory address."""
        try:
            # The first address is read from the static base + RVA
            addr = self.pm.read_longlong(base_address)
            # Follow the rest of the pointers
            for offset in offsets[:-1]:
                if addr == 0:
                    raise TeleportationError("Pointer in chain was NULL.")
                addr = self.pm.read_longlong(addr + offset)
            # The final offset is added to the last resolved address
            return addr + offsets[-1]
        except pymem.exception.MemoryReadError as e:
            logging.error(f"Failed to read memory during pointer chain resolution: {e}")
            raise TeleportationError("Could not resolve pointer chain.") from e

    def write_bit(self, address: int, bit_index: int, value: bool):
        """Reads a byte, modifies a specific bit, and writes it back."""
        try:
            current_byte = self.pm.read_bytes(address, 1)[0]
            mask = 1 << bit_index
            if value:
                new_byte = current_byte | mask  # Set bit to 1
            else:
                new_byte = current_byte & ~mask # Set bit to 0
            self.pm.write_bytes(address, new_byte.to_bytes(1, 'little'), 1)
        except pymem.exception.MemoryReadError as e:
            logging.error(f"Failed to read byte for bitwise operation at {hex(address)}: {e}")
        except pymem.exception.MemoryWriteError as e:
            logging.error(f"Failed to write byte for bitwise operation at {hex(address)}: {e}")

def safe_teleport(mem: EldenRingMemory, x: float, y: float, z: float):
    """
    Safely teleports the player by disabling death and gravity, moving the character,
    and then re-enabling the original settings.
    """
    logging.info("--- Starting Safe Teleport ---")
    worldchrman_base = mem.module_base + WORLDCHRMAN_RVA

    try:
        # 1. Resolve the final addresses for player coordinates, gravity, and death flag.
        logging.info("Resolving memory addresses...")
        addr_xyz = mem.resolve_pointer_chain(worldchrman_base, PLAYER_XYZ_OFFSETS)
        addr_gravity = mem.resolve_pointer_chain(worldchrman_base, PLAYER_GRAVITY_OFFSETS)
        addr_death = mem.resolve_pointer_chain(worldchrman_base, ALLOW_PLAYER_DEATH_OFFSETS)
        logging.info(f"  - Player Coords Addr: {hex(addr_xyz)}")
        logging.info(f"  - Player Gravity Addr: {hex(addr_gravity)}")
        logging.info(f"  - Player Death Addr: {hex(addr_death)}")

        # 2. Disable game mechanics that could kill the player during teleport.
        logging.info("Disabling player death and gravity...")
        # To prevent death, we write the value 1.
        mem.pm.write_int(addr_death, 1)
        # To disable gravity, we set the 6th bit to 0.
        mem.write_bit(addr_gravity, 6, False)
        time.sleep(0.05) # Brief pause to ensure game state updates.

        # 3. Write the new coordinates to the player's position in memory.
        logging.info(f"Writing new coordinates: X={x:.2f}, Y={y:.2f}, Z={z:.2f}")
        # The coordinates are packed into bytes representing three 32-bit floats.
        # Note: Elden Ring's coordinate system is typically X, Z, Y.
        # We write X, Y (height), Z as per the common convention in memory tools.
        position_bytes = struct.pack("<fff", x, y, z)
        mem.pm.write_bytes(addr_xyz, position_bytes, len(position_bytes))
        time.sleep(0.1) # Pause to allow the character to settle at the new location.

        # 4. Re-enable the game mechanics.
        logging.info("Re-enabling player death and gravity...")
        # To allow death again, we write the value 0.
        mem.pm.write_int(addr_death, 0)
        # To re-enable gravity, we set the 6th bit back to 1.
        mem.write_bit(addr_gravity, 6, True)

        logging.info("--- Safe Teleport Complete! ---")

    except (TeleportationError, pymem.exception.PymemError) as e:
        logging.error(f"Teleportation failed: {e}")
        logging.error("Please ensure the game is running and your character is fully loaded in a zone.")

if __name__ == "__main__":
    try:
        memory_manager = EldenRingMemory(PROCESS_NAME)
        safe_teleport(memory_manager, TARGET_X, TARGET_Y, TARGET_Z)
    except pymem.exception.ProcessNotFound:
        # The error is already logged by the constructor, so we just exit.
        pass
    except Exception as e:
        logging.critical(f"An unexpected error occurred: {e}")