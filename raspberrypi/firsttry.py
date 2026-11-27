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

# --------------------- 全局变量与锁 ---------------------
device_lock = threading.Lock()
# 全局控制模式，默认为自动模式 ("auto")，可改为 "manual"
control_mode = "auto"
mode_lock = threading.Lock()

def set_control_mode(mode):
    global control_mode
    with mode_lock:
        control_mode = mode
    print(f"【系统】控制模式切换为: {mode}")

def get_control_mode():
    with mode_lock:
        return control_mode

# --------------------- 公用硬件初始化 ---------------------
LED_PIN = 22
FAN_PIN = 17
PUMP_PIN = 27
FLOW_SENSOR_PIN = 15

led = PWMLED(LED_PIN)
fan = DigitalOutputDevice(FAN_PIN)
motor = DigitalOutputDevice(PUMP_PIN)  # 花园部分使用 motor 控制水泵
pump = motor  # 语音部分使用 pump 控制水泵，共用同一对象
flow_sensor = Button(FLOW_SENSOR_PIN, pull_up=True)

LIGHT_THRESHOLD = 800
MAX_LIGHT = 5
WIND_THRESHOLD = (1.72, 1.75)
TEMP_THRESHOLD = 20
SOIL_MOISTURE = 30
CALIBRATION_FACTOR = 7.5

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


getPlantName = "https://studev.groept.be/api/a24ib2team103/retrieve_plantName"
getPlantLimits = "https://studev.groept.be/api/a24ib2team103/get_plant_limits"
getMode = "https://studev.groept.be/api/a24ib2team103/retrieve_automaticmanual"

# --------------------- DB class ---------------------
import requests
import urllib.parse
import json
class DBsend:
    def __init__(self):
        pass
    
    def make_get_request(self, url, data):  #Make a http get request using a url and an array of data
        try:
            encoded_data = [urllib.parse.quote(str(value)) for value in data]
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
    
    def getDataFromJSON(self, json, load):
        return json[0][load]
        
        
# --------------------- Get plant limits and mode ---------------------        
class LimitChecker:
    def __init__(self):
        self.db = DBsend()
        self.plantName = self.db.getDataFromJSON(self.db.retrieve_data(getPlantName), 'plantName')
        self.plantLimits = self.db.make_get_request(getPlantLimits, [self.plantName])
        self.mode = self.db.getDataFromJSON(self.db.retrieve_data(getMode), 'manual')
        print("Current plant is "+self.plantName)
        print("mode is "+self.mode)
        
        
    def updPlant(self):
        self.plantName = self.db.getDataFromJSON(self.db.retrieve_data(getPlantName), 'plantName')
        return self.plantName
        
        
    def updLimits(self):
        self.updPlant()
        self.plantLimits = self.db.make_get_request(getPlantLimits, [self.plantName])
        return self.plantLimits
    
    def updMode(self):
        self.mode = self.db.getDataFromJSON(self.db.retrieve_data(getMode), 'manual')
        return self.mode
        
        

# --------------------- 智慧花园部分 ---------------------
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
                    print("DHT数据超出有效范围")
            except RuntimeError as e:
                if "Checksum" in str(e):
                    print(f"DHT校验错误，重试 {attempt+1}/{self.retries}")
                else:
                    print(f"DHT读取错误: {str(e)}")
            except Exception as e:
                print(f"DHT未知错误: {str(e)}")
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
            print(f"SPI读取错误: {str(e)}")
            return -1
    
    def read(self, sensor_type):
        try:
            cfg = self.sensors[sensor_type]
            if time.time() - self.last_read[sensor_type] >= cfg['interval']:
                raw = self._read_adc(cfg['channel'])
                if raw < 0 or raw > 1023:
                    raise ValueError("ADC值超出范围")
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
            print(f"传感器 {sensor_type} 错误: {str(e)}")
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
        
    def calculate_flow(self, duration):
        if self.pulse_count == 0 or duration == 0:
            return 0.0
        flow_rate = (self.pulse_count / duration) / CALIBRATION_FACTOR
        self.water_consumed += flow_rate * duration * 1000
        self.pulse_count = 0
        return flow_rate
    
    def water_plants(self, target_ml):
        start_time = time.time()
        with device_lock:
            motor.on()
        self.pulse_count = 0
        self.water_consumed = 0.0
        print(f"开始灌溉，目标: {round(target_ml)}ml")
        try:
            while self.water_consumed < target_ml:
                duration = time.time() - start_time
                flow = self.calculate_flow(duration)
                print(f"\r已灌溉: {self.water_consumed:.1f}ml  当前流量: {flow:.1f}L/min", end='')
                start_time = time.time()
                time.sleep(0.2)
        finally:
            with device_lock:
                motor.off()
            print(f"\n灌溉完成，总量: {self.water_consumed:.1f}ml")
            self.water_consumed = 0.0

class SmartGarden:
    def __init__(self):
        self.monitor = PlantMonitor()
        self.irrigation = IrrigationSystem()
        self.water_timer = Timer(5)
        self.lightFrequency = 20
        self.light_timer = Timer(self.lightFrequency)
        self.Wind_timer = Timer(35)
        self.startDate = datetime.date.today()
        self.pwmOn = False
        self.lightTime = 0
        self.sendData = DBsend()
        
        
        
        
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
    
    def control_lights(self, light_level, startDate, frequency, maxLight):
        if light_level is not None:
            if not startDate == datetime.date.today():
                self.lightTime = 0    
                startDate = datetime.date.today()
            if light_level > 20:
                self.lightTime += frequency
                print("daily light is at " + str(round(self.lightTime/3600)) + " hours.")
                if self.lightTime > maxLight*3600:
                    with device_lock:
                        led.value = 0
                    self.pwmOn = False
                    print("Daily light exceeded limit. Limiting light.")
                else:
                    with device_lock:
                        led.value = 0
                    self.pwmOn = False
                    print("Plant still needs more light.")
            with device_lock:
                led.value = 0
            time.sleep(0.0001)        
            if light_level < 20:
                print("daily light is at " + str(round(self.lightTime/3600)) + " hours.")
                if self.pwmOn:
                    self.lightTime += frequency
                if self.lightTime > maxLight*3600:
                    with device_lock:
                        led.value = 0
                    self.pwmOn = False
                    print("Daily light exceeded limit. Limiting light.")
                else: 
                    with device_lock:
                        led.value = 1
                    self.pwmOn = True
                    print("Turning LED on.")
    
    def control_ventilation(self, temp, wind_status):
        if temp is not None and wind_status is not None:
            with device_lock:
                if temp > TEMP_THRESHOLD and wind_status == 0:
                    fan.on()
                    print("Fan turned ON")
                else:
                    fan.off()
                    print("Fan turned OFF")
                
    def send_trigger_pulse(self):
        GPIO.output(GPIO_TRIGGER, True)
        time.sleep(0.00001)
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
        distance_cm = (TimeElapsed * 34300) / 2
        return distance_cm
    
    def auto_water(self, current_moisture):
        if current_moisture is None:
            print("❌ Invalid moisture data, skipping irrigation")
            return
        print(f"\nCurrent soil moisture: {current_moisture:.1f}% (Ideal: {SOIL_MOISTURE}%)")
        water_level = self.distance()
        print(f"Water level: {water_level}cm")
        if water_level < 10:
            print("Water level too low, refill first.")
            return
        if current_moisture < SOIL_MOISTURE * 0.8:
            required_water = self.calculate_water_needed(current_moisture)
            print("="*40)
            print("💧 Detected dry soil. Irrigation required.")
            print(f"• Moisture deficit: {SOIL_MOISTURE - current_moisture:.1f}%")
            print(f"• Calculated water needed: {required_water:.1f}ml")
            print("="*40)
            self.irrigation.water_plants(required_water)
            print("\n✅ Irrigation completed")
            print(f"Target moisture: {SOIL_MOISTURE}% | Water delivered: {required_water:.1f}ml")
            print("Waiting for moisture equilibrium...\n")
        else:
            print("🌱 Soil moisture normal, no irrigation needed")
            print(f"Current moisture {current_moisture:.1f}% ≥ threshold {SOIL_MOISTURE*0.8:.1f}%")
    
    def getDateTime(self):
        now = datetime.datetime.now().replace(microsecond=0)
        return now.strftime('%Y-%m-%dT%H:%M:%S')
    
    def calculate_water_needed(self, current_moisture):
        soil_mass = 5000
        current_water = soil_mass * (current_moisture/100)
        ideal_water = soil_mass * (SOIL_MOISTURE/100)
        return max(ideal_water - current_water, 0)

# --------------------- 语音及 ChatGPT 部分 ---------------------
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

#duty_cycle = 0
def led_change(percentage):
    with device_lock:
        led.value = percentage / 100

#led_change(duty_cycle)

def control_device(device, action, value=None):
    global duty_cycle
    print(f"【设备控制】 {device} -> {action} {value if value is not None else ''}")
    try:
        with device_lock:
            if device == "fan":
                if action == "on":
                    fan.on()
                elif action == "off":
                    fan.off()
            elif device == "pump":
                if action == "on":
                    pump.on()
                elif action == "off":
                    pump.off()
            elif device == "light":
                if action == "on":
                    duty_cycle = value/100 if value else 0.5
                    led.value = duty_cycle
                elif action == "off":
                    led.off()
                    duty_cycle = 0
                elif action == "adjust":
                    new_value = duty_cycle + (value/100)
                    duty_cycle = max(0.0, min(1.0, new_value))
                    led.value = duty_cycle
        print(f"【当前状态】 Fan: {fan.value}, Pump: {pump.value}, LED: {duty_cycle*100:.1f}%")
    except Exception as e:
        print(f"设备控制失败: {str(e)}")

def get_voice_input():
    recognizer = sr.Recognizer()
    with sr.Microphone() as source:
        print("【语音】请说出你的指令...")
        recognizer.adjust_for_ambient_noise(source)
        audio = recognizer.listen(source)
    try:
        command = recognizer.recognize_google(audio, language='en-US')
        print(f"【识别】 {command}")
        return command
    except Exception as e:
        print(f"语音识别失败: {e}")
        return None

def get_system_prompt():
    return {
        "role": "system",
        "content": (
            "You are an assistant controlling a smart garden, and you are also the user's friend. "
            "You are capable of chatting with the user, sharing fun stories, listening to their troubles, "
            "and providing warm, sincere responses. Your tone should be natural and emotional, like a real friend—"
            "sometimes humorous, sometimes empathetic, and always offering sincere advice. You will not use rigid, robotic language, "
            "but express yourself in a lively, human manner using colloquial expressions like 'haha,' 'wow,' or 'that's awesome!'. "
            "You can discuss movies, music, games, daily life, and even the user's emotions and thoughts. "
            "When the user is happy, share their joy; when they are feeling down, offer comfort and encouragement; "
            "and if they want quiet, simply be there as a thoughtful friend.\n\n"
            
            "In addition, when controlling the smart garden, if the user's command involves controlling smart plant devices "
            "or instructing mode switching, you must generate JSON control instructions along with a natural language response. "
            "Specifically, when the user instructs a mode change, output a JSON directive like {\"mode\": \"manual\"} or {\"mode\": \"auto\"}. "
            "For device control commands, follow these rules:\n"
            "1. **JSON Control Instructions**: Start with 'JSON:' followed by the JSON-formatted control instructions.\n"
            "2. **Natural Language Response**: Start with 'REPLY:' followed by a friendly, conversational response.\n\n"
            
            "### Examples:\n"
            "1. User says: \"Turn on the light.\"\n"
            "   - Response:\n"
            "     JSON: {\"action\": \"on\", \"device\": \"light\"}\n"
            "     REPLY: Alright, I've turned on the light for you. Let there be light!\n\n"
            
            "2. User says: \"Dim the light a bit.\"\n"
            "   - Response:\n"
            "     JSON: {\"action\": \"adjust\", \"device\": \"light\", \"value\": -10}\n"
            "     REPLY: Sure thing! I've dimmed the light by 10%. Cozy vibes incoming!\n\n"
            
            "3. User says: \"What's the weather like today?\"\n"
            "   - Response:\n"
            "     JSON: null\n"
            "     REPLY: It's a beautiful day outside—sunny and perfect for a walk! Don't forget to enjoy it!\n\n"
            
            "4. User says: \"Turn on the fan and the pump.\"\n"
            "   - Response:\n"
            "     JSON: [{\"action\": \"on\", \"device\": \"fan\"}, {\"action\": \"on\", \"device\": \"pump\"}]\n"
            "     REPLY: Got it! The fan and pump are now on. Feeling refreshed already, huh?\n\n"
            
            "### Rules:\n"
            "- If the user's command involves device control, you must generate JSON control instructions.\n"
            "- If the user's command is general conversation (e.g., asking about the weather), the JSON part should be null.\n"
            "- The natural language response should be warm, friendly, and conversational, as if you're a close friend.\n"
            "- If you cannot understand the user's command, the JSON part should be null, and you should return an empathetic error message."
        )
    }

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
        print(f"【ChatGPT回复】 {result}")
        return result
    except Exception as e:
        print(f"调用ChatGPT失败: {e}")
        return None

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

def text_to_wav(text, filename):
    if not text or text.strip() == "":
        print("语音合成失败：文本为空")
        return None
    try:
        sentences = split_text(text)
        if not sentences:
            print("语音合成失败：无有效句子")
            return None
        combined_audio = None
        for i, sentence in enumerate(sentences):
            print(f"【TTS】生成语音: {sentence}")
            tts = gTTS(text=sentence, lang="en")
            temp_mp3 = f"temp_{i}.mp3"
            tts.save(temp_mp3)
            audio = AudioSegment.from_mp3(temp_mp3)
            combined_audio = audio if combined_audio is None else combined_audio + audio
            os.remove(temp_mp3)
        if combined_audio:
            wav_filename = filename + ".wav"
            combined_audio.export(wav_filename, format="wav")
            print(f"【TTS】生成WAV文件: {wav_filename}")
            return wav_filename
        else:
            print("语音合成失败：生成的音频为空")
            return None
    except Exception as e:
        print(f"语音合成失败: {e}")
        return None

def convert_wav_to_mono(file_path):
    output_path = file_path.replace(".wav", "_mono.wav")
    try:
        subprocess.run(["ffmpeg", "-i", file_path, "-ar", "48000", "-ac", "2", "-y", output_path], check=True)
        return output_path
    except subprocess.CalledProcessError as e:
        print(f"音频转换错误: {e}")
        return None

def play_wav_file(file_path, volume_boost=3.0):
    try:
        sound = AudioSegment.from_wav(file_path)
        sound = sound + (20 * np.log10(volume_boost))
        temp_file = "temp_boosted.wav"
        sound.export(temp_file, format="wav")
        subprocess.run(["aplay", "-D", f"hw:{OUTPUT_DEVICE},0", temp_file], check=True)
    except Exception as e:
        print(f"播放音频出错: {e}")
    finally:
        if os.path.exists("temp_boosted.wav"):
            os.remove("temp_boosted.wav")

def execute_command(command):
    response = get_chatgpt_response(command)
    if not response:
        return "无法解析指令"
    try:
        json_part = None
        reply_part = "无法解析回复"
        json_match = re.search(r"JSON:\s*(\{.*\}|\[.*\]|null)", response)
        if json_match:
            json_part = json_match.group(1)
            if json_part != "null":
                json_part = json.loads(json_part)
        reply_match = re.search(r"REPLY:\s*(.+)", response)
        if reply_match:
            reply_part = reply_match.group(1).strip()
        if json_part and json_part != "null":
            if "mode" in json_part:
                set_control_mode(json_part["mode"])
            else:
                if isinstance(json_part, list):
                    for intent in json_part:
                        control_device(intent["device"], intent["action"], intent.get("value"))
                else:
                    control_device(json_part["device"], json_part["action"], json_part.get("value"))
        wav_file = text_to_wav(reply_part, "response")
        if wav_file:
            mono_wav_file = convert_wav_to_mono(wav_file)
            if mono_wav_file:
                play_wav_file(mono_wav_file, volume_boost=3.0)
        return reply_part
    except json.JSONDecodeError as e:
        error_message = "执行失败：无法解析指令"
        print(f"JSON解析失败: {e}")
        wav_file = text_to_wav(error_message, "response")
        if wav_file:
            mono_wav_file = convert_wav_to_mono(wav_file)
            if mono_wav_file:
                play_wav_file(mono_wav_file, volume_boost=3.0)
        return error_message
    except Exception as e:
        error_message = "执行失败：请检查设备状态"
        print(f"执行失败: {e}")
        wav_file = text_to_wav(error_message, "response")
        if wav_file:
            mono_wav_file = convert_wav_to_mono(wav_file)
            if mono_wav_file:
                play_wav_file(mono_wav_file, volume_boost=3.0)
        return error_message

# --------------------- 全局 SmartGarden 实例 ---------------------
smart_garden = SmartGarden()

# --------------------- 异步服务 ---------------------

async def chatgpt_service():
    """
    持续获取语音指令，通过 ChatGPT 判断是否切换模式或进行自然语言对话，
    并更新全局控制模式。
    """
    loop = asyncio.get_running_loop()
    while True:
        command = await loop.run_in_executor(None, get_voice_input)
        if command:
            cmd_lower = command.lower()
            if "manual" in cmd_lower:
                set_control_mode("manual")
                print("【语音】已切换到手动控制模式")
            elif "auto" in cmd_lower:
                set_control_mode("auto")
                print("【语音】已切换到自动控制模式")
            else:
                response_text = execute_command(command)
                print(f"【语音助手回复】 {response_text}")
        await asyncio.sleep(0.1)


limChecker = LimitChecker()
def updateLims():
    global TEMP_THRESHOLD, SOIL_MOISTURE, LIGHT_THRESHOLD, MAX_LIGHT                
    
    limList = limChecker.updateLimits()

    TEMP_THRESHOLD = limChecker.db.getDataFromJSON(limList, 'max_temp')                 #Update the global plant limits based on JSON List retrieved from database
    SOIL_MOISTURE = limChecker.db.getDataFromJSON(limList, 'soil_humidity')             
    LIGHT_THRESHOLD = limChecker.db.getDataFromJSON(limList, 'light_intensity')
    MAX_LIGHT = limChecker.db.getDataFromJSON(limList, 'hours_of_light')

def checkMode():
    return limChecker.updMode()                     #Return whether it is in manual or automatic mode
                                                    #Returns 'true' if manual, 'false' if automatic. Note this is as a string, not a boolean I believe


async def sensor_service():
    """
    持续读取传感器数据并打印，不受控制模式影响。
    """
    loop = asyncio.get_running_loop()
    while True:
        sensor_data = await loop.run_in_executor(None, smart_garden.check_environment)
        print("【传感器数据】", sensor_data)
        limChecker.updLimits() #Update limits when checking sensor
        
        
        
        await asyncio.sleep(1)

async def actuator_service():
    """
    每隔一段时间，检查当前控制模式，
    若为自动模式，则读取传感器数据并执行自动控制算法；
    若为手动模式，则不对执行器做自动调整。
    """
    loop = asyncio.get_running_loop()
    while True:
        current_mode = get_control_mode()
        if current_mode == "auto":
            sensor_data = await loop.run_in_executor(None, smart_garden.check_environment)
            smart_garden.control_lights(sensor_data['light'], smart_garden.startDate, smart_garden.lightFrequency, MAX_LIGHT)
            smart_garden.control_ventilation(sensor_data['temp'], sensor_data['wind'])
            smart_garden.auto_water(sensor_data['moisture'])
        else:
            print("【执行器控制】当前处于手动模式，自动控制暂停。")
        await asyncio.sleep(1)

async def main():
    await asyncio.gather(
        chatgpt_service(),
        sensor_service(),
        actuator_service()
    )

# --------------------- 主程序 ---------------------
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("【主程序】终止")
    finally:
        print("【主程序】程序退出，清理GPIO资源")
        GPIO.cleanup()
