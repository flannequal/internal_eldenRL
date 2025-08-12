import time


class EldenRewardMemory:
    """Reward calculator for memory-based observations.

    Accepts precise numeric game states (hp, stamina, boss_hp) instead of images.
    Keeps reward logic aligned with the existing project while removing image noise handling.
    """

    def __init__(self, config):
        self.GAME_MODE = config.get("GAME_MODE", "PVE")
        self.prev_hp = 1.0
        self.curr_hp = 1.0
        self.curr_stam = 1.0
        self.curr_boss_hp = 1.0
        self.prev_boss_hp = 1.0
        self.time_since_dmg_taken = time.time()
        self.time_since_boss_dmg = time.time()
        self.time_since_pvp_damaged = time.time()
        self.time_alive = time.time()
        self.death = False
        self.boss_death = False
        self.game_won = False

    def update(self, curr_hp: float, curr_stam: float, curr_boss_hp: float, first_step: bool):
        """Compute reward using precise memory values.

        Returns (total_reward, death, boss_death, game_won)
        """
        # 1) Current values
        self.curr_hp = max(0.0, min(1.0, float(curr_hp)))
        self.curr_stam = max(0.0, min(1.0, float(curr_stam)))
        self.curr_boss_hp = max(0.0, min(1.0, float(curr_boss_hp)))
        if first_step:
            self.time_since_dmg_taken = time.time() - 10

        self.death = self.curr_hp <= 0.01
        self.boss_death = (self.GAME_MODE == "PVE") and (self.curr_boss_hp <= 0.01)

        # 2) HP rewards
        hp_reward = 0
        if not self.death:
            if self.curr_hp > self.prev_hp + 1e-6:
                hp_reward = 100
            elif self.curr_hp < self.prev_hp - 1e-6:
                hp_reward = -69
                self.time_since_dmg_taken = time.time()
        else:
            hp_reward = -420

        time_since_taken_dmg_reward = 25 if (time.time() - self.time_since_dmg_taken > 5) else 0

        self.prev_hp = self.curr_hp

        # 3) Boss rewards (PVE only)
        boss_dmg_reward = 0
        percent_through_fight_reward = 0
        if self.GAME_MODE == "PVE":
            if self.boss_death:
                boss_dmg_reward = 420
            else:
                # Reward strictly on boss HP decrease
                if self.curr_boss_hp < self.prev_boss_hp - 1e-6:
                    boss_dmg_reward = 69
                    self.time_since_boss_dmg = time.time()
                elif time.time() - self.time_since_boss_dmg > 5:
                    boss_dmg_reward = -25
            # Encourage progress through the fight
            if self.curr_boss_hp < 0.97:
                percent_through_fight_reward = self.curr_boss_hp * 15

        # 4) PvP rewards
        pvp_reward = 0
        if self.GAME_MODE != "PVE":
            # With exact values we cannot detect damage flashes; keep time-based shaping only.
            if time.time() - self.time_since_pvp_damaged > 5:
                pvp_reward = -25
            else:
                pvp_reward = 0

        # 5) Total
        if self.GAME_MODE == "PVE":
            total_reward = hp_reward + boss_dmg_reward + time_since_taken_dmg_reward + percent_through_fight_reward
        else:
            total_reward = hp_reward + time_since_taken_dmg_reward + pvp_reward

        # Update previous boss hp tracker last
        self.prev_boss_hp = self.curr_boss_hp

        return round(total_reward, 3), self.death, self.boss_death, self.game_won


