import os
import cv2
from rich.console import Console
from rich.table import Table

class LiveStatsDisplay:
    """
    A class to generate and print live training statistics to the console.
    This version uses a simple clear screen command for frequent updates.
    """
    def __init__(self, env):
        self.console = Console()
        # Get action names from the environment for the table
        self.action_names = [v['name'] for v in env.actions_config.values()]

    def print_update(self, env, fps: float, save_vision: bool):
        """
        Clears the console and prints an updated table of stats.
        """
        os.system('cls' if os.name == 'nt' else 'clear')

        action_name = env.last_action_name
        last_info = env.last_info
        obs = env.last_observation

        table = Table(title="Elden Ring RL Live Stats", border_style="green")

        if not obs:
            table.add_row("[bold red]No observation data available yet.[/bold red]")
            self.console.print(table)
            return

        table.add_column("Metric", justify="right", style="cyan", no_wrap=True)
        table.add_column("Value", style="magenta")

        # --- Core Stats ---
        table.add_row("Player HP", f"{obs['data'][0]:.2%}")
        table.add_row("Boss HP", f"{obs['data'][1]:.2%}")
        table.add_row("Distance", f"{env.last_distance:.2f}m")
        table.add_row("Last Action", action_name)
        table.add_row("Loop FPS", f"{fps:.2f}")

        # --- Vision Feed ---
        if save_vision and "vision" in obs:
            img_bgr = cv2.cvtColor(obs["vision"], cv2.COLOR_RGB2BGR)
            cv2.imwrite("debug_vision.png", img_bgr)
            table.add_row("Vision Feed", "debug_vision.png")

        # --- Reward Breakdown ---
        if last_info and "reward_breakdown" in last_info:
            table.add_section()
            rewards = last_info["reward_breakdown"]
            for key, value in rewards.items():
                reward_style = "green" if value > 0 else "red" if value < 0 else "white"
                table.add_row(f"Reward: {key}", f"[{reward_style}]{value:+.4f}[/{reward_style}]")

            total_reward = sum(rewards.values())
            total_style = "bold green" if total_reward > 0 else "bold red" if total_reward < 0 else "bold white"
            table.add_row(f"[bold]Total Step Reward[/bold]", f"[{total_style}]{total_reward:+.4f}[/{total_style}]")

        # --- Action Counts ---
        if hasattr(env, 'action_counts'):
            table.add_section()
            table.add_row("[bold]Action Counts (Episode)[/bold]", "")
            for act_name in self.action_names:
                count = env.action_counts.get(act_name, 0)
                table.add_row(act_name, str(count))

        self.console.print(table)
