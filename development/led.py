import time
import RPi.GPIO as gpio

class LED:
    def __init__(self, pin=6, duty_cycle=50):
        self.pin = pin
        self.duty_cycle = duty_cycle
        self.pwm = None
        self.setup()
        self.state = True

    def setup(self):
        gpio.setwarnings(False)
        gpio.setmode(gpio.BCM)
        gpio.setup(self.pin, gpio.OUT)
        self.pwm = gpio.PWM(self.pin, 50)

    def toggle(self):
        self.state = not self.state
        if self.state:
            self.pwm.start(self.duty_cycle)
        else:
            self.pwm.stop()

    def on(self):
        self.state = True
        self.pwm.start(self.duty_cycle)

    def off(self):
        self.state = False
        self.pwm.stop()


led = LED()


