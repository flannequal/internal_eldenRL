import time
import pydirectinput


class InputController:
    """Executes discrete actions via keyboard input.

    Mirrors the action semantics used in the original vision environment.
    Returns a human-readable action name for logging.
    """

    def __init__(self, enabled: bool = True):
        self.time_since_heal = 0.0
        self.enabled = enabled

    def take_action(self, action: int) -> str:
        action_name = ''
        # Decide action name first (so dry-run can still log names)
        mapping = {
            0: 'stop', 1: 'w', 2: 's', 3: 'a', 4: 'd', 5: 'dodge-forward', 6: 'dodge-backward',
            7: 'dodge-left', 8: 'dodge-right', 9: 'attack', 10: 'heavy', 11: 'magic',
            12: 'weapon art light', 13: 'weapon art heavy', 14: 'running attack', 15: 'running heavy',
            16: 'running magic', 17: 'jump attack', 18: 'jump heavy', 19: 'jump magic',
            20: 'crouch attack', 21: 'heal', 99: 'warp_to_bonfire'
        }
        action_name = mapping.get(action, '')

        # Dry-run mode: do not send inputs to the OS
        if not self.enabled:
            if action == 21:
                self.time_since_heal = time.time()
            return action_name

        if action == 0:
            pydirectinput.keyUp('w'); pydirectinput.keyUp('s'); pydirectinput.keyUp('a'); pydirectinput.keyUp('d')
        elif action == 1:
            pydirectinput.keyUp('w'); pydirectinput.keyUp('s'); pydirectinput.keyDown('w')
        elif action == 2:
            pydirectinput.keyUp('w'); pydirectinput.keyUp('s'); pydirectinput.keyDown('s')
        elif action == 3:
            pydirectinput.keyUp('a'); pydirectinput.keyUp('d'); pydirectinput.keyDown('a')
        elif action == 4:
            pydirectinput.keyUp('a'); pydirectinput.keyUp('d'); pydirectinput.keyDown('d')
        elif action == 5:
            pydirectinput.keyDown('w'); pydirectinput.press('shift')
        elif action == 6:
            pydirectinput.keyDown('s'); pydirectinput.press('shift')
        elif action == 7:
            pydirectinput.keyDown('a'); pydirectinput.press('shift')
        elif action == 8:
            pydirectinput.keyDown('d'); pydirectinput.press('shift')
        elif action == 9:
            pydirectinput.press('c')
        elif action == 10:
            pydirectinput.press('v')
        elif action == 11:
            pydirectinput.press('x')
        elif action == 12:
            pydirectinput.keyDown('q'); time.sleep(0.1); pydirectinput.press('c'); pydirectinput.keyUp('q')
        elif action == 13:
            pydirectinput.keyDown('q'); time.sleep(0.1); pydirectinput.press('v'); pydirectinput.keyUp('q')
        elif action == 14:
            pydirectinput.keyDown('shift'); pydirectinput.keyDown('w'); time.sleep(0.35); pydirectinput.press('c'); pydirectinput.keyUp('shift')
        elif action == 15:
            pydirectinput.keyDown('shift'); pydirectinput.keyDown('w'); time.sleep(0.35); pydirectinput.press('v'); pydirectinput.keyUp('shift')
        elif action == 16:
            pydirectinput.keyDown('shift'); pydirectinput.keyDown('w'); time.sleep(0.35); pydirectinput.press('x'); pydirectinput.keyUp('shift')
        elif action == 17:
            pydirectinput.keyDown('shift'); pydirectinput.keyDown('w'); time.sleep(0.2); pydirectinput.press('space'); time.sleep(0.1); pydirectinput.press('c'); pydirectinput.keyUp('shift')
        elif action == 18:
            pydirectinput.keyDown('shift'); pydirectinput.keyDown('w'); time.sleep(0.2); pydirectinput.press('space'); time.sleep(0.1); pydirectinput.press('v'); pydirectinput.keyUp('shift')
        elif action == 19:
            pydirectinput.keyDown('shift'); pydirectinput.keyDown('w'); time.sleep(0.2); pydirectinput.press('space'); time.sleep(0.1); pydirectinput.press('x'); pydirectinput.keyUp('shift')
        elif action == 20:
            time.sleep(0.1); pydirectinput.keyDown('ctrl'); time.sleep(0.2); pydirectinput.press('c'); pydirectinput.keyUp('ctrl')
        elif action == 21 and time.time() - self.time_since_heal > 1.5:
            pydirectinput.press('e'); self.time_since_heal = time.time()
        elif action == 99:
            pydirectinput.press('esc'); time.sleep(0.5); pydirectinput.press('right'); time.sleep(0.4); pydirectinput.press('right'); time.sleep(0.4); pydirectinput.press('e'); time.sleep(1.5); pydirectinput.press('left'); time.sleep(0.5); pydirectinput.press('e'); time.sleep(0.5)
        return action_name


