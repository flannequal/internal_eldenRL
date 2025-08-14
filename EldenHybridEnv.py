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
    - state: (7,) float32 [player_hp, player_stamina, boss_hp, time_alive_s, dist_to_boss, time_since_boss_dmg, player_flask_count]

    Rewards/termination are computed from memory reads only (no CV-derived signals).
    Resets are instant via memory (teleport + health/stamina restore).
    """

    metadata = {"render_modes": ["human"], "render_fps": 30}

    def __init__(self, config: Dict[str, Any]):
        super().__init__()

        self.config = config
        # Removed GAME_MODE config, assuming PVE
        self.BOSS = int(config.get("BOSS", 1))
        self.DESIRED_FPS = float(config.get("DESIRED_FPS", 24))
        self.LOG_MEMORY_DEBUG = bool(config.get("LOG_MEMORY_DEBUG", False))
        self.MEMORY_DEBUG_INTERVAL = int(config.get("MEMORY_DEBUG_INTERVAL", 1))
        self.MONITOR = int(config.get("MONITOR", 1))
        self.DEBUG_MODE = bool(config.get("DEBUG_MODE", False))

        # New reward shaping parameters
        # Penalty per second for time alive without significant progress. Encourages efficient play.
        self.TIME_ALIVE_PENALTY_PER_SECOND = float(config.get("TIME_ALIVE_PENALTY_PER_SECOND", 1.0))
        # Penalty per second for not hitting the boss. Discourages stalling/running away.
        self.NO_BOSS_HIT_PENALTY_PER_SECOND = float(config.get("NO_BOSS_HIT_PENALTY_PER_SECOND", 5.0))
        self.PROGRESS_REWARD_SCALE = float(config.get("PROGRESS_REWARD_SCALE", 150.0))
        self.HEALING_FLASK_AMOUNT_HP_RATIO = float(config.get("HEALING_FLASK_AMOUNT_HP_RATIO", 0.4)) # e.g. a flask heals 40% of max HP
        self.FLASK_USAGE_REWARD = float(config.get("FLASK_USAGE_REWARD", 50.0)) # Reward for good flask use
        self.FLASK_USAGE_PENALTY = float(config.get("FLASK_USAGE_PENALTY", -25.0)) # Penalty for wasteful flask use
        self.DODGE_SUCCESS_REWARD = float(config.get("DODGE_SUCCESS_REWARD", 20.0)) # Reward for successful dodge
        self.DODGE_WASTE_PENALTY = float(config.get("DODGE_WASTE_PENALTY", -5.0)) # Penalty for dodging nothing (spamming)
        self.STAGGER_ATTACK_BONUS = float(config.get("STAGGER_ATTACK_BONUS", 100.0)) # Bonus for hitting staggered boss
        
        # Dodge spam detection parameters
        self.DODGE_SPAM_THRESHOLD_S = float(config.get("DODGE_SPAM_THRESHOLD_S", 1.0)) # Time window to consider dodges as spam
        self.DODGE_SPAM_PENALTY = float(config.get("DODGE_SPAM_PENALTY", -50.0)) # Penalty for spamming dodges

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
                # state: [player_hp, player_stamina, boss_hp, time_alive_s, dist_to_boss, time_since_boss_dmg, player_flask_count]
                "state": spaces.Box(low=-np.inf, high=np.inf, shape=(7,), dtype=np.float32), # Reduced from 10 to 7
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
        self.time_since_pvp_damaged = time.time() # This is now unused, but kept for potential future PvP mode
        self.death = False
        self.boss_death = False
        self.game_won = False
        self.flask_used_this_step = False # New flag for flask usage detection
        self.dodged_this_step = False # New flag for dodge usage detection
        self.attacked_this_step = False # New flag for attack action (if needed for dodge logic)

        # Dodge spam detection state
        self._last_dodge_time: float = 0.0
        self._consecutive_dodges: int = 0

        # Runtime
        self.action_history: list[int] = []
        self.prev_episode_start_time = time.time() # Track start time for time_alive calculation
        self.prev_boss_animation_id = -1 # Track previous boss animation (unused in state, but kept for potential future use)
        self.step_iteration = 0
        self.first_step = True
        self.curr_phase = 1.0 # This is now unused in the state vector

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
        # Removed GAME_MODE check, assuming PVE
        boss_hp = self.game.boss_hp if hp is not None else 1.0 # Use boss_hp if player_hp is valid
        dist = self.game.distance_to_boss or 0.0 # Use property directly
        time_alive = max(0.0, time.time() - self.prev_episode_start_time) # Use episode start time
        time_since_boss_dmg = max(0.0, time.time() - self.time_since_boss_dmg) # How long since boss was last hit by player
        
        flask_count = self.game.player_flask_count if self.game.player_flask_count is not None else 0
        
        # Removed: boss_anim_id, boss_is_staggered, phase
        # boss_anim_id = self.game.boss_animation_id if self.game.boss_animation_id is not None else -1
        # boss_staggered = 1.0 if self.game.boss_is_staggered else 0.0 # Convert bool to float 0.0 or 1.0

        return float(hp if hp is not None else 0.0), \
               float(stam if stam is not None else 0.0), \
               float(boss_hp if boss_hp is not None else 1.0), \
               float(dist), \
               float(time_alive), \
               float(time_since_boss_dmg), \
               float(flask_count)

    def _compute_reward_and_termination(self, curr_hp: float, curr_stam: float, curr_boss_hp: float, first_step: bool,
                                        player_flask_count: int): # Removed boss_animation_id, boss_is_staggered
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
            self.prev_episode_start_time = time.time() # Re-initialize episode start time

        self.death = self.curr_hp <= 0.01
        # Removed GAME_MODE check, assuming PVE
        self.boss_death = (self.curr_boss_hp <= 0.01)

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
        # Removed: stagger_attack_bonus = 0

        # Removed GAME_MODE check, assuming PVE
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
        
        # Removed: Bonus for hitting a staggered boss
        # if boss_is_staggered > 0.5: # Assuming 1.0 for true
        #     if self.attacked_this_step: 
        #         stagger_attack_bonus = self.STAGGER_ATTACK_BONUS


        # 3) General time penalty (encourages efficient play and shorter episodes)
        time_alive = time.time() - self.prev_episode_start_time
        time_alive_penalty = - (time_alive * self.TIME_ALIVE_PENALTY_PER_SECOND)
        time_alive_penalty = max(time_alive_penalty, -300) # Cap the penalty to prevent runaway negative rewards

        # 4) Flask usage rewards/penalties
        flask_reward = 0
        if self.flask_used_this_step: # This flag needs to be set in the step() method based on action
            # Placeholder for actual max HP (e.g., from config/addresses)
            # Assuming max HP is 1.0 in normalized space, or get it from EldenRingGame
            # We need player's max HP to calculate the absolute healing threshold
            player_max_hp_val = self.game.player_max_hp # Assuming this property exists or can be added to EldenRingGame
            if player_max_hp_val is not None:
                healing_threshold = player_max_hp_val * (1.0 - self.HEALING_FLASK_AMOUNT_HP_RATIO)
                if self.curr_hp * player_max_hp_val < healing_threshold: # Check if current HP is below threshold to need a flask
                    flask_reward = self.FLASK_USAGE_REWARD # Reward for using it when needed
                else:
                    flask_reward = self.FLASK_USAGE_PENALTY # Penalty for using it when not needed (e.g., almost full HP)
            else: # If max HP isn't readable, give a default penalty for now to discourage random use
                flask_reward = self.FLASK_USAGE_PENALTY / 2 # Moderate penalty if info missing

        # 5) Dodge rewards/penalties
        dodge_reward = 0
        if self.dodged_this_step: # This flag needs to be set in the step() method based on action
            current_time = time.time()
            time_since_last_dodge = current_time - self._last_dodge_time

            if time_since_last_dodge < self.DODGE_SPAM_THRESHOLD_S:
                # Dodged too quickly after the last dodge
                self._consecutive_dodges += 1
                dodge_reward = self.DODGE_SPAM_PENALTY # Penalty for spamming
                logging.debug(f"Dodge spam detected! Consecutive dodges: {self._consecutive_dodges}")
            else:
                # Dodge was spaced out enough, reset consecutive dodge count
                self._consecutive_dodges = 1
                dodge_reward = self.DODGE_SUCCESS_REWARD # Reward for a well-timed dodge
                logging.debug(f"Well-timed dodge. Resetting consecutive dodges to 1.")
            
            self._last_dodge_time = current_time # Update last dodge time

        # 6) PvP rewards (placeholder - can be expanded with specific PvP signals if available)
        # Removed PvP specific reward logic as GAME_MODE is removed
        pvp_reward = 0

        # 7) Total reward calculation
        total_reward = hp_reward + time_since_taken_dmg_reward + time_alive_penalty + flask_reward + dodge_reward

        # Removed GAME_MODE check, assuming PVE
        total_reward += boss_dmg_reward + progress_reward + no_hit_boss_penalty # Removed stagger_attack_bonus

        # Update previous HP and boss HP for next step's calculation
        self.prev_hp = self.curr_hp
        self.prev_boss_hp = self.curr_boss_hp
        # Removed: self.prev_boss_animation_id = boss_animation_id # Update previous boss animation

        # Reset per-step flags
        self.flask_used_this_step = False
        self.dodged_this_step = False
        self.attacked_this_step = False

        return round(total_reward, 3), self.death, self.boss_death, self.game_won # self.game_won is currently always False

    # ----- Gym API -----
    def step(self, action: int):
        t0 = time.time()

        # Read memory state and compute reward for previous transition
        # Read the full state for the current timestep
        hp, stam, boss_hp, dist, time_alive, time_since_boss_dmg, player_flask_count = self._read_state() # Removed unused params
        
        # Check if game state is valid before calculating reward/processing action
        # If any critical read fails, terminate with no reward
        if hp is None or stam is None or boss_hp is None: # These are critical for basic function
            logging.error("Failed to read critical game state. Terminating episode.")
            # Return a terminal state with no reward
            return {
                "img": np.zeros((MODEL_HEIGHT, MODEL_WIDTH, N_CHANNELS), dtype=np.uint8),
                "prev_actions": np.zeros((N_ACTIONS_HISTORY, self.NUMBER_DISCRETE_ACTIONS, 1), dtype=np.uint8),
                "state": np.zeros(7, dtype=np.float32), # Updated shape to 7
            }, 0.0, True, False, {}

        # Set per-step flags based on the action taken
        # NOTE: You MUST define these action IDs in your config (e.g., config/app.yaml or a dedicated actions.yaml)
        # and ensure they map to the correct discrete action integers.
        self.flask_used_this_step = (action == self.config.get("FLASK_ACTION_ID", -1)) 
        self.dodged_this_step = (action == self.config.get("DODGE_ACTION_ID", -1)) 
        self.attacked_this_step = (action == self.config.get("ATTACK_ACTION_ID", -1)) 
        
        reward, death, boss_death, duel_won = self._compute_reward_and_termination(
            hp, stam, boss_hp, self.first_step, player_flask_count # Removed unused params
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
        truncated = bool((time.time() - self.prev_episode_start_time) > 600) # Max episode duration, using episode start time

        action_name = "UNKNOWN"
        if not (terminated or truncated):
            action_name = self.input.take_action(int(action)) # Execute the action
        
        logging.info(f"Action: {action} -> {action_name} | Reward: {reward:.3f}")

        # Compose observation - include all new state variables
        state_vec = [hp, stam, boss_hp, time_alive, dist, time_since_boss_dmg, player_flask_count] # Reduced state vector size
        obs = {
            "img": self._grab_screen_shot(hp, stam, boss_hp, dist), # Capture image with current stats
            "prev_actions": self._one_hot_prev_actions(), # History of actions
            "state": np.asarray(state_vec, dtype=np.float32), # Numerical state vector
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
            # Read all state variables after reset
            hp, stam, boss_hp, dist, time_alive, time_since_boss_dmg, player_flask_count = self._read_state() # Removed unused params
            
            # Check for valid game state to ensure environment is ready
            # Removed GAME_MODE check, assuming PVE
            if self.game.boss_hp is not None and self.game.boss_hp <= 1.0: 
                logging.info(f"Successfully read initial boss HP: {self.game.boss_hp:.3f}. Proceeding with reset.")
                break
            logging.warning(f"Game state not yet resolved (boss HP: {self.game.boss_hp}). Retrying in 1s... ({i+1}/{max_retries})")
            time.sleep(1.0)
        else:
            logging.error("Failed to resolve stable game state after multiple retries. Reset may be unstable.")
            # Return a default state if game state is still not resolved
            return {
                "img": np.zeros((MODEL_HEIGHT, MODEL_WIDTH, N_CHANNELS), dtype=np.uint8),
                "prev_actions": np.zeros((N_ACTIONS_HISTORY, self.NUMBER_DISCRETE_ACTIONS, 1), dtype=np.uint8),
                "state": np.zeros(7, dtype=np.float32), # Updated shape to 7
            }, {}

        self.prev_episode_start_time = time.time() # Reset episode start time for new episode
        # Removed: self.curr_phase = 1.0
        
        # Reset reward system internal state for new episode
        self.prev_hp = float('nan') # Reset to NaN so first HP read triggers update
        self.curr_hp = float('nan')
        self.prev_boss_hp = float('nan')
        self.curr_boss_hp = float('nan')
        self.time_since_dmg_taken = time.time()
        self.time_since_boss_dmg = time.time() # Reset for new episode
        # Removed: self.time_since_pvp_damaged = time.time()
        self.death = False
        self.boss_death = False
        self.game_won = False
        self.flask_used_this_step = False
        self.dodged_this_step = False
        self.attacked_this_step = False
        # Removed: self.prev_boss_animation_id = -1 # Reset for new episode

        # Reset dodge spam detection state
        self._last_dodge_time = 0.0
        self._consecutive_dodges = 0

        # Reset trackers
        self.step_iteration = 0
        self.action_history = []
        self.first_step = True
        # self.t_start is now replaced by self.prev_episode_start_time

        # Final state read for initial observation
        hp, stam, boss_hp, dist, time_alive, time_since_boss_dmg, player_flask_count = self._read_state() # Removed unused params
        state_vec = [hp, stam, boss_hp, time_alive, dist, time_since_boss_dmg, player_flask_count] # Reduced state vector size
        obs = {
            "img": self._grab_screen_shot(hp, stam, boss_hp, dist),
            "prev_actions": self._one_hot_prev_actions(),
            "state": np.asarray(state_vec, dtype=np.float32),
        }
        return obs, {}
