import yaml
import time
from reward_calculator import RewardCalculator

def test_healing_penalty():
    print("--- Testing Healing Penalties ---")
    calculator = RewardCalculator(schema_name='standard') # Standard schema has the new penalty

    print("\n[Healing] Test Case 1: Unnecessary heal should have large penalty")
    total_reward, breakdown = calculator.calculate_reward(
        last_player_hp=0.7, player_hp=0.9,
        last_boss_hp=0.75, boss_hp=0.75,
        distance=10.0, time_alive=15.0,
        terminated=False, won=False, action_name='heal'
    )
    print(f"Reward: {total_reward:.4f}, Breakdown: {breakdown}")
    assert 'heal_penalty' in breakdown, "Heal penalty not applied"
    assert breakdown['heal_penalty'] == -10.0, "Heal penalty is not the new, larger value"

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

    print("\n[Hyper-Aggressive] Test Case 3: Reactive dodge reward")
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
    assert breakdown['reactive_dodge'] == 15.0, "Reactive dodge reward has wrong value"

    print("\n[Hyper-Aggressive] Test Case 4: Standard dodge reward (no recent damage)")
    calculator.time_of_last_damage = 0 # Reset damage time
    total_reward, breakdown = calculator.calculate_reward(
        last_player_hp=0.8, player_hp=0.8, last_boss_hp=0.8, boss_hp=0.8,
        distance=3.5, time_alive=16.0, terminated=False, won=False, action_name='dodge'
    )
    print(f"Reward: {total_reward:.4f}, Breakdown: {breakdown}")
    assert 'reactive_dodge' not in breakdown, "Reactive dodge reward applied incorrectly"
    # In hyper-aggressive, the base dodge reward is 0, so we expect no dodge reward here.
    assert 'dodge' not in breakdown, "Base dodge reward applied when it should be 0"


if __name__ == '__main__':
    test_healing_penalty()
    test_hyper_aggressive_schema()
