from stable_baselines3 import PPO
import os
import logging
import sys

# --- Robust Logging Setup ---
# Get the root logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Remove any existing handlers
for handler in logger.handlers[:]:
    logger.removeHandler(handler)

# Create a new handler and formatter
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)

# Add the new handler to the root logger
logger.addHandler(handler)
# --- End Logging Setup ---

def train(CREATE_NEW_MODEL, config):
    logging.info("Training will start soon. This can take a while to initialize...")

    TIMESTEPS = 10000
    HORIZON_WINDOW = 500

    model_name = f"PPO-{config.get('BOSS', 1)}"
    models_dir = f"models/{model_name}/"
    logdir = f"logs/{model_name}/"
    model_path = f"{models_dir}/model.zip"

    os.makedirs(models_dir, exist_ok=True)
    os.makedirs(logdir, exist_ok=True)
    logging.info("Folder structure created...")

    try:
        from EldenHybridEnv import EldenHybridEnv
        env = EldenHybridEnv(config)
        logging.info("EldenHybridEnv initialized...")
    except ImportError:
        logging.error("Failed to import EldenHybridEnv. Make sure the file exists and is in the correct path.")
        return
    except Exception as e:
        logging.error(f"Error initializing EldenHybridEnv: {e}")
        return

    if CREATE_NEW_MODEL or not os.path.exists(model_path):
        model = PPO('MultiInputPolicy',
                    env,
                    tensorboard_log=logdir,
                    n_steps=HORIZON_WINDOW,
                    verbose=1,
                    device='cuda')  # Changed to 'cuda' for clarity
        logging.info("New Model created...")
    else:
        try:
            model = PPO.load(model_path, env=env)
            logging.info("Model loaded...")
        except Exception as e:
            logging.error(f"Error loading model: {e}")
            return

    try:
        while True:
            model.learn(total_timesteps=TIMESTEPS, reset_num_timesteps=False, tb_log_name="PPO")
            model.save(model_path)
            logging.info("Model updated and saved.")
    except KeyboardInterrupt:
        logging.info("Training interrupted by user. Saving model...")
        model.save(model_path)
        logging.info("Model saved. Exiting.")
    finally:
        env.close()
