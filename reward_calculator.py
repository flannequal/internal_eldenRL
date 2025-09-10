import yaml
import logging
import math
import time
from typing import Dict, Any

class RewardCalculator:
    """
    Calculates rewards based on a loaded schema from a configuration file.
    """
    def __init__(self, schema_name: str, config_path: str = 'config/rewards.yaml'):
        self.schemas = self._load_schemas(config_path)
        if schema_name not in self.schemas:
            raise ValueError(f"Reward schema '{schema_name}' not found in {config_path}")
        self.schema = self.schemas[schema_name]

        logging.info(f"RewardCalculator initialized with schema: '{schema_name}'")

    def _load_schemas(self, config_path: str) -> Dict[str, Any]:
        """Loads all reward schemas from the YAML file."""
        try:
            with open(config_path, 'r') as f:
                return yaml.safe_load(f).get('schemas', {})
        except FileNotFoundError:
            logging.error(f"Reward configuration file not found at '{config_path}'.")
            return {}
        except Exception as e:
            logging.error(f"Error loading reward configuration: {e}")
            return {}

    def calculate_reward(self, last_player_hp: float, player_hp: float,
                         last_boss_hp: float, boss_hp: float,
                         time_alive: float, terminated: bool, won: bool
                         ) -> tuple[float, Dict[str, float]]:
        """
        Calculates the total reward for a step based on the loaded schema.
        """
        reward_breakdown = {}

        # --- Damage and HP Changes ---
        boss_hp_diff = last_boss_hp - boss_hp
        reward_breakdown['boss_damage'] = boss_hp_diff * self.schema.get('boss_damage_multiplier', 0)

        player_hp_diff = last_player_hp - player_hp
        if player_hp_diff > 0: # Player took damage
            reward_breakdown['hp_penalty'] = -player_hp_diff * self.schema.get('player_damage_penalty', 0)

        # --- Time-based Rewards ---
        reward_breakdown['step_time_alive'] = self.schema.get('step_time_alive_reward', 0)

        # --- Termination Rewards ---
        if terminated:
            if won:
                reward_breakdown['win_bonus'] = self.schema.get('win_bonus', 0)
            else:
                reward_breakdown['lose_penalty'] = self.schema.get('lose_penalty', 0)
            reward_breakdown['total_time_alive'] = time_alive * self.schema.get('time_alive_multiplier', 0)

        final_rewards = {k: v for k, v in reward_breakdown.items() if v != 0}
        total_reward = sum(final_rewards.values())

        return total_reward, final_rewards
