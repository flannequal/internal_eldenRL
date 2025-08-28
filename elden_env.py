import logging
import time
from typing import Any, Dict, Optional, Tuple

import gymnasium as gym
from gymnasium import spaces
import numpy as np

from elden_game import EldenRingGame

class EldenEnv(gym.Env):
    """
    A Gymnasium-like environment for Elden Ring, designed for reinforcement learning.
    It uses the high-level EldenRingGame API to interact with the game.
    """
    metadata = {'render_modes': []}

    def __init__(self):
        super().__init__()
        
        try:
            self.game = EldenRingGame()
        except RuntimeError as e:
            logging.error(f"Could not initialize Elden Ring environment: {e}")
            self.game = None
            return

        # Define action and observation spaces
        # Example: 8 actions (move f/b/l/r, attack, dodge, jump, use item)
        self.action_space = spaces.Discrete(8)

        # Observation space: player stats and position
        # [hp, max_hp, sp, max_sp, mp, max_mp, pos_x, pos_y, pos_z]
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(9,), dtype=np.float32
        )
        
        self.last_hp = 0

    def _get_observation(self) -> Optional[np.ndarray]:
        """Constructs the observation array from the current game state."""
        if not self.game: return None

        stats = self.game.get_player_stats()
        pos = self.game.get_player_position()

        if not stats or not pos:
            logging.warning("Failed to get complete game state for observation.")
            return np.zeros(self.observation_space.shape, dtype=np.float32)

        obs = np.array([
            stats.get('hp', 0),
            stats.get('max_hp', 0),
            stats.get('sp', 0),
            stats.get('max_sp', 0),
            stats.get('mp', 0),
            stats.get('max_mp', 0),
            pos[0], pos[1], pos[2]
        ], dtype=np.float32)
        
        return obs

    def reset(self, seed: Optional[int] = None, options: Optional[Dict[str, Any]] = None) -> Tuple[Any, Dict[str, Any]]:
        """
        Resets the environment to an initial state.
        For Elden Ring, this could mean teleporting to a starting point.
        """
        super().reset(seed=seed)
        if not self.game:
            return np.zeros(self.observation_space.shape, dtype=np.float32), {}

        logging.info("Resetting environment...")
        # For a real scenario, you would save a "start" location and teleport there.
        # self.game.teleport("start_arena")
        # For now, we just get the current state.
        
        initial_obs = self._get_observation()
        if initial_obs is not None:
            self.last_hp = initial_obs[0]
        
        return initial_obs, {}

    def step(self, action: int) -> Tuple[Any, float, bool, bool, Dict[str, Any]]:
        """
        Executes one time step within the environment.
        """
        if not self.game:
            return np.zeros(self.observation_space.shape, dtype=np.float32), 0.0, True, False, {}

        # 1. Execute the action (this part requires an input controller)
        # For now, we'll just log the action.
        logging.info(f"Executing action: {action}")
        # e.g., self.input_controller.perform(action)
        time.sleep(0.1) # Simulate action time

        # 2. Get the new observation
        obs = self._get_observation()
        if obs is None:
            # If we can't get an observation, it's a terminal state
            return np.zeros(self.observation_space.shape, dtype=np.float32), 0.0, True, False, {}

        # 3. Calculate the reward
        reward = 0.0
        current_hp = obs[0]
        
        if current_hp < self.last_hp:
            reward -= 10 # Penalty for taking damage
        elif current_hp > self.last_hp:
            reward += 5 # Reward for healing
            
        self.last_hp = current_hp

        # 4. Determine if the episode is done
        terminated = bool(current_hp <= 0) # Episode ends if player dies
        truncated = False # Not using time limits for now

        return obs, reward, terminated, truncated, {}

    def render(self):
        """Rendering is handled by the game window itself."""
        pass

    def close(self):
        """Closes the game connection."""
        if self.game:
            self.game.close()

if __name__ == '__main__':
    # Example usage of the environment
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    env = EldenEnv()
    if env.game:
        obs, info = env.reset()
        print("Initial Observation:", obs)
        
        # Simulate a few steps
        for i in range(5):
            action = env.action_space.sample() # Random action
            obs, reward, terminated, truncated, info = env.step(action)
            print(f"Step {i+1}: Action={action}, Reward={reward}, Terminated={terminated}")
            if terminated:
                break
        env.close()
