import logging
import time
from typing import Dict, Any, Optional

import cv2
import gymnasium as gym
import mss
import numpy as np
from gymnasium import spaces

from InputController import InputController
from EldenRingGame import EldenRingGame


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
                "state": spaces.Box(low=-np.inf, high=np.inf, shape=(7,), dtype=np.float32), # Increased from 6 to 7
            }
        )

        # Systems
        self.sct = mss.mss()
        logging.info("Initializing EldenRingGame...")
        self.game = EldenRingGame(
            process_name=config.get("PROCESS_NAME", "eldenring.exe"),
            config=config # Pass full config to EldenRingGame for its settings
        )
        logging.info("EldenRingGame initialized and attached.")

        self.input = InputController(enabled=not bool(config.get("DISABLE_INPUT", False)))

        # Reward system internal state (moved from EldenRewardMemory)
        self.prev_hp = float('nan')
        self.curr_hp = float('nan')
        self.curr_stam = float('nan')
        self.curr_boss_hp = float('nan')
        self.prev_boss_hp = float('nan')
        self.time_since_dmg_taken = time.time()
        self.time_since_boss_dmg = time.time()
        self.time_since_pvp_damaged = time.time()
        self.death = False
        self.boss_death = False
        self.game_won = False

        # Runtime
        self.action_history: list[int] = []
        self.t_start = time.time()
        self.time_alive_ref = time.time()
        self.step_iteration = 0
        self.first_step = True
        self.curr_phase = 1.0

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
        hp = self.game.player_hp
        stam = self.game.player_stamina
        boss_hp = self.game.boss_hp if self.GAME_MODE == "PVE" else 1.0
        dist = self.game.distance_to_boss or 0.0 # Use property directly
        time_alive = max(0.0, time.time() - self.time_alive_ref)
        time_since_boss_dmg = max(0.0, time.time() - self.time_since_boss_dmg) # How long since boss was last hit by player
        
        return float(hp if hp is not None else 0.0), \
               float(stam if stam is not None else 0.0), \
               float(boss_hp if boss_hp is not None else 1.0), \
               float(dist), \
               float(time_alive), \
               float(self.curr_phase), \
               float(time_since_boss_dmg)

    def _compute_reward_and_termination(self, curr_hp: float, curr_stam: float, curr_boss_hp: float, first_step: bool):
        """Compute reward using precise memory values.

        Returns (total_reward, death, boss_death, game_won)
        """
        # Update current values based on raw inputs
        self.curr_hp = max(0.0, min(1.0, float(curr_hp)))
        self.curr_stam = max(0.0, min(1.0, float(curr_stam)))
        self.curr_boss_hp = max(0.0, min(1.0, float(curr_boss_hp)))
        
        # Initialize timers/flags for the first step of an episode
        if first_step:
            self.time_since_dmg_taken = time.time() - 10 # Initialize to avoid early penalty for first few seconds
            self.time_since_boss_dmg = time.time() - 10 # Initialize for the same reason
            self.t_start = time.time() # Re-initialize episode start time

        self.death = self.curr_hp <= 0.01
        self.boss_death = (self.GAME_MODE == "PVE") and (self.curr_boss_hp <= 0.01)

        # 1) Player HP rewards
        hp_reward = 0
        if not self.death:
            if self.curr_hp > self.prev_hp + 1e-6: # Player healed
                hp_reward = 100
            elif self.curr_hp < self.prev_hp - 1e-6: # Player took damage
                hp_reward = -69
                self.time_since_dmg_taken = time.time()
        else:
            hp_reward = -420 # Large penalty for player death

        # Bonus for not taking damage for a period
        time_since_taken_dmg_reward = 25 if (time.time() - self.time_since_dmg_taken > 5) else 0

        # 2) Boss rewards (PVE only)
        boss_dmg_reward = 0
        progress_reward = 0
        no_hit_boss_penalty = 0

        if self.GAME_MODE == "PVE":
            if self.boss_death:
                boss_dmg_reward = 420 # Huge reward for defeating boss
            else:
                # Reward for damaging boss
                if self.curr_boss_hp < self.prev_boss_hp - 1e-6:
                    boss_dmg_reward = 100  # Reward for landing a hit
                    self.time_since_boss_dmg = time.time() # Reset timer since boss was hit

                # Penalty for not hitting the boss for too long (encourages aggression)
                time_since_last_hit = time.time() - self.time_since_boss_dmg
                no_hit_boss_penalty = - (time_since_last_hit * self.NO_BOSS_HIT_PENALTY_PER_SECOND)
                no_hit_boss_penalty = max(no_hit_boss_penalty, -200) # Cap the penalty

            # Encourage overall progress through the fight (proportional to HP lost)
            if self.curr_boss_hp < 0.98: # Check for *any* progress past initial full HP
                progress_reward = (1.0 - self.curr_boss_hp) * self.PROGRESS_REWARD_SCALE

        # 3) General time penalty (encourages efficient play and shorter episodes)
        time_alive = time.time() - self.t_start
        time_alive_penalty = - (time_alive * self.TIME_ALIVE_PENALTY_PER_SECOND)
        time_alive_penalty = max(time_alive_penalty, -300) # Cap the penalty to prevent runaway negative rewards

        # 4) PvP rewards (placeholder - can be expanded with specific PvP signals if available)
        pvp_reward = 0
        if self.GAME_MODE != "PVE":
            if time.time() - self.time_since_pvp_damaged > 5:
                pvp_reward = -25 # Example penalty for inaction in PvP
            else:
                pvp_reward = 0

        # 5) Total reward calculation
        if self.GAME_MODE == "PVE":
            total_reward = hp_reward + boss_dmg_reward + progress_reward + time_since_taken_dmg_reward + time_alive_penalty + no_hit_boss_penalty
        else: # For PvP mode or other general gameplay
            total_reward = hp_reward + time_since_taken_dmg_reward + time_alive_penalty + pvp_reward # Adjust as needed for non-PVE

        # Update previous HP and boss HP for next step's calculation
        self.prev_hp = self.curr_hp
        self.prev_boss_hp = self.curr_boss_hp

        return round(total_reward, 3), self.death, self.boss_death, self.game_won # self.game_won is currently always False

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

        hp, stam, boss_hp, dist, time_alive, phase, time_since_boss_dmg = self._read_state() # Unpack new state variable

        reward, death, boss_death, duel_won = self._compute_reward_and_termination(
            hp, stam, boss_hp, self.first_step
        )

        # Optional debug logging for memory values
        if self.LOG_MEMORY_DEBUG and (self.step_iteration % max(1, self.MEMORY_DEBUG_INTERVAL) == 0):
            try:
                pos = self.game.player_position
                logging.info(
                    f"[MEM] step={self.step_iteration} hp={hp:.3f} stam={stam:.3f} boss_hp={boss_hp:.3f} "
                    f"pos=({pos[0] if pos else 'N/A'}, {pos[1] if pos else 'N/A'}, {pos[2] if pos else 'N/A'}) dist={dist:.3f} "
                    f"time_alive={time_alive:.2f}s time_since_boss_dmg={time_since_boss_dmg:.2f}s" # Added time_since_boss_dmg
                )
            except Exception as e:
                logging.info(
                    f"[MEM] step={self.step_iteration} hp={hp:.3f} stam={stam:.3f} boss_hp={boss_hp:.3f} "
                    f"pos=(N/A, N/A, N/A) dist={dist:.3f} time_alive={time_alive:.2f}s time_since_boss_dmg={time_since_boss_dmg:.2f}s (Error getting player pos: {e})" # Added time_since_boss_dmg
                )

        terminated = bool(death or boss_death or duel_won)
        truncated = bool((time.time() - self.t_start) > 600)

        action_name = "UNKNOWN"
        if not (terminated or truncated):
            action_name = self.input.take_action(int(action))
        
        logging.info(f"Action: {action} -> {action_name} | Reward: {reward:.3f}")

        # Compose observation - include time_since_boss_dmg in the state vector
        state_vec = [hp, stam, boss_hp, time_alive, phase, dist, time_since_boss_dmg]
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
        
        # Memory-based instant reset
        # EldenRingGame handles attachment and essential address checks in its __init__
        self.game.reset_arena(self.BOSS, second_phase=False)
        
        # Give the game a moment to load after teleport
        logging.info("Waiting for game to load after teleport...")
        time.sleep(2.0) 

        # Attempt to get a valid state, failing fast if boss isn't loaded yet
        max_retries = 3 # Reduced retries as we want to fail fast
        for i in range(max_retries):
            hp, stam, boss_hp, dist, time_alive, phase, time_since_boss_dmg = self._read_state() # Unpack new state variable
            # Check for valid boss HP (meaning boss is loaded and game state is readable)
            # Use self.game.boss_hp to ensure we're reading from the EldenRingGame API
            if self.GAME_MODE == "PVE" and self.game.boss_hp is not None and self.game.boss_hp < 1.0: 
                logging.info(f"Successfully read initial boss HP: {self.game.boss_hp:.3f}. Proceeding with reset.")
                break
            elif self.GAME_MODE != "PVE" and hp is not None and hp > 0.01: # For PvP, just check player HP
                logging.info(f"Successfully read initial player HP: {hp:.3f}. Proceeding with reset.")
                break
            logging.warning(f"Game state not yet resolved (boss HP: {self.game.boss_hp}). Retrying in 1s... ({i+1}/{max_retries})")
            time.sleep(1.0)
        else:
            logging.error("Failed to resolve stable game state after multiple retries. Reset may be unstable.")
            # Return a default state if game state is still not resolved
            return {
                "img": np.zeros((MODEL_HEIGHT, MODEL_WIDTH, N_CHANNELS), dtype=np.uint8),
                "prev_actions": np.zeros((N_ACTIONS_HISTORY, self.NUMBER_DISCRETE_ACTIONS, 1), dtype=np.uint8),
                "state": np.zeros(7, dtype=np.float32), # Updated shape
            }, {}

        self.time_alive_ref = time.time()
        self.curr_phase = 1.0
        
        # Reset reward system internal state for new episode
        self.prev_hp = float('nan') # Reset to NaN so first HP read triggers update
        self.curr_hp = float('nan')
        self.prev_boss_hp = float('nan')
        self.curr_boss_hp = float('nan')
        self.time_since_dmg_taken = time.time()
        self.time_since_boss_dmg = time.time() # Reset for new episode
        self.time_since_pvp_damaged = time.time()
        self.death = False
        self.boss_death = False
        self.game_won = False

        # Reset trackers
        self.step_iteration = 0
        self.action_history = []
        self.first_step = True
        self.t_start = time.time()

        # Final state read - ensure time_since_boss_dmg is captured here too
        hp, stam, boss_hp, dist, time_alive, phase, time_since_boss_dmg = self._read_state() # Unpack new state variable
        state_vec = [hp, stam, boss_hp, time_alive, phase, dist, time_since_boss_dmg] # Updated state vector
        obs = {
            "img": self._grab_screen_shot(hp, stam, boss_hp, dist),
            "prev_actions": self._one_hot_prev_actions(),
            "state": np.asarray(state_vec, dtype=np.float32),
        }
        return obs, {}

    def render(self):
        pass

    def close(self):
        self.game.close() # Call close method on EldenRingGame
        cv2.destroyAllWindows()
