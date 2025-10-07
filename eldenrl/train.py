import logging
import os
from typing import Any, Dict

from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback

from eldenrl.env_elden import EldenEnv

logger = logging.getLogger(__name__)

DEFAULT_TIMESTEPS = 10000
N_STEPS = 2048


class RewardBreakdownCallback(BaseCallback):

    def _on_step(self) -> bool:
        info = self.training_env.get_attr("last_info")[0]
        for key, value in info.get("reward_breakdown", {}).items():
            self.logger.record(f"rewards/{key}", value)
        return True


def train(config: Dict[str, Any]) -> None:
    env = EldenEnv(config)

    model_name = f"PPO-Arena-{config.get('BOSS', 1)}"
    models_dir = os.path.join("models", model_name)
    log_dir = os.path.join("logs", model_name)
    model_path = os.path.join(models_dir, "model.zip")
    os.makedirs(models_dir, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)

    if os.path.exists(model_path):
        logger.info("resuming from %s", model_path)
        model = PPO.load(model_path, env=env)
    else:
        logger.info("creating new PPO model")
        model = PPO("MultiInputPolicy", env, tensorboard_log=log_dir,
                    n_steps=N_STEPS, verbose=1, device="cuda")

    timesteps = config.get("TIMESTEPS_PER_ITERATION", DEFAULT_TIMESTEPS)
    logger.info("training, follow along with: tensorboard --logdir %s", log_dir)
    logger.info("press ctrl-c to stop and save")

    try:
        while True:
            model.learn(total_timesteps=timesteps, reset_num_timesteps=False,
                        tb_log_name="PPO", callback=RewardBreakdownCallback())
            model.save(model_path)
            logger.info("saved %s", model_path)
    except KeyboardInterrupt:
        logger.info("interrupted by user")
    finally:
        model.save(model_path)
        env.close()
        logger.info("final model saved to %s", model_path)
