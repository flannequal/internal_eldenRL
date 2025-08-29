import yaml
import time
from reward_calculator import RewardCalculator

def test_standard_schema():
    print("--- Testing 'standard' schema ---")
    calculator = RewardCalculator(schema_name='standard')

    print("\n[Standard] Test Case 1: Agent heals below threshold (should be rewarded)")
    total_reward, breakdown = calculator.calculate_reward(
        last_player_hp=0.5, player_hp=0.7,
        last_boss_hp=0.75, boss_hp=0.75,
        distance=10.0, time_alive=14.0,
        terminated=False, won=False, action_name='heal'
    )
    print(f"Reward: {total_reward:.4f}, Breakdown: {breakdown}")
    assert 'heal_bonus' in breakdown, "Heal bonus not applied"
    assert 'heal_penalty' not in breakdown, "Heal penalty incorrectly applied"

    print("\n[Standard] Test Case 2: Agent heals above threshold (should be penalized)")
    total_reward, breakdown = calculator.calculate_reward(
        last_player_hp=0.7, player_hp=0.9,
        last_boss_hp=0.75, boss_hp=0.75,
        distance=10.0, time_alive=15.0,
        terminated=False, won=False, action_name='heal'
    )
    print(f"Reward: {total_reward:.4f}, Breakdown: {breakdown}")
    assert 'heal_penalty' in breakdown, "Heal penalty not applied"
    assert 'heal_bonus' not in breakdown, "Heal bonus incorrectly applied"

def test_hyper_aggressive_schema():
    print("\n--- Testing 'hyper-aggressive' schema ---")
    calculator = RewardCalculator(schema_name='hyper-aggressive')

    print("\n[Hyper-Aggressive] Test Case 1: Attack attempt reward (close enough)")
    total_reward, breakdown = calculator.calculate_reward(
        last_player_hp=0.9, player_hp=0.9, last_boss_hp=0.8, boss_hp=0.8,
        distance=3.0, time_alive=10.0, terminated=False, won=False, action_name='light_attack'
    )
    print(f"Reward: {total_reward:.4f}, Breakdown: {breakdown}")
    assert 'attack_attempt' in breakdown, "Attack attempt reward not applied when close"

    print("\n[Hyper-Aggressive] Test Case 2: No attack attempt reward (too far)")
    total_reward, breakdown = calculator.calculate_reward(
        last_player_hp=0.9, player_hp=0.9, last_boss_hp=0.8, boss_hp=0.8,
        distance=5.0, time_alive=11.0, terminated=False, won=False, action_name='light_attack'
    )
    print(f"Reward: {total_reward:.4f}, Breakdown: {breakdown}")
    assert 'attack_attempt' not in breakdown, "Attack attempt reward applied when too far"

    print("\n[Hyper-Aggressive] Test Case 3: Time since last attack penalty")
    calculator.time_of_last_attack = time.time() - 2.0
    total_reward, breakdown = calculator.calculate_reward(
        last_player_hp=0.9, player_hp=0.9, last_boss_hp=0.8, boss_hp=0.8,
        distance=8.0, time_alive=12.0, terminated=False, won=False, action_name='move_forward'
    )
    print(f"Reward: {total_reward:.4f}, Breakdown: {breakdown}")
    assert 'time_since_attack' in breakdown, "Time since attack penalty not applied"
    assert -0.21 < breakdown['time_since_attack'] < -0.19, "Time since attack penalty has wrong value"

    print("\n[Hyper-Aggressive] Test Case 4: No distance reward")
    total_reward, breakdown = calculator.calculate_reward(
        last_player_hp=0.9, player_hp=0.9, last_boss_hp=0.8, boss_hp=0.8,
        distance=15.0, time_alive=13.0, terminated=False, won=False, action_name='move_forward'
    )
    print(f"Reward: {total_reward:.4f}, Breakdown: {breakdown}")
    assert 'distance' not in breakdown, "Distance reward was applied when it should be disabled"

    print("\n[Hyper-Aggressive] Test Case 5: Reactive dodge reward")
    # First, simulate taking damage
    calculator.calculate_reward(
        last_player_hp=0.9, player_hp=0.8, last_boss_hp=0.8, boss_hp=0.8,
        distance=3.0, time_alive=14.0, terminated=False, won=False, action_name='move_forward'
    )
    # Immediately after, dodge
    total_reward, breakdown = calculator.calculate_reward(
        last_player_hp=0.8, player_hp=0.8, last_boss_hp=0.8, boss_hp=0.8,
        distance=3.5, time_alive=14.5, terminated=False, won=False, action_name='dodge'
    )
    print(f"Reward: {total_reward:.4f}, Breakdown: {breakdown}")
    assert 'reactive_dodge' in breakdown, "Reactive dodge reward not applied"

if __name__ == '__main__':
    test_standard_schema()
    test_hyper_aggressive_schema()
