import os
import train
import logging

logging.basicConfig(level=logging.DEBUG,
                    format="%(levelname)s  - %(message)s",
                    force=True)  # force=True ensures reconfiguration in recent Python versions

# Also set the root logger and all existing handlers to DEBUG to be safe
root = logging.getLogger()
root.setLevel(logging.DEBUG)
for h in root.handlers:
    h.setLevel(logging.DEBUG)


try:
    import yaml
except Exception:
    yaml = None

if __name__ == '__main__':
    env_config = {}
    cfg_path = os.path.join('config', 'app.yaml') 
    if yaml is not None and os.path.isfile(cfg_path):
        with open(cfg_path, 'r', encoding='utf-8') as f:
            env_config = yaml.safe_load(f) or {}
    elif yaml is not None and os.path.isfile(os.path.join('config', 'app.sample.yaml')):
        with open(os.path.join('config', 'app.yaml'), 'r', encoding='utf-8') as f:
            env_config = yaml.safe_load(f) or {}
    else:
        env_config = {
            "PROCESS_NAME": "eldenring.exe",
            "BOSS": 8,
            "DESIRED_FPS": 24, #we should start using this, right now isnt used
            "DISABLE_INPUT": False,
            "DEBUG_SAVE_VISION_FEED": True,
        }
    train.train(env_config)
