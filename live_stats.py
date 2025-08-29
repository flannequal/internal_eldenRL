import os
from rich.console import Console
from rich.table import Table

class LiveStatsDisplay:
    """
    A class to display live training statistics in the console.
    """
    def __init__(self):
        self.console = Console()

    def update(self, env, action_name: str):
        """
        Clears the console and prints an updated table of stats.
        """
        os.system('cls' if os.name == 'nt' else 'clear')

        last_info = env.last_info
        obs = env._get_observation() # Get the most recent observation

        if not obs:
            self.console.print("[bold red]Could not retrieve game data.[/bold red]")
            return

        player_hp_norm = obs["data"][0]
        boss_hp_norm = obs["data"][1]

        table = Table(title="Elden Ring RL Live Stats")
        table.add_column("Metric", justify="right", style="cyan", no_wrap=True)
        table.add_column("Value", style="magenta")

        # --- Core Stats ---
        table.add_row("Player HP", f"{player_hp_norm:.2%}")
        table.add_row("Boss HP", f"{boss_hp_norm:.2%}")
        table.add_row("Distance to Boss", f"{env.last_distance:.2f}m")
        table.add_row("Last Action", action_name)

        # --- Reward Breakdown ---
        if last_info and "reward_breakdown" in last_info:
            table.add_section()
            rewards = last_info["reward_breakdown"]
            for key, value in rewards.items():
                table.add_row(f"Reward: {key}", f"{value:+.4f}")

            total_reward = sum(rewards.values())
            table.add_row("[bold]Total Step Reward[/bold]", f"[bold]{total_reward:+.4f}[/bold]")

        self.console.print(table)
