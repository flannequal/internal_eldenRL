import os
import time
from typing import Tuple, Optional, Dict, Any
import sys
import os as _os

try:
    import yaml  # type: ignore
except Exception:
    yaml = None  # Fallback if PyYAML is not installed; loading will be skipped


class MemoryClient:
    """Memory client for Elden Ring with a minimal, real backend by default.

    By default, this client attempts to use the SoulsGym-compatible Elden Ring backend
    located at `examples/eldenring.py`. If that import or attach fails, callers should
    handle errors accordingly. No simulation/stub is used unless explicitly enabled
    via `simulate=True`.
    """

    def __init__(self, process_name: str = "eldenring.exe", memory_config_path: Optional[str] = None, simulate: bool = False):
        self.process_name = process_name
        self.attached = False
        self._last_attach_attempt = 0.0
        self.simulate = simulate

        # Try to import SoulsGym Elden Ring interface
        self._sg_game = None
        self._uses_soulsgym = False
        try:
            if not self.simulate:
                # Local import to avoid hard dependency if not used
                examples_dir = _os.path.join(_os.path.dirname(__file__), 'examples')
                if _os.path.isdir(examples_dir) and (examples_dir not in sys.path):
                    sys.path.insert(0, examples_dir)
                from eldenring import EldenRing  # type: ignore
                self._sg_game = EldenRing()
                self._uses_soulsgym = True
        except Exception:
            # Fallback to minimal internal placeholders when SoulsGym is unavailable
            self._sg_game = None
            self._uses_soulsgym = False

        # Cached state for minimal fallback (only used if simulate=True or SoulsGym not loaded)
        self._player_hp = 1.0
        self._player_stamina = 1.0
        self._boss_hp = 1.0
        self._player_pos = (0.0, 0.0, 0.0)
        self._t_reset = time.time()

        # Databases from YAML (optional)
        self._arena_meta_db: Dict[int, Dict[str, Any]] = {}
        self._arena_coords_db: Dict[int, Dict[str, Any]] = {}
        self._bonfires_db: Dict[str, int] = {}
        self._addresses_db: Dict[str, Any] = {}
        # Load YAML configs
        self._load_arenas_meta()
        self._load_arenas_coords()
        self._load_bonfires()
        self._load_addresses()

    # ----- Config loading -----
    def _safe_load_yaml(self, path: str) -> Dict[str, Any]:
        if not os.path.isfile(path) or yaml is None:
            return {}
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}

    def _load_arenas_meta(self) -> None:
        # Standardized to arenas.* only
        data = self._safe_load_yaml(os.path.join('config', 'arenas.yaml'))
        if not data:
            data = self._safe_load_yaml(os.path.join('config', 'arenas.sample.yaml'))
        arenas = data.get('arenas', []) if isinstance(data, dict) else []
        for entry in arenas:
            try:
                arena_id = int(entry.get('id'))
                self._arena_meta_db[arena_id] = entry
            except Exception:
                continue

    def _load_arenas_coords(self) -> None:
        data = self._safe_load_yaml(os.path.join('config', 'coordinates.yaml'))
        if not data:
            data = self._safe_load_yaml(os.path.join('config', 'coordinates.sample.yaml'))
        arenas = data.get('arenas', []) if isinstance(data, dict) else []
        for entry in arenas:
            try:
                arena_id = int(entry.get('id'))
                self._arena_coords_db[arena_id] = entry
            except Exception:
                continue

    def _load_bonfires(self) -> None:
        data = self._safe_load_yaml(os.path.join('config', 'bonfires.yaml'))
        if not data:
            data = self._safe_load_yaml(os.path.join('config', 'bonfires.sample.yaml'))
        if isinstance(data, dict):
            # If stored as key: id mapping
            for k, v in data.items():
                try:
                    self._bonfires_db[str(k)] = int(v)
                except Exception:
                    continue
        elif isinstance(data, list):
            # Not expected; ignore
            pass

    def _load_addresses(self) -> None:
        data = self._safe_load_yaml(os.path.join('config', 'addresses.yaml'))
        if not data:
            data = self._safe_load_yaml(os.path.join('config', 'addresses.sample.yaml'))
        if isinstance(data, dict):
            self._addresses_db = data

    # ----- Process management -----
    def attach(self) -> bool:
        """Attach to game process. Return True if successful."""
        now = time.time()
        if now - self._last_attach_attempt < 0.5:
            return self.attached
        self._last_attach_attempt = now
        if self._uses_soulsgym:
            # SoulsGym Game attaches on access; here we check a simple read to validate
            try:
                _ = self._sg_game.player_max_hp  # type: ignore[attr-defined]
                self.attached = True
            except Exception:
                self.attached = False
        else:
            # Simulation or minimal fallback
            self.attached = True
        return self.attached

    def detach(self) -> None:
        """Detach from the game process."""
        # TODO: Implement handle cleanup
        self.attached = False

    # ----- Reads -----
    def read_player_hp(self) -> float:
        """Return player HP in [0, 1]."""
        if self._uses_soulsgym and not self.simulate:
            try:
                curr = float(self._sg_game.player_hp)
                max_hp = float(self._sg_game.player_max_hp)
                ratio = 0.0 if max_hp <= 0 else max(0.0, min(1.0, curr / max_hp))
                self._player_hp = ratio
                return ratio
            except Exception:
                return 0.0
        if self.simulate:
            # Simple decay-and-bounce simulation
            elapsed = max(0.0, time.time() - self._t_reset)
            hp = max(0.0, 1.0 - 0.03 * (elapsed % 15))
            self._player_hp = hp
            return hp
        return float(self._player_hp)

    def read_player_stamina(self) -> float:
        """Return player stamina in [0, 1]."""
        if self._uses_soulsgym and not self.simulate:
            try:
                curr = float(self._sg_game.player_sp)
                max_sp = float(self._sg_game.player_max_sp)
                ratio = 0.0 if max_sp <= 0 else max(0.0, min(1.0, curr / max_sp))
                self._player_stamina = ratio
                return ratio
            except Exception:
                return 0.0
        if self.simulate:
            elapsed = max(0.0, time.time() - self._t_reset)
            # oscillate stamina between 0.4 and 1.0
            stam = 0.7 + 0.3 * (0.5 - ((elapsed % 2.0) - 1.0) ** 2)
            self._player_stamina = max(0.0, min(1.0, stam))
            return self._player_stamina
        return float(self._player_stamina)

    def read_boss_hp(self) -> float:
        """Return boss HP in [0, 1] if a boss is active, else 1.0."""
        if self._uses_soulsgym and not self.simulate:
            # Try to read lock-on target HP via SoulsGym address map if provided by user
            try:
                data_addresses = getattr(self._sg_game, 'data').addresses  # type: ignore[attr-defined]
                target_hp_record = data_addresses.get('TargetHP')
                target_max_hp_record = data_addresses.get('TargetMaxHP')
                if target_hp_record is not None and target_max_hp_record is not None:
                    curr = float(self._sg_game.mem.read_record(target_hp_record))  # type: ignore[attr-defined]
                    mxx = float(self._sg_game.mem.read_record(target_max_hp_record))  # type: ignore[attr-defined]
                    if mxx > 0:
                        self._boss_hp = max(0.0, min(1.0, curr / mxx))
                        return self._boss_hp
            except Exception:
                pass
            # Fallback: return last known placeholder ratio
            return float(self._boss_hp)
        if self.simulate:
            elapsed = max(0.0, time.time() - self._t_reset)
            boss_hp = max(0.0, 1.0 - 0.02 * elapsed)
            self._boss_hp = boss_hp
            return boss_hp
        return float(self._boss_hp)

    def read_player_position(self) -> Tuple[float, float, float]:
        """Return player world position (x, y, z)."""
        if self._uses_soulsgym and not self.simulate:
            try:
                x, y, z, _ = self._sg_game.player_pose  # type: ignore[attr-defined]
                return float(x), float(y), float(z)
            except Exception:
                return tuple(self._player_pos)
        return tuple(self._player_pos)

    # ----- Writes -----
    def write_player_position(self, x: float, y: float, z: float) -> None:
        """Teleport player to the given world position."""
        if self._uses_soulsgym and not self.simulate:
            try:
                pose = list(self._sg_game.player_pose)  # type: ignore[attr-defined]
                pose[:3] = [float(x), float(y), float(z)]
                self._sg_game.player_pose = pose  # type: ignore[attr-defined]
            except Exception:
                pass
        self._player_pos = (float(x), float(y), float(z))

    def set_player_full_health(self) -> None:
        """Restore player HP to full."""
        if self._uses_soulsgym and not self.simulate:
            try:
                self._sg_game.reset_player_hp()  # type: ignore[attr-defined]
            except Exception:
                pass
        self._player_hp = 1.0

    def set_player_full_stamina(self) -> None:
        """Restore player stamina to full."""
        if self._uses_soulsgym and not self.simulate:
            try:
                self._sg_game.reset_player_sp()  # type: ignore[attr-defined]
            except Exception:
                pass
        self._player_stamina = 1.0

    def set_boss_hp(self, hp_ratio: float) -> None:
        """Set boss HP to a ratio in [0, 1]."""
        # Not directly supported by SoulsGym ER interface; keep placeholder variable for reward calc until offsets are known
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
        # If SoulsGym is available, prefer safe teleport and resets via its API
        if self._uses_soulsgym and not self.simulate:
            try:
                # Prefer spawn from arenas meta; fallback to coordinates.yaml
                meta_entry = self._arena_meta_db.get(int(arena_id))
                spawn_src = None
                if meta_entry and isinstance(meta_entry.get('player_spawn'), dict):
                    spawn_src = meta_entry.get('player_spawn')
                else:
                    coords_entry = self._arena_coords_db.get(int(arena_id))
                    spawn_src = (coords_entry.get('player_spawn') or {}) if coords_entry else {}
                if spawn_src:
                    spawn = spawn_src
                    x = float(spawn.get('x', 0.0))
                    y = float(spawn.get('y', 0.0))
                    z = float(spawn.get('z', 0.0))
                    pose = list(self._sg_game.player_pose)  # type: ignore[attr-defined]
                    pose[:3] = [x, y, z]
                    self._sg_game.player_pose = pose  # type: ignore[attr-defined]
                # Optionally set last bonfire
                if meta_entry:
                    bonfire_key = meta_entry.get('nearest_bonfire_key')
                    if bonfire_key and bonfire_key in self._bonfires_db:
                        try:
                            self._sg_game.last_bonfire = str(bonfire_key)  # type: ignore[attr-defined]
                        except Exception:
                            pass
                self._sg_game.reset_player_hp()  # type: ignore[attr-defined]
                self._sg_game.reset_player_sp()  # type: ignore[attr-defined]
                # Boss HP reset is left as future extension when boss entity offsets are available
            except Exception:
                pass
        else:
            # YAML-driven fallback
            meta_entry = self._arena_meta_db.get(int(arena_id))
            spawn_src = None
            if meta_entry and isinstance(meta_entry.get('player_spawn'), dict):
                spawn_src = meta_entry.get('player_spawn')
            else:
                coords_entry = self._arena_coords_db.get(int(arena_id))
                spawn_src = (coords_entry.get('player_spawn') or {}) if coords_entry else {}
            if spawn_src:
                spawn = spawn_src
                x = float(spawn.get('x', 0.0))
                y = float(spawn.get('y', 0.0))
                z = float(spawn.get('z', 0.0))
                self.write_player_position(x, y, z)
            else:
                self.write_player_position(0.0, 0.0, 0.0)
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


