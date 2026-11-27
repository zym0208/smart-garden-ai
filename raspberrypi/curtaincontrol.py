
import spidev
import time
import RPi.GPIO as GPIO
from gpiozero import PWMLED

# MCP3008 Channel for LDR
LDR_CHANNEL = 1  

# Light intensity thresholds
CURTAIN_OPEN_THRESHOLD = 300  # If LDR < 500 (Too much light) → Open curtain
CURTAIN_CLOSE_THRESHOLD = 800  # If LDR > 800 (Not enough light) → Close curtain
NO_ACTION_RANGE = (300, 800)  # Between these values, do nothing

# Define GPIO pins
SERVO_PIN = 14  
LED_PIN = 22

# Initialize LED
led = PWMLED(LED_PIN)

# Initialize Servo Motor
GPIO.setmode(GPIO.BCM)
GPIO.setup(SERVO_PIN, GPIO.OUT)
pwm = GPIO.PWM(SERVO_PIN, 50)  # 50Hz PWM for servo
pwm.start(0)

# Initialize SPI for MCP3008
spi = spidev.SpiDev()
spi.open(0, 0)  
spi.max_speed_hz = 1350000  

# Function to read from MCP3008
def read_adc(channel):
    if channel < 0 or channel > 7:
        return -1  
    adc = spi.xfer2([1, (8 + channel) << 4, 0])  
    data = ((adc[1] & 3) << 8) + adc[2]  
    return data

# Function to set the servo angle
def set_servo_angle(angle):
    if angle < 0:
        angle = 0
    elif angle > 180:
        angle = 180
   
    duty = 2 + (angle / 18)
    pwm.ChangeDutyCycle(duty)
    print(f"Servo set to {angle} degrees")

# Function to update LED and Curtain based on LDR
def update_system():
    ldr_value = read_adc(LDR_CHANNEL)

    print(f"LDR Value: {ldr_value}")

    # Too much light → Open Curtain
    if ldr_value < CURTAIN_OPEN_THRESHOLD:
        set_servo_angle(180)  # Open curtain
        led.value = 0  # Ensure LED is OFF
        print("Too much light! Opening curtain.")

    # Not enough light → Close Curtain & Turn ON LED
    elif ldr_value > CURTAIN_CLOSE_THRESHOLD:
        led.value = 1.0  # Turn on LED
        set_servo_angle(0)  # Close Curtain
        print("Low light detected! Closing curtain & turning LED ON.")

    # Light is in the normal range (300 - 800) → No action
    else:
        print("No action needed. Curtain and LED remain unchanged.")

# Main loop
try:
    while True:
        update_system()
        time.sleep(2)  # Update every 2 seconds

except KeyboardInterrupt:
    print("Exiting program.")

finally:
    pwm.stop()
    GPIO.cleanup()
    spi.close()


