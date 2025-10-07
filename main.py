import logging
import os
import sys

import yaml

from eldenrl.train import train

CONFIG_PATH = os.path.join("config", "app.yaml")


def load_config(path: str = CONFIG_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-8s %(message)s")
    try:
        config = load_config()
    except FileNotFoundError:
        logging.error("config not found at %s", CONFIG_PATH)
        return 1

    try:
        train(config)
    except RuntimeError as exc:
        logging.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
