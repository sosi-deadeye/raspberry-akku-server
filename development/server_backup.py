#!/usr/bin/env python3

import time
import struct
import json
from pathlib import Path
from threading import Thread
from enum import IntEnum
from collections import defaultdict
from collections import deque
from itertools import cycle
from datetime import datetime as dt

import RPi.GPIO as gpio
import serial
import zmq
import pytz


TZ = pytz.timezone('Europe/Berlin')


def get_float():
    return round(struct.unpack('<f', ser.read(4))[0], 2)


def get_cell_voltage():
    cid, voltage = struct.unpack('<Bf', ser.read(5))
    cell_voltages[cid].append(voltage)
    return round(voltage, 3)


def always_true():
    return True


def read_n(bytes):
    def inner():
        return ser.read(bytes)
    return inner


class CellVoltage:
    def __init__(self):
        self.cycle = cycle(range(4))
        self.current_cell = next(self.cycle)

    def get_cell_voltage(self):
        self.current_cell = next(self.cycle)
        result = get_cell_voltage()
        return result

    __call__ = get_cell_voltage

    def __str__(self):
        return str(self.current_cell + 1)


actual_cell_voltage = CellVoltage()


FRAME_TYPE = {
    23: ('Battery off', always_true),
    31: ('Battery on', always_true),
    79: ('Current', get_float),
    71: ('Voltage', get_float),
    111: ('Capacity', get_float),
    103: ('Load Ah', get_float),
    119: ('Cell voltage', actual_cell_voltage),
    127: ('Cell temperature', get_float),
    137: ('Reset battery', always_true),
    151: ('Error flags', lambda: bin(struct.unpack('<H', ser.read(2))[0])[2:]),
    159: ('Error history', lambda: ser.read(2)),
    181: ('Configuration', lambda: ser.read(2)),
    }


def get_payload(frame_type):
    if frame_type in FRAME_TYPE:
        label, function = FRAME_TYPE[frame_type]
        if label == FRAME_TYPE[119][0]:
            #print('Got payload of cell voltage')
            label = FRAME_TYPE[119][0] + ' ' + str(actual_cell_voltage)
        data = function()
        statistic[label].append(data)


def read_loop():
    ctx = zmq.Context()
    sock = ctx.socket(zmq.SUB)
    sock.bind('tcp://127.0.0.1:4000')
    sock.subscribe(b'CONTROL')
    queries = (
        query_current, query_voltage, query_capacity,
        query_load, query_error_flags, query_cell_temperature,
        lambda: query_cell_voltage(1), lambda: query_cell_voltage(2),
        lambda: query_cell_voltage(3), lambda: query_cell_voltage(4),
    )
    time.sleep(5)
    while True:
        print('Reading row')
        statistic['timestamp'].append(dt.now(tz=TZ).replace(microsecond=0).isoformat())
        for query in queries:
            try:
                topic, cmd = sock.recv_multipart(zmq.NOBLOCK)
            except:
                pass
            else:
                if cmd == b'on':
                    print('Battery on')
                    send(set_battery_on())
                elif cmd == b'off':
                    print('Battery off')
                    send(set_battery_off())
                elif cmd == b'reset':
                    # send(set_reset_battery())
                    send(set_reset_alarm())
                    print('Sent reset alarm')
            if isinstance(query, tuple):
                cell_id, query = query
            send(query())
            time.sleep(1)
            if ser.in_waiting > 0:
                frame_type = ser.read(1)[0]
                if frame_type  in (137,):
                    ser.reset_input_buffer()
                    continue
                get_payload(frame_type)
                ser.reset_input_buffer()
            save_statistic()


def save_statistic():
    with statistic_file.open('w') as fd:
        dataset = {k: tuple(v) for k, v in statistic.items()}
        #print(dataset)
        json.dump(dataset, fd)
    # for key, value in statistic.items():
    #     print(f'{key} -> {tuple(value)}')


def gpio22interrupt():
    """wenn low > dann nicht senden für 100 ms"""


def send(data: bytearray):
    # value = bin(data[0])[2:][::-1]
    #print(f'Zum Akku: {value}')
    print('Set tx to high')
    gpio.output(17, False)
    print('Wait for rising edge')
    gpio.wait_for_edge(27, gpio.RISING)
    time.sleep(0.01)
    # print('Writing data')
    ser.write(data)
    ser.flush()
    # print('Waiting')
    time.sleep(1)
    gpio.output(17, True)
    # print('TX is now low')



class Frame(IntEnum):
    A = 0x1


class Control(IntEnum):
    Acknowledge = 0x0
    Set = 0x1
    Query = 0x2
    Answer = 0x3


def query(qtype, service_bit=0, service_bits=0, databytes=None):
    packet = 1
    packet |= (qtype << 1)
    packet |= service_bit << 3
    packet |= service_bits << 4
    data = bytearray([packet])
    if databytes:
        data.extend(databytes)
    return data


def query_all():
    send(query_error_flags())
    send(query_battery_on())
    send(query_load_percent())
    send(query_voltage())
    send(query_current())
    send(query_cell_voltages())
    send(query_cell_temperature())


def query_load_percent():
    return query_load() + query_capacity()


def query_cell_voltages():
    data = bytearray()
    for i in range(4):
        data += query_cell_voltage(i)
    return data

def query_battery_on():
    return query(Control.Query, service_bits=1)


def set_battery_off():
    return query(Control.Set, service_bits=1)


def set_battery_on():
    return query(Control.Set, service_bit=1, service_bits=1)


def query_voltage():
    return query(Control.Query, service_bit=0x0, service_bits=4)


def query_current():
    return query(Control.Query, service_bit=0x1, service_bits=4)


def query_load():
    return query(Control.Query, service_bit=0x0, service_bits=6)


def query_capacity():
    return query(Control.Query, service_bit=0x1, service_bits=6)


def query_cell_voltage(cell_id):
    return query(Control.Query, service_bit=0x0, service_bits=7, databytes=bytearray([cell_id]))


def query_configuration():
    return query(Control.Query, service_bit=0x0, service_bits=10)


def query_error_flags():
    return query(Control.Query, service_bit=0x0, service_bits=9)


def query_error_history(area):
    data = struct.pack('<H', area)
    return query(Control.Query, service_bit=0x0, service_bits=9, databytes=data)


def query_cell_temperature():
    return query(Control.Query, service_bit=0x1, service_bits=7)


def set_reset_alarm():
    return query(Control.Set, service_bit=0x0, service_bits=8)


def set_reset_battery():
    return query(Control.Set, service_bit=0x1, service_bits=8)


def start_daemon():
    thread = Thread(target=read_loop, daemon=True)
    thread.start()
    print('Thread started')
    return thread


def queue():
    return deque(maxlen=1000)


gpio.setwarnings(False)
gpio.setmode(gpio.BCM)
gpio.setup(17, gpio.OUT, initial=gpio.HIGH)
gpio.setup(27, gpio.IN, pull_up_down=gpio.PUD_DOWN)
cell_voltages = defaultdict(list)

ser = serial.Serial(
    '/dev/serial0', baudrate=1000, parity=serial.PARITY_EVEN,
    bytesize=serial.EIGHTBITS, stopbits=serial.STOPBITS_ONE
    )

statistic_file = Path('/root/akku/stats.json')
if statistic_file.exists():
    try:
        data = json.load(statistic_file.open())
        statistic = defaultdict(queue)
        statistic.update({k: deque(v, maxlen=1000) for k, v in data.items()})
    except:
        statistic_file.unlink()
else:
    statistic = defaultdict(queue)
thread = start_daemon()
thread.join()
