# input_controller.py
import time
import yaml
import logging
from typing import Dict, Optional
try:
    import pydirectinput
except Exception:
    pydirectinput = None

logger = logging.getLogger(__name__)

class InputController:
    """
    Lightweight input controller.
    - Loads key bindings from YAML (actions: index->name, key_bindings)
    - take_action(action_index) returns action_name (and executes key presses if enabled)
    - Supports simulation mode (enabled=False) for headless testing.
    - Provides release_all() to clear movement keys.
    """

    DEFAULT_COOLDOWNS = {
        "heal": 1.5
    }

    def __init__(self, enabled: bool = True, actions_config_path: str = 'config/actions.yaml'):
        self.enabled = enabled and (pydirectinput is not None)
        self._load_config(actions_config_path)
        self._last_heal = 0.0
        # common movement keys to release when switching direction
        self._movement_keys = set(['w', 'a', 's', 'd'])
        # small configurable timing
        self._short_delay = float(self.cfg.get("short_delay", 0.05))
        self._long_delay = float(self.cfg.get("long_delay", 0.35))

    def _load_config(self, actions_config_path: str):
        with open(actions_config_path, 'r', encoding='utf-8') as f:
            self.cfg = yaml.safe_load(f) or {}
        # mapping from integer index to action name (strings)
        self.action_map: Dict[int, str] = self.cfg.get('action_names', {})
        # key bindings: logical key -> physical key string
        self.keys: Dict[str, str] = self.cfg.get('key_bindings', {})

    def release_all(self):
        """Release all standard movement keys."""
        if not self.enabled:
            return
        for k in self._movement_keys:
            key = self.keys.get(k)
            if key:
                try:
                    pydirectinput.keyUp(key)
                except Exception:
                    pass

    def reset(self):
        """Reset any internal timers/flags (e.g. heal cooldown)."""
        self._last_heal = 0.0
        self.release_all()

    def set_enabled(self, enabled: bool):
        """Toggle live input (True -> will press keys)."""
        self.enabled = enabled and (pydirectinput is not None)
        if not self.enabled:
            logger.info("InputController: switched to SIMULATION mode (no keypresses).")

    def _press(self, key: str):
        if not key:
            return
        if not self.enabled:
            logger.debug(f"(SIM) press {key}")
            return
        try:
            pydirectinput.press(key)
        except Exception as e:
            logger.warning(f"press failed {key}: {e}")

    def _keydown(self, key: str):
        if not key:
            return
        if not self.enabled:
            logger.debug(f"(SIM) keyDown {key}")
            return
        try:
            pydirectinput.keyDown(key)
        except Exception as e:
            logger.warning(f"keyDown failed {key}: {e}")

    def _keyup(self, key: str):
        if not key:
            return
        if not self.enabled:
            logger.debug(f"(SIM) keyUp {key}")
            return
        try:
            pydirectinput.keyUp(key)
        except Exception as e:
            logger.warning(f"keyUp failed {key}: {e}")

    def take_action(self, action_index: int) -> str:
        """
        Execute the mapped action for 'action_index' and return the action_name (string).
        If the controller is disabled, actions are simulated (logged) but not physically executed.
        """
        action_name = self.action_map.get(action_index, "")
        if not action_name:
            return ""

        # movement keys
        if action_name == "stop":
            self.release_all()
            return action_name

        if action_name in self._movement_keys:
            # release other movement keys, press the requested one
            for k in self._movement_keys:
                if k != action_name:
                    self._keyup(self.keys.get(k))
            self._keydown(self.keys.get(action_name))
            return action_name

        # dodge variations: hold movement then press dodge
        if action_name.startswith("dodge"):
            # e.g. "dodge-forward" -> movement 'w'
            dir_map = {
                "dodge-forward": "w",
                "dodge-backward": "s",
                "dodge-left": "a",
                "dodge-right": "d"
            }
            move = dir_map.get(action_name)
            if move:
                self._keydown(self.keys.get(move))
                self._press(self.keys.get("dodge"))
                # release movement after short delay
                time.sleep(self._short_delay)
                self._keyup(self.keys.get(move))
            return action_name

        # basic attacks
        if action_name == "attack":
            self._press(self.keys.get("attack"))
            return action_name
        if action_name == "heavy":
            self._press(self.keys.get("heavy_attack"))
            return action_name
        if action_name == "magic":
            self._press(self.keys.get("magic"))
            return action_name

        # running attacks (press dodge + forward then attack)
        if action_name.startswith("running_"):
            # running_attack / running_heavy / running_magic
            real = action_name.split("_", 1)[1]
            self._keydown(self.keys.get("dodge"))
            self._keydown(self.keys.get("w"))
            time.sleep(self._long_delay)
            if real == "attack":
                self._press(self.keys.get("attack"))
            elif real == "heavy":
                self._press(self.keys.get("heavy_attack"))
            elif real == "magic":
                self._press(self.keys.get("magic"))
            self._keyup(self.keys.get("dodge"))
            self._keyup(self.keys.get("w"))
            return action_name

        # jump attacks (shorter timing)
        if action_name.startswith("jump_"):
            self._keydown(self.keys.get("dodge"))
            self._keydown(self.keys.get("w"))
            time.sleep(0.2)
            self._press(self.keys.get("jump"))
            time.sleep(0.08)
            what = action_name.split("_", 1)[1]
            if what == "attack":
                self._press(self.keys.get("attack"))
            elif what == "heavy":
                self._press(self.keys.get("heavy_attack"))
            elif what == "magic":
                self._press(self.keys.get("magic"))
            self._keyup(self.keys.get("dodge"))
            self._keyup(self.keys.get("w"))
            return action_name

        # crouch attack
        if action_name == "crouch_attack":
            self._keydown(self.keys.get("crouch"))
            time.sleep(0.15)
            self._press(self.keys.get("attack"))
            self._keyup(self.keys.get("crouch"))
            return action_name

        # heal with cooldown
        if action_name == "heal":
            now = time.time()
            cd = self.DEFAULT_COOLDOWNS.get("heal", 1.5)
            if now - self._last_heal >= cd:
                self._press(self.keys.get("heal"))
                self._last_heal = now
            else:
                logger.debug("heal on cooldown")
            return action_name

        # warp shortcut or menuing sequences (kept as a single press sequence)
        if action_name == "warp_to_bonfire":
            # if in sim mode, just log
            if not self.enabled:
                logger.debug("(SIM) warp sequence")
                return action_name
            # basic example: ESC -> right,right -> e -> left -> e  (user may override YAML)
            seq = self.cfg.get("warp_sequence", ["esc", "right", "right", "e", "left", "e"])
            for k in seq:
                self._press(k)
                time.sleep(0.35)
            return action_name

        # fallback: try to press named key
        key = self.keys.get(action_name)
        if key:
            self._press(key)
        else:
            logger.debug(f"Unknown action '{action_name}' (no key binding)")

        return action_name
