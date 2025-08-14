import os
import train

try:
    import yaml  # type: ignore
except Exception:
    yaml = None

if __name__ == '__main__':
    # Centralized config: load from config/app.yaml (or sample), allow env var overrides
    env_config = {}
    cfg_path = os.environ.get('ELDENRL_APP_CONFIG', os.path.join('config', 'app.yaml'))
    if yaml is not None and os.path.isfile(cfg_path):
        with open(cfg_path, 'r', encoding='utf-8') as f:
            env_config = yaml.safe_load(f) or {}
    elif yaml is not None and os.path.isfile(os.path.join('config', 'app.sample.yaml')):
        with open(os.path.join('config', 'app.sample.yaml'), 'r', encoding='utf-8') as f:
            env_config = yaml.safe_load(f) or {}
    else:
        env_config = {
            "PROCESS_NAME": "eldenring.exe",
            # Removed GAME_MODE config, assuming PVE
            "BOSS": 8,
            "DESIRED_FPS": 24,
            "SIMULATE_MEMORY": False,
            "DISABLE_INPUT": False,
            "LOG_MEMORY_DEBUG": True,
            "MEMORY_DEBUG_INTERVAL": 1,
        }
    CREATE_NEW_MODEL = True
         #Create a new model or resume training for an existing model

    train.train(CREATE_NEW_MODEL, env_config)
