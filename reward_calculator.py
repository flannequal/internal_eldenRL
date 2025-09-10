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

        # State for time-sensitive rewards
        self.last_dodge_time = 0
        self.last_boss_hit_time = 0
        self.time_of_last_attack = time.time()
        self.time_of_last_damage = 0 # Initialize to 0 (the distant past)

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
                         terminated: bool, won: bool,
                         action_name: str) -> tuple[float, Dict[str, float]]:
        """
        Calculates the total reward for a step based on the loaded schema.
        """
        reward_breakdown = {}
        current_time = time.time()

        # --- Damage and HP Changes ---
        boss_hp_diff = last_boss_hp - boss_hp
        reward_breakdown['boss_damage'] = boss_hp_diff * self.schema.get('boss_damage_multiplier', 0)

        player_hp_diff = last_player_hp - player_hp
        if player_hp_diff > 0: # Player took damage
            reward_breakdown['hp_penalty'] = -player_hp_diff * self.schema.get('player_damage_penalty', 0)
            self.time_of_last_damage = current_time

        # --- Distance Reward ---
        if self.schema.get('enable_distance_reward', False):
            reward_breakdown['distance'] = self._calculate_distance_reward(distance)

        # --- Time-based Rewards ---
        reward_breakdown['step_time_alive'] = self.schema.get('step_time_alive_reward', 0)

        time_since_last_attack = current_time - self.time_of_last_attack
        time_penalty = time_since_last_attack * self.schema.get('time_since_attack_penalty', 0)
        if time_penalty != 0:
            reward_breakdown['time_since_attack'] = time_penalty

        # --- Action-specific Rewards ---
        if action_name == 'light_attack':
            threshold = self.schema.get('attack_distance_threshold')
            if threshold is None or distance <= threshold:
                reward_breakdown['attack_attempt'] = self.schema.get('attack_attempt_reward', 0)
            self.time_of_last_attack = current_time

        if action_name == 'dodge':
            # Reactive dodge reward
            dodge_window = self.schema.get('reactive_dodge_window')
            if dodge_window and (current_time - self.time_of_last_damage < dodge_window):
                reward_breakdown['reactive_dodge'] = self.schema.get('reactive_dodge_reward', 0)
            # Standard dodge reward
            else:
                cooldown = self.schema.get('dodge_cooldown', 1.5)
                if current_time - self.last_dodge_time > cooldown:
                    reward_breakdown['dodge'] = self.schema.get('dodge_reward', 0)
            self.last_dodge_time = current_time

        if player_hp > last_player_hp: # Player healed
            threshold = self.schema.get('heal_health_threshold', 0.6)
            if last_player_hp < threshold:
                reward_breakdown['heal_bonus'] = self.schema.get('heal_reward', 0)
            else:
                reward_breakdown['heal_penalty'] = self.schema.get('unnecessary_heal_penalty', 0)

        # --- Combo Rewards ---
        if boss_hp_diff > 0:
            window = self.schema.get('successive_hits_time_window', 2.5)
            if current_time - self.last_boss_hit_time < window:
                reward_breakdown['combo'] = self.schema.get('successive_hits_reward', 0)
            self.last_boss_hit_time = current_time

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

    #calculate distance to boss
    def _calculate_distance_reward(self, distance: float) -> float:  
        reward_type = self.schema.get('distance_reward_type', 'bell')
        optimal_dist = self.schema.get('optimal_distance', 8.0)
        scale = self.schema.get('distance_reward_scale', 5.0)

        if reward_type == 'bell':
            falloff = self.schema.get('distance_falloff', 5.0)
            exponent = -((distance - optimal_dist) ** 2) / (2 * falloff ** 2)
            return scale * math.exp(exponent)
        elif reward_type == 'linear':
            return max(0, -scale * (distance - optimal_dist))
        return 0.0
