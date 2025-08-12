import argparse
import os
import sys
import time
from typing import Any, Dict

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from MemoryClient import MemoryClient  # noqa: E402
from EldenMemoryEnv import EldenMemoryEnv  # noqa: E402


def cmd_validate(config_path: str) -> int:
    """Validate the arenas YAML file structure."""
    client = MemoryClient(memory_config_path=config_path, simulate=True)
    # Internal DB is private; rely on side effects of loader
    if not os.path.isfile(config_path):
        print(f"❌ Config file not found: {config_path}")
        return 1
    try:
        import yaml  # type: ignore
    except Exception:
        print("❌ PyYAML not installed. Install with: pip install pyyaml")
        return 1

    with open(config_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}

    errors = []
    if not isinstance(data, dict):
        errors.append("Top-level YAML must be a mapping (dict)")
    if data.get('version') is None:
        errors.append("Missing 'version'")
    arenas = data.get('arenas') or []
    if not isinstance(arenas, list) or not arenas:
        errors.append("'arenas' must be a non-empty list")
    else:
        for idx, arena in enumerate(arenas):
            prefix = f"arena[{idx}]"
            try:
                _validate_arena(arena, prefix, errors)
            except Exception as exc:
                errors.append(f"{prefix}: exception during validation: {exc}")

    if errors:
        print("❌ Validation failed:")
        for e in errors:
            print(f"  - {e}")
        return 2

    print("✅ Validation passed")
    return 0


def _validate_arena(arena: Dict[str, Any], prefix: str, errors: list) -> None:
    required_root = ['id', 'name', 'player_spawn', 'player', 'boss', 'flags', 'second_phase']
    for key in required_root:
        if key not in arena:
            errors.append(f"{prefix}: missing '{key}'")

    spawn = arena.get('player_spawn') or {}
    for k in ['x', 'y', 'z', 'rot']:
        if k not in spawn:
            errors.append(f"{prefix}.player_spawn: missing '{k}'")

    # Memory addresses may be null at this stage; presence of keys is required
    for sect in ['player', 'boss', 'flags', 'second_phase']:
        sect_val = arena.get(sect)
        if sect_val is None:
            errors.append(f"{prefix}: missing '{sect}' section")


def cmd_sim_loop(iterations: int, boss: int, fps: float) -> int:
    """Run a lightweight simulation loop without a running game."""
    config = {
        "GAME_MODE": "PVE",
        "BOSS": boss,
        "BOSS_HAS_SECOND_PHASE": False,
        "DESIRED_FPS": fps,
        "PROCESS_NAME": "eldenring.exe",
        "SIMULATE_MEMORY": True,
        "MEMORY_CONFIG_PATH": os.path.join("config", "memory_arenas.sample.yaml"),
    }
    env = EldenMemoryEnv(config)
    obs, info = env.reset()
    total_r = 0.0
    for i in range(iterations):
        action = env.action_space.sample()
        obs, reward, terminated, truncated, info = env.step(action)
        total_r += float(reward)
        if terminated or truncated:
            obs, info = env.reset()
        time.sleep(0.0)
    env.close()
    print(f"✅ Simulated {iterations} steps. Total reward: {round(total_r, 2)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="eldenrl-tools", description="CLI for validation and simulation")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_val = sub.add_parser("validate", help="Validate arenas YAML structure")
    p_val.add_argument("config_path", type=str, help="Path to arenas YAML")

    p_sim = sub.add_parser("sim_loop", help="Run a simulation loop (no game required)")
    p_sim.add_argument("iterations", type=int, help="Number of steps to simulate")
    p_sim.add_argument("--boss", type=int, default=8, help="Boss/arena id to use (default: 8)")
    p_sim.add_argument("--fps", type=float, default=24.0, help="Target steps per second")

    args = parser.parse_args()
    if args.cmd == "validate":
        return cmd_validate(args.config_path)
    if args.cmd == "sim_loop":
        return cmd_sim_loop(args.iterations, args.boss, args.fps)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())


