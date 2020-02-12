#!/usr/bin/env python3

import time
import struct
import statistics
import mmap
from collections import deque
from threading import Thread, Semaphore
from typing import Union
from datetime import datetime
from enum import IntEnum, Enum
from subprocess import call
from logging import getLogger, basicConfig, INFO
from queue import Queue

import RPi.GPIO as gpio
import serial
import zmq

from database import (
    Session, session,
    Configuration, Error, State,
    set_cycle, delete_old_cycles, Statistik
)

import notify
import errors
import timedaemon


class QueryScheduler:
    NORMAL = 'normal'
    LIVE = 'live'

    def __init__(self, queries_normal, queries_live, live_timeout=10):
        self.mode = self.NORMAL
        self.queries_normal = queries_normal
        self.queries_live = queries_live
        # first all normal queries are waiting
        self.waiting = [(query, freq, 0) for (query, freq) in queries_normal]
        self.live_timeout = live_timeout
        self.normal_after = time.monotonic()

    def _next_in_waiting(self):
        if self.mode == self.NORMAL:
            queries = self.queries_normal
        elif self.mode == self.LIVE:
            queries = self.queries_live
        else:
            return []
        return [(query, freq, time.monotonic() + freq) for query, freq in queries]

    def _next_in_queue(self):
        return [
            (
                query,
                freq,
                time.monotonic() + freq if time.monotonic() > after else after,
            )
            for query, freq, after in self.waiting
        ]

    def __iter__(self):
        return self

    def __next__(self):
        if self.mode == self.LIVE and time.monotonic() > self.normal_after:
            log.info('Switching back to normal mode')
            self.switch(self.NORMAL)
        current_queries = [bytes(query) for (query, freq, after) in self.waiting if time.monotonic() > after]
        self.waiting = self._next_in_queue()
        # log.info(current_queries)
        return current_queries

    def switch(self, mode):
        if mode == self.LIVE:
            self.normal_after = time.monotonic() + self.live_timeout
        if self.mode != mode:
            self.mode = mode
            self.waiting = self._next_in_waiting()
            if mode == self.LIVE:
                log.info(f'Switch mode to {mode}')


class Frame(IntEnum):
    A = 0x1


class Control(IntEnum):
    Acknowledge = 0x0
    Set = 0x1
    Query = 0x2
    Answer = 0x3


class Mode(Enum):
    QueryOnOff = 'Anfrage Akku Ein/Aus'
    AnswerOn = 'Antwort Akku An'
    AnswerOff = 'Antwort Akku Aus'
    SetOff = 'Befehl Akku Aus'
    AnswerSetOff = 'Bestätigung Akku Aus'
    SetOn = 'Befehl Akku Ein'
    AnswerSetOn = 'Bestätigung Akku Ein'


class Data(Enum):
    QueryVoltage = 'Anfrage Spannung'
    AnswerVoltage = 'Antwort Spannung'
    QueryCurrent = 'Anfrage Strom'
    AnswerCurrent = 'Antwort Strom'
    QueryCharge = 'Anfrage Ladung'
    AnswerCharge = 'Antwort Ladung'
    QueryCapacity = 'Anfrage Kapazität'
    AnswerCapacity = 'Antwort Kapazität'
    QueryCellVoltage = 'Anfrage Zellspannung'
    AnswerCellVoltage = 'Antwort Zellspannung'
    QueryTemperature = 'Anfrage Zelltemperatur'
    AnswerTemperature = 'Antwort Zelltemperatur'


class Reset(Enum):
    SetResetError = 'Fehler zurücksetzen'
    SetResetAnswer = 'Antwort Fehler zurücksetzen'
    SetAkkuResetError = 'Akku zurücksetzen'
    SetAkkuResetAnswer = 'Antwort Akku zurücksetzen'


class Fault(Enum):
    QueryErrorFlags = 'Anfrage Fehlercode'
    AnswerErrorFlags = 'Antwort Fehlercode'
    QueryErrorMemory = 'Anfrage Fehlerspeicher'
    AnswerErrorMemory = 'Antwort Fehlerspeicher'


class Message(Enum):
    Answer = 'Nachricht'
    Ack = 'Bestätigung der Nachricht'


class FConfiguration(Enum):
    QueryDimension = 'Anfrage Diemension'
    AnswerDimension = 'Antwort Dimension'
    Set = 'Befehl Setting'
    Ack = 'Bestätigung Setting'


class FrameParser:
    types = {
        # Mode
        (Frame.A, Control.Query, 0, 1): {'type': Mode.QueryOnOff},
        (Frame.A, Control.Answer, 1, 1): {'type': Mode.AnswerOn},
        (Frame.A, Control.Answer, 0, 1): {'type': Mode.AnswerOff},
        (Frame.A, Control.Set, 0, 1): {'type': Mode.SetOff},
        (Frame.A, Control.Answer, 0, 1): {'type': Mode.AnswerSetOff},
        (Frame.A, Control.Set, 1, 1): {'type': Mode.SetOn},
        (Frame.A, Control.Answer, 1, 1): {'type': Mode.AnswerSetOn},
        # Data
        (Frame.A, Control.Query, 0, 4): {'type': Data.QueryVoltage},
        (Frame.A, Control.Answer, 0, 4): {'type': Data.AnswerVoltage, 'constraints': lambda x: 0 < x[0] < 200},
        (Frame.A, Control.Query, 1, 4): {'type': Data.QueryCurrent},
        (Frame.A, Control.Answer, 1, 4): {'type': Data.AnswerCurrent, 'constraints': lambda x: -1000 < x[0] < 1000},
        (Frame.A, Control.Query, 0, 6): {'type': Data.QueryCharge},
        (Frame.A, Control.Answer, 0, 6): {'type': Data.AnswerCharge, 'constraints': lambda x: -100 < x[0] < 2000},
        (Frame.A, Control.Query, 1, 6): {'type': Data.QueryCapacity},
        (Frame.A, Control.Answer, 1, 6): {'type': Data.AnswerCapacity, 'constraints': lambda x: -100 < x[0] < 1000},
        (Frame.A, Control.Query, 0, 7): {'type': Data.QueryCellVoltage},
        (Frame.A, Control.Answer, 0, 7): {'type': Data.AnswerCellVoltage, 'constraints': lambda x: 0 < x[1] < 5},
        (Frame.A, Control.Query, 1, 7): {'type': Data.QueryTemperature},
        (Frame.A, Control.Answer, 1, 7): {'type': Data.AnswerTemperature, 'constraints': lambda x: -300 < x[0] < 300},
        # Reset
        (Frame.A, Control.Set, 0, 8): {'type': Reset.SetResetError},
        (Frame.A, Control.Answer, 0, 8): {'type': Reset.SetResetAnswer},
        (Frame.A, Control.Set, 1, 8): {'type': Reset.SetAkkuResetError},
        (Frame.A, Control.Answer, 1, 8): {'type': Reset.SetAkkuResetAnswer},
        # Fault
        (Frame.A, Control.Query, 0, 9): {'type': Fault.QueryErrorFlags},
        (Frame.A, Control.Answer, 0, 9): {'type': Fault.AnswerErrorFlags},
        (Frame.A, Control.Query, 1, 9): {'type': Fault.QueryErrorMemory},
        (Frame.A, Control.Answer, 1, 9): {'type': Fault.AnswerErrorMemory},
        # Message
        (Frame.A, Control.Answer, 0, 10): {'type': Message.Answer},
        (Frame.A, Control.Acknowledge, 0, 10): {'type': Message.Ack},
        # Configuration
        (Frame.A, Control.Query, 0, 11): {'type': FConfiguration.QueryDimension},
        (Frame.A, Control.Answer, 0, 11): {'type': FConfiguration.AnswerDimension},
        (Frame.A, Control.Set, 1, 11): {'type': FConfiguration.Set},
        (Frame.A, Control.Acknowledge, 1, 11): {'type': FConfiguration.Ack},
        # Protocol Error
        (Frame.A, Control.Answer, 0, 5): {'type': 'Protokollfehler'},
    }

    def __init__(self, frame, control, data_bit, service_bits):
        self.frame = frame
        self.control = control
        self.data_bit = data_bit
        self.service_bits = service_bits
        try:
            self.frame_type = self.types[(frame, control, data_bit, service_bits)]
        except KeyError:
            self.frame_type = {'type': None, 'constraints': lambda x: x}

    def is_zero(self):
        return self.frame == 0 and self.control == 0 and self.data_bit == 0 and self.service_bits == 0

    def read_reply(self, serial):
        frame_type = self.frame_type['type']
        if frame_type in (
                Data.AnswerVoltage,
                Data.AnswerCurrent,
                Data.AnswerCharge,
                Data.AnswerCapacity,
                Data.AnswerTemperature,
        ):
            values = struct.unpack('<f', serial.read(4))
        elif frame_type is Data.AnswerCellVoltage:
            values = struct.unpack('<Bf', serial.read(5))
        elif frame_type is Fault.AnswerErrorFlags:
            values = struct.unpack('<H', serial.read(2))
        elif frame_type is Mode.AnswerSetOff:
            values = (False,)
        elif frame_type is Mode.AnswerSetOn:
            values = (True,)
        else:
            raise TypeError('No data is supplied by this Answer')
        if 'constraints' in self.frame_type and not self.frame_type['constraints'](values):
            raise ValueError(f'Value "{values}" is not in allowed range')
        return values

    def is_reply(self, other):
        if other.service_bits != 1:
            return self.frame == other.frame and self.data_bit == other.data_bit and self.service_bits == other.service_bits
        else:
            return self.frame == other.frame and self.service_bits == other.service_bits

    def to_bytes(self):
        return bytes(bytearray([self.frame | self.control << 1 | self.data_bit << 3 | self.service_bits << 4]))

    @classmethod
    def from_bytes(cls, value: Union[int, bytes]):
        if isinstance(value, int):
            value = bytes(bytearray([value]))
        else:
            log.debug(f'Bytes gelesen: [{value}]')
        try:
            data = value[0]
            frame = Frame(data & 0x1)
            control = Control(data & 0x03)
            data_bit = bool(data & 0x08)
            service_bits = data >> 4
            log.error(f'Frame: {frame}, {control}, {data_bit}, {service_bits}')
            return cls(frame, control, data_bit, service_bits)
        except ValueError:
            return FrameParser(0, 0, 0, 0)

    def __eq__(self, other):
        return self.frame == other.frame and self.control == other.control and self.data_bit == other.data_bit and self.service_bits == other.service_bits

    def __bytes__(self):
        return self.to_bytes()

    def __repr__(self):
        return f'{self.__class__.__name__}(frame={self.frame}, control={self.control}, data_bit={self.data_bit}, service_bits={self.service_bits})'


class DataReader(Thread):

    def __init__(self, serial, queries, normal_interval=30, live_interval=0, cells=4):
        self.ser = serial
        self.normal_interval = normal_interval
        self.live_interval = live_interval
        self.cells = cells
        self.queries = queries
        self.session = Session()
        self.capacity = None
        self.last_error = None
        self.last_error_flags = None
        self.error_topics = [0x0010, 0x0020, 0x0100, 0x0200, 0x1000, 0x2000, 0x4000, 0x8000]
        self.notified = False
        self.row = 0
        self.battery_state = None
        self.current_values = {
            'voltage': 0.0,
            'current': 0.0,
            'charge': 0.0,
            'capacity': 0.0,
            'temperature': 0.0,
            'cell_voltages': [0.0] * self.cells,
            'error': 0,
        }
        self.create_mmap()
        self.db_update_interval = 60
        self.db_next_update = time.monotonic() + 120
        self.stats_current = deque(maxlen=4)
        self.timedelta_queue: Union[None, Queue] = None
        self.notified = False
        super().__init__()

    def handle_error(self, error_flags: int):
        # error_flags = 0x7330
        # error_flags = 0xFFFF
        if error_flags != self.last_error_flags:
            self.last_error_flags = error_flags
            self.current_values['error'] = error_flags
            self.session.add(Error(row=self.row, cycle=CYCLE, error=error_flags))
            error_text = errors.get_msg(error_flags, err_topics=self.error_topics)
            if error_text and error_text != self.last_error:
                self.last_error = error_text
                Thread(target=notify.send_report, args=(error_text,)).start()

    def create_mmap(self):
        """
        Format:
        5i: id, row, cycle, capacity, error
        9f: voltage, current, charge, temperature, timestamp, 4 x cell_voltages
        """
        self._current_values_st = struct.Struct('<5i9f')
        with open('/media/data/current_values.bin', 'wb') as fd:
            fd.write(b'\x00' * self._current_values_st.size)
        self._fd = open('/media/data/current_values.bin', 'r+b')
        self._mmap = mmap.mmap(
            fileno=self._fd.fileno(),
            length=self._current_values_st.size,
            access=mmap.ACCESS_WRITE
        )

    def update_current_values(self):
        current_data = (
            self.row,
            self.row,
            CYCLE,
            int(self.current_values['capacity']),
            self.current_values['error'],
            self.current_values['voltage'],
            self.current_values['current'],
            self.current_values['charge'],
            self.current_values['temperature'],
            datetime.now().timestamp(),
            *self.current_values['cell_voltages'],
        )
        self._current_values_st.pack_into(
            self._mmap,
            0,
            *current_data,
        )

    def check_timedelta(self) -> None:
        """
        Prüfe ob es Sprünge in der Zeit gab.

        Anschließende Korrektur der Zeitstempel.
        """
        if not self.timedelta_queue.empty():
            log.info(f'Die Systemzeit hat sich geändert. Aktualisiere die Daten aus dem Zyklus {CYCLE}')
            diff, positive = self.timedelta_queue.get()
            # den Zyklus und alle Zeilen < self.row müssen aktualisiert werden
            for stat in self.session.query(Statistik).filter(Statistik.cycle == CYCLE, Statistik.row < self.row):
                if positive:
                    corrected_timestamp = stat.timestamp + diff
                else:
                    corrected_timestamp = stat.timestamp - diff
                stat.timestamp = corrected_timestamp
                self.session.merge(stat)

    def get_important_values(self):
        """
        Frage Kapazität, Status und Ladung ab
        """
        log.info('Frage Kapazität ab')
        for description, (capacity, *_) in send(self.ser, [query_capacity()]):
            log.info(f'Kapazität ist {capacity:.0f} Ah')
            self.capacity = capacity
            self.current_values['capacity'] = capacity
        self.session.add(Configuration(capacity=self.capacity, cycle=CYCLE))
        # Query nur einmal senden
        # wird noch nicht ausgewertet
        self.ser.write(query_battery_on())
        values = [self.capacity]
        for frame_type, values in send(self.ser, [query_load()]):
            self.current_values['charge'] = values[0]
        log.info(f'Ladung beträgt {values[0]:.0f} V.')

    def run(self):
        """
        Diese Funktion wird indirekt durch die Methode start() aufgerufen.
        """
        log.info('Starte Zeitüberwachung')
        self.timedelta_queue: Queue = timedaemon.start()
        log.info(f'Zyklus: {CYCLE}')
        self.get_important_values()
        log.info('Betrete Endlosschleife')
        while True:
            # Prüfe ob sich die Zeit geändert hat
            # und führe Korrekturen aus
            self.check_timedelta()

            # Nächsten query anfordern
            query = next(self.queries)

            # Query verarbeiten
            self.handle_query(query)

            # 100 ms warten.
            time.sleep(0.1)

    def check_alert(self) -> None:
        """
        Prüfe ob die Ladung unter 10% ist.
        (Ladung kann auch negativ sein.)

        Ladung unter 15% ist -> E-Mail versenden
        Ladung unter 10% ist -> E-Mail versenden, WLAN-Modul herunterfahren.
        """
        if self.current_values['charge'] and self.capacity:
            relative_load = (self.current_values['charge'] / self.capacity) * 100
            # log.info(f'Relative Ladung {relative_load}')
            if not self.notified and 10 < relative_load < 15:
                log.warning('Ladung unter 15%. E-Mail wird gesendet.')
                notify_thread = Thread(
                    target=notify.send_report,
                    args=('Die Ladung des Akkus liegt zwuschen 10 und 15%. Bitte nachladen.',)
                )
                notify_thread.start()
                self.notified = True
            elif relative_load < 10:
                notify.send_report('Die Ladung des Akkus ist unter 10%. Das Wlan-Modul wird heruntergefahren.')
                log.warning(f'Achtung Ladung: {relative_load:.1f} %')
                gpio.setup(5, gpio.OUT)
                gpio.output(5, True)
                time.sleep(2)
                gpio.output(5, False)
                time.sleep(1)
                gpio.output(5, True)
                time.sleep(2)
                gpio.output(5, False)
                call(['shutdown', '-h', '0'])

    def database_insert(self) -> None:
        """
        Prüfe ob nächster Datenbankeintrag fällig ist.
        Falls ja, Daten speichern und Timer neu setzen.
        """
        if time.monotonic() > self.db_next_update:
            log.info(f'Speichere Datensatz {self.row} in der Datenbank')
            current_values = self.current_values.copy()
            try:
                current_mean = statistics.mean(self.stats_current)
            except statistics.StatisticsError:
                pass
            else:
                current_values['current'] = current_mean
            del current_values['capacity']  # this key is in a different table
            del current_values['error']     # this also
            dataset = Statistik(cycle=CYCLE, row=self.row, **current_values)
            self.session.add(dataset)
            self.session.commit()
            self.row += 1
            self.db_next_update = time.monotonic() + self.db_update_interval

    def handle_query(self, query):
        if query:
            for frame_type, values in send(ser, query):
                frame_type = frame_type['type']
                if frame_type is Data.AnswerVoltage:
                    self.current_values['voltage'] = values[0]
                elif frame_type is Data.AnswerCurrent:
                    self.current_values['current'] = values[0]
                    self.stats_current.append(values[0])
                elif frame_type is Data.AnswerCharge:
                    self.current_values['charge'] = values[0]
                elif frame_type is Data.AnswerTemperature:
                    self.current_values['temperature'] = values[0]
                elif frame_type is Data.AnswerCellVoltage:
                    cell_id, cell_voltage = values
                    try:
                        self.current_values['cell_voltages'][cell_id] = cell_voltage
                    except IndexError:
                        log.error(f'Zellen-Index {cell_id} ist ungültig')
                elif frame_type is Fault.AnswerErrorFlags:
                    self.handle_error(values[0])
                elif frame_type is Mode.AnswerSetOff:
                    self.session.add(State(cycle=CYCLE, row=self.row, onoff=False))
                elif frame_type is Mode.AnswerSetOn:
                    self.session.add(State(cycle=CYCLE, row=self.row, onoff=True))
            self.update_current_values()
            self.database_insert()
            self.check_alert()


class Commands(Enum):
    topic = b'CONTROL'
    on = b'on'
    off = b'off'
    reset = b'reset'
    ack = b'ack'
    live = b'live'


def command_loop():
    ctx = zmq.Context()
    sock = ctx.socket(zmq.SUB)
    sock.bind('tcp://127.0.0.1:4000')
    sock.subscribe(Commands.topic.value)
    while True:
        topic, cmd = sock.recv_multipart()
        if cmd == Commands.on.value:
            log.info('Set Battery on')
            send_command(set_battery_on())
        elif cmd == Commands.off.value:
            log.info('Set Battery off')
            send_command(set_battery_off())
        elif cmd == Commands.reset.value:
            log.info('Reset battery')
            send_command(set_reset_battery())
        elif cmd == Commands.ack.value:
            log.info('Send Ack')
            send_command(set_reset_alarm())
        elif cmd == Commands.live.value:
            query_scheduler.switch(QueryScheduler.LIVE)


def send_command(frame):
    with sending:
        while True:
            if gpio.input(TXD_SENSE):
                break
            time.sleep(1)
        gpio.output(TXD_EN, False)
        gpio.wait_for_edge(RXD_SENSE, gpio.RISING)
        while True:
            time.sleep(0.3)
            ser.reset_input_buffer()
            ser.write(frame)
            data = ser.read(1)
            print('XX', end='', flush=True)
            req = FrameParser.from_bytes(frame)
            rep = FrameParser.from_bytes(data)
            if req.is_reply(rep):
                break
        gpio.output(TXD_EN, True)


def txd_sense_wait():
    while True:
        if gpio.wait_for_edge(TXD_SENSE, gpio.FALLING, timeout=10000) is None:
            break


def send(ser, frames):
    with sending:
        txd_sense_wait()
        gpio.output(TXD_EN, False)
        for frame in frames:
            time.sleep(0.1)
            while True:
                ser.reset_input_buffer()

                ser.write(frame)
                # print('T', end='', flush=True)

                data = ser.read(1)
                # print('R', end='', flush=True)

                req = FrameParser.from_bytes(frame)
                rep = FrameParser.from_bytes(data)

                log.info(f'{req.frame_type["type"]} -> {rep.frame_type["type"]}')
                if req.is_reply(rep):
                    try:
                        values = rep.read_reply(ser)
                    except (TypeError, ValueError) as e:
                        log.critical(f'{e} {rep}')
                    else:
                        yield rep.frame_type, values
                        break
        gpio.output(TXD_EN, True)


def query(qtype, service_bit=0, service_bits=0, databytes=None) -> bytes:
    packet = 1
    packet |= (qtype << 1)
    packet |= service_bit << 3
    packet |= service_bits << 4
    data = bytearray([packet])
    if databytes:
        data.extend(databytes)
    return bytes(data)


def query_battery_on() -> bytes:
    return query(Control.Query, service_bits=1)


def set_battery_off() -> bytes:
    return query(Control.Set, service_bits=1)


def set_battery_on() -> bytes:
    return query(Control.Set, service_bit=0x1, service_bits=1)


def query_voltage() -> bytes:
    return query(Control.Query, service_bit=0x0, service_bits=4)


def query_current() -> bytes:
    return query(Control.Query, service_bit=0x1, service_bits=4)


def query_load() -> bytes:
    return query(Control.Query, service_bit=0x0, service_bits=6)


def query_capacity() -> bytes:
    return query(Control.Query, service_bit=0x1, service_bits=6)


def query_cell_voltage(cell_id) -> bytes:
    return query(Control.Query, service_bit=0x0, service_bits=7, databytes=bytearray([cell_id]))


def query_configuration() -> bytes:
    return query(Control.Query, service_bit=0x0, service_bits=10)


def query_error_flags() -> bytes:
    return query(Control.Query, service_bit=0x0, service_bits=9)


def query_error_history(area) -> bytes:
    data = struct.pack('<H', area)
    return query(Control.Query, service_bit=0x0, service_bits=9, databytes=data)


def query_cell_temperature() -> bytes:
    return query(Control.Query, service_bit=0x1, service_bits=7)


def set_reset_alarm() -> bytes:
    return query(Control.Set, service_bit=0x0, service_bits=8)


def set_reset_battery() -> bytes:
    return query(Control.Set, service_bit=0x1, service_bits=8)


def discard_old_cycles() -> None:
    cycle = 1
    while session.query(Statistik).count() > 1_000_000:
        log.info(f'Lösche Zyklus {cycle}')
        session.query(Statistik).filter(Statistik.cycle == cycle).delete()
        cycle += 1


basicConfig(level=INFO)
log = getLogger('Server')
sending = Semaphore()


if __name__ == '__main__':
    CYCLE = set_cycle()
    discard_old_cycles()
    gpio.setwarnings(False)
    gpio.setmode(gpio.BCM)
    TXD_EN = 17
    TXD_SENSE = 22
    RXD_SENSE = 27
    gpio.setup(TXD_EN, gpio.OUT, initial=gpio.HIGH)            # /Transmit Data Enable
    gpio.setup(RXD_SENSE, gpio.IN, pull_up_down=gpio.PUD_DOWN) # Receive Data Sense
    gpio.setup(TXD_SENSE, gpio.IN, pull_up_down=gpio.PUD_UP)   # /Transmit Data Sense
    ser = serial.Serial(
        '/dev/serial0', baudrate=1000, parity=serial.PARITY_EVEN,
        bytesize=serial.EIGHTBITS, stopbits=serial.STOPBITS_ONE
    )

    # def txd_en_off(*args):
    #     gpio.output(TXD_EN, True)
    #     old_signal()
    #
    # atexit.register(txd_en_off)
    # old_signal = signal.signal(signal.SIGTERM, txd_en_off)

    queries_normal = [
        (query_voltage(), 60),
        (query_current(), 10),
        (query_load(), 60),
        (query_cell_temperature(), 60),
        *[(query_cell_voltage(n), 60) for n in range(4)],
        (query_error_flags(), 60),
    ]

    queries_live = [
        (query_voltage(), 15),
        (query_current(), 2),
        (query_load(), 60),
        (query_cell_temperature(), 60),
        *[(query_cell_voltage(n), 15) for n in range(4)],
        (query_error_flags(), 15),
    ]

    log.debug('Starte QueryScheduler')
    query_scheduler = QueryScheduler(queries_normal, queries_live)

    # starte Thread mit einem zmq subscriber,
    # der lediglich Befehle an den Akku sendet
    log.debug('Starte Befehlsempfänger')
    command_server = Thread(target=command_loop)
    command_server.start()

    # starte den Datenlogger.
    log.debug('Starte Datenlogger')
    data_logger = DataReader(ser, query_scheduler, normal_interval=60, live_interval=5)
    data_logger.start()
