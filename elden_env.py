import logging
import time
import os
import yaml
from typing import Any, Dict, Optional, Tuple

import gymnasium as gym
from gymnasium import spaces
import numpy as np
import mss
import cv2

from elden_game import EldenRingGame
from input_controller import InputController

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

        except RuntimeError as e:
            logging.error(f"Could not initialize Elden Ring environment: {e}")
            self.game = None
            return
            
        self.arena_id = env_config.get("BOSS", 1)
        self.training_mode = env_config.get("TRAINING_MODE", "standard")
        self.arena_config = self.game.arenas.get(self.arena_id)
        if not self.arena_config:
            raise ValueError(f"Arena ID {self.arena_id} not found in arenas.yaml")

        with open(actions_path, 'r') as f:
            self.actions_config = yaml.safe_load(f)['actions']
            num_actions = len(self.actions_config)
        self.action_space = spaces.Discrete(num_actions)

        # --- Hybrid Observation Space (Vision + Data) ---
        self.observation_space = spaces.Dict({
            "vision": spaces.Box(low=0, high=255, shape=(90, 160, 3), dtype=np.uint8),
            "data": spaces.Box(low=0.0, high=1.0, shape=(2,), dtype=np.float32) # [player_hp, boss_hp]
        })
        
        self.last_player_hp = 1.0
        self.last_boss_hp = 1.0
        self.last_distance = 0.0

    def _get_observation(self) -> Optional[Dict[str, np.ndarray]]:
        if not self.game: return None

        # --- Capture Vision ---
        monitor = self.sct.monitors[1]
        sct_img = self.sct.grab(monitor)
        frame = np.array(sct_img)
        # Resize for the model (e.g., 160x90)
        vision_obs = cv2.resize(frame, (160, 90))
        vision_obs = cv2.cvtColor(vision_obs, cv2.COLOR_BGRA2RGB)

        # --- Capture Data ---
        player_stats = self.game.get_player_stats()
        boss_stats = self.game.get_boss_hp()
        
        if not player_stats or not boss_stats: return None

        player_hp_norm = player_stats.get('hp', 0) / max(1, player_stats.get('max_hp', 1))
        boss_hp_norm = boss_stats[0] / max(1, boss_stats[1])
        
        data_obs = np.array([player_hp_norm, boss_hp_norm], dtype=np.float32)

        return {"vision": vision_obs, "data": data_obs}

    def reset(self, seed: Optional[int] = None, options: Optional[Dict[str, Any]] = None) -> Tuple[Any, Dict[str, Any]]:
        super().reset(seed=seed)
        if not self.game:
            return self.observation_space.sample(), {}

        logging.info("Resetting... waiting for death state or cutscene to end.")
        player_hp = self.game.get_player_stats().get('hp', 0)
        while self.game.is_in_cutscene() or player_hp <= 0:
            time.sleep(0.5)
            player_hp = self.game.get_player_stats().get('hp', 0)
        logging.info("Player is alive. Proceeding with teleport.")

        if not self.game.teleport_to_arena(self.arena_id):
            return self.observation_space.sample(), {"error": "teleport_failed"}
        
        time.sleep(2.0)
        
        boss_param_id_str = str(self.arena_config.get("boss", {}).get("char_param_id", ""))
        boss_param_id = int(boss_param_id_str.split(':')[0])
        if not self.game.find_boss_entity(boss_param_id):
             return self.observation_space.sample(), {"error": "boss_not_found"}

        logging.info("Attempting to lock on to boss...")
        self.input_controller.lock_on()
        time.sleep(0.5)

        self.episode_start_time = time.time()
        initial_obs = self._get_observation()
        if initial_obs is not None:
            self.last_player_hp = initial_obs["data"][0]
            self.last_boss_hp = initial_obs["data"][1]
        
        return initial_obs, {}

    def step(self, action: int) -> Tuple[Any, float, bool, bool, Dict[str, Any]]:
        if not self.game:
            return self.observation_space.sample(), 0.0, True, False, {}

        self.total_steps += 1
        action_name = self.actions_config.get(action, {}).get("name", "UNKNOWN")

        self.input_controller.take_action(action)
        time.sleep(0.1)

        obs = self._get_observation()
        if obs is None:
            return self.observation_space.sample(), 0.0, False, False, {}

        player_hp_norm = obs["data"][0]
        boss_hp_norm = obs["data"][1]
        distance = self.game.get_distance_to_boss() or self.last_distance
        
        # --- Continuous Reward Calculation ---
        reward_breakdown = {
            "boss_damage": (self.last_boss_hp - boss_hp_norm) * 150.0,
            "hp_penalty": (self.last_player_hp - player_hp_norm) * 100.0,
            "distance": 0.0,
            "time_alive": 0.0,
            "win_bonus": 0.0,
            "lose_penalty": 0.0
        }

        # Smooth distance reward
        if self.training_mode == 'aggressive':
            # Reward is highest at dist=0, lowest at dist=15. Range [-2, 8]
            reward_breakdown["distance"] = -0.66 * min(distance, 15) + 8
        elif self.training_mode == 'defensive':
            # Reward is highest at dist=20, lowest at dist=0. Range [-8, 2]
            reward_breakdown["distance"] = 0.5 * min(distance, 20) - 8

        self.last_player_hp = player_hp_norm
        self.last_boss_hp = boss_hp_norm
        self.last_distance = distance

        terminated = False
        if player_hp_norm <= 0.01:
            reward_breakdown["lose_penalty"] = -100.0
            terminated = True
        if boss_hp_norm <= 0.01:
            reward_breakdown["win_bonus"] = 200.0
            terminated = True
        
        if terminated:
            time_alive = time.time() - self.episode_start_time
            reward_breakdown["time_alive"] = max(0, time_alive * 0.1) # 0.1 points per second survived

        total_reward = sum(reward_breakdown.values())
        self.last_info = {"reward_breakdown": reward_breakdown}

        return obs, total_reward, terminated, False, self.last_info

    def close(self):
        if self.input_controller: self.input_controller.release_all()
        if self.game: self.game.close()
