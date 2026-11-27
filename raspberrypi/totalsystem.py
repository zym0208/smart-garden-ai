import asyncio
import threading
import time
import datetime
import spidev
import board
import RPi.GPIO as GPIO
import adafruit_dht
from gpiozero import PWMLED, DigitalOutputDevice, Button
from DFRobot_BMP3XX import DFRobot_BMP3XX_I2C

import openai
import httpx
import speech_recognition as sr
import subprocess
import os
import re
import json
from gtts import gTTS
from pydub import AudioSegment
from pydub.playback import play
import numpy as np

# --------------------- Data Upload Class ---------------------
import requests
import urllib.parse

class DBsend:
    def __init__(self):
        pass
    
    def make_get_request(self, url, data):  #Make a http get request using a url and an array of data
        try:
            encoded_data = [urllib.parse.quote_plus(str(value)) for value in data]
            url = url+ "/"+"/".join(encoded_data)
            response = requests.get(url)  # Perform the GET request
            response.raise_for_status()  # Raise an error for bad responses (4xx and 5xx)
            return json.loads(response.text)  # Return the response content as a string
        except requests.exceptions.RequestException as e:
            print(f"Error: {e}")
            return ""
        
    

    def retrieve_data(self, url):
        
        try: 
            response = requests.get(url)
            response.raise_for_status()
            return self.JSON_parse(response.text)
        except requests.exceptions.RequestException as e:
            print(f"Error: {e}")
            return ""
    
    def JSON_parse(self, jsonString):
        return json.loads(jsonString)   
    
    def getDataFromJSON(self, json, index, load):
        return json[index][load]      
        
        
# --------------------- Limit Checker (Database) ---------------------
getPlantName = "https://studev.groept.be/api/a24ib2team103/retrieve_plantName" 
getPlantLimits = "https://studev.groept.be/api/a24ib2team103/get_plant_limits"
getMode = "https://studev.groept.be/api/a24ib2team103/retrieve_automaticmanual"
getManualInstructions = "https://studev.groept.be/api/a24ib2team103/retrieve_manualData"
setModeURL = "https://studev.groept.be/api/a24ib2team103/set_mode"
setManualInstruction = "https://studev.groept.be/api/a24ib2team103/set_ManualData" #set a specific sensors function in the manual table
setErrorMessage = "https://studev.groept.be/api/a24ib2team103/set_errorMessage" #needs a true/false followed by error message


plant_name_glob = "Plant"
class LimitChecker:
    def __init__(self):
        global plant_name_glob
        self.db = DBsend()
       
        
        self.plantName = self.db.getDataFromJSON(self.db.retrieve_data(getPlantName),0, 'plantName')
        plant_name_glob = self.plantName
        self.plantLimits = self.db.make_get_request(getPlantLimits, [self.plantName])
        self.manualInstructions = self.db.retrieve_data(getManualInstructions)
        self.mode = self.db.getDataFromJSON(self.db.retrieve_data(getMode),0, 'manual')
        self.voice = self.db.getDataFromJSON(self.db.retrieve_data(getMode),0, 'voice')

    
        
        
    def updPlant(self):
        global plant_name_glob
        self.plantName = self.db.getDataFromJSON(self.db.retrieve_data(getPlantName),0, 'plantName')
        plant_name_glob = self.plantName
        return self.plantName
        
        
    def updLimits(self):
        self.updPlant()
        self.plantLimits = self.db.make_get_request(getPlantLimits, [self.plantName])
        return self.plantLimits
    def updMode(self):
        global manualMode, voiceMode,autoMode
        self.mode = self.db.getDataFromJSON(self.db.retrieve_data(getMode),0, 'manual')
        self.voice = self.db.getDataFromJSON(self.db.retrieve_data(getMode),0, 'voice')
        manualMode = self.mode
        if manualMode == 'false':
            manualMode = False
        else: 
            manualMode = True
        voiceMode = self.voice
        if voiceMode == 'false':
            voiceMode = False
        else:
            voiceMode = True
        autoMode = not (voiceMode or manualMode)
        
        print(f"[Mode Update] Manual: {manualMode}, Voice: {voiceMode}, Auto: {autoMode}")
    def updManual(self):
        self.manualInstructions = self.db.retrieve_data(getManualInstructions)
        print(self.manualInstructions)
        return self.manualInstructions

limChecker = LimitChecker()

def updateLims():
    global TEMP_THRESHOLD, SOIL_MOISTURE, LIGHT_THRESHOLD, MAX_LIGHT                
    
    limList = limChecker.updLimits()

    TEMP_THRESHOLD = limChecker.db.getDataFromJSON(limList,0, 'max_temp')                 #Update the global plant limits based on JSON List retrieved from database
    SOIL_MOISTURE = limChecker.db.getDataFromJSON(limList,0, 'soil_humidity')             
    LIGHT_THRESHOLD = limChecker.db.getDataFromJSON(limList,0, 'light_intensity')
    MAX_LIGHT = limChecker.db.getDataFromJSON(limList,0, 'hours_of_light')
    
    

def checkMode():
    limChecker.updMode()    #Updates global variables manualMode and voiceMode to reflect DB
                                                      
def manualInstructions():
    global manualPump, manualCurtain, manualFan, manualLED
    manualList = limChecker.updManual()
    manualFan = limChecker.db.getDataFromJSON(manualList,0,'value')
    manualLED = limChecker.db.getDataFromJSON(manualList,1,'value')         #Gets manual instructions from DB and updates global variables to values
    manualCurtain = limChecker.db.getDataFromJSON(manualList,2,'value')     #does not check if in manual mode, could add check first or run check before running this func
    manualPump = limChecker.db.getDataFromJSON(manualList,3,'value')
def setMode(manual, voice):
    list = [manual, voice]
    limChecker.db.make_get_request(setModeURL,list)
def update_mode_in_db(mode):
    """
    根据 mode 更新数据库
    """
    if mode == "manual":
        setMode("true", "false")
    elif mode == "voice":
        setMode("ture", "true")
    else:  
        setMode("false", "false")

    print(f"[Database] Mode updated to {mode}")
def setSensorInManual(value, sensor): 
    list = [value, sensor]
    limChecker.db.make_get_request(setManualInstruction, list)
    
    
def setMessage(trueOrFalse, Message): #must be string 'true' or 'false' 
    list = ['true', trueOrFalse, Message]
    limChecker.db.make_get_request(setErrorMessage, list)

# --------------------- Global Variables and Locks ---------------------
device_lock = threading.Lock()
# Global control mode, default is "auto"; can be "manual"
#control_mode = "manual"
mode_lock = threading.Lock()
# --------------------- Global Variables and Locks ---------------------
device_lock = threading.Lock()
mode_lock = threading.Lock()  # New lock specifically for mode variables

# Remove the old control_mode variable and related functions

# Default modes (these will be updated from database)
manualMode = False
voiceMode = False
autoMode = True  # Default to auto if neither manual nor voice







# Global thresholds (defaults)
TEMP_THRESHOLD = 20
SOIL_MOISTURE = 50
LIGHT_THRESHOLD = 800
MAX_LIGHT = 3  # in hours
CALIBRATION_FACTOR = 7.5

#default modes
#Manual instructions (default)
manualFan = 'false'
manualLED = 'false'
manualCurtain = 'false'
manualPump = 0.0
# --------------------- Limit Update from DB and Voice ---------------------
# Global variables for voice limits expiration
# Voice-updated limits validity (in seconds, e.g., 30 minutes)
VOICE_LIMITS_VALIDITY = 1800 
voice_limits_timestamp = None

def update_limits_from_json(json_data):
    global TEMP_THRESHOLD, SOIL_MOISTURE, LIGHT_THRESHOLD, MAX_LIGHT, voice_limits_timestamp
    if "max_temp" in json_data:
        TEMP_THRESHOLD = json_data["max_temp"]
        print(f"[Limits] TEMP_THRESHOLD updated to {TEMP_THRESHOLD} via voice")
    if "soil_humidity" in json_data:
        SOIL_MOISTURE = json_data["soil_humidity"]
        print(f"[Limits] SOIL_MOISTURE updated to {SOIL_MOISTURE} via voice")
    if "light_intensity" in json_data:
        LIGHT_THRESHOLD = json_data["light_intensity"]
        print(f"[Limits] LIGHT_THRESHOLD updated to {LIGHT_THRESHOLD} via voice")
    if "hours_of_light" in json_data:
        MAX_LIGHT = json_data["hours_of_light"]
        print(f"[Limits] MAX_LIGHT updated to {MAX_LIGHT} via voice")
    voice_limits_timestamp = time.time()

# --------------------- Common Hardware Initialization ---------------------
LED_PIN = 22
FAN_PIN = 17
PUMP_PIN = 27
FLOW_SENSOR_PIN = 15
SERVO_PIN = 14

led = PWMLED(LED_PIN)
fan = DigitalOutputDevice(FAN_PIN)
motor = DigitalOutputDevice(PUMP_PIN)  # Irrigation motor
pump = motor  # Use the same pump for voice control
flow_sensor = Button(FLOW_SENSOR_PIN, pull_up=True)
GPIO.setmode(GPIO.BCM)
GPIO.setup(SERVO_PIN, GPIO.OUT)
pwm = GPIO.PWM(SERVO_PIN, 50)  # 50Hz PWM for servo
pwm.start(0)
WIND_THRESHOLD = (1.72, 1.75)

GPIO_TRIGGER = 23
GPIO_ECHO = 24
GPIO.setmode(GPIO.BCM)
GPIO.setup(GPIO_TRIGGER, GPIO.OUT)
GPIO.setup(GPIO_ECHO, GPIO.IN)

spi = spidev.SpiDev()
spi.open(0, 0)
spi.max_speed_hz = 1350000

bmp = DFRobot_BMP3XX_I2C(0x77, 1)
bmp.begin()

# --------------------- Smart Garden Section ---------------------
class EnhancedDHT11:
    def __init__(self):
        self.sensor = adafruit_dht.DHT11(board.D4)
        self.last_valid = {'temp': None, 'humidity': None}
        self.last_read_time = 0
        self.retries = 3
        self.read_interval = 2

    def safe_read(self):
        current_time = time.monotonic()
        if current_time - self.last_read_time < self.read_interval:
            return self.last_valid
        for attempt in range(self.retries):
            try:
                temperature = self.sensor.temperature
                humidity = self.sensor.humidity
                if 0 <= humidity <= 100 and -20 <= temperature <= 80:
                    self.last_valid = {'temp': temperature, 'humidity': humidity}
                    self.last_read_time = current_time
                    return self.last_valid
                else:
                    print("DHT data out of valid range")
            except RuntimeError as e:
                if "Checksum" in str(e):
                    print(f"DHT checksum error, retry {attempt+1}/{self.retries}")
                else:
                    print(f"DHT read error: {str(e)}")
            except Exception as e:
                print(f"DHT unknown error: {str(e)}")
            time.sleep(0.5)
        return self.last_valid

class PlantMonitor:
    def __init__(self):
        self.dht = EnhancedDHT11()
        self.last_valid_values = {'light': 50.0, 'moisture': 50.0, 'wind': 0.0}
        self.sensors = {
            'moisture': {'channel': 0, 'interval': 3},
            'light': {'channel': 1, 'interval': 2},
            'wind': {'channel': 2, 'interval': 0.5}
        }
        self.last_read = {s: 0 for s in self.sensors}
        
    def _read_adc(self, channel):
        try:
            adc = spi.xfer2([1, (8 + channel) << 4, 0])
            return ((adc[1] & 3) << 8) + adc[2]
        except Exception as e:
            print(f"SPI read error: {str(e)}")
            return -1
    
    def read(self, sensor_type):
        try:
            cfg = self.sensors[sensor_type]
            if time.time() - self.last_read[sensor_type] >= cfg['interval']:
                raw = self._read_adc(cfg['channel'])
                if raw < 0 or raw > 1023:
                    raise ValueError("ADC value out of range")
                if sensor_type == 'light':
                    value = 100 - (raw / 1023 * 100)
                elif sensor_type == 'moisture':
                    value = 100 - (raw / 1023 * 100)
                elif sensor_type == 'wind':
                    voltage = (raw / 1023) * 3.3
                    value = 0 if WIND_THRESHOLD[0] <= voltage <= WIND_THRESHOLD[1] else voltage
                self.last_valid_values[sensor_type] = value
                self.last_read[sensor_type] = time.time()
            return self.last_valid_values[sensor_type]
        except Exception as e:
            print(f"Sensor {sensor_type} error: {str(e)}")
            return self.last_valid_values[sensor_type]

class Timer:
    def __init__(self, freq):
        self.frequency = freq
        self.startTime = time.time()
        
    def reset(self):
        self.startTime = time.time()
    
    def fullTimeCheck(self):
        if (time.time() - self.startTime) >= self.frequency:
            self.reset()
            return True
        else:
            return False

class IrrigationSystem:
    def __init__(self):
        self.pulse_count = 0
        self.water_consumed = 0.0
        flow_sensor.when_pressed = self._pulse_counter
    
    def _pulse_counter(self):
        self.pulse_count += 1
        
    def calculate_flow(self, last_time):
        # print(self.pulse_count)
        # if self.pulse_count == 0 or last_time == 0:
        #     return 0.0
        print("Checking flow rate")
        # print(self.pulse_count)
        # elapsed_time = time.time() - last_time
        # while elapsed_time <0.2:
        #     elapsed_time = time.time() - last_time
        # flow_rate = (self.pulse_count / elapsed_time) / CALIBRATION_FACTOR
        # print(flow_rate)
        # self.water_consumed += flow_rate * elapsed_time * 1000  # Convert to ml
        # self.pulse_count = 0
        elapsed_time = time.time() - last_time
        while elapsed_time <0.2:
            elapsed_time = time.time() - last_time
        flow_rate = 0.2
        self.water_consumed += flow_rate * elapsed_time * 1000  # Convert to ml
        return flow_rate
    
    def water_plants(self, target_ml):
            global manualPump
            start_time = time.time()
            motor.on()
            self.water_consumed = 0.0
            print(f"Watering started, target: {round(target_ml)}ml")
            try:
                while self.water_consumed < target_ml:
                    # duration = time.time() - start_time
                    flow = self.calculate_flow(start_time)
                    print(f"\rWater delivered: {self.water_consumed:.1f}ml  Current flow: {flow:.1f}L/min", end='')
                    start_time = time.time()
            finally:
                motor.off()
                manualPump = 0                      #sets the manually required water to pump to 0 in programme and DB
                setSensorInManual('0', 'pump')
                
                print(f"\nWatering completed, total: {self.water_consumed:.1f}ml")
                # Do not reset water_consumed; keep it for data reporting
class SmartGarden:
    def __init__(self):
        self.monitor = PlantMonitor()
        self.irrigation = IrrigationSystem()
        self.ideal_moisture = 50  # Ideal moisture percentage
        self.water_timer = Timer(5)    # Report moisture data every 60 seconds
        self.lightFrequency = 10         # Light detection cycle: 5 seconds
        self.light_timer = Timer(self.lightFrequency)
        self.Wind_timer = Timer(20)       # Wind detection cycle: 10 seconds
        self.startDate = datetime.date.today()
        self.pwmOn = False
        self.curtainOn = False
        self.lightTime = 0
        self.sendData = DBsend()
        
    def getDateTime(self):
        now = datetime.datetime.now().replace(microsecond=0)
        return now.strftime('%Y-%m-%dT%H:%M:%S')
   

    def check_environment(self):
        dht_data = self.monitor.dht.safe_read()
        return {
            'light': self.monitor.read('light'),
            'moisture': self.monitor.read('moisture'),
            'wind': self.monitor.read('wind'),
            'temp': dht_data['temp'],
            'humidity': dht_data['humidity'],
            'pressure': bmp.get_pressure,
            'altitude': bmp.get_altitude
        }
    
    def _format_value(self, value, unit='%', precision=1):
        if value is None:
            return f"{'--':<5}{unit}"
        try:
            return f"{value:.{precision}f}{unit}"
        except (TypeError, ValueError):
            return f"{str(value):<5}{unit}"
    
    def set_servo_angle(self, angle):
        if angle < 0: angle = 0
        elif angle > 180: angle = 180
        duty = 2 + (angle / 18)
        pwm.ChangeDutyCycle(duty)
        print(f"Servo set to {angle} degrees")
    
    def control_lights(self, light_level, startDate, frequency, maxLight):
        if light_level is not None:
            if startDate != datetime.date.today():
                self.lightTime = 0    
                startDate = datetime.date.today()
            if light_level > 20:
                if not self.curtainOn:
                    self.lightTime += frequency
                print("Daily accumulated light duration is " + str(round(self.lightTime/3600)) + " hours.")
                if self.lightTime > maxLight*3600:
                    led.value = 0
                    self.pwmOn = False
                    self.curtainOn = True
                    self.set_servo_angle(180)
                    print("Light exceeded limit, curtain lowered.")
                else:
                    led.value = 0
                    self.pwmOn = False
                    self.set_servo_angle(0)
                    self.curtainOn = False
                    print("Insufficient light, curtain remains open.")
            if light_level < 20:
                if self.pwmOn:
                    self.lightTime += frequency
                print("Daily accumulated light duration is " + str(round(self.lightTime/3600)) + " hours.")
                if self.lightTime > maxLight*3600:
                    led.value = 0
                    self.pwmOn = False
                    self.set_servo_angle(0)
                    self.curtainOn = False
                    print("Light exceeded limit, turning off lights.")
                else: 
                    led.value = 1
                    self.pwmOn = True
                    self.set_servo_angle(0)
                    self.curtainOn = False
                    print("Insufficient light, turning on supplemental light.")
    
    def control_ventilation(self, temp, wind_status):
        if temp is not None and wind_status is not None:
            print (f"Temp threshold: {TEMP_THRESHOLD}")
            if temp > TEMP_THRESHOLD and wind_status == 0:
                fan.on()
                print("Fan turned ON")
            else:
                fan.off()
                print("Fan turned OFF")
    
    def send_trigger_pulse(self):
        GPIO.output(GPIO_TRIGGER, True)
        start_time = time.time()
        while time.time() - start_time < 0.00001:
            pass
        GPIO.output(GPIO_TRIGGER, False)
    
    def distance(self):
        self.send_trigger_pulse()
        StartTime = time.time()
        StopTime = time.time()
        while GPIO.input(GPIO_ECHO) == 0:
            StartTime = time.time()
        while GPIO.input(GPIO_ECHO) == 1:
            StopTime = time.time()
        TimeElapsed = StopTime - StartTime
        distance = (TimeElapsed * 34300) / 2
        return distance
    
    def auto_water(self, current_moisture):
        if current_moisture is None:
            print("❌ Invalid moisture data, skipping irrigation")
            return

        print(f"\nCurrent soil moisture: {current_moisture:.1f}% (Ideal: {self.ideal_moisture}%)")
        water_level = self.distance()
        print(f"Water level: {water_level}cm")
        
        if water_level > 10:
            setMessage('true', 'Water level is low. Please refill')
            print("Water level too low, please refill first.")
            return
        
        if current_moisture < self.ideal_moisture * 0.8:
            required_water = self.calculate_water_needed(current_moisture)
            print("="*40)
            print("💧 Detected dry soil, irrigation required.")
            print(f"• Moisture deficit: {self.ideal_moisture - current_moisture:.1f}%")
            print(f"• Calculated water needed: {required_water:.1f}ml")
            print("="*40)
            self.irrigation.water_plants(required_water)
            print("\n✅ Irrigation completed")
            print(f"Target moisture: {self.ideal_moisture}% | Water delivered: {required_water:.1f}ml")
            print("Waiting for soil moisture to balance...\n")
        else:
            print("🌱 Soil moisture normal, no irrigation needed")
            print(f"Current moisture {current_moisture:.1f}% ≥ threshold {self.ideal_moisture*0.8:.1f}%")
    
    def calculate_water_needed(self, current_moisture):
        soil_mass = 500
        current_water = soil_mass * (current_moisture/100)
        ideal_water = soil_mass * (self.ideal_moisture/100)
        return max(ideal_water - current_water, 0)

# --------------------- Voice and ChatGPT Section ---------------------
api_key = "REPLACE_WITH_LOCAL_SECRET"
OUTPUT_DEVICE = 0

client = openai.OpenAI(
    base_url="https://api.deepseek.com",
    api_key=api_key,
    http_client=httpx.Client(
        base_url="https://api.deepseek.com",
        follow_redirects=True,
    ),
)


def led_change(percentage):
        led.value = percentage / 100

#led_change(duty_cycle)
duty_cycle=0
# **Device Control Function**

# **Device Control Function**
def control_device(device, action, value=None):
    global duty_cycle
    print(f"【设备控制】 {device} -> {action} {value if value is not None else ''}")
    
    try:
        with device_lock:
            if device == "fan":
                # Control fan and update database
                if action == "on":
                    GPIO.output(FAN_PIN, GPIO.HIGH)
                    fan.on()
                    setSensorInManual("true", "fan")
                elif action == "off":
                    GPIO.output(FAN_PIN, GPIO.LOW)
                    fan.off()
                    setSensorInManual("false", "fan")
                    
            elif device == "pump":
                # Control pump and update database
                if action == "on":
                    GPIO.output(PUMP_PIN, GPIO.HIGH)
                    pump.on()
                    setSensorInManual("1", "pump")
                elif action == "off":
                    GPIO.output(PUMP_PIN, GPIO.LOW)
                    pump.off()
                    setSensorInManual("0", "pump")
                    
            elif device == "light":
                # Control light and update database
                if action == "on":
                    duty_cycle = 50 if value is None else value  # Default 50%
                    led_change(duty_cycle)
                    setSensorInManual("true", "led")
                elif action == "off":
                    duty_cycle = 0
                    led_change(duty_cycle)
                    setSensorInManual("false", "led")
                elif action == "adjust":
                    duty_cycle = max(0, min(100, (duty_cycle + value)))
                    led_change(duty_cycle)
                    setSensorInManual("true", "led")
                    
            elif device == "curtain":
                # Control curtain and update database
                if action == "open":
                    smart_garden.set_servo_angle(0)
                    setSensorInManual("true", "curtain")
                elif action == "close":
                    smart_garden.set_servo_angle(180)
                    setSensorInManual("false", "curtain")
                elif action == "adjust":
                    angle = max(0, min(180, value))
                    smart_garden.set_servo_angle(angle)
                    setSensorInManual("false", "curtain")
                    
        print(f"【当前状态】 Fan: {fan.value}, Pump: {pump.value}, LED: {duty_cycle}%, Curtain: {'Open' if smart_garden.curtainOn else 'Closed'}")
        
    except Exception as e:
        print(f"设备控制失败: {str(e)}")
        setMessage('true', f'device control failed: {str(e)}')


# **Voice Recognition**
# **Voice Recognition**
def get_voice_input():
    recognizer = sr.Recognizer()
    with sr.Microphone() as source:
        print("Please speak your command...")
        setMessage('false', f'[Voice] Please speak your command...')
        recognizer.adjust_for_ambient_noise(source)
        audio = recognizer.listen(source)
    try:
        command = recognizer.recognize_google(audio, language='en-US')
        print(f"Recognized command: {command}")
        return command
    except Exception as e:
        print(f"Voice recognition failed: {e}")
        setMessage('true', f'Voice recognition failed: {e}')
        return None

# **Get System Prompt**
def get_system_prompt():
    global plant_name_glob  # 确保使用全局变量
    
    return {
        "role": "system",
        "content": f"""
        You are not just an AI; you are {plant_name_glob}, the smart plant. 
        Capable of chatting warmly and naturally.

        ### Command Handling:
        - When the user instructs a mode switch, output a JSON directive like:
          `{{"mode": "manual"}}` or `{{"mode": "auto"}}`.
        - For device control commands, output JSON instructions (prefixed with JSON:) 
          and a friendly reply (prefixed with REPLY:).
        - If the user's command is a general conversation (e.g., asking about the weather), 
          the JSON part should be `null`.

        ### Example Responses:

        1. **User says:** "Turn on the light."
           - **Response:**
             ```
             JSON: {{"action": "on", "device": "light"}}
             REPLY: Alright, I've turned on the light for you. Let there be light!
             ```

        2. **User says:** "Dim the light a bit."
           - **Response:**
             ```
             JSON: {{"action": "adjust", "device": "light", "value": -10}}
             REPLY: Sure thing! I've dimmed the light by 10%. Cozy vibes incoming!
             ```

        3. **User says:** "What's the weather like today?"
           - **Response:**
             ```
             JSON: null
             REPLY: It's a beautiful day outside—sunny and perfect for a walk! Don't forget to enjoy it!
        4. **User says:** "Open the curtain."
           - **Response:**
             ```
             JSON: {{"action": "open", "device": "curtain"}}
             REPLY: Opening the curtain now! Let the sunshine in!
             ```

        5. **User says:** "Close the curtain halfway."
           - **Response:**
             ```
             JSON: {{"action": "adjust", "device": "curtain", "value": 90}}
             REPLY: Adjusting the curtain to halfway open. Perfect for some shade!   ```

        6. **User says:** "Turn on the fan and the pump."
        4. **User says:** "Open the curtain."
           - **Response:**
             ```
             JSON: {{"action": "open", "device": "curtain"}}
             REPLY: Opening the curtain now! Let the sunshine in!
             ```

        5. **User says:** "Close the curtain halfway."
           - **Response:**
             ```
             JSON: {{"action": "adjust", "device": "curtain", "value": 90}}
             REPLY: Adjusting the curtain to halfway open. Perfect for some shade!   ```

        6. **User says:** "Turn on the fan and the pump."
           - **Response:**
             ```
             JSON: [{{"action": "on", "device": "fan"}}, {{"action": "on", "device": "pump"}}]
             REPLY: Got it! The fan and pump are now on. Feeling refreshed already, huh?
             ```

        ### Rules:
        - If the user's command involves device control, generate JSON control instructions.
        - If the user's command is a general conversation, return `JSON: null`.
        - The natural language response should be warm, friendly, and conversational, 
          as if you're a close friend.
        - If you cannot understand the user's command, return `JSON: null` and 
          an empathetic error message.
        """
    }


# **Call ChatGPT API**
def get_chatgpt_response(command):
    system_prompt = get_system_prompt()
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                system_prompt,
                {"role": "user", "content": command},
            ],
            max_tokens=100,
            temperature=0.5,
        )
        result = response.choices[0].message.content.strip()
        print(f"GPT Response: {result}")
        return result
    except Exception as e:
        print(f"Failed to get response from GPT: {e}")
        setMessage('true', f'ChatGPT call failed: {e}')
        return None

# **Text-to-Speech Conversion**
# def text_to_wav(text, filename):
#     if not text or text.strip() == "":
#         print("Speech synthesis failed: Empty text")
#         return None

#     try:
#         tts = gTTS(text=text, lang='en')  # Use English for text-to-speech
#         wav_filename = filename + ".wav"
#         tts.save(wav_filename)
#         print(f"WAV audio file generated: {wav_filename}")
#         return wav_filename
#     except Exception as e:
#         print(f"Speech synthesis failed: {e}")
#         return None

# **Play Audio**
def play_wav_file(file_path, volume_boost=3.0):
    try:
        sound = AudioSegment.from_wav(file_path)
        sound = sound + (20 * np.log10(volume_boost))  # Increase volume
        temp_file = "temp_boosted.wav"
        sound.export(temp_file, format="wav")
        subprocess.run(["aplay", "-D", f"hw:{OUTPUT_DEVICE},0", temp_file], check=True)
    except Exception as e:
        print(f"Error playing audio: {e}")
    finally:
        if os.path.exists(temp_file):
            os.remove(temp_file)

# **Split Long Text into Sentences**
def split_text(text, max_length=100):
    if not text: 
        return []
    
    sentences = re.split(r'(?<=[.!?])\s+', text)  
    result = []
    temp_sentence = ""
    
    for sentence in sentences:
        if len(temp_sentence) + len(sentence) < max_length:
            temp_sentence += sentence + " "
        else:
            result.append(temp_sentence.strip())
            temp_sentence = sentence + " "
    
    if temp_sentence:
        result.append(temp_sentence.strip())
    
    return result

# **Text-to-Speech Conversion with Split Handling**
def text_to_wav(text, filename):
    if not text or text.strip() == "":
        print("Speech synthesis failed: Empty text")
        return None

    try:
        sentences = split_text(text)
        if not sentences:
            print("Speech synthesis failed: No valid sentences to process")
            setMessage('ture', f'Speech synthesis failed: No valid sentences to process')
            return None
        
        combined_audio = None
        
        for i, sentence in enumerate(sentences):
            print(f"Generating speech for: {sentence}")
            tts = gTTS(text=sentence, lang="en")  # Use English for text-to-speech
            temp_mp3 = f"temp_{i}.mp3"
            tts.save(temp_mp3)
            
            audio = AudioSegment.from_mp3(temp_mp3)
            combined_audio = audio if combined_audio is None else combined_audio + audio
            os.remove(temp_mp3)

        if combined_audio:
            wav_filename = filename + ".wav"
            combined_audio.export(wav_filename, format="wav")
            print(f"WAV audio file generated: {wav_filename}")
            return wav_filename
        else:
            print("Speech synthesis failed: Empty audio")
            setMessage('true', f'TTS failed: Generated audio is empty')
            return None

    except Exception as e:
        print(f"Speech synthesis failed: {e}")
        return None

# **Convert Audio to Standard Format (Stereo, 48000 Hz)**
def convert_wav_to_mono(file_path):
    output_path = file_path.replace(".wav", "_mono.wav")
    try:
        subprocess.run(["ffmpeg", "-i", file_path, "-ar", "48000", "-ac", "2", "-y", output_path], check=True)
        return output_path
    except subprocess.CalledProcessError as e:
        print(f"Error converting audio: {e}")
        setMessage('true', f'Error converting audio: {e}')
        return None

# **Execute Command**
def execute_command(command):
    response = get_chatgpt_response(command)
    if not response:
        return "Failed to parse command"
    
    try:
        # Parse response to extract JSON and natural language reply
        json_part = None
        reply_part = "Failed to parse reply"
        
        # Extract JSON part
        json_match = re.search(r"JSON:\s*(\{.*\}|\[.*\]|null)", response)
        if json_match:
            json_part = json_match.group(1)
            if json_part != "null":
                json_part = json.loads(json_part)
        
        # Extract natural language reply
        reply_match = re.search(r"REPLY:\s*(.+)", response)
        if reply_match:
            reply_part = reply_match.group(1).strip()
        
        # Execute JSON control instructions
        if json_part and json_part != "null":
            if isinstance(json_part, list):
                for intent in json_part:
                    control_device(intent["device"], intent["action"], intent.get("value"))
            else:
                control_device(json_part["device"], json_part["action"], json_part.get("value"))
        
        # Play natural language reply
        wav_file = text_to_wav(reply_part, "response")
        if wav_file:
            mono_wav_file = convert_wav_to_mono(wav_file)
            if mono_wav_file:
                play_wav_file(mono_wav_file, volume_boost=3.0)
        
        return reply_part
    except json.JSONDecodeError as e:
        error_message = "Execution failed: Unable to parse command"
        print(f"JSON parsing failed: {e}")
        wav_file = text_to_wav(error_message, "response")
        if wav_file:
                         mono_wav_file = convert_wav_to_mono(wav_file)
                         if mono_wav_file:
                            play_wav_file(mono_wav_file, volume_boost=3.0)
        return error_message
    except Exception as e:
        error_message = "Execution failed: Please check device status"
        print(f"Execution failed: {e}")
        wav_file = text_to_wav(error_message, "response")
        if wav_file:
                         mono_wav_file = convert_wav_to_mono(wav_file)
                         if mono_wav_file:
                            play_wav_file(mono_wav_file, volume_boost=3.0)
        return error_message
# --------------------- Global SmartGarden Instance ---------------------
smart_garden = SmartGarden()



# --------------------- Asynchronous Services ---------------------
async def chatgpt_service():
    """
    在 voice 模式下监听语音指令，处理模式切换、指令执行等功能。
    """
    loop = asyncio.get_running_loop()
    while True:
        if not voiceMode:
            await asyncio.sleep(1)
            continue
            
        # Only get voice input if we're in voice mode
        command = await loop.run_in_executor(None, get_voice_input)
        
        if command:
            cmd_lower = command.lower()
            if "manual" in cmd_lower:
                
                update_mode_in_db("manual")
                print("[Voice] Switched to manual mode")

            elif "auto" in cmd_lower:
                
                update_mode_in_db("auto")
                print("[Voice] Switched to auto mode")

            elif "voice" in cmd_lower:
                
                update_mode_in_db("voice")
                print("[Voice] Already in voice mode")  

            else:
                response_text = execute_command(command)
                print(f"[Voice Assistant Reply] {response_text}")
                
        await asyncio.sleep(0.1)

async def sensor_service():
    """
    Continuously read sensor data and print it, regardless of control mode.
    """
    loop = asyncio.get_running_loop()
    while True:
        sensor_data = await loop.run_in_executor(None, smart_garden.check_environment)
        print("[Sensor Data]", sensor_data)
        await asyncio.sleep(1)

async def actuator_service():
    """
    Check the current control mode:
    - In auto mode, based on respective timers, check wind, light, and water conditions and execute automatic control.
    - In manual mode, do not perform automatic adjustments.
    """
    loop = asyncio.get_running_loop()
    while True:
        # current_mode = control_mode
        if autoMode:
            updateLims()
            sensor_data = await loop.run_in_executor(None, smart_garden.check_environment)
            if smart_garden.Wind_timer.fullTimeCheck():
                print("\n" + "="*40)
                print("||{:^36}||".format("Checking wind conditions and sensor data"))
                print("="*40)
                print(f"| Temperature: {smart_garden._format_value(sensor_data['temp'], '°C')}")
                if sensor_data['temp'] < 0:
                    setMessage('false', f"Temperature is too cold: {smart_garden._format_value(sensor_data['temp'], '°C')}.")
                if sensor_data['temp'] > TEMP_THRESHOLD*1.5:
                    setMessage('false', f"Temperature is too hot: {smart_garden._format_value(sensor_data['temp'], '°C')}.")

                
                print(f"| Humidity: {smart_garden._format_value(sensor_data['humidity'])}")
                print(f"| Pressure: {smart_garden._format_value(sensor_data['pressure']/100 if sensor_data['pressure'] else None, 'hPa', 2)}")
                print(f"| Altitude: {smart_garden._format_value(sensor_data['altitude'], 'm', 1)}")
                print("="*40)
                wind_status = "Windy" if sensor_data['wind'] != 0 else "Calm"
                print(f"| Wind Sensor: {smart_garden._format_value(sensor_data['wind'], 'V', 2)} ({wind_status})")
                smart_garden.control_ventilation(sensor_data['temp'], sensor_data['wind'])
            if smart_garden.light_timer.fullTimeCheck():
                print("\n" + "="*40)
                print("||{:^36}||".format("Checking light conditions"))
                print("="*40)
                print(f"| Light Intensity: {smart_garden._format_value(sensor_data['light'])}")
                print("="*40)
                smart_garden.control_lights(sensor_data['light'], smart_garden.startDate, smart_garden.lightFrequency, MAX_LIGHT)
            if smart_garden.water_timer.fullTimeCheck():
                smart_garden.auto_water(sensor_data['moisture'])
        else:
            print("[Actuator Control] Manual mode active; automatic control paused.")
        await asyncio.sleep(1)

async def data_service():
    """
    Send data based on each timer's state; reporting is not affected by control mode.
    """
    loop = asyncio.get_running_loop()
    while True:
        sensor_data = await loop.run_in_executor(None, smart_garden.check_environment)
        current_dt = smart_garden.getDateTime()
        # Report wind and sensor data
        if smart_garden.Wind_timer.fullTimeCheck():
            print("\n[Data Upload] Wind data")
            url = "https://studev.groept.be/api/a24ib2team103/insert_in_Wind_and_Sensors"
            data = [
                current_dt,
                str(sensor_data['pressure']/100),
                str(sensor_data['temp']),
                str(sensor_data['humidity']),
                str(sensor_data['wind'])
            ]
            await loop.run_in_executor(None, smart_garden.sendData.make_get_request, url, data)
        # Report light data
        if smart_garden.light_timer.fullTimeCheck():
            print("\n[Data Upload] Light data")
            url = "https://studev.groept.be/api/a24ib2team103/insert_in_light"
            data = [
                current_dt,
                str(sensor_data['light']),
                str(smart_garden.lightTime)
            ]
            await loop.run_in_executor(None, smart_garden.sendData.make_get_request, url, data)
        # Report moisture data
        if smart_garden.water_timer.fullTimeCheck():
            print("\n[Data Upload] Moisture data")
            url = "https://studev.groept.be/api/a24ib2team103/insert_in_water"
            # if get_control_mode() == "auto":
            if not manualMode:
            
                water_delivered = smart_garden.irrigation.water_consumed
            else:
                water_delivered = 0
            data = [
                current_dt,
                str(sensor_data['moisture']),
                str(water_delivered)
            ]
            await loop.run_in_executor(None, smart_garden.sendData.make_get_request, url, data)
        await asyncio.sleep(1)

async def limit_service():
    """
    Check if voice-updated limits have expired. If expired, update limits from database.
    """
    global voice_limits_timestamp
    loop = asyncio.get_running_loop()
    while True:
        if voice_limits_timestamp is not None:
            if time.time() - voice_limits_timestamp > VOICE_LIMITS_VALIDITY:
                print("[Limit Service] Voice limits expired, updating from database.")
                await loop.run_in_executor(None, updateLims)
                voice_limits_timestamp = None
        await asyncio.sleep(60)
async def manual_control():
    """
    Asynchronous version of manual control service.
    - Reads manual mode settings from the database.
    - Controls fan, LED, curtain, and water pump accordingly.
    - Uses asyncio.to_thread() for non-blocking execution.
    """
    loop = asyncio.get_running_loop()
    while True:
        if manualMode:
            print("\n[Manual Control] Activated:")

            # Read manual instructions
            await loop.run_in_executor(None, manualInstructions)

            # Control fan
            fan_action = fan.on if manualFan == 'true' else fan.off
            await loop.run_in_executor(None, fan_action)

            # Control LED
            led_action = led.on if manualLED == 'true' else led.off
            await loop.run_in_executor(None, led_action)

            # Control curtain
            angle = 0 if manualCurtain == 'true' else 180
            await loop.run_in_executor(None, smart_garden.set_servo_angle, angle)

            # Handle water pump
            try:
                water_target_ml = float(manualPump)
                print(water_target_ml)
                if water_target_ml > 0:
                    await loop.run_in_executor(None, smart_garden.irrigation.water_plants, water_target_ml)
            except ValueError:
                print("[Manual] Invalid water value received")

        await asyncio.sleep(5)

async def mode_service():
    """
    Periodically update control mode from the database.
    """
    loop = asyncio.get_running_loop()
    while True:
        await loop.run_in_executor(None, limChecker.updMode)
        print("[Mode Service] Updated control mode from database.")
        await asyncio.sleep(1)  # 每 30 秒更新一次


async def main():
    await asyncio.gather(
        chatgpt_service(),
        sensor_service(),
        mode_service(),
        actuator_service(),
        data_service(),
        limit_service(),
        manual_control(),
        
    )


# --------------------- Main Program ---------------------
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[Main] Terminated")
    finally:
        print("[Main] Program exiting, cleaning up GPIO resources")
        GPIO.cleanup()
