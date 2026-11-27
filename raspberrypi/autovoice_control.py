import spidev
import time
from gpiozero import PWMLED, DigitalOutputDevice, Button
import adafruit_dht
import board
import datetime
from DFRobot_BMP3XX import DFRobot_BMP3XX_I2C

import RPi.GPIO as GPIO

# --------------------- Hardware Initialization ---------------------
# Lighting Control
LED_PIN = 22
led = PWMLED(LED_PIN)
LIGHT_THRESHOLD = 800

# Servo motor
SERVO_PIN = 14  
GPIO.setmode(GPIO.BCM)
GPIO.setup(SERVO_PIN, GPIO.OUT)
pwm = GPIO.PWM(SERVO_PIN, 50)  # 50Hz PWM for servo
pwm.start(0)

# Ventilation System
FAN_PIN = 17
fan = DigitalOutputDevice(FAN_PIN)
WIND_THRESHOLD = (1.72, 1.75)  # No-wind voltage range
TEMP_THRESHOLD = 20 # Fan activation temperature

# Irrigation System
PUMP_PIN = 27
FLOW_SENSOR_PIN = 15
motor = DigitalOutputDevice(PUMP_PIN)
flow_sensor = Button(FLOW_SENSOR_PIN, pull_up=True)
CALIBRATION_FACTOR = 7.5  # Flow meter calibration factor


# Ultrasonic Sensor Pins
GPIO_TRIGGER = 23
GPIO_ECHO = 24

GPIO.setmode(GPIO.BCM)
GPIO.setup(GPIO_TRIGGER, GPIO.OUT)
GPIO.setup(GPIO_ECHO, GPIO.IN)

# Sensor Initialization
spi = spidev.SpiDev()
spi.open(0, 0)
spi.max_speed_hz = 1350000

bmp = DFRobot_BMP3XX_I2C(0x77, 1)
bmp.begin()

# --------------------- Upload to DB class ---------------------
import requests
import urllib.parse
class DBsend:
    def __init__(self):
        pass
    
    def make_get_request(self, url, data):  #Make a http get request using a url and an array of data
        try:
            encoded_data = [urllib.parse.quote(str(value)) for value in data]
            url = url+ "/"+"/".join(encoded_data)
            response = requests.get(url)  # Perform the GET request
            response.raise_for_status()  # Raise an error for bad responses (4xx and 5xx)
            return response.text  # Return the response content as a string
        except requests.exceptions.RequestException as e:
            print(f"Error: {e}")
            return ""
# --------------------- Enhanced DHT11 Class ---------------------
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
        motor.on()
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
            motor.off()
            print(f"\nWatering completed, total: {self.water_consumed:.1f}ml")
            self.water_consumed = 0.0  # Reset counter

# --------------------- Main Control System ---------------------
class SmartGarden:
    def __init__(self):
        self.monitor = PlantMonitor()
        self.irrigation = IrrigationSystem()
        self.ideal_moisture = 50  # Ideal moisture percentage
        self.water_timer = Timer(60)
        self.lightFrequency = 5
        self.light_timer = Timer(self.lightFrequency)
        self.Wind_timer = Timer(10)
        self.startDate = datetime.date.today()
        self.pwmOn = False
        self.curtainOn = False
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
    
    def set_servo_angle(self, angle):
        if angle < 0:
            angle = 0
        elif angle > 180:
            angle = 180
   
        duty = 2 + (angle / 18)
        pwm.ChangeDutyCycle(duty)
        print(f"Servo set to {angle} degrees")
    
    def _format_value(self, value, unit='%', precision=1):
        """Uniform value formatting"""
        if value is None:
            return f"{'--':<5}{unit}"
        try:
            return f"{value:.{precision}f}{unit}"
        except (TypeError, ValueError):
            return f"{str(value):<5}{unit}"
    
    # def control_lights(self, light_level):
    #     if light_level is not None:
    #         new_status = 1.0 if light_level < 20 else 0.0
            
    #         if new_status != self.last_led_status:
    #             if new_status == 1.0:
    #                 print("💡 Low light detected! Supplemental lighting activated.")
    #             else:
    #                 print("🌞 Sufficient light, supplemental lighting deactivated.")
    #             self.last_led_status = new_status
            
    #         led.value = new_status
    def control_lights(self, light_level, startDate, frequency, maxLight):
        if light_level is not None:
            if not startDate == datetime.date.today():
                self.lightTime = 0    
                startDate = datetime.date.today()
            if light_level > 20:
                if not (self.curtainOn):
                    self.lightTime += frequency
                print("daily light is at "+str(round(self.lightTime/3600))+" hours.")
                if self.lightTime > maxLight*3600:
                    led.value = 0
                    self.pwmOn = False
                    self.curtainOn = True
                    self.set_servo_angle(180)
                    
                    print("Daily light has exceeded the limit. Limitting light.")
                   
                else:
                    led.value = 0
                    self.pwmOn = False
                    self.set_servo_angle(0)
                    self.curtainOn = False
                    print("Plant still needs more light.")
                   

                  
            if light_level < 20:
                if (self.pwmOn):
                    self.lightTime += frequency
                print("daily light is at "+str(round(self.lightTime/3600))+" hours.")
                if self.lightTime > maxLight*3600:
                    led.value = 0
                    self.pwmOn = False
                    self.set_servo_angle(0)
                    self.curtainOn = False
                    print("Daily light has exceeded the limit. Limitting light.")
                 

                else: 
                    led.value = 1
                    self.pwmOn = True
                    self.set_servo_angle(0)
                    self.curtainOn = False
                    print("Plant still needs more light. Turning LED on")
                   

                
                
        
        
    
    def control_ventilation(self, temp, wind_status):
        if temp is not None and wind_status is not None:
            if temp > TEMP_THRESHOLD and wind_status == 0:
                fan.on()
                print("Fan turned ON")
            else:
                fan.off()
                print("Fan turned OFF")
    
    def auto_water(self, current_moisture):
        if current_moisture is None:
            print("❌ Invalid moisture data, skipping irrigation")
            return
        
        print(f"\nCurrent soil moisture: {current_moisture:.1f}% (Ideal: {self.ideal_moisture}%)")
        water_level = self.distance()
        print(f"water level is at {water_level}cm")
        
        if water_level >10:
            print("Water level too low, please refill before I can water again.")
            return
        if current_moisture < self.ideal_moisture * 0.8:
            required_water = self.calculate_water_needed(current_moisture)
            print("="*40)
            print(f"💧 Dry soil detected, irrigation required")
            print(f"• Moisture deficit: {self.ideal_moisture - current_moisture:.1f}%")
            print(f"• Calculated water needed: {required_water:.1f}ml")
            print("="*40)
            url = "https://studev.groept.be/api/a24ib2team103/insert_in_water"
            data = [str(self.getDateTime())]
            data.append(str(current_moisture))
            data.append(str(required_water))
            self.sendData.make_get_request(url, data)

            self.irrigation.water_plants(required_water)
            
            print("\n✅ Irrigation completed")
            print(f"Target moisture: {self.ideal_moisture}% | Final amount: {required_water:.1f}ml")
            print("Waiting for moisture balance...\n")
        else:
            print("🌱 Soil moisture normal, no irrigation needed")
            print(f"Current moisture {current_moisture:.1f}% ≥ threshold {self.ideal_moisture*0.8:.1f}%")
            url = "https://studev.groept.be/api/a24ib2team103/insert_in_water"
            data = [str(self.getDateTime())]
            data.append(str(current_moisture))
            data.append(str(0))
            self.sendData.make_get_request(url, data)
    
    def calculate_water_needed(self, current_moisture):
        soil_mass = 5000  # Assume 5kg soil mass
        current_water = soil_mass * (current_moisture/100)
        ideal_water = soil_mass * (self.ideal_moisture/100)
        return max(ideal_water - current_water, 0)
    
    def getDateTime(self):
        now = datetime.datetime.now().replace(microsecond=0)
        return now.strftime('%Y-%m-%dT%H:%M:%S')
    
    def run(self):
        try:
            
            while True:
                env_data = self.check_environment()
                if self.Wind_timer.fullTimeCheck():
                    print("\n" + "="*40)
                    print("||{:^36}||".format("Checking wind conditions and sensor data"))
                    print("="*40)
                    print(f"| Temperature: {self._format_value(env_data['temp'], '°C')}")
                    print(f"| Humidity: {self._format_value(env_data['humidity'])}")
                    print(f"| Pressure: {self._format_value(env_data['pressure']/100 if env_data['pressure'] else None, 'hPa', 2)}")
                    print(f"| Altitude: {self._format_value(env_data['altitude'], 'm', 1)}")
                    print("="*40)
                    wind_status = "Windy" if env_data['wind'] != 0 else "Calm"
                    print(f"| Wind Sensor: {self._format_value(env_data['wind'], 'V', 2)} ({wind_status})")
                    url = "https://studev.groept.be/api/a24ib2team103/insert_in_Wind_and_Sensors"
                    data = [str(self.getDateTime())]
                    data.append(str(env_data['pressure']/100))
                    data.append(str(env_data['temp']))
                    data.append(str(env_data['humidity']))
                    data.append(str(env_data['wind']))
                    self.sendData.make_get_request(url, data)
                    self.control_ventilation(env_data['temp'], env_data['wind'])
                if self.light_timer.fullTimeCheck():
                    print("\n" + "="*40)
                    print("||{:^36}||".format("Checking light conditions"))
                    print("="*40)
                    print(f"| Light Intensity: {self._format_value(env_data['light'])}")
                    print("="*40)
                    self.control_lights(env_data['light'], self.startDate, self.lightFrequency, 3) #change to dynamic max light
                    url = "https://studev.groept.be/api/a24ib2team103/insert_in_light"
                    data = [str(self.getDateTime())]
                    data.append(str(env_data['light']))
                    data.append(str(self.lightTime))
                    self.sendData.make_get_request(url, data)
                if self.water_timer.fullTimeCheck():
                    print("\n" + "="*40)
                    print("||{:^36}||".format("Checking plant water conditions"))
                    print("="*40)
                    print(f"| Soil Moisture: {self._format_value(env_data['moisture'])}")
                    self.auto_water(env_data['moisture'])
                
                time.sleep(1)
                
        except KeyboardInterrupt:
            print("\nSafely shutting down system...")
        finally:
            spi.close()
            led.close()
            fan.close()
            motor.close()
            flow_sensor.close()
            try:
                self.monitor.dht.sensor.exit()
            except:
                pass

# --------------------- System Startup ---------------------
if __name__ == "__main__":
    garden = SmartGarden()
    garden.run()