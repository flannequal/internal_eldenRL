import logging
import struct
import time
from typing import Dict, Optional, Tuple

from memory_manager import MemoryManager

class TeleportManager:
    """
    Handles all teleportation-related logic, including saving/loading locations
    and executing the teleport by manipulating player and global coordinates.
    This class preserves the exact logic from the original Cheat Engine implementation.
    """

    def __init__(self, mem: MemoryManager):
        self.mem = mem
        self.locations: Dict[str, Dict] = {}

    def save_current_location(self, name: str) -> bool:
        """
        Reads the player's current global coordinates and saves them under a given name.
        """
        coords = self.mem.read_teleport_coords()
        if coords is None:
            logging.error("Failed to read current global coordinates. Cannot save location.")
            return False
        
        x, z, y = coords
        # The bonfire ID is a magic number used by the original CE table.
        bonfire_id = 0x3E213247 
        tp_data = struct.pack("<fffI", x, z, y, bonfire_id)
        
        self.locations[name] = {
            "x": x,
            "z": z,
            "y": y,
            "tp_data_hex": tp_data.hex()
        }
        logging.info(f"Saved location '{name}': (X: {x:.2f}, Z: {z:.2f}, Y: {y:.2f})")
        return True

    def teleport_to_coords(self, x: float, z: float, y: float) -> bool:
        """
        Teleports the player to a specific set of coordinates using the precise
        Cheat Engine logic.
        """
        logging.info(f"Initiating teleport to (X:{x:.2f}, Z:{z:.2f}, Y:{y:.2f})...")

        # 1. Get addresses for all required pointers
        addr_x_player = self.mem._get_address_from_config("xPlayer")
        addr_z_player = self.mem._get_address_from_config("zPlayer")
        addr_y_player = self.mem._get_address_from_config("yPlayer")
        addr_x_global = self.mem._get_address_from_config("xGlobal")
        addr_z_global = self.mem._get_address_from_config("zGlobal")
        addr_y_global = self.mem._get_address_from_config("yGlobal")
        addr_gravity = self.mem._get_address_from_config("PlayerGravity")

        if not all([addr_x_player, addr_z_player, addr_y_player, addr_x_global, addr_z_global, addr_y_global, addr_gravity]):
            logging.error("Could not resolve all necessary addresses for teleport.")
            return False

        # 2. Read current values from memory
        val_x_player = self.mem.read_float(addr_x_player)
        val_z_player = self.mem.read_float(addr_z_player)
        val_y_player = self.mem.read_float(addr_y_player)
        val_x_global = self.mem.read_float(addr_x_global)
        val_z_global = self.mem.read_float(addr_z_global)
        val_y_global = self.mem.read_float(addr_y_global)

        if any(v is None for v in [val_x_player, val_z_player, val_y_player, val_x_global, val_z_global, val_y_global]):
            logging.error("Failed to read one or more coordinate values from memory.")
            return False
            
        # 3. Perform the coordinate calculation (exact CE logic)
        new_x = x - (val_x_global - val_x_player)
        new_z = z - (val_z_global - val_z_player)
        new_y = (y - (val_y_global + val_y_player)) * -1

        # 4. Disable gravity, write new coordinates, wait, and re-enable gravity
        logging.info("Disabling gravity and writing new coordinates...")
        self.mem.write_int(addr_gravity, 1) # Disable gravity
        time.sleep(0.05)
        
        self.mem.write_float(addr_x_player, new_x)
        self.mem.write_float(addr_z_player, new_z)
        self.mem.write_float(addr_y_player, new_y)
        
        time.sleep(1.5) # Give the game time to process the new position
        
        self.mem.write_int(addr_gravity, 0) # Re-enable gravity
        logging.info("Gravity re-enabled. Teleport complete.")

        return True

    def teleport_to_location(self, name: str) -> bool:
        """Teleports the player to a previously saved location."""
        location = self.locations.get(name)
        if not location:
            logging.error(f"Location '{name}' not found.")
            return False
        
        return self.teleport_to_coords(location['x'], location['z'], location['y'])
