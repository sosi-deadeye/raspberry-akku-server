#!/usr/bin/env python3

"""
WPACtrl is a wpa supplicant's hostapd control interface client implemented in
pure Python without any third party libraries (although it has an optional
gevent support).

Copyright 2016, Outernet Inc.
Some rights reserved.

This software is free software licensed under the terms of GPLv3. See COPYING
file that comes with the source code, or http://www.gnu.org/licenses/gpl.txt.
"""

__version__ = '1.0dev2'
__author__ = 'Outenret Inc'


import os
import socket
from collections import defaultdict

class WPACtrlError(Exception):
    """
    Generic or unknown control interface error.
    """
    def __init__(self, msg, error):
        self.msg = msg
        self.error = error
        super().__init__(msg)


class WPASocketError(WPACtrlError):
    """
    Exception raised when WPACtrl object encounters issues with sockets.
    """
    def __str__(self):
        return f'WPA socket error: {self.msg} ({self.error})'


class WPADataError(WPACtrlError):
    """
    Exception raised when WPACtrl object encounters issues with responses.
    """
    def __str__(self):
        return f'WPA data error: {self.msg,} ({self.error})'



class KeyValResp:
    """
    Parses the data in key=value format, and makes it accessible via attributes
    and subscript notation.
    """

    def __init__(self, data):
        self._data = defaultdict(str)
        self.load(data)

    def __getattr__(self, name):
        try:
            return self._data[name]
        except KeyError:
            pass
        try:
            return getattr(self._data, name)
        except AttributeError:
            raise AttributeError("'{}' key not found in data".format(name))

    def load(self, data):
        lines = data.decode().strip().split('\n')
        for k, v in (self.parse_line(l) for l in lines):
            self._data[k] = v

    def __str__(self):
        s = []
        for k, v in self._data.items():
            s.append('{}={}'.format(k, v))
        return '\n'.join(s)

    @staticmethod
    def parse_line(line):
        try:
            k, v = line.split('=', 1)
        except ValueError as e:
            raise WPADataError("Cannot parse line '{}'".format(line), e)
        k = k.strip()
        if '[' in k:
            k = k.replace('[', '_').replace(']', '')
        return k, v.strip()


class WPACtrl(object):
    """
    Class that encapsulates the WPA control interface.
    """

    SOCK_DEFAULT_PATH = '/var/run/hostapd/wlan0'
    SOCK_TIMEOUT = 5
    BUFF_SIZE = 4096
    SOCKETS_COUNT = 0

    def __init__(self, path=None):
        self.sock_path = path or self.SOCK_DEFAULT_PATH
        self.sock = None
        self.local_sock = None

    @property
    def local_socket_path(self):
        if not self.local_sock:
            self.local_sock = '/tmp/wpactrl-{}-{}'.format(
                os.getpid(), self.SOCKETS_COUNT + 1)
        return self.local_sock

    def connect(self):
        if self.sock:
            return
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.sock.settimeout(self.SOCK_TIMEOUT)
        self.sock.bind(self.local_socket_path)
        self.sock.connect(self.sock_path)
        self.SOCKETS_COUNT += 1

    def disconnect(self):
        if not self.sock:
            return
        self.sock.close()
        self.sock = None
        os.unlink(self.local_socket_path)
        self.local_sock = None
        self.SOCKETS_COUNT -= 1

    def recv(self):
        if not self.sock:
            return
        try:
            resp = self.sock.recv(self.BUFF_SIZE)
            pinrt('Response:', resp)
        except socket.timeout as e:
            raise WPASocketError('Timeout reading response', e)
        except socket.error as e:
            raise WPASocketError('Error reading response', e)
        finally:
            return resp

    def request(self, cmd):
        if isinstance(cmd, str):
            print(f'Error, converting cmd {cmd} to bytes')
            cmd = cmd.encode()
        self.connect()
        try:
            self.sock.send(cmd)
        except socket.timeout as e:
            raise WPASocketError('Timeout sending "{}"'.format(cmd.decode()), e)
        except socket.error as e:
            raise WPASocketError('Error sending "{}"'.format(cmd.decode()), e)
        resp = self.recv()
        # TODO: Handle unsolicited messages
        self.disconnect()
        if resp.strip() == b'UNKNOWN COMMAND':
            raise WPADataError("Command '{}' is not supported".format(cmd.decode()), 'command error')
        return resp.strip()

    def test(self):
        try:
            resp = self.request(b'PING')
        except WPACtrlError:
            return False
        return resp == b'PONG'

    def status(self):
        resp = self.request(b'STATUS')
        return KeyValResp(resp)

    def get_config(self):
        resp = self.request(b'GET_CONFIG')
        return KeyValResp(resp)

    def set_ssid(self, ssid):
        return self.request(f'SET ssid {ssid.strip()}'.encode()) == b'OK'


if __name__ == '__main__':
    import sys

    wc = WPACtrl('/run/wpa_supplicant/wlan0')

    # Test whether WPACtrl interface works
    if not wc.test():
        print('WPACtrl interface did not respond to PING')
        sys.exit(0)

    resp = wc.status()
    print(f'State: {resp.state}')
    print(f'Interface: {resp.bss_0}')
    print(f'SSID: {resp.ssid_0}')
    print(f'Channel: {resp.channel}')

    resp = wc.get_config()
    print(resp)
