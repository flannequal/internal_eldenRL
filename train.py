from stable_baselines3 import PPO
import os
import logging
import sys


logger = logging.getLogger()
logger.setLevel(logging.INFO)

for handler in logger.handlers[:]:
    logger.removeHandler(handler)

handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)


def train(CREATE_NEW_MODEL, config):
    logging.info("Initializing training environment...")

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
        logging.info("EldenHybridEnv initialized.")
    except ImportError:
        logging.error(
            "Failed to import EldenHybridEnv. Make sure the file exists and is in the correct path.")
        sys.exit(1)  # Exit if env cannot be imported
    except RuntimeError as e:
        logging.error(f"Failed to initialize EldenHybridEnv: {e}")
        sys.exit(1)  # Exit if env initialization fails due to memory issues
    except Exception as e:
        logging.error(
            f"An unexpected error occurred during EldenHybridEnv initialization: {e}")
        sys.exit(1)

    if CREATE_NEW_MODEL or not os.path.exists(model_path):
        model = PPO('MultiInputPolicy',
                    env,
                    tensorboard_log=logdir,
                    n_steps=HORIZON_WINDOW,
                    verbose=1,
                    device='cuda')
        logging.info("New PPO Model created...")
    else:
        try:
            model = PPO.load(model_path, env=env)
            logging.info(f"Model loaded from {model_path}...")
        except Exception as e:
            logging.error(f"Error loading model from {model_path}: {e}")
            sys.exit(1)

    try:
        logging.info("Starting training loop...")
        while True:
            model.learn(total_timesteps=TIMESTEPS,
                        reset_num_timesteps=False, tb_log_name="PPO")
            model.save(model_path)
            logging.info("Model updated and saved.")
    except KeyboardInterrupt:
        logging.info("Training interrupted by user. Saving model...")
        model.save(model_path)
        logging.info("Model saved. Exiting.")
    except Exception as e:
        logging.error(f"An error occurred during training: {e}")
        model.save(model_path)  # Attempt to save model on error
        logging.info("Model saved due to error. Exiting.")
    finally:
        env.close()
        logging.info("Environment closed. Training finished.")
