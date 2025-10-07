import json
import logging
import os
import struct
import time
from typing import Dict, Optional

from eldenrl.memory_mngr import MemoryManager

logger = logging.getLogger(__name__)

LOCATIONS_PATH = os.path.join("config", "locations.json")
BONFIRE_ID = 0x3E213247  # constant taken from the ce table
GRAVITY_SETTLE_S = 1.5


class TeleportManager:

    def __init__(self, mem: MemoryManager, locations_path: str = LOCATIONS_PATH):
        self.mem = mem
        self.locations_path = locations_path
        self.locations: Dict[str, Dict] = self._load_locations()

    def _load_locations(self) -> Dict[str, Dict]:
        try:
            with open(self.locations_path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_locations(self) -> None:
        with open(self.locations_path, "w", encoding="utf-8") as handle:
            json.dump(self.locations, handle, indent=2)

    def save_current_location(self, name: str) -> bool:
        coords = self.mem.read_teleport_coords()
        if coords is None:
            logger.error("could not read global coordinates")
            return False

        x, z, y = coords
        self.locations[name] = {
            "x": x,
            "z": z,
            "y": y,
            "tpdata_hex": struct.pack("<fffI", x, z, y, BONFIRE_ID).hex(),
        }
        self._save_locations()
        logger.info("saved '%s' at (%.2f, %.2f, %.2f)", name, x, z, y)
        return True

    def delete_location(self, name: str) -> bool:
        if name not in self.locations:
            logger.error("no saved location named '%s'", name)
            return False
        del self.locations[name]
        self._save_locations()
        return True

    def teleport_to_coords(self, x: float, z: float, y: float) -> bool:
        logger.info("teleporting to (%.2f, %.2f, %.2f)", x, z, y)

        names = ("xPlayer", "zPlayer", "yPlayer", "xGlobal", "zGlobal", "yGlobal")
        addrs = {name: self.mem.resolve(name) for name in names}
        gravity_addr = self.mem.resolve("PlayerGravity")
        if not all(addrs.values()) or gravity_addr is None:
            logger.error("could not resolve teleport pointers")
            return False

        values = {name: self.mem.read_float(addr) for name, addr in addrs.items()}
        if any(value is None for value in values.values()):
            logger.error("could not read current coordinates")
            return False

        # globals hold the world offset
        new_x = x - (values["xGlobal"] - values["xPlayer"])
        new_z = z - (values["zGlobal"] - values["zPlayer"])
        new_y = (y - (values["yGlobal"] + values["yPlayer"])) * -1  # ce inverts y

        self.mem.write_int(gravity_addr, 1)
        time.sleep(0.05)
        self.mem.write_float(addrs["xPlayer"], new_x)
        self.mem.write_float(addrs["zPlayer"], new_z)
        self.mem.write_float(addrs["yPlayer"], new_y)
        time.sleep(GRAVITY_SETTLE_S)
        self.mem.write_int(gravity_addr, 0)

        logger.info("teleport complete")
        return True

    def teleport_to_location(self, name: str) -> bool:
        location = self.locations.get(name)
        if not location:
            logger.error("no saved location named '%s'", name)
            return False
        return self.teleport_to_coords(location["x"], location["z"], location["y"])
