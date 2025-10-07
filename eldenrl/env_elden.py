import logging
import os
import time
from typing import Any, Dict, Optional, Tuple

import cv2
import gymnasium as gym
import mss
import numpy as np
import yaml
from gymnasium import spaces

from eldenrl.game import EldenRingGame
from eldenrl.input import InputController

logger = logging.getLogger(__name__)

VISION_WIDTH = 160
VISION_HEIGHT = 90
ACTION_HOLD_S = 0.1
TELEPORT_SETTLE_S = 2.0
DEAD_HP_FRACTION = 0.01

BOSS_DAMAGE_SCALE = 150.0
PLAYER_DAMAGE_SCALE = 100.0
TIME_ALIVE_SCALE = 0.1
WIN_BONUS = 200.0
LOSE_PENALTY = -100.0


class EldenEnv(gym.Env):

    metadata = {"render_modes": []}

    def __init__(self, env_config: Dict[str, Any], config_dir: str = "config"):
        super().__init__()

        self.arena_id = env_config.get("BOSS", 1)
        self.training_mode = env_config.get("TRAINING_MODE", "standard")
        self.monitor_index = env_config.get("MONITOR", 1)

        actions_path = os.path.join(config_dir, "actions.yaml")
        with open(actions_path, "r", encoding="utf-8") as handle:
            self.actions_config = (yaml.safe_load(handle) or {})["actions"]

        self.game = EldenRingGame(
            process_name=env_config.get("PROCESS_NAME", "eldenring.exe"),
            arenas_path=os.path.join(config_dir, "arenas.yaml"),
        )
        self.input_controller = InputController(
            enabled=not env_config.get("DISABLE_INPUT", False),
            actions_config_path=actions_path,
        )
        self.sct = mss.mss()

        self.arena_config = self.game.arenas.get(self.arena_id)
        if not self.arena_config:
            raise ValueError(f"arena {self.arena_id} not found in arenas.yaml")

        self.action_space = spaces.Discrete(len(self.actions_config))
        self.observation_space = spaces.Dict({
            "vision": spaces.Box(low=0, high=255,
                                 shape=(VISION_HEIGHT, VISION_WIDTH, 3), dtype=np.uint8),
            "data": spaces.Box(low=0.0, high=1.0, shape=(2,), dtype=np.float32),
        })

        self.total_steps = 0
        self.episode_start_time = time.time()
        self.last_info: Dict[str, Any] = {}
        self.last_player_hp = 1.0
        self.last_boss_hp = 1.0
        self.last_distance = 0.0

    def _boss_param_id(self) -> int:
        raw = str(self.arena_config.get("boss", {}).get("char_param_id", ""))
        return int(raw.split(":")[0])

    def _get_observation(self) -> Optional[Dict[str, np.ndarray]]:
        frame = np.array(self.sct.grab(self.sct.monitors[self.monitor_index]))
        vision = cv2.cvtColor(cv2.resize(frame, (VISION_WIDTH, VISION_HEIGHT)),
                              cv2.COLOR_BGRA2RGB)

        player_stats = self.game.get_player_stats()
        boss_hp = self.game.get_boss_hp()
        if not player_stats or not boss_hp:
            return None

        data = np.array([
            player_stats["hp"] / max(1, player_stats["max_hp"]),
            boss_hp[0] / max(1, boss_hp[1]),
        ], dtype=np.float32)

        return {"vision": vision, "data": data}

    def reset(self, seed: Optional[int] = None,
              options: Optional[Dict[str, Any]] = None) -> Tuple[Any, Dict[str, Any]]:
        super().reset(seed=seed)

        logger.info("waiting for cutscene or death transition to finish")
        while True:
            stats = self.game.get_player_stats()
            if stats and stats["hp"] > 0 and not self.game.is_in_cutscene():
                break
            time.sleep(0.5)

        if not self.game.teleport_to_arena(self.arena_id):
            return self.observation_space.sample(), {"error": "teleport_failed"}
        time.sleep(TELEPORT_SETTLE_S)

        if not self.game.find_boss_entity(self._boss_param_id()):
            return self.observation_space.sample(), {"error": "boss_not_found"}

        self.input_controller.lock_on()
        time.sleep(0.5)

        self.episode_start_time = time.time()
        obs = self._get_observation()
        if obs is None:
            return self.observation_space.sample(), {"error": "observation_failed"}

        self.last_player_hp, self.last_boss_hp = obs["data"]
        return obs, {}

    def _distance_reward(self, distance: float) -> float:
        if self.training_mode == "aggressive":
            return -0.66 * min(distance, 15) + 8
        if self.training_mode == "defensive":
            return 0.5 * min(distance, 20) - 8
        return 0.0

    def step(self, action: int) -> Tuple[Any, float, bool, bool, Dict[str, Any]]:
        self.total_steps += 1
        self.input_controller.take_action(action)
        time.sleep(ACTION_HOLD_S)

        obs = self._get_observation()
        if obs is None:
            return self.observation_space.sample(), 0.0, False, False, self.last_info

        player_hp, boss_hp = obs["data"]
        distance = self.game.get_distance_to_boss() or self.last_distance

        rewards = {
            "boss_damage": (self.last_boss_hp - boss_hp) * BOSS_DAMAGE_SCALE,
            "hp_penalty": (player_hp - self.last_player_hp) * PLAYER_DAMAGE_SCALE,
            "distance": self._distance_reward(distance),
            "time_alive": 0.0,
            "win_bonus": 0.0,
            "lose_penalty": 0.0,
        }

        self.last_player_hp, self.last_boss_hp, self.last_distance = player_hp, boss_hp, distance

        terminated = False
        if player_hp <= DEAD_HP_FRACTION:
            rewards["lose_penalty"] = LOSE_PENALTY
            terminated = True
        if boss_hp <= DEAD_HP_FRACTION:
            rewards["win_bonus"] = WIN_BONUS
            terminated = True

        if terminated:
            rewards["time_alive"] = (time.time() - self.episode_start_time) * TIME_ALIVE_SCALE

        self.last_info = {"reward_breakdown": rewards}
        return obs, sum(rewards.values()), terminated, False, self.last_info

    def close(self) -> None:
        self.input_controller.release_all()
        self.game.close()
