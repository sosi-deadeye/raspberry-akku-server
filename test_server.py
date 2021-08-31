#!/usr/bin/env python3
from __future__ import annotations

import datetime
import io
import struct
import time
from enum import Enum, IntEnum
from threading import Thread
from typing import Tuple, Union, List, Optional

import RPi.GPIO as GPIO
from serial import Serial, EIGHTBITS, PARITY_EVEN, STOPBITS_ONE

TXD_EN = 17  # /Transmit Data Enable
TXD_SENSE = 22  # Receive Data Sense
RXD_SENSE = 27  # /Transmit Data Sense


class Frame(IntEnum):
    A = 0x1


class Control(IntEnum):
    Acknowledge = 0x0
    Set = 0x1
    Query = 0x2
    Answer = 0x3


class Mode(Enum):
    QueryOnOff = "Anfrage Akku Ein/Aus"
    AnswerOn = "Antwort Akku An"
    AnswerOff = "Antwort Akku Aus"
    SetOff = "Befehl Akku Aus"
    AnswerSetOff = "Bestätigung Akku Aus"
    SetOn = "Befehl Akku Ein"
    AnswerSetOn = "Bestätigung Akku Ein"


class Data(Enum):
    QueryVoltage = "Anfrage Spannung"
    AnswerVoltage = "Antwort Spannung"
    QueryCurrent = "Anfrage Strom"
    AnswerCurrent = "Antwort Strom"
    QueryCharge = "Anfrage Ladung"
    AnswerCharge = "Antwort Ladung"
    QueryCapacity = "Anfrage Kapazität"
    AnswerCapacity = "Antwort Kapazität"
    QueryCellVoltage = "Anfrage Zellspannung"
    AnswerCellVoltage = "Antwort Zellspannung"
    QueryTemperature = "Anfrage Zelltemperatur"
    AnswerTemperature = "Antwort Zelltemperatur"
    QueryLowHighCellVoltage = "Niedrigste/Höchste Zellspannung abfragen"
    AnswerLowHighCellVoltage = "Niedrigste/Höchste Zellspannung abfragen"


class Reset(Enum):
    SetResetError = "Fehler zurücksetzen"
    SetResetAnswer = "Antwort Fehler zurücksetzen"
    SetAkkuResetError = "Akku zurücksetzen"
    SetAkkuResetAnswer = "Antwort Akku zurücksetzen"


class Fault(Enum):
    QueryErrorFlags = "Anfrage Fehlercode"
    AnswerErrorFlags = "Antwort Fehlercode"
    QueryErrorMemory = "Anfrage Fehlerspeicher"
    AnswerErrorMemory = "Antwort Fehlerspeicher"


class Message(Enum):
    Answer = "Nachricht"
    Ack = "Bestätigung der Nachricht"


class FConfiguration(Enum):
    QueryDimension = "Anfrage Diemension"
    AnswerDimension = "Antwort Dimension"
    Set = "Befehl Setting"
    Ack = "Bestätigung Setting"


def make_query(
    query_type: int,
    service_bit: int = 0,
    service_bits: int = 0,
    databytes: Union[None, bytes] = None,
) -> bytes:
    """
    Die Funktion erstellt einen Query basiert auf den übergebenen Argumenten.
    """
    packet = 1
    packet |= query_type << 1
    packet |= service_bit << 3
    packet |= service_bits << 4
    data = bytearray([packet])
    if databytes:
        data.extend(databytes)
    return bytes(data)


def decode_query(data: bytes) -> Tuple[Frame, Control, int, int]:
    """
    Die Funktion soll einen Query dekodieren ...
    """
    first_byte = data[0]
    packet = Frame(first_byte & 0x01)
    query_type = Control((first_byte >> 1) & 0b11)
    service_bit = (first_byte >> 3) & 0x01
    service_bits = (first_byte >> 4) & 0b1111

    return packet, query_type, service_bit, service_bits


def query_battery_on() -> bytes:
    """
    Query für die Abfrage ob der Akku ein- oder
    ausgeschaltet ist
    """
    return make_query(Control.Query, service_bits=1)


def set_battery_off() -> bytes:
    """
    Query um den Akku auszuschalten
    """
    return make_query(Control.Set, service_bits=1)


def set_battery_on() -> bytes:
    """
    Query um den Akku einzuschalten
    """
    return make_query(query_type=Control.Set, service_bit=0x1, service_bits=1)


def query_cell_voltage(cell_id) -> bytes:
    """
    Query um die Zellspannung abzufragen.
    Die ID der Zelle fängt bei 0 an und der Regel
    besteht ein 12V Akku aus 4 Zellen.
    """
    return make_query(
        Control.Query, service_bit=0x0, service_bits=7, databytes=bytearray([cell_id])
    )


def query_lower_upper_voltage() -> bytes:
    """
    Query um die untere/obere Zellspannung abzufragen.
    """
    return make_query(
        Control.Query,
        service_bit=1,
        service_bits=10,
    )


def query_configuration() -> bytes:
    """
    Query um die Konfiguration des Akkus abzufragen
    """
    return make_query(Control.Query, service_bit=0x0, service_bits=10)


def query_error_history(area) -> bytes:
    """
    Query für den Fehler-Speicher
    """
    data = struct.pack("<H", area)
    return make_query(Control.Query, service_bit=0x0, service_bits=9, databytes=data)


def query_dimensions() -> bytes:
    """
    Query der Dimensionierung
    """
    return make_query(Control.Query, service_bit=0x0, service_bits=0b1001)


def set_reset_alarm() -> bytes:
    """
    Query um den Alarm zurück zu setzen
    """
    return make_query(Control.Set, service_bit=0x0, service_bits=8)


def set_reset_battery() -> bytes:
    """
    Query um die den Akku zurück zu setzen
    """
    return make_query(Control.Set, service_bit=0x1, service_bits=8)


QUERIES = {
    "capacity": dict(service_bit=0x1, service_bits=6, fmt="<Bf"),
    "load": dict(service_bit=0x0, service_bits=6, fmt="<Bf"),
    "voltage": dict(service_bit=0x0, service_bits=4, fmt="<Bf"),
    "current": dict(service_bit=0x1, service_bits=4, fmt="<Bf"),
    "temperature": dict(service_bit=0x1, service_bits=7, fmt="<Bf"),
    "cell_voltage": dict(service_bit=0x0, service_bits=7, fmt="<BBf"),
    "error_flags": dict(service_bit=0x0, service_bits=9, fmt="<BH"),
    "set_battery_on": dict(
        query_type=Control.Set, service_bit=0x1, service_bits=1, fmt="<B"
    ),
    "set_battery_off": dict(
        query_type=Control.Set, service_bit=0x0, service_bits=1, fmt="<B"
    ),
}


def get_cell_voltage(cell_id: int):
    qry = QUERIES["cell_voltage"].copy()
    # noinspection PyTypeChecker
    qry["databytes"] = bytes([cell_id])
    return qry


class Query(Thread):
    def __init__(self, ser: Serial):
        super().__init__(daemon=True)
        self.ser = ser

    def run(self):
        while True:
            header_size = self.get_header()

            if header_size is None:
                continue

            header, size, decoder, name = header_size
            payload = self.ser.read(size)
            _, *values = decoder.unpack(header + payload)
            print(datetime.datetime.now(), name, values)

    def do_query(self, queries: List[str]):
        queries, reply_size = self.encode(queries)
        timeout = 1 + len(queries) * 0.2
        GPIO.output(TXD_EN, 0)
        time.sleep(0.2)
        self.ser.write(queries)
        time.sleep(timeout)
        GPIO.output(TXD_EN, 1)

    @staticmethod
    def encode(queries: List[Union[str, dict]]) -> Tuple[bytes, int]:
        query_bytes = b""
        answer_size = 0
        for query in queries:
            if isinstance(query, dict):
                query_type = query.get("query_type", Control.Query.value)
                service_bit = query["service_bit"]
                service_bits = query["service_bits"]
                fmt = query["fmt"]
                databytes = query.get("databytes")
            elif isinstance(query, str):
                query_type = QUERIES[query].get("query_type", Control.Query.value)
                service_bit = QUERIES[query]["service_bit"]
                service_bits = QUERIES[query]["service_bits"]
                fmt = QUERIES[query]["fmt"]
                databytes = QUERIES[query].get("databytes")
            else:
                continue

            query_bytes += make_query(
                query_type=query_type,
                service_bit=service_bit,
                service_bits=service_bits,
                databytes=databytes,
            )
            answer_size += struct.calcsize(fmt)
        return query_bytes, answer_size

    def get_header(self) -> Optional[Tuple[bytes, int, struct.Struct, str]]:
        header = self.ser.read(1)
        try:
            _, control, service_bit, service_bits = decode_query(header)
        except ValueError:
            return

        for name, query in QUERIES.items():
            if control != Control.Answer.value:
                return

            cond1 = query["service_bit"] == service_bit
            cond2 = query["service_bits"] == service_bits
            if cond1 and cond2:
                fmt = query["fmt"]
                decoder = struct.Struct(fmt)
                size = decoder.size - 1
                return header, size, decoder, name

    @staticmethod
    def decode(self, data: bytes):
        reader = io.BytesIO(data)
        while True:
            header = reader.read(1)

            if not header:
                break

            try:
                _, control, service_bit, service_bits = decode_query(header)
            except ValueError:
                continue


def setup_gpio():
    """
    Ein- und Ausgänge konfigurieren und setzen.
    """

    def cb(text):
        def inner(pin):
            print(text, pin, GPIO.input(pin))

        return inner

    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(TXD_EN, GPIO.OUT, initial=GPIO.HIGH)  # /Transmit Data Enable
    # GPIO.setup(RXD_SENSE, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)  # Receive Data Sense
    # GPIO.setup(TXD_SENSE, GPIO.IN, pull_up_down=GPIO.PUD_UP)  # /Transmit Data Sense
    # GPIO.add_event_detect(RXD_SENSE, GPIO.BOTH, cb("RXD_SENSE"))
    # GPIO.add_event_detect(TXD_SENSE, GPIO.BOTH, cb("TXD_SENSE"))


def read(query, answer_size) -> bytes:
    GPIO.output(TXD_EN, 0)
    serial.flushInput()

    timeout = 5 + time.monotonic()
    while serial.in_waiting < 2:
        time.sleep(0.01)
        if timeout < time.monotonic():
            print("Master does not react.")
            GPIO.output(TXD_EN, 1)
            serial.flushInput()
            return b""

    serial.flushInput()
    serial.write(query)

    timeout = (answer_size * 0.1) + time.monotonic()
    while serial.in_waiting < answer_size:
        time.sleep(0.01)
        if timeout < time.monotonic():
            print("Got timeout")
            break

    time.sleep(0.5)
    GPIO.output(TXD_EN, 1)

    data = serial.read(serial.in_waiting)[:answer_size]
    serial.flushInput()
    return data


def read_all():
    q = (
        query_voltage()
        + query_current()
        + query_load()
        + query_cell_temperature()
        + query_error_flags()
        + query_capacity()
        + query_cell_voltage(0)
    )
    fmt = "<BfBfBfBfBHBfBBf"
    print(struct.calcsize(fmt))
    data = read(q, struct.calcsize(fmt))
    return struct.unpack(fmt, data)


if __name__ == "__main__":
    setup_gpio()
    serial = Serial(
        "/dev/serial0",
        1000,
        EIGHTBITS,
        PARITY_EVEN,
        STOPBITS_ONE,
    )
    q = Query(serial)
    q.start()
