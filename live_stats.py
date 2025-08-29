from rich.table import Table
from rich.panel import Panel
from rich.text import Text

class LiveStatsDisplay:
    """
    A class to generate a renderable object for live training statistics.
    """
    def __init__(self):
        pass

    def generate_table(self, env, action_name: str) -> Panel:
        """
        Generates a Rich Panel containing the stats table.
        """
        last_info = env.last_info
        # Use the last observation from the environment to avoid re-capturing
        obs = env.last_observation if hasattr(env, 'last_observation') else None

        if not obs:
            return Panel(Text("Could not retrieve game data.", justify="center"), title="[bold red]Error[/bold red]", border_style="red")

        player_hp_norm = obs["data"][0]
        boss_hp_norm = obs["data"][1]

        table = Table(title="Elden Ring RL Live Stats", border_style="green")
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
                # Color rewards based on value
                reward_style = "green" if value > 0 else "red" if value < 0 else "white"
                table.add_row(f"Reward: {key}", f"[{reward_style}]{value:+.4f}[/{reward_style}]")

            total_reward = sum(rewards.values())
            total_style = "bold green" if total_reward > 0 else "bold red" if total_reward < 0 else "bold white"
            table.add_row(f"[bold]Total Step Reward[/bold]", f"[{total_style}]{total_reward:+.4f}[/{total_style}]")

        return Panel(table, border_style="blue")
