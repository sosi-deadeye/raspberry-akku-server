#!/usr/bin/env python3

import time
from pathlib import Path
from threading import Timer
from subprocess import call, check_output

import wlanpw

from netifaces import ifaddresses, AF_INET
from gpiozero import (
    Button,
    Buzzer,
    LED,
)

AP = "ap0"
CLIENT = "wlan0"
MODES = (AP, CLIENT)
WIFI_MODE = Path("/media/data/wifi_mode")


def set_mode(mode):
    """
    Write mode ap0 or wlan0 to file wifi_mode
    """
    if mode in MODES:
        WIFI_MODE.write_text(f"{mode}\n")


def get_mode():
    """
    Get the current mode from file wifi_mode and return it.
    If the file does not exist, AP mode is written to the file
    and returned.
    """
    mode = "ap0"
    if not WIFI_MODE.exists():
        set_mode(AP)
    else:
        mode = WIFI_MODE.read_text().strip()
        if mode not in MODES:
            set_mode(AP)
            mode = AP
    return mode


class State:
    def __init__(self):
        self._state = None

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, value):
        value = value.strip()
        if value not in ("ap0", "wlan0"):
            raise ValueError('Only "ap0" or "wlan0" is allowed')
        if value != self._state:
            if value == "ap0":
                led.off()
                print("Starting hotspot")
                call(["ifdown", "wlan0"])
                call(["systemctl", "start", "wlan-ap"])
                call(["ifup", "ap0"])
                call(["systemctl", "start", "hostapd"])
                call(
                    [
                        "ip",
                        "route",
                        "add",
                        "default",
                        "via",
                        "192.168.0.1",
                        "dev",
                        "ap0",
                    ]
                )
                self._state = value
                buzzer.beep(1, 1, n=2)
            elif value == "wlan0":
                print("Connecting to hotspot")
                led.blink(0.1, 0.1)
                call(
                    [
                        "ip",
                        "route",
                        "del",
                        "default",
                        "via",
                        "192.168.0.1",
                        "dev",
                        "ap0",
                    ]
                )
                call(["systemctl", "stop", "hostapd"])
                call(["ifdown", "ap0"])
                call(["systemctl", "start", "wlan-ap-del"])
                call(["ifup", "wlan0"])
                self._state = value
                buzzer.beep(0.5, 0.5, n=2)
                led.blink(0.1, 2)
                try:
                    ips = ifaddresses("wlan0").get(AF_INET, [])
                    hosts = Path("/media/data/hosts.custom")
                    hostname = check_output(["hostname"], encoding="utf8")
                    with hosts.open("w") as fd:
                        for ip in ips:
                            fd.write(f'{ip.get("addr")}    {hostname}\n')
                except Exception as e:
                    print(repr(e))

    def switch(self):
        self.state = "wlan0" if self.state == "ap0" else "ap0"


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
        print("ACT:", self.count, n)
        if self.count == n == 1:
            self.state.switch()
        elif self.count == n == 3:
            call(["shutdown", "-h", "0"])
        elif self.count == n == 5:
            wlanpw.reset()


if __name__ == "__main__":
    buzzer = Buzzer(5)
    led = LED(6)
    switch = SuperButton()
    # initial state is always ap0
    if get_mode() != AP:
        switch.state.switch()
        # not so proud of it
    while True:
        time.sleep(10)
