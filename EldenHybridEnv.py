import logging
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
    - state: (6,) float32 [player_hp, player_stamina, boss_hp, time_alive_s, arena_phase, dist_to_boss]

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
        self.LOG_MEMORY_DEBUG = bool(config.get("LOG_MEMORY_DEBUG", False))
        self.MEMORY_DEBUG_INTERVAL = int(config.get("MEMORY_DEBUG_INTERVAL", 1))
        self.MONITOR = int(config.get("MONITOR", 1))
        self.DEBUG_MODE = bool(config.get("DEBUG_MODE", False))

        # For debug overlay
        self.font = cv2.FONT_HERSHEY_SIMPLEX
        self.font_scale = 0.5
        self.font_color = (255, 255, 255)
        self.line_type = 2

        self.NUMBER_DISCRETE_ACTIONS = int(config.get("NUMBER_DISCRETE_ACTIONS", 22))
        self.action_space = spaces.Discrete(self.NUMBER_DISCRETE_ACTIONS)
        self.observation_space = spaces.Dict(
            {
                "img": spaces.Box(low=0, high=255, shape=(MODEL_HEIGHT, MODEL_WIDTH, N_CHANNELS), dtype=np.uint8),
                "prev_actions": spaces.Box(low=0, high=1, shape=(N_ACTIONS_HISTORY, self.NUMBER_DISCRETE_ACTIONS, 1), dtype=np.uint8),
                "state": spaces.Box(low=-np.inf, high=np.inf, shape=(6,), dtype=np.float32),
            }
        )

        # Systems
        self.sct = mss.mss()
        logging.info("Initializing MemoryClient...")
        self.mem = MemoryClient(
            process_name=config.get("PROCESS_NAME", "eldenring.exe")
        )
        
        # Attempt to attach and resolve essential addresses immediately
        if not self.mem.attach():
            logging.error("Failed to attach to Elden Ring process or resolve essential memory addresses. Please ensure the game is running and the configuration is correct.")
            raise RuntimeError("Failed to initialize MemoryClient.")
        logging.info("MemoryClient initialized and attached.")

        self.rewardGen = EldenRewardMemory(config)
        self.input = InputController(enabled=not bool(config.get("DISABLE_INPUT", False)))

        # Runtime
        self.action_history: list[int] = []
        self.t_start = time.time()
        self.time_alive_ref = time.time()
        self.step_iteration = 0
        self.first_step = True
        self.curr_phase = 1.0

        # Check if essential memory addresses are resolved after attachment
        if not self._check_essential_addresses():
            raise RuntimeError("Essential memory addresses could not be resolved. Cannot proceed.")

    def _check_essential_addresses(self) -> bool:
        """Checks if critical memory addresses are resolved."""
        if not self.mem.attached:
            logging.error("MemoryClient is not attached.")
            return False
        
        # Check for addresses that are critical for basic operation
        critical_addresses = ["WorldChrMan", "CSLuaEventManager", "PlayerHP", "PlayerSP", "PlayerXYZA"]
        for addr_key in critical_addresses:
            if self.mem._resolve_pointer_path(addr_key) is None:
                logging.error(f"Critical address '{addr_key}' could not be resolved.")
                return False
        logging.info("All essential memory addresses resolved successfully.")
        return True

    # ----- Helpers -----
    def _one_hot_prev_actions(self):
        one_hot = np.zeros(
            shape=(N_ACTIONS_HISTORY, self.NUMBER_DISCRETE_ACTIONS, 1), dtype=np.uint8
        )
        for i in range(N_ACTIONS_HISTORY):
            if len(self.action_history) >= (i + 1):
                one_hot[i][self.action_history[-(i + 1)]][0] = 1
        return one_hot

    def _render_text_overlay(self, frame, hp, stam, boss_hp, dist):
        """Draws debug text on the frame."""
        cv2.putText(frame, f"Player HP: {hp:.2f}", (10, 20), self.font, self.font_scale, self.font_color, self.line_type)
        cv2.putText(frame, f"Stamina: {stam:.2f}", (10, 40), self.font, self.font_scale, self.font_color, self.line_type)
        cv2.putText(frame, f"Boss HP: {boss_hp:.2f}", (10, 60), self.font, self.font_scale, self.font_color, self.line_type)
        cv2.putText(frame, f"Distance: {dist:.2f}", (10, 80), self.font, self.font_scale, self.font_color, self.line_type)
        return frame

    def _grab_screen_shot(self, hp=1.0, stam=1.0, boss_hp=1.0, dist=0.0) -> np.ndarray:
        monitor = self.sct.monitors[self.MONITOR]
        sct_img = self.sct.grab(monitor)
        frame = cv2.cvtColor(np.asarray(sct_img), cv2.COLOR_BGRA2RGB)
        frame = frame[46 : IMG_HEIGHT + 46, 12 : IMG_WIDTH + 12]
        obs = cv2.resize(frame, (MODEL_WIDTH, MODEL_HEIGHT))
        if self.DEBUG_MODE:
            obs_with_overlay = self._render_text_overlay(obs.copy(), hp, stam, boss_hp, dist)
            cv2.imshow("debug-render", obs_with_overlay)
            cv2.waitKey(1)
        return obs

    def _read_state(self):
        hp = self.mem.read_player_hp()
        stam = self.mem.read_player_stamina()
        boss_hp = self.mem.read_boss_hp() if self.GAME_MODE == "PVE" else 1.0
        dist = self.mem.read_distance_to_boss() or 0.0
        time_alive = max(0.0, time.time() - self.time_alive_ref)
        return float(hp), float(stam), float(boss_hp), float(dist), float(time_alive), float(self.curr_phase)

    # ----- Gym API -----
    def step(self, action: int):
        t0 = time.time()

        # Read memory state and compute reward for previous transition
        hp, stam, boss_hp, dist, time_alive, phase = self._read_state()
        
        # Check if game state is valid before calculating reward/processing action
        if hp is None or stam is None or boss_hp is None:
            logging.error("Failed to read critical game state. Terminating episode.")
            # Return a terminal state with no reward
            return {
                "img": np.zeros((MODEL_HEIGHT, MODEL_WIDTH, N_CHANNELS), dtype=np.uint8),
                "prev_actions": np.zeros((N_ACTIONS_HISTORY, self.NUMBER_DISCRETE_ACTIONS, 1), dtype=np.uint8),
                "state": np.zeros(6, dtype=np.float32),
            }, 0.0, True, False, {}

        reward, death, boss_death, duel_won = self.rewardGen.update(
            hp, stam, boss_hp, self.first_step
        )

        # Optional debug logging for memory values
        if self.LOG_MEMORY_DEBUG and (self.step_iteration % max(1, self.MEMORY_DEBUG_INTERVAL) == 0):
            try:
                pos = self.mem.read_player_position()
                logging.info(
                    f"[MEM] step={self.step_iteration} hp={hp:.3f} stam={stam:.3f} boss_hp={boss_hp:.3f} "
                    f"pos=({pos[0]}, {pos[1]}, {pos[2]}) dist={dist:.3f} time_alive={time_alive:.2f}s"
                )
            except Exception:
                pos = (None, None, None)
                logging.info(
                    f"[MEM] step={self.step_iteration} hp={hp:.3f} stam={stam:.3f} boss_hp={boss_hp:.3f} "
                    f"pos=({pos[0]}, {pos[1]}, {pos[2]}) dist={dist:.3f} time_alive={time_alive:.2f}s"
                )

        terminated = bool(death or boss_death or duel_won)
        truncated = bool((time.time() - self.t_start) > 600)

        action_name = "UNKNOWN"
        if not (terminated or truncated):
            action_name = self.input.take_action(int(action))
        
        logging.info(f"Action: {action} -> {action_name} | Reward: {reward:.3f}")

        # Compose observation
        state_vec = [hp, stam, boss_hp, time_alive, phase, dist]
        obs = {
            "img": self._grab_screen_shot(hp, stam, boss_hp, dist),
            "prev_actions": self._one_hot_prev_actions(),
            "state": np.asarray(state_vec, dtype=np.float32),
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
        
        # Ensure MemoryClient is attached and essential addresses are resolved
        if not self.mem.attached or not self._check_essential_addresses():
            logging.error("MemoryClient not attached or essential addresses not resolved. Cannot reset.")
            # Return a default state to prevent further errors, but training should ideally stop.
            return {
                "img": np.zeros((MODEL_HEIGHT, MODEL_WIDTH, N_CHANNELS), dtype=np.uint8),
                "prev_actions": np.zeros((N_ACTIONS_HISTORY, self.NUMBER_DISCRETE_ACTIONS, 1), dtype=np.uint8),
                "state": np.zeros(6, dtype=np.float32),
            }, {}

        # Memory-based instant reset
        self.mem.reset_arena(self.BOSS, second_phase=False)
        
        # Give the game a moment to load after teleport
        logging.info("Waiting for game to load after teleport...")
        time.sleep(2.0) 

        # Attempt to get a valid state, failing fast if boss isn't loaded yet
        max_retries = 3 # Reduced retries as we want to fail fast
        for i in range(max_retries):
            hp, stam, boss_hp, dist, time_alive, phase = self._read_state()
            if boss_hp is not None and boss_hp < 1.0: # Check for valid boss HP
                logging.info(f"Successfully read initial boss HP: {boss_hp:.3f}. Proceeding with reset.")
                break
            logging.warning(f"Boss HP not yet resolved (is {boss_hp}). Retrying in 1s... ({i+1}/{max_retries})")
            time.sleep(1.0)
        else:
            logging.error("Failed to resolve boss HP after multiple retries. Reset may be unstable.")
            # Return a default state if boss HP is still not resolved
            return {
                "img": np.zeros((MODEL_HEIGHT, MODEL_WIDTH, N_CHANNELS), dtype=np.uint8),
                "prev_actions": np.zeros((N_ACTIONS_HISTORY, self.NUMBER_DISCRETE_ACTIONS, 1), dtype=np.uint8),
                "state": np.zeros(6, dtype=np.float32),
            }, {}

        self.time_alive_ref = time.time()
        self.curr_phase = 1.0

        # Reset trackers
        self.step_iteration = 0
        self.action_history = []
        self.first_step = True
        self.t_start = time.time()

        # Final state read
        hp, stam, boss_hp, dist, time_alive, phase = self._read_state()
        state_vec = [hp, stam, boss_hp, time_alive, phase, dist]
        obs = {
            "img": self._grab_screen_shot(hp, stam, boss_hp, dist),
            "prev_actions": self._one_hot_prev_actions(),
            "state": np.asarray(state_vec, dtype=np.float32),
        }
        return obs, {}

    def render(self):
        pass

    def close(self):
        self.mem.detach()
        cv2.destroyAllWindows()
