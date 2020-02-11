#!/usr/bin/env python3

import time
from pathlib import Path
from threading import Timer
from subprocess import call, check_output

import wlanpw

from netifaces import (
    ifaddresses,
    AF_INET
)
from gpiozero import (
    Button,
    Buzzer,
    LED,
)

class State:
    def __init__(self):
        self._state = None
        self.state = 'ap0'

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, value):
        value = value.strip()
        if value not in ('ap0', 'wlan0'):
            raise ValueError('Only "ap0" or "wlan0" is allowed')
        if value != self._state:
            if value == 'ap0':
                led.off()
                print('Starting hotspot')
                call(['ifdown', 'wlan0'])
                call(['systemctl', 'start', 'wlan-ap'])
                call(['ifup', 'ap0'])
                call(['systemctl', 'start', 'hostapd'])
                self._state = value
                buzzer.beep(1, 1, n=2)
            elif value == 'wlan0':
                print('Connecting to hotspot')
                led.blink(0.1, 0.1)
                call(['systemctl', 'stop', 'hostapd'])
                call(['ifdown', 'ap0'])
                call(['systemctl', 'start', 'wlan-ap-del'])
                call(['ifup', 'wlan0'])
                self._state = value
                amazon = call(['ping', '-c1', '1.1.1.1'])
                google = call(['ping', '-c1', '8.8.8.8'])
                if amazon == 0 or google == 0:
                    buzzer.beep(0.5, 0.5, n=2)
                    led.blink(0.1, 2)
                    ips = ifaddresses('wlan0').get(AF_INET, [])
                    hosts = Path('/media/data/hosts.custom')
                    hostname = check_output(['hostname'], encoding='utf8')
                    with hosts.open('w') as fd:
                        for ip in ips:
                            fd.write(f'{ip.get("addr")}    {hostname}\n')
                else:
                    self.state = 'ap0'
                    # keine Internetverbindung > autonomer Betrieb

    def switch(self):
        if self.state == 'ap0':
            self.state = 'wlan0'
        elif self.state == 'wlan0':
            self.state = 'ap0'
        else:
            self.state = 'ap0'


class SuperButton:
    def __init__(self):
        self.button = Button(13, pull_up=True, bounce_time=0.1, hold_time=0.3)
        self.button.when_held = self.callback
        self.state = State()
        self.count = 0
        self.timeout = None

    def callback(self):
        if self.timeout is None or time.time() > self.timeout:
            self.count = 1
            buzzer.beep(0.5, 0.5, n=1)
        else:
            self.count += 1
            buzzer.beep(0.1, 0.1, n=1)
        self.timeout = time.time() + 2.0
        print(self.count)
        Timer(interval=5, function=self.act, args=[self.count]).start()


    def act(self, n):
        print('ACT:', self.count, n)
        if self.count == n == 1:
            self.state.switch()
        elif self.count == n == 3:
            call(['shutdown', '-h', '0'])
        elif self.count == n == 5:
            wlanpw.reset()


if __name__ == '__main__':
    buzzer = Buzzer(5)
    led = LED(6)
    switch = SuperButton()
    while True:
        time.sleep(10)
