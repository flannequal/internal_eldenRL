import logging
import struct
import time
from typing import Dict, Optional, Tuple

from memory_manager import MemoryManager

class TeleportManager:
    """
    Handles all teleportation-related logic, including saving/loading locations
    and executing the teleport by manipulating entity and global coordinates.
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
        
        x, y, z = coords
        bonfire_id = 0x3E213247 
        tp_data = struct.pack("<fffI", x, y, z, bonfire_id)
        
        self.locations[name] = {
            "x": x,
            "y": y,
            "z": z,
            "tp_data_hex": tp_data.hex()
        }
        logging.info(f"Saved location '{name}': (X: {x:.2f}, Y: {y:.2f}, Z: {z:.2f})")
        return True

    def teleport_to_coords(self, x: float, y: float, z: float, entity_addr: Optional[int] = None) -> bool:
        """
        Teleports an entity to a specific set of global coordinates.
        If entity_addr is None, it defaults to the local player.
        """
        target_name = "Player" if entity_addr is None else f"Entity at {hex(entity_addr)}"
        logging.info(f"Initiating teleport for {target_name} to (X:{x:.2f}, Y:{y:.2f}, Z:{z:.2f})...")

        # 1. Determine the addresses for the target entity's local coordinates and gravity
        if entity_addr is None:
            # Default to player, using named pointers from config
            addr_x_local = self.mem._get_address_from_config("xPlayer")
            addr_y_local = self.mem._get_address_from_config("yPlayer")
            addr_z_local = self.mem._get_address_from_config("zPlayer")
            addr_gravity = self.mem._get_address_from_config("PlayerGravity")
        else:
            # Calculate addresses dynamically for the given entity
            try:
                comp_ptr = self.mem.read_longlong(entity_addr + 0x190)
                if not comp_ptr: raise ValueError("Component pointer is null")
                transform_ptr = self.mem.read_longlong(comp_ptr + 0x68)
                if not transform_ptr: raise ValueError("Transform pointer is null")

                addr_x_local = transform_ptr + 0x70
                addr_y_local = transform_ptr + 0x74
                addr_z_local = transform_ptr + 0x78
                addr_gravity = transform_ptr + 0x1D3
            except Exception as e:
                logging.error(f"Failed to get dynamic addresses for entity {hex(entity_addr)}: {e}")
                return False

        # 2. Get addresses for global coordinates (these are always the same)
        addr_x_global = self.mem._get_address_from_config("xGlobal")
        addr_y_global = self.mem._get_address_from_config("yGlobal")
        addr_z_global = self.mem._get_address_from_config("zGlobal")

        if not all([addr_x_local, addr_y_local, addr_z_local, addr_gravity, addr_x_global, addr_y_global, addr_z_global]):
            logging.error(f"Could not resolve all necessary addresses for teleporting {target_name}.")
            return False

        # 3. Read current values from memory
        val_x_local = self.mem.read_float(addr_x_local)
        val_y_local = self.mem.read_float(addr_y_local)
        val_z_local = self.mem.read_float(addr_z_local)
        val_x_global = self.mem.read_float(addr_x_global)
        val_y_global = self.mem.read_float(addr_y_global)
        val_z_global = self.mem.read_float(addr_z_global)

        if any(v is None for v in [val_x_local, val_y_local, val_z_local, val_x_global, val_y_global, val_z_global]):
            logging.error(f"Failed to read one or more coordinate values for {target_name}.")
            return False
            
        # 4. Perform the coordinate calculation (exact CE logic, standardized to Y-up)
        # This calculates the required local coordinates to achieve the target global coordinates.
        new_x = x - (val_x_global - val_x_local)
        new_y = y - (val_y_global - val_y_local)
        new_z = z - (val_z_global - val_z_local)

        # 5. Disable gravity, write new coordinates, wait, and re-enable gravity
        logging.info(f"Disabling gravity for {target_name} and writing new coordinates...")
        self.mem.write_int(addr_gravity, 1)
        time.sleep(0.05)
        
        self.mem.write_float(addr_x_local, new_x)
        self.mem.write_float(addr_y_local, new_y)
        self.mem.write_float(addr_z_local, new_z)
        
        time.sleep(1.5)
        
        self.mem.write_int(addr_gravity, 0)
        logging.info(f"Gravity re-enabled. Teleport complete for {target_name}.")

        return True

    def teleport_to_location(self, name: str) -> bool:
        """Teleports the player to a previously saved location."""
        location = self.locations.get(name)
        if not location:
            logging.error(f"Location '{name}' not found.")
            return False
        
        # Player teleport is the default (entity_addr=None)
        return self.teleport_to_coords(location['x'], location['y'], location['z'])
