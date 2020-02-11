import time
from itertools import cycle
import RPi.GPIO as gpio


# buzzer: 5
# led: 6



gpio.setmode(gpio.BCM)
pins = [5, 6, 13]
[gpio.setup(p, gpio.OUT, initial=0) for p in pins]
last = cycle(pins)
curr = cycle(pins)
next(curr)


for i, (l, c) in enumerate(zip(last, curr)):
    if i > 20: break
    gpio.output(l, False)
    gpio.output(c, True)
    time.sleep(0.2)

[gpio.output(p, False) for p in pins]
