import time
import pydirectinput


class InputController:
    """Executes discrete actions via keyboard input.

    Mirrors the action semantics used in the original vision environment.
    Returns a human-readable action name for logging.
    """

    def __init__(self):
        self.time_since_heal = 0.0

    def take_action(self, action: int) -> str:
        action_name = ''
        if action == 0:
            pydirectinput.keyUp('w')
            pydirectinput.keyUp('s')
            pydirectinput.keyUp('a')
            pydirectinput.keyUp('d')
            action_name = 'stop'
        elif action == 1:
            pydirectinput.keyUp('w')
            pydirectinput.keyUp('s')
            pydirectinput.keyDown('w')
            action_name = 'w'
        elif action == 2:
            pydirectinput.keyUp('w')
            pydirectinput.keyUp('s')
            pydirectinput.keyDown('s')
            action_name = 's'
        elif action == 3:
            pydirectinput.keyUp('a')
            pydirectinput.keyUp('d')
            pydirectinput.keyDown('a')
            action_name = 'a'
        elif action == 4:
            pydirectinput.keyUp('a')
            pydirectinput.keyUp('d')
            pydirectinput.keyDown('d')
            action_name = 'd'
        elif action == 5:
            pydirectinput.keyDown('w')
            pydirectinput.press('shift')
            action_name = 'dodge-forward'
        elif action == 6:
            pydirectinput.keyDown('s')
            pydirectinput.press('shift')
            action_name = 'dodge-backward'
        elif action == 7:
            pydirectinput.keyDown('a')
            pydirectinput.press('shift')
            action_name = 'dodge-left'
        elif action == 8:
            pydirectinput.keyDown('d')
            pydirectinput.press('shift')
            action_name = 'dodge-right'
        elif action == 9:
            pydirectinput.press('c')
            action_name = 'attack'
        elif action == 10:
            pydirectinput.press('v')
            action_name = 'heavy'
        elif action == 11:
            pydirectinput.press('x')
            action_name = 'magic'
        elif action == 12:
            pydirectinput.keyDown('q')
            time.sleep(0.1)
            pydirectinput.press('c')
            pydirectinput.keyUp('q')
            action_name = 'weapon art light'
        elif action == 13:
            pydirectinput.keyDown('q')
            time.sleep(0.1)
            pydirectinput.press('v')
            pydirectinput.keyUp('q')
            action_name = 'weapon art heavy'
        elif action == 14:
            pydirectinput.keyDown('shift')
            pydirectinput.keyDown('w')
            time.sleep(0.35)
            pydirectinput.press('c')
            pydirectinput.keyUp('shift')
            action_name = 'running attack'
        elif action == 15:
            pydirectinput.keyDown('shift')
            pydirectinput.keyDown('w')
            time.sleep(0.35)
            pydirectinput.press('v')
            pydirectinput.keyUp('shift')
            action_name = 'running heavy'
        elif action == 16:
            pydirectinput.keyDown('shift')
            pydirectinput.keyDown('w')
            time.sleep(0.35)
            pydirectinput.press('x')
            pydirectinput.keyUp('shift')
            action_name = 'running magic'
        elif action == 17:
            pydirectinput.keyDown('shift')
            pydirectinput.keyDown('w')
            time.sleep(0.2)
            pydirectinput.press('space')
            time.sleep(0.1)
            pydirectinput.press('c')
            pydirectinput.keyUp('shift')
            action_name = 'jump attack'
        elif action == 18:
            pydirectinput.keyDown('shift')
            pydirectinput.keyDown('w')
            time.sleep(0.2)
            pydirectinput.press('space')
            time.sleep(0.1)
            pydirectinput.press('v')
            pydirectinput.keyUp('shift')
            action_name = 'jump heavy'
        elif action == 19:
            pydirectinput.keyDown('shift')
            pydirectinput.keyDown('w')
            time.sleep(0.2)
            pydirectinput.press('space')
            time.sleep(0.1)
            pydirectinput.press('x')
            pydirectinput.keyUp('shift')
            action_name = 'jump magic'
        elif action == 20:
            time.sleep(0.1)
            pydirectinput.keyDown('ctrl')
            time.sleep(0.2)
            pydirectinput.press('c')
            pydirectinput.keyUp('ctrl')
            action_name = 'crouch attack'
        elif action == 21 and time.time() - self.time_since_heal > 1.5:
            pydirectinput.press('e')
            self.time_since_heal = time.time()
            action_name = 'heal'
        elif action == 99:
            pydirectinput.press('esc')
            time.sleep(0.5)
            pydirectinput.press('right')
            time.sleep(0.4)
            pydirectinput.press('right')
            time.sleep(0.4)
            pydirectinput.press('e')
            time.sleep(1.5)
            pydirectinput.press('left')
            time.sleep(0.5)
            pydirectinput.press('e')
            time.sleep(0.5)
            action_name = 'warp_to_bonfire'
        return action_name


