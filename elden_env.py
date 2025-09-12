import logging
import time
import os
import yaml
import math
from typing import Any, Dict, Optional, Tuple, Callable

import gymnasium as gym
from gymnasium import spaces
import numpy as np

from elden_game import EldenRingGame
from input_controller import InputController
from reward_calculator import RewardCalculator

class EldenEnv(gym.Env):
    """
    A hybrid vision/memory environment for Elden Ring.
    """
    metadata = {'render_modes': []}

    def __init__(self, env_config: Dict[str, Any]):
        super().__init__()
        
        self.total_steps = 0
        self.episode_start_time = time.time()
        self.last_info = {}
        self.last_observation = None
        
        try:
            arenas_path = os.path.join('config', 'arenas.yaml')
            actions_path = os.path.join('config', 'actions.yaml')
            
            self.game = EldenRingGame(config=env_config, arenas_path=arenas_path)
            self.input_controller = InputController(actions_config_path=actions_path)

            reward_schema = env_config.get("REWARD_SCHEMA", "standard")
            self.reward_calculator = RewardCalculator(reward_schema)

        except (RuntimeError, ValueError) as e:
            logging.error(f"Could not initialize Elden Ring environment: {e}")
            self.game = None
            return
            
        self.arena_id = env_config.get("BOSS", 1)
        self.arena_config = self.game.arenas.get(self.arena_id)
        if not self.arena_config:
            raise ValueError(f"Arena ID {self.arena_id} not found in arenas.yaml")

        with open(actions_path, 'r') as f:
            self.actions_config = yaml.safe_load(f)['actions']
            num_actions = len(self.actions_config)
        self.action_space = spaces.Discrete(num_actions)

        # Initialize action counter
        self.action_names = [v['name'] for v in self.actions_config.values()]
        self.action_counts = {name: 0 for name in self.action_names}

        # Observation space is now just player HP and boss HP
        self.observation_space = spaces.Box(low=0.0, high=1.0, shape=(3,), dtype=np.float32)
        
        self.last_player_hp = 1.0
        self.last_boss_hp = 1.0
        self.last_action_name = "N/A"

    def _wait_for_condition(self, condition_func: Callable[[], Any], expected_value: Any = True, timeout: float = 3.0, poll_interval: float = 0.1) -> bool:
        """
        Waits for a condition function to return an expected value or timeout.
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            value = condition_func()
            if value == expected_value:
                return True
            time.sleep(poll_interval)
        logging.warning(f"Timeout waiting for condition '{condition_func.__name__}' to be {expected_value}.")
        return False

    def _get_observation(self) -> Optional[np.ndarray]:
        if not self.game: return None

        player_stats = self.game.get_player_stats()
        boss_stats = self.game.get_boss_hp()
        distance = self.game.get_distance_to_boss()
        
        if not player_stats or not boss_stats or distance is None :
            return None

        player_hp_norm = player_stats.get('hp', 0) / max(1, player_stats.get('max_hp', 1))
        boss_hp_norm = boss_stats[0] / max(1, boss_stats[1])
        distance_norm = 1.0 - math.tanh(distance / 15.0)
        
        self.last_observation = np.array([player_hp_norm, boss_hp_norm, distance_norm], dtype=np.float32)
        return self.last_observation

    def reset(self, seed: Optional[int] = None, options: Optional[Dict[str, Any]] = None) -> Any:
        super().reset(seed=seed)
        if not self.game:
            return self.observation_space.sample(), {}

        logging.info("Resetting environment...")
        self.game.set_invisibility(True)
        self.game.set_player_animation_override(0)

        #player health and stats reset
        player_stats = self.game.get_player_stats()
        if player_stats:
            max_hp = player_stats.get('max_hp', 1000)
            self.game.set_player_hp(max_hp)

            # Wait for HP to be restored
            if not self._wait_for_condition(lambda: self.game.get_player_stats().get('hp'), max_hp):
                logging.error("Player HP failed to restore during reset.")
                #still continue as might be fixed after

        boss_stats = self.game.get_boss_hp()
        if boss_stats:
            self.game.set_boss_hp(boss_stats[1])

        # teleport to arena
        if not self.game.teleport_to_arena(self.arena_id):
            self.game.set_invisibility(False) # Make sure we are visible on failure
            return self.observation_space.sample(), {"error": "teleport_failed"}

        time.sleep(1.0)

        #re-align player facing angle and re-fetch boss
        angle_config = self.arena_config.get("player_spawn_angle", {})
        self.game.set_player_angle(angle_config.get('cos_z', 1.0), angle_config.get('sin_z', 0.0))

        boss_param_id = int(str(self.arena_config.get("boss", {}).get("char_param_id", "")).split(':')[0])
        if not self.game.find_boss_entity(boss_param_id):
            logging.error(f"Could not find boss with param ID {boss_param_id}.")
            self.game.set_invisibility(False)
            return self.observation_space.sample(), {"error": "boss_not_found"}
        time.sleep(0.1)

        # --- 4. Lock-on and Finalize ---
        logging.info("Attempting to lock on to boss...")
        self.input_controller.lock_on()
        time.sleep(0.5)

        self.game.set_player_animation_override(-1) # Release animation override
        self.game.set_invisibility(False) # Become visible again

        # --- 5. Final Observation ---
        self.episode_start_time = time.time()
        initial_obs = self._get_observation()
        if initial_obs is None:
            logging.error("Failed to get initial observation after reset.")
            return self.observation_space.sample(), {"error": "initial_obs_failed"}

        self.last_player_hp = initial_obs[0]
        self.last_boss_hp = initial_obs[1]
        self.action_counts = {name: 0 for name in self.action_names}
        
        logging.info("Environment reset successfully.")
        return initial_obs, {}


    def step(self, action: int) -> Tuple[Any, float, bool, bool, Dict[str, Any]]:
        if not self.game:
            return self.observation_space.sample(), 0.0, True, False, {}

        self.total_steps += 1
        #logging actions for convenience
        self.last_action_name = self.input_controller.take_action(action)
        if self.last_action_name in self.action_counts:
            self.action_counts[self.last_action_name] += 1
            
        #time.sleep(0.1)

        obs = self._get_observation()
        if obs is None:
            return self.observation_space.sample(), 0.0, False, False, {"error": "obs_failed"}

        player_hp_norm, boss_hp_norm, distance_norm  = obs
        
        terminated = (player_hp_norm <= 0.01)
        won = (boss_hp_norm <= 0.01)
        if won: terminated = True

        time_alive = time.time() - self.episode_start_time

        total_reward, reward_breakdown = self.reward_calculator.calculate_reward(
            self.last_player_hp, player_hp_norm,
            self.last_boss_hp, boss_hp_norm,
            time_alive, distance_norm, terminated, won
        )

        self.last_player_hp = player_hp_norm
        self.last_boss_hp = boss_hp_norm
        self.last_info = {"reward_breakdown": reward_breakdown}

        return obs, total_reward, terminated, False, self.last_info

    def close(self):
        if self.input_controller: self.input_controller.release_all()
        if self.game: self.game.close()
