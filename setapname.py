#!/usr/bin/env python3
import re
import string
import sys
from pathlib import Path
from subprocess import call
from contextlib import contextmanager

from python_hosts import Hosts, HostsEntry


ALPHA = string.ascii_lowercase + string.ascii_uppercase + string.digits + "_"


def filter_name(name):
    return "".join(c for c in name if c in ALPHA)


@contextmanager
def read_write():
    call(["mount", "-o", "remount,rw", "remount", "/"])
    yield
    call(["mount", "-o", "remount,ro", "remount", "/"])


def get_serial():
    cpuinfo = Path("/proc/cpuinfo").read_text()
    # Serial          : 00000000413c11de
    for line in cpuinfo.splitlines():
        if "Serial" in line:
            return line.strip().split(":")[1].strip()[8:]
    else:
        return "FFF00000"


def set_ap(host_name=None):
    hostapd_conf = Path("/etc/hostapd/hostapd.conf")
    name = f"ssid=Akku{get_serial()}" if host_name is None else f"ssid={host_name}"
    try:
        new_config = re.sub(
            r"^ssid=(.*)",
            name,
            hostapd_conf.read_text(),
            flags=re.MULTILINE,
        )
    except Exception as e:
        print(repr(e))
    else:
        if new_config:
            hostapd_conf.write_text(new_config)


def get_hostname():
    with open("/etc/hostname") as fd:
        return fd.read().strip()


def create_hostname():
    serial = get_serial()
    return f"Akku{serial}"


def set_hostname(name=None):
    if name is None:
        name = create_hostname()
    etc_hostname = Path("/etc/hostname")
    if etc_hostname.read_text().strip() != name:
        with read_write():
            etc_hostname.write_text(name + "\n")
        call(["hostname", name])
        call(["systemctl", "restart", "avahi-daemon"])


def set_hostname_dhclient():
    hostname = get_hostname()
    fmt = 'send host-name = "{}";'
    regex = re.compile(r'send host\-name ?= ?"?(.+)"?;')
    config = Path("/media/data/dhclient.conf")
    old = config.read_text()
    result = regex.search(old)
    if result:
        new = regex.sub(fmt.format(hostname), config.read_text())
        if new != old:
            config.write_text(new)


def set_hosts():
    hostname = get_hostname()
    hosts_file = Hosts()
    entry = HostsEntry(entry_type="ipv4", address="127.0.0.1", names=[hostname])
    current_hosts = [
        host
        for host in hosts_file.entries
        if host.entry_type == "ipv4"
        and "localhost" not in host.names
    ]
    for current_host in current_hosts:
        for name in current_host.names:
            hosts_file.remove_all_matching(name=name)

    hosts_file.add([entry])
    with read_write():
        hosts_file.write()


def set_all(name):
    set_ap(name)
    set_hostname(name)
    set_hostname_dhclient()
    set_hosts()


if __name__ == "__main__":
    host_name = None
    if len(sys.argv) == 2:
        host_name = sys.argv[1]
    if Path("/media/data/custom_hostname").exists():
        host_name = get_hostname()
    set_all(host_name)
