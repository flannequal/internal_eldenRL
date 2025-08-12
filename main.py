import train

if __name__ == '__main__':
    '''User Settings'''
    env_config = {
        "ENV_MODE": "VISION",   # VISION or MEMORY
        "PYTESSERACT_PATH": r'C:\Program Files\Tesseract-OCR\tesseract.exe',    # Set the path to PyTesseract
        "MONITOR": 1,           #Set the monitor to use (1,2,3)
        "DEBUG_MODE": False,    #Renders the AI vision (pretty scuffed)
        "GAME_MODE": "PVP",     #PVP or PVE
        "BOSS": 8,              #1-6 for PVE (look at walkToBoss.py for boss names) | Is ignored for GAME_MODE PVP
        "BOSS_HAS_SECOND_PHASE": False,  #Set to True if the boss has a second phase (only for PVE)
        "PLAYER_HP": 2140,      #Set the player hp (used for hp bar detection)
        "PLAYER_STAMINA": 118,  #Set the player stamina (used for stamina bar detection)
        "DESIRED_FPS": 24,      #Set the desired fps (used for actions per second) (24 = 2.4 actions per second)
        # Memory mode specific
        "PROCESS_NAME": "eldenring.exe",
        # Optional: path to YAML arenas. Defaults: config/memory_arenas.yaml, then sample
        "MEMORY_CONFIG_PATH": r"config\memory_arenas.yaml",
    }
    CREATE_NEW_MODEL = True
         #Create a new model or resume training for an existing model


    '''Start Training'''
    print("💍 EldenRL 💍")
    train.train(CREATE_NEW_MODEL, env_config)