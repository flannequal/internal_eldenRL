import logging
import time
import os
import yaml
import math
from typing import Any, Dict, Optional, Tuple

import gymnasium as gym
from gymnasium import spaces
import numpy as np
import mss
import cv2

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
        
        try:
            arenas_path = os.path.join('config', 'arenas.yaml')
            actions_path = os.path.join('config', 'actions.yaml')
            
            self.game = EldenRingGame(arenas_path=arenas_path)
            self.input_controller = InputController(actions_config_path=actions_path)
            self.sct = mss.mss()

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

        self.observation_space = spaces.Dict({
            "vision": spaces.Box(low=0, high=255, shape=(90, 160, 3), dtype=np.uint8),
            "data": spaces.Box(low=0.0, high=1.0, shape=(2,), dtype=np.float32)
        })
        
        self.last_player_hp = 1.0
        self.last_boss_hp = 1.0
        self.last_distance = 0.0
        self.last_action_name = "N/A"
        self.last_observation = None

    def _get_observation(self) -> Optional[Dict[str, np.ndarray]]:
        if not self.game: return None

        monitor = self.sct.monitors[1]
        sct_img = self.sct.grab(monitor)
        frame = np.array(sct_img)
        vision_obs = cv2.resize(frame, (160, 90))
        vision_obs = cv2.cvtColor(vision_obs, cv2.COLOR_BGRA2RGB)

        player_stats = self.game.get_player_stats()
        boss_stats = self.game.get_boss_hp()
        
        if not player_stats or not boss_stats:
            return None

        player_hp_norm = player_stats.get('hp', 0) / max(1, player_stats.get('max_hp', 1))
        boss_hp_norm = boss_stats[0] / max(1, boss_stats[1])
        
        data_obs = np.array([player_hp_norm, boss_hp_norm], dtype=np.float32)

        self.last_observation = {"vision": vision_obs, "data": data_obs}
        return self.last_observation

    def reset(self, seed: Optional[int] = None, options: Optional[Dict[str, Any]] = None) -> Tuple[Any, Dict[str, Any]]:
        super().reset(seed=seed)
        if not self.game:
            return self.observation_space.sample(), {}

        logging.info("Resetting environment...")

        player_stats = self.game.get_player_stats()
        if player_stats and player_stats.get('hp', 0) <= 0:
            logging.info("Player is dead, performing instant reset.")
            self.game.set_invisibility(True)
            self.game.set_player_hp(player_stats.get('max_hp', 1000))

            boss_stats = self.game.get_boss_hp()
            if boss_stats: self.game.set_boss_hp(boss_stats[1])

            self.game.set_player_animation_override(0)
            time.sleep(0.1)

        if not self.game.teleport_to_arena(self.arena_id):
            return self.observation_space.sample(), {"error": "teleport_failed"}
        time.sleep(0.2)

        angle_config = self.arena_config.get("player_spawn_angle", {})
        cos_z = angle_config.get('cos_z', 1.0)
        sin_z = angle_config.get('sin_z', 0.0)
        self.game.set_player_angle(cos_z, sin_z)
        time.sleep(0.1)

        boss_param_id = int(str(self.arena_config.get("boss", {}).get("char_param_id", "")).split(':')[0])
        if not self.game.find_boss_entity(boss_param_id):
            return self.observation_space.sample(), {"error": "boss_not_found"}

        player_pos = self.game.get_player_position()
        if player_pos:
            new_boss_x = player_pos[0] - (sin_z * 5)
            new_boss_y = player_pos[1]
            new_boss_z = player_pos[2] + (cos_z * 5)
            self.game.set_boss_position(new_boss_x, new_boss_y, new_boss_z)

        time.sleep(0.3)

        logging.info("Attempting to lock on to boss...")
        self.input_controller.lock_on()
        time.sleep(0.5)

        self.game.set_player_animation_override(-1)
        self.game.set_invisibility(False)

        self.episode_start_time = time.time()
        initial_obs = self._get_observation()
        if initial_obs is None:
            return self.observation_space.sample(), {"error": "initial_obs_failed"}

        self.last_player_hp = initial_obs["data"][0]
        self.last_boss_hp = initial_obs["data"][1]
        
        return initial_obs, {}

    def step(self, action: int) -> Tuple[Any, float, bool, bool, Dict[str, Any]]:
        if not self.game:
            return self.observation_space.sample(), 0.0, True, False, {}

        self.total_steps += 1
        self.last_action_name = self.input_controller.take_action(action)
        time.sleep(0.1)

        obs = self._get_observation()
        if obs is None:
            return self.observation_space.sample(), 0.0, False, False, {"error": "obs_failed"}

        player_hp_norm, boss_hp_norm = obs["data"]
        distance = self.game.get_distance_to_boss() or self.last_distance
        
        terminated = (player_hp_norm <= 0.01)
        won = (boss_hp_norm <= 0.01)
        if won: terminated = True

        time_alive = time.time() - self.episode_start_time

        total_reward, reward_breakdown = self.reward_calculator.calculate_reward(
            self.last_player_hp, player_hp_norm,
            self.last_boss_hp, boss_hp_norm,
            distance, time_alive, terminated, won
        )

        self.last_player_hp = player_hp_norm
        self.last_boss_hp = boss_hp_norm
        self.last_distance = distance
        self.last_info = {"reward_breakdown": reward_breakdown}

        return obs, total_reward, terminated, False, self.last_info

    def close(self):
        if self.input_controller: self.input_controller.release_all()
        if self.game: self.game.close()
