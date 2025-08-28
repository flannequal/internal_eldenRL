import os
import yaml

def load_config(config_path: str = None):
    """
    Loads the YAML configuration for memory pointers, bases, and modules.
    """
    if config_path is None:
        config_path = os.path.join("config", "addresses.yaml")

    if not os.path.isfile(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    return cfg
