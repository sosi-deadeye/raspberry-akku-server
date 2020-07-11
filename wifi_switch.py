"""
This module run as deamon to control the wireless lan
connection.
"""

import time
from subprocess import call, DEVNULL
from socket import gethostname
from threading import Lock
from typing import Optional, Sequence
from threading import Timer
from pathlib import Path

from gpiozero import Button, LED, Buzzer
from netifaces import ifaddresses, gateways, AF_INET

import wlanpw


PING_IPS_TYPE = Optional[Sequence[str]]


class State:
    """
    This class manages the state of two different interfaces.
    """

    def __init__(
        self,
        local_interface: str,
        client_interface: str,
        initial_state: str,
        status_led: LED,
        buzzer: Buzzer,
        do_online_check: bool = True,
        ping_ips: PING_IPS_TYPE = None,
    ):
        """
        local_interface is for example ap0
        client_interface is usually wlan0
        initial_state is which mode should used during initialization
        do_online_check defines if the internet connection is tested
        ping_ips are the ips to ping for the online check
        """
        self.local_interface = local_interface
        self.client_interface = client_interface
        self.interfaces = [local_interface, client_interface]
        if initial_state not in self.interfaces:
            raise ValueError(f"{initial_state} is not a local nor a client interface.")
        self.status_led = status_led
        self.buzzer = buzzer
        self.do_online_check = do_online_check
        self.ping_ips = ping_ips or ("1.1.1.1", "8.8.8.8")
        self._state = initial_state
        self._lock = Lock()
        with self._lock:
            if initial_state == local_interface:
                self._toggle_ap()
            elif initial_state == client_interface:
                self._toggle_online()

    @staticmethod
    def ping_ip(ip: str) -> bool:
        """
        Ping an IP and return True if ping got a reply.
        """
        print(f"Ping ip {ip}", flush=True)
        return call(["ping", "-qc1", "-w1", ip], stdout=DEVNULL, stderr=DEVNULL) == 0

    @property
    def is_online(self) -> bool:
        """
        True if the client is online.
        """
        return any(self.ping_ip(ip) for ip in self.ping_ips)

    @property
    def local_ip(self) -> str:
        """
        The local IP address of active interface.
        """
        try:
            return ifaddresses(self._state).get(AF_INET)[0]["addr"]
        except (TypeError, KeyError, IndexError):
            return ""

    @property
    def router_ip(self) -> str:
        """
        Current router IP. If it's in local mode, the router IP is localhost.
        """
        try:
            return gateways().get("default")[AF_INET][0]
        except (TypeError, KeyError, IndexError):
            return ""

    @property
    def hostname(self) -> str:
        """
        Current hostname
        """
        return gethostname()

    def _toggle_online(self) -> None:
        self.status_led.blink(0.1, 0.1)
        self._set_mode_client()
        if self.do_online_check and not self.is_online:
            self._state = self.local_interface
            self._set_mode_ap()
            self.buzzer.beep(1, 1, n=2)
            self.status_led.off()
        elif not (self.do_online_check or self.ping_ip(self.router_ip)):
            self._state = self.local_interface
            self._set_mode_ap()
            self.buzzer.beep(1, 1, n=2)
            self.status_led.off()
        else:
            self.buzzer.beep(0.5, 0.5, n=2)
            self.status_led.blink(0.1, 2)
            self._state = self.client_interface
            call(["systemctl", "start", "ntp"])

    def _toggle_ap(self) -> None:
        call(["systemctl", "stop", "ntp"])
        self._state = self.local_interface
        self.status_led.off()
        self._set_mode_ap()
        self.buzzer.beep(1, 1, n=2)

    def _set_mode_ap(self) -> None:
        """
        Start the hotspot.
        """
        print("Starting hotspot")
        call(["ifdown", "wlan0"])
        # call(['systemctl', 'start', 'wlan-ap'])
        call(["/sbin/iw", "phy", "phy0", "interface", "add", "ap0", "type", "__ap"])
        call(["ifup", "ap0"])
        call(["systemctl", "start", "hostapd"])
        call(["ip", "route", "add", "default", "via", "192.168.0.1", "dev", "ap0"])
        print("Hostname:", self.hostname)
        print("Local IP:", self.local_ip)
        print("Router IP:", self.router_ip)

    def _set_mode_client(self) -> None:
        """
        Connect as a client to a hotspot.
        """
        print("Connecting to hotspot")
        call(["ip", "route", "del", "default", "via", "192.168.0.1", "dev", "ap0"])
        call(["systemctl", "stop", "hostapd"])
        call(["ifdown", "ap0"])
        # call(['systemctl', 'start', 'wlan-ap-del'])
        call(["/sbin/iw", "dev", "ap0", "del"])
        call(["ifup", "wlan0"])
        print("Hostname:", self.hostname)
        print("Local IP:", self.local_ip)
        print("Router IP:", self.router_ip)

    @property
    def state(self) -> str:
        """
        Current interface/mode
        """
        return self._state

    @state.setter
    def state(self, value: str) -> None:
        """
        Switch the interface/mode
        """
        if value == self._state:
            return
        with self._lock:
            if value == self.local_interface:
                self._toggle_ap()
            elif value == self.client_interface:
                self._toggle_online()

    def toggle(self) -> None:
        """
        Toggle the mode between local interface (ap0)
        or client interface (wlan0).
        """
        index = self.interfaces.index(self.state)
        index += 1
        index %= len(self.interfaces)
        self.state = self.interfaces[index]


class SuperButton:
    """
    This class implements an one-button logic to toggle between local
    and client mode.
    """

    def __init__(self, button: Button, buzzer: Buzzer, led: LED, state: State):
        """
        A button, buzzer and led instance is combined here.
        The button controls the state or activates other events
        depending on the count.
        """
        self.buzzer = buzzer
        self.button = button
        self.button.when_held = self.callback
        self.state = state
        self.count = 0
        self.timeout = time.monotonic()
        self.timers = []

    def callback(self) -> None:
        """
        Callback is called if the button was pressed.
        It starts a timer.
        """
        if time.monotonic() > self.timeout:
            self.count = 1
            self.buzzer.beep(0.5, 0.5, n=1)
        else:
            self.count += 1
            self.buzzer.beep(0.1, 0.1, n=1)
        self.timeout = time.monotonic() + 2.0
        print(self.count)
        timer = Timer(interval=5, function=self.act)
        timer.start()
        self.timers.append(timer)

    def act(self) -> None:
        """
        Callback of timer.
        If a callback was once successful, all timers are cancelled
        and self.timers is cleared.
        """
        print("ACT:", self.count, self.timeout)
        if time.monotonic() < self.timeout:
            print("Still in progress")
            return
        elif self.count == 1:
            self.state.toggle()
        elif self.count == 3:
            # call(["shutdown", "-h", "0"])
            print("SHUTDOWN!!!!")
        elif self.count == 5:
            wlanpw.reset()
            print("Resetting wlan password...")
        timers = self.timers.copy()
        self.timers.clear()
        [t.cancel() for t in timers]


if __name__ == "__main__":
    led = LED(6)
    ping_ips = ["1.1.1.1", "8.8.8.8", "8.8.4.4"]
    buzzer = Buzzer(5)
    if Path("/media/data/online").exists():
        initial_interface = "wlan0"
    else:
        initial_interface = "ap0"
    state = State(
        local_interface="ap0",
        client_interface="wlan0",
        initial_state=initial_interface,
        do_online_check=True,
        ping_ips=ping_ips,
        status_led=led,
        buzzer=buzzer,
    )
    button = Button(13, pull_up=True, bounce_time=0.1, hold_time=0.3)
    switch = SuperButton(button=button, buzzer=buzzer, led=led, state=state)
    while True:
        time.sleep(10)
