import logging
from typing import Dict

import yaml

try:
    import pydirectinput
except ImportError:
    pydirectinput = None

logger = logging.getLogger(__name__)

MOVEMENT_KEYS = frozenset({"w", "a", "s", "d"})
MOUSE_BUTTONS = frozenset({"left", "right", "middle"})


class InputController:

    def __init__(self, enabled: bool = True, actions_config_path: str = "config/actions.yaml"):
        self.enabled = enabled and pydirectinput is not None
        if enabled and pydirectinput is None:
            logger.warning("pydirectinput unavailable, running without input")

        with open(actions_config_path, "r", encoding="utf-8") as handle:
            config = yaml.safe_load(handle) or {}
        self.actions: Dict[int, Dict] = config.get("actions", {})

    def release_all(self) -> None:
        if not self.enabled:
            return
        for key in MOVEMENT_KEYS:
            try:
                pydirectinput.keyUp(key)
            except Exception as exc:
                logger.debug("keyUp %s failed: %s", key, exc)

    def lock_on(self) -> None:
        if not self.enabled:
            logger.debug("(sim) lock_on")
            return
        pydirectinput.click(button="middle")

    def take_action(self, action_index: int) -> str:
        action = self.actions.get(action_index)
        if not action:
            return "UNKNOWN"

        name = action.get("name", "UNKNOWN")
        key = action.get("key")

        if not key:
            if name == "stop":
                self.release_all()
            return name

        if not self.enabled:
            logger.debug("(sim) %s -> %s", name, key)
            return name

        if key in MOUSE_BUTTONS:
            pydirectinput.click(button=key)
        elif key in MOVEMENT_KEYS:
            for other in MOVEMENT_KEYS - {key}:
                pydirectinput.keyUp(other)
            pydirectinput.keyDown(key)
        else:
            pydirectinput.press(key)

        return name
