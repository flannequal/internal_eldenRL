import time
from typing import Dict, Any

import cv2
import gymnasium as gym
import mss
import numpy as np
from gymnasium import spaces

from EldenRewardMemory import EldenRewardMemory
from InputController import InputController
from MemoryClient import MemoryClient


# Image/capture settings (match legacy env defaults)
N_CHANNELS = 3
IMG_WIDTH = 1920
IMG_HEIGHT = 1080
MODEL_WIDTH = int(800 / 2)
MODEL_HEIGHT = int(450 / 2)

N_ACTIONS_HISTORY = 10


class EldenHybridEnv(gym.Env):
    """Hybrid Gym environment: vision for spatial context + memory for exact game state.

    Observation space:
    - img: resized game frame, uint8
    - prev_actions: (10, num_actions, 1) one-hot history
    - state: (5,) float32 [player_hp, player_stamina, boss_hp, time_alive_s, arena_phase]

    Rewards/termination are computed from memory reads only (no CV-derived signals).
    Resets are instant via memory (teleport + health/stamina restore).
    """

    metadata = {"render_modes": ["human"], "render_fps": 30}

    def __init__(self, config: Dict[str, Any]):
        super().__init__()

        self.config = config
        self.GAME_MODE = config.get("GAME_MODE", "PVE")
        self.BOSS = int(config.get("BOSS", 1))
        self.BOSS_HAS_SECOND_PHASE = bool(config.get("BOSS_HAS_SECOND_PHASE", False))
        self.DESIRED_FPS = float(config.get("DESIRED_FPS", 24))

        # Discrete action space compatible with original env
        self.NUMBER_DISCRETE_ACTIONS = int(config.get("NUMBER_DISCRETE_ACTIONS", 22))
        self.action_space = spaces.Discrete(self.NUMBER_DISCRETE_ACTIONS)
        self.observation_space = spaces.Dict(
            {
                "img": spaces.Box(low=0, high=255, shape=(MODEL_HEIGHT, MODEL_WIDTH, N_CHANNELS), dtype=np.uint8),
                "prev_actions": spaces.Box(low=0, high=1, shape=(N_ACTIONS_HISTORY, self.NUMBER_DISCRETE_ACTIONS, 1), dtype=np.uint8),
                "state": spaces.Box(low=-np.inf, high=np.inf, shape=(5,), dtype=np.float32),
            }
        )

        # Systems
        self.sct = mss.mss()
        self.mem = MemoryClient(
            process_name=config.get("PROCESS_NAME", "eldenring.exe"),
            memory_config_path=config.get("MEMORY_CONFIG_PATH"),
        )
        self.rewardGen = EldenRewardMemory(config)
        self.input = InputController(enabled=not bool(config.get("DISABLE_INPUT", False)))

        # Runtime
        self.action_history: list[int] = []
        self.t_start = time.time()
        self.time_alive_ref = time.time()
        self.step_iteration = 0
        self.first_step = True
        self.curr_phase = 1.0

        # Attach early
        self.mem.attach()

        # Required for screenshot cropping
        self.MONITOR = int(config.get("MONITOR", 1))
        self.DEBUG_MODE = bool(config.get("DEBUG_MODE", False))

    # ----- Helpers -----
    def _one_hot_prev_actions(self):
        one_hot = np.zeros(
            shape=(N_ACTIONS_HISTORY, self.NUMBER_DISCRETE_ACTIONS, 1), dtype=np.uint8
        )
        for i in range(N_ACTIONS_HISTORY):
            if len(self.action_history) >= (i + 1):
                one_hot[i][self.action_history[-(i + 1)]][0] = 1
        return one_hot

    def _grab_screen_shot(self) -> np.ndarray:
        monitor = self.sct.monitors[self.MONITOR]
        sct_img = self.sct.grab(monitor)
        frame = cv2.cvtColor(np.asarray(sct_img), cv2.COLOR_BGRA2RGB)
        frame = frame[46 : IMG_HEIGHT + 46, 12 : IMG_WIDTH + 12]
        obs = cv2.resize(frame, (MODEL_WIDTH, MODEL_HEIGHT))
        if self.DEBUG_MODE:
            cv2.imshow("debug-render", obs)
            cv2.waitKey(1)
        return obs

    def _read_state(self):
        hp = self.mem.read_player_hp()
        stam = self.mem.read_player_stamina()
        boss_hp = self.mem.read_boss_hp() if self.GAME_MODE == "PVE" else 1.0
        time_alive = max(0.0, time.time() - self.time_alive_ref)
        return float(hp), float(stam), float(boss_hp), float(time_alive), float(self.curr_phase)

    # ----- Gym API -----
    def step(self, action: int):
        t0 = time.time()

        # Read memory state and compute reward for previous transition
        hp, stam, boss_hp, time_alive, phase = self._read_state()
        reward, death, boss_death, duel_won = self.rewardGen.update(
            hp, stam, boss_hp, self.first_step
        )

        terminated = bool(death or boss_death or duel_won)
        truncated = bool((time.time() - self.t_start) > 600)

        if not (terminated or truncated):
            self.input.take_action(int(action))

        # Compose observation
        obs = {
            "img": self._grab_screen_shot(),
            "prev_actions": self._one_hot_prev_actions(),
            "state": np.asarray([hp, stam, boss_hp, time_alive, phase], dtype=np.float32),
        }

        # Book-keeping
        self.first_step = False
        self.step_iteration += 1
        self.action_history.append(int(action))

        # FPS limiter
        dt = time.time() - t0
        min_step = 1.0 / max(1.0, self.DESIRED_FPS)
        if dt < min_step:
            time.sleep(min_step - dt)

        return obs, float(reward), terminated, truncated, {}

    def reset(self, *, seed: int | None = None, options: Dict[str, Any] | None = None):
        super().reset(seed=seed)
        if not self.mem.attached:
            self.mem.attach()

        # Memory-based instant reset
        self.mem.reset_arena(self.BOSS, second_phase=False)
        self.time_alive_ref = time.time()
        self.curr_phase = 1.0

        # Reset trackers
        self.step_iteration = 0
        self.action_history = []
        self.first_step = True
        self.t_start = time.time()

        hp, stam, boss_hp, time_alive, phase = self._read_state()
        obs = {
            "img": self._grab_screen_shot(),
            "prev_actions": self._one_hot_prev_actions(),
            "state": np.asarray([hp, stam, boss_hp, time_alive, phase], dtype=np.float32),
        }
        return obs, {}

    def render(self):
        pass

    def close(self):
        self.mem.detach()


