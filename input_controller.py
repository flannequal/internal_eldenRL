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
    Handles keyboard and mouse inputs based on a unified actions configuration file.
    """

    def __init__(self, enabled: bool = True, actions_config_path: str = 'config/actions.yaml'):
        self.enabled = enabled and (pydirectinput is not None)
        self._load_config(actions_config_path)
        self._movement_keys = {'w', 'a', 's', 'd'}
        self._mouse_buttons = {'left', 'right', 'middle'} # Simplified to match pydirectinput

    def _load_config(self, actions_config_path: str):
        """
        Loads the unified action configuration.
        """
        with open(actions_config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
        
        self.actions: Dict[int, Dict] = config.get('actions', {})
        self.special_keys: Dict[str, str] = config.get('special_keys', {})

    def release_all(self):
        """Release all standard movement keys."""
        if not self.enabled: return
        for key in self._movement_keys:
            try:
                pydirectinput.keyUp(key)
            except Exception:
                pass
    
    def lock_on(self):
        """Performs a middle mouse click to lock on to a target."""
        if not self.enabled:
            logger.debug("(SIM) Action: lock_on, Key: middle_click")
            return
        pydirectinput.click(button='middle')

    def take_action(self, action_index: int) -> str:
        """
        Executes the mapped action for 'action_index', handling mouse vs. keyboard.
        """
        action_data = self.actions.get(action_index)
        if not action_data:
            return "UNKNOWN"
            
        action_name = action_data.get("name", "UNKNOWN")
        key = action_data.get("key")

        if not key:
            if action_name == "stop":
                self.release_all()
            return action_name

        if not self.enabled:
            logger.debug(f"(SIM) Action: {action_name}, Key: {key}")
            return action_name

        # REVISED: Check if the key is a mouse button
        if key in self._mouse_buttons:
            pydirectinput.click(button=key)
        elif key in self._movement_keys:
            # Handle continuous movement keys
            for other_key in self._movement_keys:
                if other_key != key:
                    pydirectinput.keyUp(other_key)
            pydirectinput.keyDown(key)
        else: 
            # Handle single-press keyboard actions
            pydirectinput.press(key)
            
        return action_name
