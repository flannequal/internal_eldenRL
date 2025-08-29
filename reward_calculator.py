import yaml
import logging
import math
from typing import Dict, Any, Optional

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
                         distance: float, time_alive: float,
                         terminated: bool, won: bool) -> Tuple[float, Dict[str, float]]:
        """
        Calculates the total reward for a step based on the loaded schema.
        """
        reward_breakdown = {}

        # Boss damage reward
        boss_hp_diff = last_boss_hp - boss_hp
        reward_breakdown['boss_damage'] = boss_hp_diff * self.schema.get('boss_damage_multiplier', 0)

        # Player damage penalty
        player_hp_diff = last_player_hp - player_hp
        reward_breakdown['hp_penalty'] = -player_hp_diff * self.schema.get('player_damage_penalty', 0)

        # Distance reward
        if self.schema.get('enable_distance_reward', False):
            reward_breakdown['distance'] = self._calculate_distance_reward(distance)
        else:
            reward_breakdown['distance'] = 0.0

        # Win/Loss/Time rewards (only on termination)
        reward_breakdown['win_bonus'] = 0.0
        reward_breakdown['lose_penalty'] = 0.0
        reward_breakdown['time_alive'] = 0.0
        if terminated:
            if won:
                reward_breakdown['win_bonus'] = self.schema.get('win_bonus', 0)
            else:
                reward_breakdown['lose_penalty'] = self.schema.get('lose_penalty', 0)

            reward_breakdown['time_alive'] = time_alive * self.schema.get('time_alive_reward', 0)

        total_reward = sum(reward_breakdown.values())
        return total_reward, reward_breakdown

    def _calculate_distance_reward(self, distance: float) -> float:
        """Calculates reward based on distance to the boss."""
        reward_type = self.schema.get('distance_reward_type', 'bell')
        optimal_dist = self.schema.get('optimal_distance', 8.0)
        scale = self.schema.get('distance_reward_scale', 5.0)

        if reward_type == 'bell':
            falloff = self.schema.get('distance_falloff', 5.0)
            # Gaussian-like function, peaks at optimal_distance
            exponent = -((distance - optimal_dist) ** 2) / (2 * falloff ** 2)
            return scale * math.exp(exponent)

        elif reward_type == 'linear':
            # Simple linear penalty for being far away
            return max(0, -scale * (distance - optimal_dist))

        return 0.0
