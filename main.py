import train

if __name__ == '__main__':
    '''User Settings'''
    env_config = {
        # Single-pipeline hybrid env (vision image + memory state)
        "ENV_MODE": "HYBRID",
        "PYTESSERACT_PATH": r'C:/msys64/mingw64/bin/tesseract.exe',    # Set the path to PyTesseract
        "MONITOR": 1,           #Set the monitor to use (1,2,3)
        "DEBUG_MODE": False,    #Renders the AI vision (pretty scuffed)
        "GAME_MODE": "PVE",     #PVP or PVE
        "BOSS": 8,              #1-6 for PVE (look at walkToBoss.py for boss names) | Is ignored for GAME_MODE PVP
        "BOSS_HAS_SECOND_PHASE": False,  #Set to True if the boss has a second phase (only for PVE)
        "PLAYER_HP": 2140,      #Set the player hp (used for hp bar detection)
        "PLAYER_STAMINA": 118,  #Set the player stamina (used for stamina bar detection)
        "DESIRED_FPS": 24,      #Set the desired fps (used for actions per second) (24 = 2.4 actions per second)
        # Memory backend
        "PROCESS_NAME": "eldenring.exe",
        # SoulsGym backend uses `examples/data/eldenring/addresses.yaml` implicitly
        # Optional: path to YAML arenas for spawn defaults and notes
        "MEMORY_CONFIG_PATH": r"config\memory_arenas.yaml",
        # Set to False to use real memory via SoulsGym backend
        "SIMULATE_MEMORY": False,
        # Disable inputs for dry-runs (set False for real playing)
        "DISABLE_INPUT": False,
    }
    CREATE_NEW_MODEL = True
         #Create a new model or resume training for an existing model


    '''Start Training'''
    print("💍 EldenRL 💍")
    train.train(CREATE_NEW_MODEL, env_config)