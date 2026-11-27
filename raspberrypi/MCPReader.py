import RPi.GPIO as GPIO
import spidev
import time

class MCP3008_Reader:
    def __init__(self):
     
        self.spi = spidev.SpiDev()
        self.spi.open(0, 0)
        self.spi.max_speed_hz = 1350000
        self.sensor_config = {
            'light': {
                'channel': 1,
                'convert': self._convert_light,
                'interval': 2
            },
            'moisture': {
                'channel': 0,
                'convert': self._convert_moisture,
                'interval': 3
            },
            'wind': {
                'channel': 2,
                'convert': self._convert_wind,
                'interval': 0.5,
                'thresholds': (1.63, 1.66)
            }
        }
        self.last_read = {sensor: 0 for sensor in self.sensor_config}

    def _read_channel(self, channel, samples=5):
      
        total = 0
        for _ in range(samples):
            adc = self.spi.xfer2([1, (8 + channel) << 4, 0])
            data = ((adc[1] & 0x03) << 8) + adc[2]
            total += data
            time.sleep(0.01)
        return total / samples

    def _convert_light(self, raw):
     
        return 100-round(raw / 1023 * 100, 1)  # 转换为百分比

    def _convert_moisture(self, raw):
      
        return round((raw / 1023) * 100, 1)  # 反向百分比

    def _convert_wind(self, raw):
   
        voltage = (raw / 1023) * 3.3
        low, high = self.sensor_config['wind']['thresholds']
    
        if low <= voltage <= high:
            return 0.0  
        elif voltage > high:
            return voltage  
        else:
            return -voltage 

    def read_sensor(self, sensor_type):
       
        cfg = self.sensor_config[sensor_type]
        now = time.time()
        
        if now - self.last_read[sensor_type] >= cfg['interval']:
            raw = self._read_channel(cfg['channel'])
            value = cfg['convert'](raw)
            self.last_read[sensor_type] = now
            return value
        return None

    def cleanup(self):
       
        self.spi.close()
        GPIO.cleanup()

if __name__ == "__main__":
    try:
        reader = MCP3008_Reader()
        
       
        GPIO.setmode(GPIO.BCM)
       

        while True:
           
            light = reader.read_sensor('light')
            moisture = reader.read_sensor('moisture')
            wind = reader.read_sensor('wind')

       
            if light is not None:
                print(f"Light Level: {light}%")
            if moisture is not None:
                print(f"Moisture: {moisture}%")
            if wind is not None:
                print(f"Wind Status: {wind}")

            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\nMonitoring stopped.")
    finally:
        reader.cleanup()