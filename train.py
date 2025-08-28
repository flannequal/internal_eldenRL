import os
import logging
import sys
import yaml
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback

from elden_env import EldenEnv

class TensorboardCallback(BaseCallback):
    """
    A custom callback to log reward components to TensorBoard.
    """
    def _on_step(self) -> bool:
        # Check if the environment has logged reward components
        if 'reward_breakdown' in self.training_env.get_attr('last_info')[0]:
            rewards = self.training_env.get_attr('last_info')[0]['reward_breakdown']
            for key, value in rewards.items():
                self.logger.record(f'rewards/{key}', value)
        return True

def train(config: dict):
    """
    Main training function with TensorBoard integration.
    """
    logging.info("Initializing training environment...")

    try:
        env = EldenEnv(config)
        if not env.game:
            raise RuntimeError("EldenEnv could not attach to the game.")
        logging.info("EldenEnv initialized successfully.")
    except Exception as e:
        logging.error(f"Failed to create Elden Ring environment: {e}")
        sys.exit(1)

    arena_id = config.get('BOSS', 1)
    model_name = f"PPO-Arena-{arena_id}"
    models_dir = f"models/{model_name}/"
    logdir = f"logs/{model_name}/"
    model_path = f"{models_dir}/model.zip"

    os.makedirs(models_dir, exist_ok=True)
    os.makedirs(logdir, exist_ok=True)

    # --- Use MultiInputPolicy for vision + data ---
    if os.path.exists(model_path):
        logging.info(f"Loading existing model from {model_path}...")
        model = PPO.load(model_path, env=env)
    else:
        logging.info("Creating a new PPO model with MultiInputPolicy...")
        model = PPO('MultiInputPolicy',
                    env,
                    tensorboard_log=logdir,
                    n_steps=2048,
                    verbose=1,
                    device='cuda')

    timesteps_per_iteration = config.get("TIMESTEPS_PER_ITERATION", 10000)
    try:
        print("\n" + "="*50)
        logging.info("Starting training loop...")
        logging.info(f"To view progress, run: tensorboard --logdir {logdir}")
        logging.info("Press CTRL+C to interrupt training and save the model.")
        print("="*50 + "\n")
        
        callback = TensorboardCallback()
        while True:
            model.learn(total_timesteps=timesteps_per_iteration,
                        reset_num_timesteps=False, 
                        tb_log_name="PPO",
                        callback=callback)
            model.save(model_path)
            logging.info(f"\nModel updated and saved to {model_path}")
    except KeyboardInterrupt:
        logging.info("\nTraining interrupted by user.")
    except Exception as e:
        logging.error(f"\nAn error occurred during training: {e}", exc_info=True)
    finally:
        model.save(model_path)
        logging.info(f"Final model saved to {model_path}")
        env.close()
        logging.info("Environment closed. Training finished.")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    config_path = os.path.join('config', 'app.yaml')
    try:
        with open(config_path, 'r') as f:
            app_config = yaml.safe_load(f)
    except FileNotFoundError:
        logging.error(f"Config file not found at {config_path}. Please create it.")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Error loading config file: {e}")
        sys.exit(1)

    train(app_config)
