import time
import yaml
import pydirectinput


class InputController:
    """Executes discrete actions via keyboard input.

    Loads key bindings from a YAML file for configurability.
    """

    def __init__(self, enabled: bool = True, actions_config_path: str = 'config/actions.yaml'):
        self.time_since_heal = 0.0
        self.enabled = enabled
        self._load_config(actions_config_path)

    def _load_config(self, actions_config_path):
        with open(actions_config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        # Action names for logging
        self.action_map = config.get('action_names', {})
        
        # Key bindings
        self.keys = config.get('key_bindings', {})

    def take_action(self, action: int) -> str:
        action_name = self.action_map.get(action, '')

        if not self.enabled:
            if action_name == 'heal':
                self.time_since_heal = time.time()
            return action_name

        # General movement
        if action_name == 'stop':
            for key in ['w', 's', 'a', 'd']:
                pydirectinput.keyUp(self.keys.get(key))
        elif action_name in ['w', 's', 'a', 'd']:
            for key in ['w', 's', 'a', 'd']:
                pydirectinput.keyUp(self.keys.get(key))
            pydirectinput.keyDown(self.keys.get(action_name))
        
        # Dodging
        elif action_name == 'dodge-forward':
            pydirectinput.keyDown(self.keys['w']); pydirectinput.press(self.keys['dodge'])
        elif action_name == 'dodge-backward':
            pydirectinput.keyDown(self.keys['s']); pydirectinput.press(self.keys['dodge'])
        elif action_name == 'dodge-left':
            pydirectinput.keyDown(self.keys['a']); pydirectinput.press(self.keys['dodge'])
        elif action_name == 'dodge-right':
            pydirectinput.keyDown(self.keys['d']); pydirectinput.press(self.keys['dodge'])

        # Basic combat
        elif action_name == 'attack':
            pydirectinput.press(self.keys['attack'])
        elif action_name == 'heavy':
            pydirectinput.press(self.keys['heavy_attack'])
        elif action_name == 'magic':
            pydirectinput.press(self.keys['magic'])

        # Weapon arts
        elif action_name == 'weapon_art_light':
            pydirectinput.keyDown(self.keys['weapon_art']); time.sleep(0.1); pydirectinput.press(self.keys['attack']); pydirectinput.keyUp(self.keys['weapon_art'])
        elif action_name == 'weapon_art_heavy':
            pydirectinput.keyDown(self.keys['weapon_art']); time.sleep(0.1); pydirectinput.press(self.keys['heavy_attack']); pydirectinput.keyUp(self.keys['weapon_art'])

        # Running attacks
        elif action_name == 'running_attack':
            pydirectinput.keyDown(self.keys['dodge']); pydirectinput.keyDown(self.keys['w']); time.sleep(0.35); pydirectinput.press(self.keys['attack']); pydirectinput.keyUp(self.keys['dodge'])
        elif action_name == 'running_heavy':
            pydirectinput.keyDown(self.keys['dodge']); pydirectinput.keyDown(self.keys['w']); time.sleep(0.35); pydirectinput.press(self.keys['heavy_attack']); pydirectinput.keyUp(self.keys['dodge'])
        elif action_name == 'running_magic':
            pydirectinput.keyDown(self.keys['dodge']); pydirectinput.keyDown(self.keys['w']); time.sleep(0.35); pydirectinput.press(self.keys['magic']); pydirectinput.keyUp(self.keys['dodge'])

        # Jump attacks
        elif action_name == 'jump_attack':
            pydirectinput.keyDown(self.keys['dodge']); pydirectinput.keyDown(self.keys['w']); time.sleep(0.2); pydirectinput.press(self.keys['jump']); time.sleep(0.1); pydirectinput.press(self.keys['attack']); pydirectinput.keyUp(self.keys['dodge'])
        elif action_name == 'jump_heavy':
            pydirectinput.keyDown(self.keys['dodge']); pydirectinput.keyDown(self.keys['w']); time.sleep(0.2); pydirectinput.press(self.keys['jump']); time.sleep(0.1); pydirectinput.press(self.keys['heavy_attack']); pydirectinput.keyUp(self.keys['dodge'])
        elif action_name == 'jump_magic':
            pydirectinput.keyDown(self.keys['dodge']); pydirectinput.keyDown(self.keys['w']); time.sleep(0.2); pydirectinput.press(self.keys['jump']); time.sleep(0.1); pydirectinput.press(self.keys['magic']); pydirectinput.keyUp(self.keys['dodge'])

        # Other actions
        elif action_name == 'crouch_attack':
            time.sleep(0.1); pydirectinput.keyDown(self.keys['crouch']); time.sleep(0.2); pydirectinput.press(self.keys['attack']); pydirectinput.keyUp(self.keys['crouch'])
        elif action_name == 'heal' and time.time() - self.time_since_heal > 1.5:
            pydirectinput.press(self.keys['heal']); self.time_since_heal = time.time()
        
        # Menuing (remains hardcoded for now)
        elif action_name == 'warp_to_bonfire':
            pydirectinput.press('esc'); time.sleep(0.5); pydirectinput.press('right'); time.sleep(0.4); pydirectinput.press('right'); time.sleep(0.4); pydirectinput.press('e'); time.sleep(1.5); pydirectinput.press('left'); time.sleep(0.5); pydirectinput.press('e'); time.sleep(0.5)
        
        return action_name


