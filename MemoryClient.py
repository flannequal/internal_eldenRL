import os
import time
from typing import Tuple, Optional, Dict, Any

try:
    import yaml  # type: ignore
except Exception:
    yaml = None  # Fallback if PyYAML is not installed; loading will be skipped


class MemoryClient:
    """Stubbed memory client for Elden Ring.

    This class defines the interface required by the memory-based environment.
    Replace stub implementations with real memory read/write logic.
    """

    def __init__(self, process_name: str = "eldenring.exe", memory_config_path: Optional[str] = None, simulate: bool = False):
        self.process_name = process_name
        self.attached = False
        self._last_attach_attempt = 0.0
        self.simulate = simulate

        # Cached state (for testing scaffolding). Replace with live reads.
        self._player_hp = 1.0
        self._player_stamina = 1.0
        self._boss_hp = 1.0
        self._player_pos = (0.0, 0.0, 0.0)
        self._t_reset = time.time()

        # Arena DB from YAML (optional)
        self._arena_db: Dict[int, Dict[str, Any]] = {}
        # Load YAML arenas
        candidate_paths = []
        if memory_config_path:
            candidate_paths.append(memory_config_path)
        # default fallbacks
        candidate_paths.append(os.path.join('config', 'memory_arenas.yaml'))
        candidate_paths.append(os.path.join('config', 'memory_arenas.sample.yaml'))
        for path in candidate_paths:
            if os.path.isfile(path):
                self._load_config(path)
                break

    # ----- Config loading -----
    def _load_config(self, path: str) -> None:
        if not os.path.isfile(path):
            return
        if yaml is None:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
            arenas = data.get('arenas', [])
            for entry in arenas:
                arena_id = int(entry.get('id'))
                self._arena_db[arena_id] = entry
        except Exception:
            # Silently ignore config errors for now; callers can validate presence
            self._arena_db = {}

    # ----- Process management -----
    def attach(self) -> bool:
        """Attach to game process. Return True if successful."""
        now = time.time()
        if now - self._last_attach_attempt < 0.5:
            return self.attached
        self._last_attach_attempt = now
        # TODO: Implement actual process handle acquisition
        self.attached = True
        return self.attached

    def detach(self) -> None:
        """Detach from the game process."""
        # TODO: Implement handle cleanup
        self.attached = False

    # ----- Reads -----
    def read_player_hp(self) -> float:
        """Return player HP in [0, 1]."""
        if self.simulate:
            # Simple decay-and-bounce simulation
            elapsed = max(0.0, time.time() - self._t_reset)
            hp = max(0.0, 1.0 - 0.03 * (elapsed % 15))
            self._player_hp = hp
            return hp
        return float(self._player_hp)

    def read_player_stamina(self) -> float:
        """Return player stamina in [0, 1]."""
        if self.simulate:
            elapsed = max(0.0, time.time() - self._t_reset)
            # oscillate stamina between 0.4 and 1.0
            stam = 0.7 + 0.3 * (0.5 - ((elapsed % 2.0) - 1.0) ** 2)
            self._player_stamina = max(0.0, min(1.0, stam))
            return self._player_stamina
        return float(self._player_stamina)

    def read_boss_hp(self) -> float:
        """Return boss HP in [0, 1] if a boss is active, else 1.0."""
        if self.simulate:
            elapsed = max(0.0, time.time() - self._t_reset)
            boss_hp = max(0.0, 1.0 - 0.02 * elapsed)
            self._boss_hp = boss_hp
            return boss_hp
        return float(self._boss_hp)

    def read_player_position(self) -> Tuple[float, float, float]:
        """Return player world position (x, y, z)."""
        # TODO: Replace with memory read
        return tuple(self._player_pos)

    # ----- Writes -----
    def write_player_position(self, x: float, y: float, z: float) -> None:
        """Teleport player to the given world position."""
        # TODO: Replace with memory write
        self._player_pos = (float(x), float(y), float(z))

    def set_player_full_health(self) -> None:
        """Restore player HP to full."""
        # TODO: Replace with memory write
        self._player_hp = 1.0

    def set_player_full_stamina(self) -> None:
        """Restore player stamina to full."""
        # TODO: Replace with memory write
        self._player_stamina = 1.0

    def set_boss_hp(self, hp_ratio: float) -> None:
        """Set boss HP to a ratio in [0, 1]."""
        # TODO: Replace with memory write
        self._boss_hp = max(0.0, min(1.0, float(hp_ratio)))

    # ----- Arena / reset -----
    def reset_arena(self, arena_id: int, second_phase: bool = False) -> None:
        """Place player and boss into a valid starting state for the given arena.

        This should:
        - Teleport player to arena start
        - Reset player hp/stamina
        - Reset boss state and hp
        - Set any required flags (e.g., fog state cleared)
        """
        # If config exists, use it to set spawn position and reset boss/player
        arena = self._arena_db.get(int(arena_id))
        if arena:
            spawn = (arena.get('player_spawn') or {})
            x = float(spawn.get('x', 0.0))
            y = float(spawn.get('y', 0.0))
            z = float(spawn.get('z', 0.0))
            # TODO: Apply rotation and camera if needed
            self.write_player_position(x, y, z)
        else:
            # Fallback placeholder position
            self.write_player_position(0.0, 0.0, 0.0)

        # TODO: Clear fog/triggers/flags via memory writes when available
        self.set_player_full_health()
        self.set_player_full_stamina()
        self.set_boss_hp(1.0)
        self._t_reset = time.time()

    # ----- Test helpers (optional) -----
    def simulate_damage(self, player_delta: Optional[float] = None, boss_delta: Optional[float] = None) -> None:
        if player_delta is not None:
            self._player_hp = max(0.0, min(1.0, self._player_hp + float(player_delta)))
        if boss_delta is not None:
            self._boss_hp = max(0.0, min(1.0, self._boss_hp + float(boss_delta)))


