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
from gpiozero import PWMLED, DigitalOutputDevice, Button
import threading
import spidev
import time
import adafruit_dht
import board
import datetime
from DFRobot_BMP3XX import DFRobot_BMP3XX_I2C
import RPi.GPIO as GPIO

# --------------------- 硬件初始化 ---------------------
# PWM控制的LED
led = PWMLED(22)  # GPIO22
duty_cycle = 0.5  # 初始亮度50%

# 数字输出设备（风扇和水泵）
fan = DigitalOutputDevice(17)  # GPIO17
pump = DigitalOutputDevice(27) # GPIO27

# 超声波传感脚
GPIO.setmode(GPIO.BCM)
 
GPIO_TRIGGER = 23
GPIO_ECHO = 24
 
GPIO.setup(GPIO_TRIGGER, GPIO.OUT)
GPIO.setup(GPIO_ECHO, GPIO.IN)

# 流量传感器
FLOW_SENSOR_PIN = 15
flow_sensor = Button(FLOW_SENSOR_PIN, pull_up=True)

# 传感器初始化
spi = spidev.SpiDev()
spi.open(0, 0)
spi.max_speed_hz = 1350000
bmp = DFRobot_BMP3XX_I2C(0x77, 1)
bmp.begin()

# --------------------- 全局配置 ---------------------
api_key = "REPLACE_WITH_LOCAL_SECRET"
OUTPUT_DEVICE = 0  # 音频输出设备号
LIGHT_THRESHOLD = 800
WIND_THRESHOLD = (1.72, 1.75)
TEMP_THRESHOLD = 20
CALIBRATION_FACTOR = 7.5
lock = threading.Lock()

# --------------------- 语音控制部分 ---------------------
class VoiceControl:
    def __init__(self):
        self.client = openai.OpenAI(
            base_url="https://api.deepseek.com",
            api_key=api_key,
            http_client=httpx.Client(
                base_url="https://api.deepseek.com",
                follow_redirects=True,
            ),
        )
        self.in_conversation = False

    def control_device(self, device, action, value=None):
        """线程安全的设备控制"""
        with lock:
            try:
                print(f"控制设备: {device}, 操作: {action}, 值: {value}")
                if device == "fan":
                    if action == "on": fan.on()
                    elif action == "off": fan.off()
                elif device == "pump":
                    if action == "on": pump.on()
                    elif action == "off": pump.off()
                elif device == "light":
                    if action == "on":
                        new_value = (value/100) if value else 0.5
                        led.value = new_value
                    elif action == "off":
                        led.off()
                    elif action == "adjust":
                        new_value = led.value + (value/100)
                        led.value = max(0.0, min(1.0, new_value))
                print(f"当前状态 - 风扇: {fan.value}, 水泵: {pump.value}, 灯光亮度: {led.value*100:.1f}%")
            except Exception as e:
                print(f"设备控制失败: {str(e)}")

    def get_voice_input(self):
        recognizer = sr.Recognizer()
        with sr.Microphone() as source:
            print("请说出你的指令...")
            recognizer.adjust_for_ambient_noise(source)
            audio = recognizer.listen(source)
        try:
            command = recognizer.recognize_google(audio, language='en-US')
            print(f"识别到的指令: {command}")
            return command
        except Exception as e:
            print(f"语音识别失败: {e}")
            return None

    def get_system_prompt(self):
        return {
            "role": "system",
            "content": '''（保持原有的prompt内容不变）'''
        }

    def get_chatgpt_response(self, command):
        system_prompt = self.get_system_prompt()
        try:
            response = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[system_prompt, {"role": "user", "content": command}],
                max_tokens=100,
                temperature=0.5,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"GPT请求失败: {e}")
            return None
        


    # 正确的方法缩进（4空格）
    def split_text(self, text, max_length=100):
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

    def text_to_wav(self, text, filename):
        if not text or text.strip() == "":
            print("Speech synthesis failed: Empty text")
            return None

        try:
            sentences = self.split_text(text)
            if not sentences:
                print("Speech synthesis failed: No valid sentences to process")
                return None
            
            combined_audio = None
            
            for i, sentence in enumerate(sentences):
                print(f"Generating speech for: {sentence}")
                tts = gTTS(text=sentence, lang="en")
                temp_mp3 = f"temp_{i}.mp3"
                tts.save(temp_mp3)
                
                audio = AudioSegment.from_mp3(temp_mp3)
                combined_audio = audio if combined_audio is None else combined_audio + audio
                os.remove(temp_mp3)

            if combined_audio:
                wav_filename = filename + ".wav"
                combined_audio.export(wav_filename, format="wav")
                return wav_filename
            return None
        except Exception as e:
            print(f"Speech synthesis failed: {e}")
            return None

    def convert_wav_to_mono(self, file_path):
        output_path = file_path.replace(".wav", "_mono.wav")
        try:
            subprocess.run(
                ["ffmpeg", "-i", file_path, 
                 "-ar", "48000", "-ac", "2", "-y", 
                 output_path],
                check=True
            )
            return output_path
        except subprocess.CalledProcessError as e:
            print(f"Error converting audio: {e}")
            return None

    def execute_command(self, command):
        response = self.get_chatgpt_response(command)
        if not response: 
            return "指令解析失败"

        try:
            # 解析JSON和自然语言回复
            json_part = re.search(r"JSON:\s*(\{.*\}|\[.*\]|null)", response)
            reply_part = re.search(r"REPLY:\s*(.+)", response)
            
            # 执行设备控制
            if json_part and json_part.group(1) != "null":
                instructions = json.loads(json_part.group(1))
                if isinstance(instructions, list):
                    for cmd in instructions:
                        self.control_device(cmd["device"], cmd["action"], cmd.get("value"))
                else:
                    self.control_device(instructions["device"], instructions["action"], instructions.get("value"))
            
            # 语音反馈
            if reply_part:
                reply_text = reply_part.group(1).strip()
                wav_file = self.text_to_wav(reply_text, "response")
                if wav_file:
                    mono_wav_file = self.convert_wav_to_mono(wav_file)
                    if mono_wav_file:
                        self.play_wav_file(mono_wav_file, volume_boost=3.0)
            
            return reply_text if reply_part else ""
        except Exception as e:
            print(f"指令执行失败: {e}")
            return "指令执行出错"
    

    def voice_loop(self):
        try:
            while True:
                command = self.get_voice_input()
                if command:
                    if "hello" in command.lower():
                        self.in_conversation = True
                        self.text_to_speech("Hello! How can I assist you today?")
                    elif "bye" in command.lower():
                        self.in_conversation = False
                        self.text_to_speech("Goodbye! Have a great day!")
                    elif self.in_conversation:
                        self.execute_command(command)
                time.sleep(1)
        except KeyboardInterrupt:
            print("语音线程退出")
class EnhancedDHT11:
    def __init__(self):
        self.sensor = adafruit_dht.DHT11(board.D4)
        self.last_valid = {'temp': None, 'humidity': None}
        self.last_read_time = 0
        self.retries = 3
        self.read_interval = 2  # DHT11 minimum read interval

    def safe_read(self):
        """Safely read sensor data with retry mechanism and rate limiting"""
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
        
        return self.last_valid  # Return last valid value

# --------------------- Sensor Reader Class ---------------------
class PlantMonitor:
    def __init__(self):
        self.dht = EnhancedDHT11()
        self.last_valid_values = {
            'light': 50.0,
            'moisture': 50.0,
            'wind': 0.0
        }
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

# --------------------- Timer Class ---------------------
class Timer:
    def __init__(self, freq):
        self.frequency = freq
        self.startTime = time.time()
        
    def reset(self):
        self.startTime = time.time()
    
    def print(self):
        print(self.startTime)
        print(time.time() )
        print(self.frequency)
    
    def fullTimeCheck(self):
        if (time.time() - self.startTime) >= self.frequency:
            self.reset()
            return True
        else:
            return False

# --------------------- System Modules ---------------------
class IrrigationSystem:
    def __init__(self):
        self.pulse_count = 0
        self.water_consumed = 0.0
        flow_sensor.when_pressed = self._pulse_counter
    
    def _pulse_counter(self):
        self.pulse_count += 1
        #print(f"Water flow pulse detected! Total count: {self.pulse_count}")  # Debug output
        
    def calculate_flow(self, duration):
        if self.pulse_count == 0 or duration == 0:
            return 0.0
        flow_rate = (self.pulse_count / duration) / CALIBRATION_FACTOR
        self.water_consumed += flow_rate * duration * 1000  # Convert to milliliters
        self.pulse_count = 0
        return flow_rate
    
    def water_plants(self, target_ml):
        start_time = time.time()
        pump.on()
        self.pulse_count = 0
        self.water_consumed = 0.0
        print(f"Watering started, target: {round(target_ml)}ml")
        
        try:
            while self.water_consumed < target_ml:
                duration = time.time() - start_time
                flow = self.calculate_flow(duration)
                print(f"\rWater delivered: {self.water_consumed:.1f}ml  Current flow: {flow:.1f}L/min", end='')
                start_time = time.time()
                time.sleep(0.2)
        finally:
            pump.off()
            print(f"\nWatering completed, total: {self.water_consumed:.1f}ml")
            self.water_consumed = 0.0  # Reset counter

# --------------------- 自动控制部分 ---------------------
class SmartGarden:
    def __init__(self):
        self.monitor = PlantMonitor()
        self.irrigation = IrrigationSystem()
        self.ideal_moisture = 50
        self.light_timer = Timer(20)
        self.wind_timer = Timer(35)
        self.water_timer = Timer(5)

# --------------------- Enhanced DHT11 Class ---------------------
   


    def control_lights(self, light_level):
        with lock:
            if light_level < 20 and led.value == 0:
                led.on()
                print("光照不足，开启补光")
            elif light_level >= 20 and led.value == 1:
                led.off()
                print("光照充足，关闭补光")

    def control_ventilation(self, temp, wind_status):
        with lock:
            if temp > TEMP_THRESHOLD and wind_status == 0:
                fan.on()
                print("温度过高，开启风扇")
            else:
                fan.off()

    def auto_control_loop(self):
        try:
            while True:
                env_data = self.monitor.read_all()
                
                if self.wind_timer.fullTimeCheck():
                    self.control_ventilation(env_data['temp'], env_data['wind'])
                
                if self.light_timer.fullTimeCheck():
                    self.control_lights(env_data['light'])
                
                if self.water_timer.fullTimeCheck():
                    self.irrigation.check_moisture(env_data['moisture'])
                
                time.sleep(1)
        except KeyboardInterrupt:
            print("自动控制线程退出")

# --------------------- 主程序 ---------------------
if __name__ == "__main__":
    # 初始化所有设备
    led.off()
    fan.off()
    pump.off()

    # 创建控制实例
    voice_control = VoiceControl()
    smart_garden = SmartGarden()

    # 启动线程
    voice_thread = threading.Thread(target=voice_control.voice_loop)
    auto_thread = threading.Thread(target=smart_garden.auto_control_loop)

    voice_thread.start()
    auto_thread.start()

    voice_thread.join()
    auto_thread.join()

    # 清理资源
    led.close()
    fan.close()
    pump.close()
    GPIO.cleanup()
    spi.close()