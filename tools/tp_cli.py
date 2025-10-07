import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eldenrl.memory_mngr import MemoryManager
from eldenrl.teleport import TeleportManager


def build_teleporter(process_name: str, config_dir: str) -> TeleportManager:
    mem = MemoryManager(process_name)
    if not mem.attach():
        raise SystemExit(f"could not attach to {process_name}")
    mem.load_addresses(os.path.join(config_dir, "addresses.yaml"))
    return TeleportManager(mem, os.path.join(config_dir, "locations.json"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Save and warp to named Elden Ring locations.")
    parser.add_argument("--process", default="eldenring.exe")
    parser.add_argument("--config-dir", default="config")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list saved locations")
    for name, help_text in (("save", "save the current position"),
                            ("go", "teleport to a saved position"),
                            ("delete", "remove a saved position")):
        sub.add_parser(name, help=help_text).add_argument("name")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
    teleporter = build_teleporter(args.process, args.config_dir)

    if args.command == "list":
        if not teleporter.locations:
            print("no saved locations")
        for name, loc in teleporter.locations.items():
            print(f"{name:<20} x={loc['x']:.2f} z={loc['z']:.2f} y={loc['y']:.2f}")
        return 0

    actions = {
        "save": teleporter.save_current_location,
        "go": teleporter.teleport_to_location,
        "delete": teleporter.delete_location,
    }
    return 0 if actions[args.command](args.name) else 1


if __name__ == "__main__":
    sys.exit(main())
