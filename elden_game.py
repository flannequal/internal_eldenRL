import logging
from typing import Optional, Tuple

from memory_manager import MemoryManager
from teleport import TeleportManager

class EldenRingGame:
    """
    Provides a high-level API to interact with the Elden Ring game,
    abstracting away the complexities of memory manipulation.
    """

    def __init__(self, process_name: str = "eldenring.exe"):
        self.mem = MemoryManager(process_name)
        if not self.mem.attach():
            raise RuntimeError(f"Failed to attach to {process_name}. Is the game running?")
        
        self.mem.load_addresses("addresses.yaml")
        self.teleporter = TeleportManager(self.mem)
        logging.info("EldenRingGame API initialized.")

    def get_player_hp(self) -> Optional[Tuple[int, int]]:
        """Returns the player's current and maximum HP."""
        _, current_hp = self.mem.read_pointer("PlayerHP")
        _, max_hp = self.mem.read_pointer("PlayerMaxHP")
        if current_hp is not None and max_hp is not None:
            return current_hp, max_hp
        return None

    def get_player_stats(self) -> Optional[dict]:
        """Returns a dictionary of all primary player stats."""
        stats = {}
        hp = self.get_player_hp()
        if hp:
            stats['hp'], stats['max_hp'] = hp

        _, sp = self.mem.read_pointer("PlayerSP")
        _, max_sp = self.mem.read_pointer("PlayerMaxSP")
        if sp is not None and max_sp is not None:
            stats['sp'], stats['max_sp'] = sp, max_sp

        _, mp = self.mem.read_pointer("PlayerMP")
        _, max_mp = self.mem.read_pointer("PlayerMaxMP")
        if mp is not None and max_mp is not None:
            stats['mp'], stats['max_mp'] = mp, max_mp
            
        return stats if stats else None

    def get_player_position(self) -> Optional[Tuple[float, float, float]]:
        """Returns the player's current X, Y, Z coordinates."""
        addr, pos_bytes = self.mem.read_pointer("PlayerPosition")
        if not pos_bytes or len(pos_bytes) < 12:
            return None
        import struct
        x, y, z = struct.unpack("<fff", pos_bytes[:12])
        return x, y, z

    def save_teleport_location(self, name: str):
        """Saves the player's current position as a named teleport location."""
        self.teleporter.save_current_location(name)

    def teleport(self, name: str):
        """Teleports the player to a named location."""
        self.teleporter.teleport_to_location(name)
        
    def get_last_grace(self) -> Optional[int]:
        """Returns the ID of the last grace the player rested at."""
        _, grace_id = self.mem.read_pointer("LastGrace")
        return grace_id

    def close(self):
        """Detaches from the game process."""
        # In pymem, the process is automatically closed when the object is destroyed.
        logging.info("EldenRingGame API shutting down.")

