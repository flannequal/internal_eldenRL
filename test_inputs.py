import time
import yaml
import logging
from input_controller import InputController

def run_input_test(actions_config_path: str = 'config/actions.yaml'):
    """
    Cycles through all defined actions to allow for manual verification in-game.
    """
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    print("="*50)
    print("Starting input test in 5 seconds...")
    print("Please focus the Elden Ring game window now.")
    print("The script will cycle through each action every 2 seconds.")
    print("="*50)
    time.sleep(5)

    try:
        controller = InputController(enabled=True, actions_config_path=actions_config_path)
    except FileNotFoundError:
        logging.error(f"Could not find actions config at '{actions_config_path}'.")
        return
    except Exception as e:
        logging.error(f"Failed to initialize InputController: {e}")
        return

    if not controller.enabled:
        logging.error("InputController is not enabled. Is pydirectinput installed?")
        return

    actions = sorted(controller.actions.items())

    try:
        while True:
            print("\n--- Starting new cycle of actions ---")
            for action_index, action_data in actions:
                action_name = action_data.get('name', 'UNKNOWN')
                print(f"Executing action: [ {action_name} ]")

                controller.take_action(action_index)

                # Wait before the next action
                time.sleep(2)

            print("\n--- Cycle complete. Repeating in 5 seconds... (Press CTRL+C to stop) ---")
            time.sleep(5)

    except KeyboardInterrupt:
        print("\nInput test stopped by user.")
    finally:
        controller.release_all()
        print("All keys released. Exiting.")

if __name__ == '__main__':
    run_input_test()
