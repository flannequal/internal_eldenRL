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
        self._pm = None

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
                if hasattr(self._sg_game, '_process'):
                    self._pm = self._sg_game._process  # type: ignore[attr-defined]
        except Exception:
            # Fallback to minimal internal placeholders when SoulsGym is unavailable
            self._sg_game = None
            self._uses_soulsgym = False
            self._pm = None

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
        self._addr_records: Dict[str, Any] = {}
        self._bases_static: Dict[str, int] = {}
        self._wcm_offsets: Dict[str, int] = {}
        self._char_offsets: Dict[str, int] = {}
        # Cached boss selection
        self._boss_param_id: Optional[int] = None
        self._boss_stats_addr: int = 0
        self._boss_comp_addr: int = 0
        self._boss_transform_addr: int = 0
        self._boss_last_resolve: float = 0.0
        self._boss_resolve_retry_sec: float = 1.0
        # Load YAML configs
        self._load_arenas_meta()
        self._load_arenas_coords()
        self._load_bonfires()
        self._load_addresses()
        # Parse address records and bases_static
        if isinstance(self._addresses_db, dict):
            self._addr_records = self._addresses_db.get('addresses', {}) or {}
            bases_static = self._addresses_db.get('bases_static', {}) or {}
            for k, v in bases_static.items():
                try:
                    self._bases_static[k] = int(str(v), 16)
                except Exception:
                    continue
            # Helper offsets for entity list scanning (optional)
            wcm = self._addresses_db.get('worldchrman') or {}
            ch = self._addresses_db.get('character') or {}
            for k, v in (wcm.items() if isinstance(wcm, dict) else []):
                try:
                    self._wcm_offsets[str(k)] = int(str(v), 16)
                except Exception:
                    continue
            for k, v in (ch.items() if isinstance(ch, dict) else []):
                try:
                    self._char_offsets[str(k)] = int(str(v), 16)
                except Exception:
                    continue

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
        # Also support JSON bases exported by CE (elden_bases.json)
        try:
            import json  # type: ignore
            json_path = os.path.join('config', 'elden_bases.json')
            if os.path.isfile(json_path):
                with open(json_path, 'r', encoding='utf-8') as fh:
                    bases = json.load(fh)
                if isinstance(bases, dict):
                    if 'bases_static' not in self._addresses_db:
                        self._addresses_db['bases_static'] = {}
                    for k, v in bases.items():
                        try:
                            self._addresses_db['bases_static'][k] = int(str(v), 16)
                        except Exception:
                            continue
        except Exception:
            pass

    # ----- Process management -----
    def attach(self) -> bool:
        """Attach to game process. Return True if successful."""
        now = time.time()
        if now - self._last_attach_attempt < 0.5:
            return self.attached
        self._last_attach_attempt = now
        # Simulation path attaches without process handle
        self.attached = self.simulate or self.attached
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
        if not self.simulate and self.attached and hasattr(self, '_pm') and self._pm is not None:
            # Fast path: read from cached stats address if available
            if self._boss_stats_addr:
                cur = self._read_int(self._boss_stats_addr)
                mxx = self._read_int(self._boss_stats_addr + 4)
                if cur is not None and mxx is not None and mxx > 0:
                    self._boss_hp = max(0.0, min(1.0, float(cur) / float(mxx)))
                    return self._boss_hp
            # Resolve target once (or retry after cooldown)
            now = time.time()
            if (now - self._boss_last_resolve) < self._boss_resolve_retry_sec:
                return float(self._boss_hp)
            self._boss_last_resolve = now
            self._resolve_boss_stats_address()
            # Try immediate read after resolve
            if self._boss_stats_addr:
                cur = self._read_int(self._boss_stats_addr)
                mxx = self._read_int(self._boss_stats_addr + 4)
                if cur is not None and mxx is not None and mxx > 0:
                    self._boss_hp = max(0.0, min(1.0, float(cur) / float(mxx)))
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
        # Capture boss Param ID for this arena (used for cached selection)
        meta_entry = self._arena_meta_db.get(int(arena_id))
        self._boss_param_id = None
        if meta_entry and isinstance(meta_entry.get('boss'), dict):
            try:
                self._boss_param_id = int(meta_entry['boss'].get('char_param_id'))
            except Exception:
                self._boss_param_id = None
        self._boss_stats_addr = 0
        self._boss_comp_addr = 0
        self._boss_transform_addr = 0
        self._boss_last_resolve = 0.0
        self._t_reset = time.time()

    # ----- Helpers -----
    def _read_qword(self, addr: int) -> Optional[int]:
        if self._pm:
            try:
                return self._pm.read_longlong(addr)  # type: ignore[attr-defined]
            except Exception:
                return None
        return None

    def _read_int(self, addr: int) -> Optional[int]:
        if self._pm:
            try:
                return self._pm.read_int(addr)  # type: ignore[attr-defined]
            except Exception:
                return None
        return None

    def _read_float(self, addr: int) -> Optional[float]:
        if self._pm:
            try:
                return self._pm.read_float(addr)  # type: ignore[attr-defined]
            except Exception:
                return None
        return None

    def _resolve_base_ptr(self, name: str) -> Optional[int]:
        if self._pm is None:
            return None
        offset = self._bases_static.get(name)
        if offset is None:
            return None
        try:
            # Assumes single-level pointer from game base
            base_address = self._pm.base_address  # type: ignore[attr-defined]
            return self._read_qword(base_address + offset)
        except Exception:
            return None

    def _resolve_boss_stats_address(self) -> None:
        """Find and cache the boss stats qword address by Param ID. No-op if not found."""
        self._boss_stats_addr = 0
        self._boss_comp_addr = 0
        self._boss_transform_addr = 0
        if self._pm is None:
            return
        # Determine target Param ID (from cached meta)
        target_param_id = self._boss_param_id
        # If none set, try first arena or skip
        if target_param_id is None:
            return
        wcm_ptr = self._resolve_base_ptr('WorldChrMan')
        if wcm_ptr is None:
            return
        begin_off = self._wcm_offsets.get('character_list_begin_off', 0x1F1B8)
        end_off = self._wcm_offsets.get('character_list_end_off', 0x1F1C0)
        begin = self._read_qword(wcm_ptr + begin_off)
        end = self._read_qword(wcm_ptr + end_off)
        if not (begin and end and end > begin):
            return
        p = begin
        comp_off = self._char_offsets.get('comp_190_off', 0x190)
        stats_off = self._char_offsets.get('stats_qword_off', 0x138)
        tr_off = self._char_offsets.get('transform_68_off', 0x68)
        while p < end:
            ent = self._read_qword(p)
            p += 8
            if ent is None or ent < 0x10000:
                continue
            pid = self._read_int(ent + 0x60)
            if int(pid) != int(target_param_id):
                continue
            comp = self._read_qword(ent + comp_off)
            if not comp:
                continue
            stats = self._read_qword(comp + stats_off)
            if stats:
                self._boss_stats_addr = int(stats)
                self._boss_comp_addr = int(comp)
                self._boss_transform_addr = self._read_qword(self._boss_comp_addr + tr_off)
                return

    # ----- Additional reads -----
    def read_boss_position(self) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        if self.simulate:
            return None, None, None
        if self._pm is None:
            return None, None, None
        if not self._boss_transform_addr:
            self._resolve_boss_stats_address()
        addr = self._boss_transform_addr
        if not addr:
            return None, None, None
        x = self._read_float(addr + 0x70)
        y = self._read_float(addr + 0x74)
        z = self._read_float(addr + 0x78)
        if x is None or y is None or z is None:
            return None, None, None
        return float(x), float(y), float(z)

    def read_distance_to_boss(self) -> Optional[float]:
        px, py, pz = self.read_player_position()
        bx, by, bz = self.read_boss_position()
        if None in (px, py, pz, bx, by, bz):
            return None
        try:
            dx = float(px) - float(bx)
            dy = float(py) - float(by)
            dz = float(pz) - float(bz)
            import math
            return float(math.sqrt(dx * dx + dy * dy + dz * dz))
        except Exception:
            return None

    # ----- Test helpers (optional) -----
    def simulate_damage(self, player_delta: Optional[float] = None, boss_delta: Optional[float] = None) -> None:
        if player_delta is not None:
            self._player_hp = max(0.0, min(1.0, self._player_hp + float(player_delta)))
        if boss_delta is not None:
            self._boss_hp = max(0.0, min(1.0, self._boss_hp + float(boss_delta)))


