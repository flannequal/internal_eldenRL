import yaml
from reward_calculator import RewardCalculator

def test_reward_calculator():
    print("Testing RewardCalculator...")

    # Use the 'standard' schema for testing
    calculator = RewardCalculator(schema_name='standard')

    print("\n--- Test Case 1: Basic step, no special events ---")
    total_reward, breakdown = calculator.calculate_reward(
        last_player_hp=0.9, player_hp=0.9,
        last_boss_hp=0.8, boss_hp=0.8,
        distance=8.0, time_alive=10.0,
        terminated=False, won=False,
        action_name='move_forward'
    )
    print(f"Reward: {total_reward:.4f}, Breakdown: {breakdown}")

    print("\n--- Test Case 2: Player takes damage ---")
    total_reward, breakdown = calculator.calculate_reward(
        last_player_hp=0.9, player_hp=0.8,
        last_boss_hp=0.8, boss_hp=0.8,
        distance=8.0, time_alive=11.0,
        terminated=False, won=False,
        action_name='move_forward'
    )
    print(f"Reward: {total_reward:.4f}, Breakdown: {breakdown}")

    print("\n--- Test Case 3: Agent deals damage ---")
    total_reward, breakdown = calculator.calculate_reward(
        last_player_hp=0.8, player_hp=0.8,
        last_boss_hp=0.8, boss_hp=0.75,
        distance=3.0, time_alive=12.0,
        terminated=False, won=False,
        action_name='light_attack'
    )
    print(f"Reward: {total_reward:.4f}, Breakdown: {breakdown}")

    print("\n--- Test Case 4: Agent dodges ---")
    total_reward, breakdown = calculator.calculate_reward(
        last_player_hp=0.8, player_hp=0.8,
        last_boss_hp=0.75, boss_hp=0.75,
        distance=3.0, time_alive=13.0,
        terminated=False, won=False,
        action_name='dodge'
    )
    print(f"Reward: {total_reward:.4f}, Breakdown: {breakdown}")

    print("\n--- Test Case 5: Agent heals below threshold ---")
    total_reward, breakdown = calculator.calculate_reward(
        last_player_hp=0.5, player_hp=0.7,
        last_boss_hp=0.75, boss_hp=0.75,
        distance=10.0, time_alive=14.0,
        terminated=False, won=False,
        action_name='heal'
    )
    print(f"Reward: {total_reward:.4f}, Breakdown: {breakdown}")

    print("\n--- Test Case 6: Agent heals above threshold ---")
    total_reward, breakdown = calculator.calculate_reward(
        last_player_hp=0.7, player_hp=0.9,
        last_boss_hp=0.75, boss_hp=0.75,
        distance=10.0, time_alive=15.0,
        terminated=False, won=False,
        action_name='heal'
    )
    print(f"Reward: {total_reward:.4f}, Breakdown: {breakdown}")

    print("\n--- Test Case 7: Successive hits ---")
    calculator.calculate_reward(
        last_player_hp=0.9, player_hp=0.9,
        last_boss_hp=0.75, boss_hp=0.70,
        distance=3.0, time_alive=16.0,
        terminated=False, won=False,
        action_name='light_attack'
    )
    total_reward, breakdown = calculator.calculate_reward(
        last_player_hp=0.9, player_hp=0.9,
        last_boss_hp=0.70, boss_hp=0.65,
        distance=3.0, time_alive=17.0,
        terminated=False, won=False,
        action_name='light_attack'
    )
    print(f"Reward: {total_reward:.4f}, Breakdown: {breakdown}")


if __name__ == '__main__':
    test_reward_calculator()
