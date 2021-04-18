#!/usr/bin/env python3
import re
import string
import sys
from pathlib import Path
from subprocess import call
from contextlib import contextmanager

# from python_hosts import Hosts, HostsEntry


ALPHA = string.ascii_lowercase + string.ascii_uppercase + string.digits + "-"


def filter_name(name: str) -> str:
    return "".join(c for c in name.replace("_", "-") if c in ALPHA)


@contextmanager
def read_write():
    call(["mount", "-o", "remount,rw", "remount", "/"])
    yield
    call(["mount", "-o", "remount,ro", "remount", "/"])


def get_serial() -> str:
    """
    Returns from 8th position on the cpu serial number

    Example:
        original serial number: 00000000413c11de
        return value: 413c11de
    """
    with open("/proc/cpuinfo") as fd:
        for line in fd:
            if "Serial" in line:
                return line.strip().split(":")[1].strip()[8:]
        else:
            return "FFF00000"


def get_hostname() -> str:
    """
    Return /etc/hostname
    """
    with open("/etc/hostname") as fd:
        return fd.read().strip()


def create_hostname() -> str:
    return f"Akku{get_serial()}"


def set_ap(host_name: str):
    """
    Set the ssid of access point to provided host_name
    """
    hostapd_conf = Path("/etc/hostapd/hostapd.conf")
    name = f"ssid={host_name}"
    new_config = re.sub(
        r"^ssid=(.*)", name, hostapd_conf.read_text(), flags=re.MULTILINE,
    )
    try:
        hostapd_conf.write_text(new_config)
    except PermissionError:
        pass


def set_hostname(host_name: str):
    """
    Write host_name to /etc/hostname
    """
    with read_write():
        with open("/etc/hostname", "w") as fd:
            fd.write(host_name + "\n")


def set_hostname_dhclient(hostname: str):
    fmt = 'send host-name = "{}";'
    regex = re.compile(r'send host\-name ?= ?"?(.+)"?;')
    config = Path("/media/data/dhclient.conf")
    old = config.read_text()
    result = regex.search(old)
    if result:
        new = regex.sub(fmt.format(hostname), config.read_text())
        if new != old:
            config.write_text(new)


def set_hosts(hostname: str):
    from python_hosts import Hosts, HostsEntry

    hosts_file = Hosts()
    entry = HostsEntry(entry_type="ipv4", address="127.0.0.1", names=[hostname])
    current_hosts = [
        host
        for host in hosts_file.entries
        if host.entry_type == "ipv4" and "localhost" not in host.names
    ]
    for current_host in current_hosts:
        for name in current_host.names:
            hosts_file.remove_all_matching(name=name)
    print(f"Adding entry to hosts: {entry}")
    hosts_file.add([entry])
    with read_write():
        hosts_file.write()


def set_hostname_kernel(name: str):
    call(["hostname", name])


def set_all(name: str):
    set_ap(name)
    set_hostname(name)
    set_hostname_kernel(name)
    set_hostname_dhclient(name)
    set_hosts(name)


def main():
    custom_hostname = Path("/media/data/custom_hostname").exists()
    default_hostname = create_hostname()
    etc_hostname = get_hostname()

    print(f"Custom: {custom_hostname}")
    print(f"default: {default_hostname}")
    print(f"/etc/hostname: {etc_hostname}")
    if not custom_hostname and default_hostname != etc_hostname:
        set_all(default_hostname)
    elif custom_hostname:
        set_all(etc_hostname)


if __name__ == "__main__":
    main()
