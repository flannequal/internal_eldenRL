import os
import cv2

class LiveStatsDisplay:
    """
    A class to generate and print live training statistics to the console.
    This version uses simple print statements for maximum compatibility and speed.
    """
    def __init__(self, env):
        # Get action names from the environment for the display
        self.action_names = [v['name'] for v in env.actions_config.values()]

    def print_update(self, env, fps: float, save_vision: bool):
        """
        Clears the console and prints an updated block of stats.
        """
        os.system('cls' if os.name == 'nt' else 'clear')

        action_name = env.last_action_name
        last_info = env.last_info
        obs = env.last_observation

        print("--- Elden Ring RL Live Stats ---")

        if not obs:
            print("No observation data available yet.")
            return

        # --- Core Stats ---
        print(f"Player HP:    {obs['data'][0]:.2%}")
        print(f"Boss HP:      {obs['data'][1]:.2%}")
        print(f"Distance:     {env.last_distance:.2f}m")
        print(f"Last Action:  {action_name}")
        print(f"Loop FPS:     {fps:.2f}")

        # --- Vision Feed ---
        if save_vision and "vision" in obs:
            img_bgr = cv2.cvtColor(obs["vision"], cv2.COLOR_RGB2BGR)
            cv2.imwrite("debug_vision.png", img_bgr)
            print("Vision Feed:  debug_vision.png (saved)")

        # --- Reward Breakdown ---
        if last_info and "reward_breakdown" in last_info:
            print("\n--- Reward Breakdown ---")
            rewards = last_info["reward_breakdown"]
            for key, value in rewards.items():
                print(f"{key:<20}: {value:+.4f}")

            total_reward = sum(rewards.values())
            print("-" * 20)
            print(f"{'Total Step Reward':<20}: {total_reward:+.4f}")

        # --- Action Counts ---
        if hasattr(env, 'action_counts'):
            print("\n--- Action Counts (Episode) ---")
            for act_name in self.action_names:
                count = env.action_counts.get(act_name, 0)
                print(f"{act_name:<20}: {count}")

        print("-" * 30)
