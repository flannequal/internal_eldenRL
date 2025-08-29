import os
import logging
import sys
import time
import yaml
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback

from elden_env import EldenEnv
from live_stats import LiveStatsDisplay

class ComprehensiveCallback(BaseCallback):
    """
    A custom callback that handles:
    - Per-episode TensorBoard logging.
    - Periodic CLI stats updates.
    """
    def __init__(self, display_manager: LiveStatsDisplay, save_vision_flag: bool, verbose: int = 0):
        super(ComprehensiveCallback, self).__init__(verbose)
        self.display_manager = display_manager
        self.save_vision = save_vision_flag
        self.episode_num = 0
        self.last_print_time = 0
        self.fps = 0
        self.last_time = time.time()
        self.last_steps = 0

    def _on_step(self) -> bool:
        # Check for episode termination
        if self.locals['dones'][0]:
            self.episode_num += 1

        # Log reward components to TensorBoard with an episode prefix
        if 'reward_breakdown' in self.training_env.get_attr('last_info')[0]:
            rewards = self.training_env.get_attr('last_info')[0]['reward_breakdown']
            for key, value in rewards.items():
                self.logger.record(f'ep_{self.episode_num}/{key}', value)

            # Also log the standard rollout/ep_rew_mean for overall tracking
            if 'ep_rew_mean' in self.locals['infos'][0]:
                 self.logger.record('rollout/ep_rew_mean', self.locals['infos'][0]['ep_rew_mean'])

            self.logger.dump(step=self.num_timesteps)

        # Update the CLI display periodically (e.g., every 2 seconds)
        current_time = time.time()
        if current_time - self.last_print_time > 2.0:
            steps_delta = self.num_timesteps - self.last_steps
            time_delta = current_time - self.last_time
            if time_delta > 0:
                self.fps = steps_delta / time_delta

            self.last_time = current_time
            self.last_steps = self.num_timesteps

            env = self.training_env.envs[0].env
            self.display_manager.print_update(env, self.fps, self.save_vision)
            self.last_print_time = current_time

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
        logging.error(f"Failed to create Elden Ring environment: {e}", exc_info=True)
        sys.exit(1)

    arena_id = config.get('BOSS', 1)
    model_name = f"PPO-Arena-{arena_id}"
    run_id = int(time.time())
    models_dir = f"models/{model_name}/"
    logdir = f"logs/{model_name}/{run_id}/"
    model_path = f"{models_dir}/model.zip"

    os.makedirs(models_dir, exist_ok=True)
    os.makedirs(logdir, exist_ok=True)

    if os.path.exists(model_path):
        logging.info(f"Found existing model at {model_path}. Deleting to ensure MultiInputPolicy is used.")
        os.remove(model_path)

    logging.info("Creating a new PPO model with MultiInputPolicy...")
    model = PPO('MultiInputPolicy',
                env,
                tensorboard_log=logdir,
                n_steps=2048,
                verbose=1,
                device='cuda')

    timesteps_per_iteration = config.get("TIMESTEPS_PER_ITERATION", 100000)
    try:
        print("\n" + "="*50)
        logging.info("Starting training loop...")
        logging.info(f"To view progress, run: tensorboard --logdir {logdir}")
        logging.info("Press CTRL+C to interrupt training and save the model.")
        print("="*50 + "\n")
        
        display_manager = LiveStatsDisplay(env)
        save_vision = config.get("DEBUG_SAVE_VISION_FEED", False)
        callback = ComprehensiveCallback(display_manager, save_vision)

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
        if 'model' in locals() and model_path:
            model.save(model_path)
            logging.info(f"Final model saved to {model_path}")
        if 'env' in locals():
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
