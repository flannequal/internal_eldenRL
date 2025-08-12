import gymnasium as gym
import time
import numpy as np
from gymnasium import spaces

from MemoryClient import MemoryClient
from EldenRewardMemory import EldenRewardMemory
from InputController import InputController


N_ACTIONS_HISTORY = 10
NUMBER_DISCRETE_ACTIONS = 22  # Must match EldenEnv.DISCRETE_ACTIONS length


class EldenMemoryEnv(gym.Env):
    """Gym environment that uses direct memory access rather than vision.

    Observation space (no image):
    - prev_actions: (10, num_actions, 1) one-hot history
    - state: (5,) float32 [player_hp, player_stamina, boss_hp, time_alive_s, arena_phase]
    """

    def __init__(self, config):
        super().__init__()

        self.config = config
        self.GAME_MODE = config.get("GAME_MODE", "PVE")
        self.BOSS = config.get("BOSS", 1)
        self.BOSS_HAS_SECOND_PHASE = config.get("BOSS_HAS_SECOND_PHASE", False)
        self.DESIRED_FPS = float(config.get("DESIRED_FPS", 24))

        # Discrete action space compatible with original env
        self.action_space = spaces.Discrete(NUMBER_DISCRETE_ACTIONS)
        self.observation_space = gym.spaces.Dict(
            {
                "prev_actions": spaces.Box(low=0, high=1, shape=(N_ACTIONS_HISTORY, NUMBER_DISCRETE_ACTIONS, 1), dtype=np.uint8),
                "state": spaces.Box(low=-np.inf, high=np.inf, shape=(5,), dtype=np.float32),
            }
        )

        # Systems
        self.mem = MemoryClient(
            process_name=config.get("PROCESS_NAME", "eldenring.exe"),
            memory_config_path=config.get("MEMORY_CONFIG_PATH"),
            simulate=bool(config.get("SIMULATE_MEMORY", False))
        )
        self.rewardGen = EldenRewardMemory(config)
        # Disable actual OS input when simulating to avoid interfering with the terminal/desktop
        self.input = InputController(enabled=not bool(config.get("SIMULATE_MEMORY", False)))

        # Runtime
        self.action_history = []
        self.t_start = time.time()
        self.step_iteration = 0
        self.first_step = True
        self.done = False
        self.reward = 0.0
        self.max_reward = None
        self.reward_history = []
        self.time_alive_ref = time.time()
        self.curr_phase = 1.0

        # Attach to process early (non-fatal if not attached; retry in reset)
        self.mem.attach()

    def one_hot_prev_actions(self):
        one_hot = np.zeros(shape=(N_ACTIONS_HISTORY, NUMBER_DISCRETE_ACTIONS, 1), dtype=np.uint8)
        for i in range(N_ACTIONS_HISTORY):
            if len(self.action_history) >= (i + 1):
                one_hot[i][self.action_history[-(i + 1)]][0] = 1
        return one_hot

    def _read_state(self):
        hp = self.mem.read_player_hp()
        stam = self.mem.read_player_stamina()
        boss_hp = self.mem.read_boss_hp() if self.GAME_MODE == "PVE" else 1.0
        time_alive = max(0.0, time.time() - self.time_alive_ref)
        return float(hp), float(stam), float(boss_hp), float(time_alive), float(self.curr_phase)

    def step(self, action: int):
        t0 = time.time()

        # 1) Read current memory state
        hp, stam, boss_hp, time_alive, phase = self._read_state()

        # 2) Compute reward of previous step
        self.reward, death, boss_death, duel_won = self.rewardGen.update(hp, stam, boss_hp, self.first_step)

        # 3) Check termination/truncation (Gymnasium API)
        terminated = False
        truncated = False
        if death or boss_death or duel_won:
            terminated = True
        elif (time.time() - self.t_start) > 600:
            truncated = True

        # 4) Execute action (still via keyboard simulation)
        if not (terminated or truncated):
            self.input.take_action(int(action))

        # 5) Observation
        obs = {
            "prev_actions": self.one_hot_prev_actions(),
            "state": np.asarray(self._read_state(), dtype=np.float32),
        }

        # Book-keeping
        self.first_step = False
        self.step_iteration += 1
        self.action_history.append(int(action))
        if self.max_reward is None or self.max_reward < self.reward:
            self.max_reward = self.reward
        self.reward_history.append(self.reward)

        # 6) FPS limiter
        dt = time.time() - t0
        min_step = 1.0 / max(1.0, self.DESIRED_FPS)
        if dt < min_step:
            time.sleep(min_step - dt)

        return obs, self.reward, terminated, truncated, {}

    def reset(self):
        # Ensure attached
        if not self.mem.attached:
            self.mem.attach()

        # Instant arena reset via memory
        self.mem.reset_arena(self.BOSS, second_phase=False)
        self.time_alive_ref = time.time()
        self.curr_phase = 1.0

        # Reset trackers
        self.step_iteration = 0
        self.reward_history = []
        self.done = False
        self.first_step = True
        self.max_reward = None
        self.action_history = []
        self.t_start = time.time()

        # First observation
        obs = {
            "prev_actions": self.one_hot_prev_actions(),
            "state": np.asarray(self._read_state(), dtype=np.float32),
        }
        return obs, {}

    def render(self, mode="human"):
        pass

    def close(self):
        self.mem.detach()


