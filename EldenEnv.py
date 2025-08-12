import cv2
import gymnasium as gym
import mss
import time
import numpy as np
from gymnasium import spaces
import pydirectinput
import pytesseract                              # Pytesseract is not just a simple pip install.
from EldenReward import EldenReward
from MemoryClient import MemoryClient


N_CHANNELS = 3                                  #Image format
IMG_WIDTH = 1920                                #Game capture resolution
IMG_HEIGHT = 1080                             
MODEL_WIDTH = int(800 / 2)                      #Ai vision resolution
MODEL_HEIGHT = int(450 / 2)


'''Ai action list'''
DISCRETE_ACTIONS = {'release_wasd': 'release_wasd',
                    'w': 'run_forwards',                
                    's': 'run_backwards',
                    'a': 'run_left',
                    'd': 'run_right',
                    'w+shift': 'dodge_forwards',
                    's+shift': 'dodge_backwards',
                    'a+shift': 'dodge_left',
                    'd+shift': 'dodge_right',
                    'c': 'attack',
                    'v': 'strong_attack',
                    'x': 'magic',
                    'q+c': 'weapon_art_light',
                    'q+v': 'weapon_art_heavy',
                    'w+c': 'running_attack',
                    'w+v': 'running_heavy',
                    'w+x': 'running_magic',
                    'w+shift+space+c' : 'jump_attack',
                    'w+shift+space+v' : 'jump_strong_attack',
                    'w+shift+space+x' : 'jump_magic',
                    'ctrl + c': 'crouch_attack',
                    'e': 'use_item'}

NUMBER_DISCRETE_ACTIONS = len(DISCRETE_ACTIONS)
NUM_ACTION_HISTORY = 10                         #Number of actions the agent can remember


class EldenEnv(gym.Env):
    """Custom Elden Ring Environment that follows gym interface"""


    def __init__(self, config):
        '''Setting up the environment'''
        super(EldenEnv, self).__init__()

        '''Setting up the gym spaces'''
        self.action_space = spaces.Discrete(NUMBER_DISCRETE_ACTIONS)                                                            #Discrete action space with NUM_ACTION_HISTORY actions to choose from
        spaces_dict = {                                                                                                         #Observation space (img, prev_actions, state)
            'img': spaces.Box(low=0, high=255, shape=(MODEL_HEIGHT, MODEL_WIDTH, N_CHANNELS), dtype=np.uint8),                      #Image of the game
            'prev_actions': spaces.Box(low=0, high=1, shape=(NUM_ACTION_HISTORY, NUMBER_DISCRETE_ACTIONS, 1), dtype=np.uint8),      #Last 10 actions as one hot encoded array
            'state': spaces.Box(low=0, high=1, shape=(2,), dtype=np.float32),                                                       #Stamina and helth of the player in percent
        }
        self.observation_space = spaces.Dict(spaces_dict)
    

        '''Setting up the variables'''''
        pytesseract.pytesseract.tesseract_cmd = config["PYTESSERACT_PATH"]          #Setting the path to pytesseract.exe            
        self.sct = mss.mss()                                                        #Initializing CV2 and MSS (used to take screenshots)
        self.reward = 0                                                             #Reward of the previous step
        self.rewardGen = EldenReward(config)                                        #Setting up the reward generator class
        self.death = False                                                          #If the agent died
        self.duel_won = False                                                       #If the agent won the duel
        self.t_start = time.time()                                                  #Time when the training started
        self.done = False                                                           #If the game is done
        self.step_iteration = 0                                                     #Current iteration (number of steps taken in this fight)
        self.first_step = True                                                      #If this is the first step
        self.max_reward = None                                                      #The maximum reward that the agent has gotten in this fight
        self.reward_history = []                                                    #Array of the rewards to calculate the average reward of fight
        self.action_history = []                                                    #Array of the actions that the agent took.
        self.time_since_heal = time.time()                                          #Time since the last heal
        self.action_name = ''                                                       #Name of the action for logging
        self.MONITOR = config["MONITOR"]                                            #Monitor to use
        self.DEBUG_MODE = config["DEBUG_MODE"]                                      #If we are in debug mode
        self.GAME_MODE = config["GAME_MODE"]                                        #If we are in PVP or PVE mode
        self.DESIRED_FPS = config["DESIRED_FPS"]                                    #Desired FPS (not implemented yet)
        self.BOSS_HAS_SECOND_PHASE = config["BOSS_HAS_SECOND_PHASE"]                #If the boss has a second phase
        self.are_in_second_phase = False                                            #If we are in the second phase of the boss
        self.BOSS = config.get("BOSS", 1)
        self.RESET_MODE = config.get("RESET_MODE", "MEMORY").upper()
        self.mem = None
        if self.RESET_MODE == "MEMORY":
            self.mem = MemoryClient(
                process_name=config.get("PROCESS_NAME", "eldenring.exe"),
                memory_config_path=config.get("MEMORY_CONFIG_PATH")
            )
        # VISION mode no longer uses WalkToBoss
    

    '''One hot encoding of the last 10 actions'''
    def oneHotPrevActions(self, actions):
        oneHot = np.zeros(shape=(NUM_ACTION_HISTORY, NUMBER_DISCRETE_ACTIONS, 1))
        for i in range(NUM_ACTION_HISTORY):
            if len(actions) >= (i + 1):
                oneHot[i][actions[-(i + 1)]][0] = 1
        #print(oneHot)
        return oneHot 


    '''Grabbing a screenshot of the game'''
    def grab_screen_shot(self):
        monitor = self.sct.monitors[self.MONITOR]
        sct_img = self.sct.grab(monitor)
        frame = cv2.cvtColor(np.asarray(sct_img), cv2.COLOR_BGRA2RGB)
        frame = frame[46:IMG_HEIGHT + 46, 12:IMG_WIDTH + 12]    #cut the frame to the size of the game
        if self.DEBUG_MODE:
            self.render_frame(frame)
        return frame
    

    '''Rendering the frame for debugging'''
    def render_frame(self, frame):                
        cv2.imshow('debug-render', frame)
        cv2.waitKey(100)
        cv2.destroyAllWindows()
        
    
    '''Defining the actions that the agent can take'''
    def take_action(self, action):
        #action = -1 #Uncomment this for emergency block all actions
        if action == 0:
            pydirectinput.keyUp('w')
            pydirectinput.keyUp('s')
            pydirectinput.keyUp('a')
            pydirectinput.keyUp('d')
            self.action_name = 'stop'
        elif action == 1:
            pydirectinput.keyUp('w')
            pydirectinput.keyUp('s')
            pydirectinput.keyDown('w')
            self.action_name = 'w'
        elif action == 2:
            pydirectinput.keyUp('w')
            pydirectinput.keyUp('s')
            pydirectinput.keyDown('s')
            self.action_name = 's'
        elif action == 3:
            pydirectinput.keyUp('a')
            pydirectinput.keyUp('d')
            pydirectinput.keyDown('a')
            self.action_name = 'a'
        elif action == 4:
            pydirectinput.keyUp('a')
            pydirectinput.keyUp('d')
            pydirectinput.keyDown('d')
            self.action_name = 'd'
        elif action == 5:
            pydirectinput.keyDown('w')
            pydirectinput.press('shift')
            self.action_name = 'dodge-forward'
        elif action == 6:
            pydirectinput.keyDown('s')
            pydirectinput.press('shift')
            self.action_name = 'dodge-backward'
        elif action == 7:
            pydirectinput.keyDown('a')
            pydirectinput.press('shift')
            self.action_name = 'dodge-left'
        elif action == 8:
            pydirectinput.keyDown('d')
            pydirectinput.press('shift')
            self.action_name = 'dodge-right'
        elif action == 9:
            pydirectinput.press('c')
            self.action_name = 'attack'
        elif action == 10:
            pydirectinput.press('v')
            self.action_name = 'heavy'
        elif action == 11:
            pydirectinput.press('x')
            self.action_name = 'magic'
        elif action == 12:                  #weapon art light
            pydirectinput.keyDown('q')
            time.sleep(0.1)
            pydirectinput.press('c')
            pydirectinput.keyUp('q')
            self.action_name = 'weapon art light'
        elif action == 13:                  #weapon art heavy
            pydirectinput.keyDown('q')
            time.sleep(0.1)
            pydirectinput.press('v')
            pydirectinput.keyUp('q')
            self.action_name = 'weapon art heavy'
        elif action == 14:                  #running attack
            pydirectinput.keyDown('shift')
            pydirectinput.keyDown('w')
            time.sleep(0.35)
            pydirectinput.press('c')
            pydirectinput.keyUp('shift')
            self.action_name = 'running attack'
        elif action == 15:                  #running heavy
            pydirectinput.keyDown('shift')
            pydirectinput.keyDown('w')
            time.sleep(0.35)
            pydirectinput.press('v')
            pydirectinput.keyUp('shift')
            self.action_name = 'running heavy'
        elif action == 16:                  #running magic
            pydirectinput.keyDown('shift')
            pydirectinput.keyDown('w')
            time.sleep(0.35)
            pydirectinput.press('x')
            pydirectinput.keyUp('shift')
            self.action_name = 'running magic'
        elif action == 17:                  #jump attack
            pydirectinput.keyDown('shift')
            pydirectinput.keyDown('w')
            time.sleep(0.2)
            pydirectinput.press('space')
            time.sleep(0.1)
            pydirectinput.press('c')
            pydirectinput.keyUp('shift')
            self.action_name = 'jump attack'
        elif action == 18:                  #jump heavy
            pydirectinput.keyDown('shift')
            pydirectinput.keyDown('w')
            time.sleep(0.2)
            pydirectinput.press('space')
            time.sleep(0.1)
            pydirectinput.press('v')
            pydirectinput.keyUp('shift')
            self.action_name = 'jump heavy'
        elif action == 19:                  #jump magic
            pydirectinput.keyDown('shift')
            pydirectinput.keyDown('w')
            time.sleep(0.2)
            pydirectinput.press('space')
            time.sleep(0.1)
            pydirectinput.press('x')
            pydirectinput.keyUp('shift')
            self.action_name = 'jump magic' 
        elif action == 20:                  #crouch attack
            time.sleep(0.1)  
            pydirectinput.keyDown('ctrl')
            time.sleep(0.2)
            pydirectinput.press('c')   
            pydirectinput.keyUp('ctrl')
            self.action_name = 'crouch attack'  
        elif action == 21 and time.time() - self.time_since_heal > 1.5: #to prevent spamming heal we only allow it to be pressed every 1.5 seconds
            pydirectinput.press('e')        #item
            self.time_since_heal = time.time()
            self.action_name = 'heal'
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
            print('🔄🔥')
        
    
    
        

    '''Step function that is called by train.py'''
    def step(self, action):
        #📍 Lets look at what step does
        #📍 1. Collect the current observation 
        #📍 2. Collect the reward based on the observation (reward of previous step)            #⚔️PvP reward
        #📍 3. Check if the game is done (player died, boss died, 10minute time limit reached)  #⚔️Or duel won
        #📍 4. Take the next action (based on the decision of the agent)
        #📍 5. Ending the step
        #📍 6. Returning the observation, the reward, if we are done, and the info
        #📍 7*. train.py decides the next action and calls step again


        if self.first_step: print("🐾#1 first step")
        
        '''Grabbing variables'''
        t_start = time.time()    #Start time of this step
        frame = self.grab_screen_shot()                                         #📍 1. Collect the current observation
        self.reward, self.death, self.boss_death, self.duel_won = self.rewardGen.update(frame, self.first_step) #📍 2. Collect the reward based on the observation (reward of previous step)
        

        if self.DEBUG_MODE:
            print('🎁 Reward: ', self.reward)
            print('🎁 self.death: ', self.death)
            print('🎁 self.boss_death: ', self.boss_death)


        '''📍 3. Checking termination/truncation (Gymnasium API)'''
        terminated = False
        truncated = False
        if self.death or self.boss_death or self.duel_won:
            terminated = True
        elif (time.time() - self.t_start) > 600:
            truncated = True
            

        '''📍 4. Taking the action'''
        if not (terminated or truncated):
            self.take_action(action)
        

        '''📍 5. Ending the steap'''

        '''Return values'''
        info = {}                                                       #Empty info for gym
        observation = cv2.resize(frame, (MODEL_WIDTH, MODEL_HEIGHT))    #We resize the frame so the agent dosnt have to deal with a 1920x1080 image (400x225)
        if self.DEBUG_MODE: self.render_frame(observation)              #🐜 If we are in debug mode we render the frame
        if self.max_reward is None:                                     #Max reward
            self.max_reward = self.reward
        elif self.max_reward < self.reward:
            self.max_reward = self.reward
        self.reward_history.append(self.reward)                         #Reward history
        spaces_dict = {                                                 #Combining the observations into one dictionary like gym wants it
            'img': observation,
            'prev_actions': self.oneHotPrevActions(self.action_history),
            'state': np.asarray([self.rewardGen.curr_hp, self.rewardGen.curr_stam])
        }


        '''Other variables that need to be updated'''
        self.first_step = False
        self.step_iteration += 1
        self.action_history.append(int(action))                         #Appending the action to the action history


        '''FPS LIMITER'''
        t_end = time.time()                                             
        desired_fps = (1 / self.DESIRED_FPS)                            #My CPU (i9-13900k) can run the training at about 2.4SPS (steps per secons)
        time_to_sleep = desired_fps - (t_end - t_start)
        if time_to_sleep > 0:
            time.sleep(time_to_sleep)
        '''END FPS LIMITER'''


        current_fps = str(round(((1 / ((t_end - t_start) *10)) * 10), 1))     #Current SPS (steps per second)


        '''Console output of the step'''
        if not (terminated or truncated): #Losts of python string formatting to make the console output look nice
            self.reward = round(self.reward, 0)
            reward_with_spaces = str(self.reward)
            for i in range(5 - len(reward_with_spaces)):
                reward_with_spaces = ' ' + reward_with_spaces
            max_reward_with_spaces = str(self.max_reward)
            for i in range(5 - len(max_reward_with_spaces)):
                max_reward_with_spaces = ' ' + max_reward_with_spaces
            for i in range(18 - len(str(self.action_name))):
                self.action_name = ' ' + self.action_name
            for i in range(5 - len(current_fps)):
                current_fps = ' ' + current_fps
            print('👣 Iteration: ' + str(self.step_iteration) + '| FPS: ' + current_fps + '| Reward: ' + reward_with_spaces + '| Max Reward: ' + max_reward_with_spaces + '| Action: ' + str(self.action_name))
        else:           #If the game is done (Logging Reward for dying or winning)
            print('👣✔️ Reward: ' + str(self.reward) + '| Max Reward: ' + str(self.max_reward))


        #📍 6. Returning the observation, the reward, termination, truncation, and the info (Gymnasium API)
        return spaces_dict, self.reward, terminated, truncated, info
    

    '''Reset function that is called if the game is done'''
    def reset(self):
        #📍 1. Clear any held down keys
        #📍 2. Print the average reward for the last run
        #📍 3. Reset to arena (memory-based)
        #📍 4. Reset all variables
        #📍 5. Create the first observation for the first step and return it


        print('🔄 Reset called...')


        '''📍 1.Clear any held down keys'''
        self.take_action(0)
        print('🔄🔪 Unholding keys...')

        '''📍 2. Print the average reward for the last run'''
        if len(self.reward_history) > 0:
            total_r = 0
            for r in self.reward_history:
                total_r += r
            avg_r = total_r / len(self.reward_history)                              
            print('🔄🎁 Average reward for last run:', avg_r) 


        '''📍 3. Memory-based reset'''
        if self.RESET_MODE == "MEMORY" and self.mem is not None:
            if not self.mem.attached:
                self.mem.attach()
            self.mem.reset_arena(self.BOSS, second_phase=False)

        if self.death:                           #Death counter in txt file
            f = open("deathCounter.txt", "r")
            deathCounter = int(f.read())
            f.close()
            deathCounter += 1
            f = open("deathCounter.txt", "w")
            f.write(str(deathCounter))
            f.close()


        '''📍 4. Reset all variables'''
        self.step_iteration = 0
        self.reward_history = [] 
        self.done = False
        self.first_step = True
        self.max_reward = None
        self.rewardGen.prev_hp = 1
        self.rewardGen.curr_hp = 1
        self.rewardGen.time_since_dmg_taken = time.time()
        self.rewardGen.curr_boss_hp = 1
        self.rewardGen.prev_boss_hp = 1
        self.action_history = []
        self.t_start = time.time()


        '''📍 5. Return the first observation (Gymnasium API)'''
        frame = self.grab_screen_shot()
        observation = cv2.resize(frame, (MODEL_WIDTH, MODEL_HEIGHT))    #Reset also returns the first observation for the agent
        spaces_dict = { 
            'img': observation,                                         #The image
            'prev_actions': self.oneHotPrevActions(self.action_history),#The last 10 actions (empty)
            'state': np.asarray([1.0, 1.0])                             #Full hp and full stamina
        }
        
        print('🔄✔️ Reset done.')
        return spaces_dict, {}                                          #return the new observation


    '''No render function implemented (just look at the game)'''
    def render(self, mode='human'):
        pass


    '''Closing the environment (not used)'''
    def close (self):
        self.cap.release()
