#!/usr/bin/env python3
from __future__ import annotations

import math
import statistics
import struct
import time
from collections import deque
from datetime import datetime
from enum import IntEnum, Enum
from logging import getLogger, basicConfig, DEBUG, INFO
from queue import Empty as QueueEmpty
from queue import PriorityQueue, Queue
from subprocess import call
from threading import Thread
from typing import Union, List, Tuple, Optional

import RPi.GPIO as GPIO
import serial
import zmq

import errors
import notify
import timedaemon
from database import (
    Session,
    Configuration,
    Error,
    State,
    set_cycle,
    Statistik,
)
from current_values import set_values as set_current_values


TXD_EN = 17  # /Transmit Data Enable
TXD_SENSE = 22  # Receive Data Sense
RXD_SENSE = 27  # /Transmit Data Sense

QueriesType = List[Tuple[bytes, int]]


class QueryScheduler:
    NORMAL = "normal"
    LIVE = "live"

    def __init__(
        self,
        queries_normal: QueriesType,
        queries_live: QueriesType,
        live_timeout: float = 10,
    ):
        self.mode = self.NORMAL
        self.queries_normal = queries_normal
        self.queries_live = queries_live
        # first all normal queries are waiting
        self.waiting = [(query, freq, 0) for (query, freq) in queries_normal]
        self.live_timeout = live_timeout
        self.normal_after = time.monotonic()
        self.first_run = True

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

    def __next__(self) -> List[bytes]:
        if self.first_run:
            self.first_run = False
        elif self.mode == self.LIVE and time.monotonic() > self.normal_after:
            log.info("Switching back to normal mode")
            self.switch(self.NORMAL)

        current_queries = [
            bytes(query)
            for (query, freq, after) in self.waiting
            if time.monotonic() > after
        ]

        self.waiting = self._next_in_queue()
        return current_queries

    def switch(self, mode):
        if self.first_run:
            return
        if mode == self.LIVE:
            self.normal_after = time.monotonic() + self.live_timeout
        if self.mode != mode:
            self.mode = mode
            self.waiting = self._next_in_waiting()
            if mode == self.LIVE:
                log.info(f"Switch mode to {mode}")

    def live(self):
        self.switch(self.LIVE)


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


class FrameParser:
    types = {
        # Mode
        (Frame.A, Control.Query, 0, 1): {"type": Mode.QueryOnOff},
        (Frame.A, Control.Answer, 1, 1): {"type": Mode.AnswerOn},
        (Frame.A, Control.Answer, 0, 1): {"type": Mode.AnswerOff},
        (Frame.A, Control.Set, 0, 1): {"type": Mode.SetOff},
        (Frame.A, Control.Answer, 0, 1): {"type": Mode.AnswerSetOff},
        (Frame.A, Control.Set, 1, 1): {"type": Mode.SetOn},
        (Frame.A, Control.Answer, 1, 1): {"type": Mode.AnswerSetOn},
        # Data
        (Frame.A, Control.Query, 0, 4): {"type": Data.QueryVoltage},
        (Frame.A, Control.Answer, 0, 4): {
            "type": Data.AnswerVoltage,
            "constraints": lambda x: 0 < x[0] < 200,
        },
        (Frame.A, Control.Query, 1, 4): {"type": Data.QueryCurrent},
        (Frame.A, Control.Answer, 1, 4): {
            "type": Data.AnswerCurrent,
            "constraints": lambda x: -1000 < x[0] < 1000,
        },
        (Frame.A, Control.Query, 0, 6): {"type": Data.QueryCharge},
        (Frame.A, Control.Answer, 0, 6): {
            "type": Data.AnswerCharge,
            "constraints": lambda x: -100 < x[0] < 2000,
        },
        (Frame.A, Control.Query, 1, 6): {"type": Data.QueryCapacity},
        (Frame.A, Control.Answer, 1, 6): {
            "type": Data.AnswerCapacity,
            "constraints": lambda x: -100 < x[0] < 1000,
        },
        (Frame.A, Control.Query, 0, 7): {"type": Data.QueryCellVoltage},
        (Frame.A, Control.Answer, 0, 7): {
            "type": Data.AnswerCellVoltage,
            "constraints": lambda x: 0 < x[1] < 5,
        },
        (Frame.A, Control.Query, 1, 7): {"type": Data.QueryTemperature},
        (Frame.A, Control.Answer, 1, 7): {
            "type": Data.AnswerTemperature,
            "constraints": lambda x: -300 < x[0] < 300,
        },
        # Reset
        (Frame.A, Control.Set, 0, 8): {"type": Reset.SetResetError},
        (Frame.A, Control.Answer, 0, 8): {"type": Reset.SetResetAnswer},
        (Frame.A, Control.Set, 1, 8): {"type": Reset.SetAkkuResetError},
        (Frame.A, Control.Answer, 1, 8): {"type": Reset.SetAkkuResetAnswer},
        # Fault
        (Frame.A, Control.Query, 0, 9): {"type": Fault.QueryErrorFlags},
        (Frame.A, Control.Answer, 0, 9): {"type": Fault.AnswerErrorFlags},
        (Frame.A, Control.Query, 1, 9): {"type": Fault.QueryErrorMemory},
        (Frame.A, Control.Answer, 1, 9): {"type": Fault.AnswerErrorMemory},
        # Message
        (Frame.A, Control.Answer, 0, 10): {"type": Message.Answer},
        (Frame.A, Control.Acknowledge, 0, 10): {"type": Message.Ack},
        # Configuration
        (Frame.A, Control.Query, 0, 11): {"type": FConfiguration.QueryDimension},
        (Frame.A, Control.Answer, 0, 11): {"type": FConfiguration.AnswerDimension},
        (Frame.A, Control.Set, 1, 11): {"type": FConfiguration.Set},
        (Frame.A, Control.Acknowledge, 1, 11): {"type": FConfiguration.Ack},
        # Protocol Error
        (Frame.A, Control.Answer, 0, 5): {"type": "Protokollfehler"},
    }

    def __init__(self, frame, control, data_bit, service_bits):
        self.frame = frame
        self.control = control
        self.data_bit = data_bit
        self.service_bits = service_bits
        self.values = []
        try:
            self.frame_type = self.types[(frame, control, data_bit, service_bits)]
        except KeyError:
            self.frame_type = {"type": None, "constraints": lambda x: x}

    def is_zero(self):
        return (
            self.frame == 0
            and self.control == 0
            and self.data_bit == 0
            and self.service_bits == 0
        )

    def read_reply(self, serial_connection: serial.Serial) -> Tuple:
        frame_type = self.frame_type["type"]
        if frame_type in (
            Data.AnswerVoltage,
            Data.AnswerCurrent,
            Data.AnswerCharge,
            Data.AnswerCapacity,
            Data.AnswerTemperature,
        ):
            values = struct.unpack("<f", serial_connection.read(4))
        elif frame_type is Data.AnswerCellVoltage:
            values = struct.unpack("<Bf", serial_connection.read(5))
        elif frame_type is Fault.AnswerErrorFlags:
            values = struct.unpack("<H", serial_connection.read(2))
        elif frame_type is Mode.AnswerSetOff:
            values = (False,)
        elif frame_type is Mode.AnswerSetOn:
            values = (True,)
        else:
            raise TypeError("Fehlerhafte Antwort")
        if "constraints" in self.frame_type and not self.frame_type["constraints"](
            values
        ):
            raise ValueError(f'Value "{values}" is not in allowed range')
        self.values = values
        return values

    def is_reply(self, other) -> bool:
        # if other.service_bits == 9:
        #     print(other, other.frame_type)
        if other.service_bits != 1:
            return (
                self.frame == other.frame
                and self.data_bit == other.data_bit
                and self.service_bits == other.service_bits
            )
        else:
            return self.frame == other.frame and self.service_bits == other.service_bits

    def to_bytes(self) -> bytes:
        return bytes(
            bytearray(
                [
                    self.frame
                    | self.control << 1
                    | self.data_bit << 3
                    | self.service_bits << 4
                ]
            )
        )

    @classmethod
    def from_bytes(cls, value: Union[int, bytes]) -> FrameParser:
        if not value:
            return cls(0, 0, 0, 0)
        if isinstance(value, int):
            value = bytes(bytearray([value]))
        try:
            data = value[0]
            frame = Frame(data & 0x1)
            control = Control(data >> 1 & 0x03)
            data_bit = bool(data & 0x08)
            service_bits = data >> 4
            return cls(frame, control, data_bit, service_bits)
        except (ValueError, IndexError):
            return cls(0, 0, 0, 0)

    def __eq__(self, other) -> bool:
        return (
            self.frame == other.frame
            and self.control == other.control
            and self.data_bit == other.data_bit
            and self.service_bits == other.service_bits
        )

    def __bytes__(self) -> bytes:
        return self.to_bytes()

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(frame={self.frame}, "
            f"control={self.control}, data_bit={self.data_bit}, "
            f"service_bits={self.service_bits})"
        )


class DataReader(Thread):
    def __init__(
        self, answer_queue: ManyQueue, queries: QueryScheduler, cells: int = 4,
    ):
        self.answer_queue: ManyQueue = answer_queue
        self.cells: int = cells
        self.queries: QueryScheduler = queries
        self.session = Session()
        self.cycle: int = set_cycle(self.session)
        self.capacity: Optional[float] = None
        self.last_error: Optional[int] = None
        self.last_error_flags: Optional[int] = None
        self.error_topics: list = [
            0x0010,
            0x0020,
            0x0100,
            0x0200,
            0x1000,
            0x2000,
            0x4000,
            0x8000,
        ]
        self.notified: bool = False
        self.row: int = 0
        self.current_values = {
            "voltage": 0.0,
            "current": 0.0,
            "charge": 0.0,
            "capacity": 0.0,
            "temperature": 0.0,
            "cell_voltages": [0.0] * self.cells,
            "error": 0,
        }
        self.db_update_interval: float = 60
        self.db_next_update: float = time.monotonic() + 120
        self.stats_current: deque = deque(maxlen=4)
        self.stats_charge: deque = deque(maxlen=4)
        self.timedelta_queue: Optional[Queue] = None
        self.notified: bool = False
        super().__init__()

    def handle_error(self, error_flags: int) -> None:
        """
        Fehlerbehandlung
        """
        if error_flags != self.last_error_flags:
            self.last_error_flags = error_flags
            self.current_values["error"] = error_flags
            self.session.add(Error(row=self.row, cycle=self.cycle, error=error_flags))
            error_text = errors.get_msg(error_flags, err_topics=self.error_topics)
            if error_text and error_text != self.last_error:
                self.last_error = error_text
                Thread(target=notify.send_report, args=(error_text,)).start()

    def update_current_values(self) -> None:
        current_data = (
            self.row,
            self.row,
            self.cycle,
            int(self.current_values["capacity"]),
            self.current_values["error"],
            self.current_values["voltage"],
            self.current_values["current"],
            self.current_values["charge"],
            self.current_values["temperature"],
            datetime.now().timestamp(),
            *self.current_values["cell_voltages"],
        )
        set_current_values(current_data)

    def check_timedelta(self) -> None:
        """
        Prüfe ob es Sprünge in der Zeit gab.

        Anschließende Korrektur der Zeitstempel.
        """
        if not self.timedelta_queue.empty():
            log.info(
                f"Die Systemzeit hat sich geändert. Aktualisiere die Daten aus dem Zyklus {self.cycle}"
            )
            diff, positive = self.timedelta_queue.get()
            # den Zyklus und alle Zeilen < self.row müssen aktualisiert werden
            for stat in self.session.query(Statistik).filter(
                Statistik.cycle == self.cycle, Statistik.row < self.row
            ):
                if positive:
                    corrected_timestamp = stat.timestamp + diff
                else:
                    corrected_timestamp = stat.timestamp - diff
                stat.timestamp = corrected_timestamp
                self.session.merge(stat)

    def get_important_values(self) -> None:
        """
        Frage Kapazität, Status und Ladung ab
        """
        # log.info("Frage Kapazität ab")
        #
        # # ==============================
        # send_one_query(query_capacity())
        # _, values = self.answer_queue.get()
        # capacity = values[0]
        # log.info(f"Kapazität ist {capacity:.0f} Ah")
        # # ==============================
        #
        # self.capacity = capacity
        # self.current_values["capacity"] = capacity
        # self.session.add(Configuration(capacity=self.capacity, cycle=self.cycle))
        #
        # send_one_query(query_load())
        # _, values = self.answer_queue.get()
        # charge = values[0]
        # self.current_values["charge"] = charge
        # log.info(f"Ladung beträgt {charge:.0f} Ah.")
        send_many_queries([query_capacity(), query_load(), query_battery_on()])

    def run(self) -> None:
        """
        Diese Funktion wird indirekt durch die Methode start() aufgerufen.
        """
        log.debug("Datalogger: Starte Zeitüberwachung")
        self.timedelta_queue: Queue = timedaemon.start()
        log.info(f"Zyklus: {self.cycle}")
        self.get_important_values()
        log.info("Datalogger: Betrete Endlosschleife")
        while True:
            # Prüfe ob sich die Zeit geändert hat
            # und führe Korrekturen aus
            self.check_timedelta()

            queries = next(self.queries)
            self.send_queries(queries)
            self.handle_queries()
            self.database_insert()
            self.check_alert()

            # 100 ms warten.
            time.sleep(0.1)

    def check_alert(self) -> None:
        """
        Prüfe ob die Ladung unter 10% ist.
        (Ladung kann auch negativ sein.)

        Ladung unter 15% ist -> E-Mail versenden
        Ladung unter 10% ist -> E-Mail versenden, WLAN-Modul herunterfahren.
        """
        if self.capacity is not None and not math.isclose(self.capacity, 0):
            try:
                median_charge = statistics.median(self.stats_charge)
                median_current = statistics.median(self.stats_current)
            except statistics.StatisticsError:
                return
            relative_load = (median_charge / self.capacity) * 100
            # log.info(f'Relative Ladung {relative_load}')
            if not self.notified and 10 < relative_load < 15:
                log.warning("Ladung unter 15%. E-Mail wird gesendet.")
                notify_thread = Thread(
                    target=notify.send_report,
                    args=(
                        "Die Ladung des Akkus liegt zwuschen 10 und 15%. Bitte nachladen.",
                    ),
                )
                notify_thread.start()
                self.notified = True
            elif relative_load < 10 and median_current < 0:
                notify.send_report(
                    "Die Ladung des Akkus ist unter 10%. Das Wlan-Modul wird heruntergefahren."
                )
                log.warning(f"Achtung Ladung: {relative_load:.1f} %")
                GPIO.setup(5, GPIO.OUT)
                GPIO.output(5, True)
                time.sleep(2)
                GPIO.output(5, False)
                time.sleep(1)
                GPIO.output(5, True)
                time.sleep(2)
                GPIO.output(5, False)
                call(["shutdown", "-h", "0"])

    def database_insert(self) -> None:
        """
        Prüfe ob nächster Datenbankeintrag fällig ist.
        Falls ja, Daten speichern und Timer neu setzen.
        """
        if time.monotonic() > self.db_next_update:
            log.info(f"Speichere Datensatz {self.row} in der Datenbank")
            current_values = self.current_values.copy()
            try:
                current_mean = statistics.mean(self.stats_current)
            except statistics.StatisticsError:
                pass
            else:
                current_values["current"] = current_mean
            del current_values["capacity"]  # this key is in a different table
            del current_values["error"]  # this also
            dataset = Statistik(cycle=self.cycle, row=self.row, **current_values)
            self.session.add(dataset)
            self.session.commit()
            self.row += 1
            self.db_next_update = time.monotonic() + self.db_update_interval

    @staticmethod
    def send_queries(queries: List[bytes, ...]) -> None:
        if not queries:
            return
        send_many_queries(queries)

    def handle_queries(self) -> None:
        for frame_type, values in self.answer_queue.get_many():
            frame_type = frame_type["type"]
            if frame_type is Data.AnswerCapacity:
                self.current_values["capacity"] = values[0]
            elif frame_type is Data.AnswerVoltage:
                self.current_values["voltage"] = values[0]
            elif frame_type is Data.AnswerCurrent:
                self.current_values["current"] = values[0]
                self.stats_current.append(values[0])
            elif frame_type is Data.AnswerCharge:
                self.current_values["charge"] = values[0]
                self.stats_charge.append(values[0])
            elif frame_type is Data.AnswerTemperature:
                self.current_values["temperature"] = values[0]
            elif frame_type is Data.AnswerCellVoltage:
                cell_id, cell_voltage = values
                try:
                    self.current_values["cell_voltages"][cell_id] = cell_voltage
                except IndexError:
                    log.error(f"Zellen-Index {cell_id} ist ungültig")
            elif frame_type is Fault.AnswerErrorFlags:
                self.handle_error(values[0])
            elif frame_type is Mode.AnswerSetOff:
                self.session.add(State(cycle=self.cycle, row=self.row, onoff=False))
            elif frame_type is Mode.AnswerSetOn:
                self.session.add(State(cycle=self.cycle, row=self.row, onoff=True))
        self.update_current_values()


class Commands(Enum):
    topic = b"CONTROL"
    on = b"on"
    off = b"off"
    reset = b"reset"
    ack = b"ack"
    live = b"LIVE"


class Priority(IntEnum):
    """
    Lower value > higher priority
    """

    command = 5
    query = 10


class GetMany:
    """
    Additional method for a Queue, PriorityQueue or other Queues
    """

    def get_many(self, timout=0.5, max_queue_size=None):
        """
        Return as many queries as possible in a list
        """
        queries = []
        if max_queue_size is None:
            while True:
                try:
                    item = self.get(block=True, timeout=timout)
                except QueueEmpty:
                    break
                else:
                    queries.append(item)
            return queries
        else:
            for _ in range(max_queue_size):
                try:
                    item = self.get(block=True, timeout=timout)
                except QueueEmpty:
                    break
                else:
                    queries.append(item)
            return queries

    def get(self, block: bool, timeout: float):
        raise NotImplementedError


class ManyPriorityQueue(PriorityQueue, GetMany):
    """
    Extended PriorityQueue
    """

    def get_many(self, timout=0.5, max_queue_size=5):
        """
        Return as many queries as possible in a list
        Priority is removed from list

        Identical queries are removed, but the order is kept
        """
        return list(
            dict.fromkeys(
                item[1]
                for item in super().get_many(
                    timout=timout, max_queue_size=max_queue_size
                )
            ).keys()
        )


class ManyQueue(Queue, GetMany):
    """
    ExtendedQueue
    """


class CommandLoop(Thread):
    def __init__(self, addr):
        super().__init__()
        self.ctx = zmq.Context()
        # noinspection PyUnresolvedReferences
        self.addr = addr
        self.sock = self.ctx.socket(zmq.SUB)
        self.sock.bind(addr)
        self.sock.subscribe(Commands.topic.value)

    def run(self):
        while True:
            topic, cmd = self.sock.recv_multipart()
            if cmd == Commands.on.value:
                log.info("Set Battery on")
                send_command(set_battery_on())
            elif cmd == Commands.off.value:
                log.info("Set Battery off")
                send_command(set_battery_off())
            elif cmd == Commands.reset.value:
                log.info("Reset battery")
                send_command(set_reset_battery())
            elif cmd == Commands.ack.value:
                log.info("Send Ack")
                send_command(set_reset_alarm())
            elif cmd == Commands.live.value:
                query_scheduler.live()


class SerialTxLock:
    """
    Kontextmanager der die Logik für den Handshake regelt.
    """

    def __init__(
        self,
        txd_timeout: Union[float, int] = 300,
        rxd_timeout: Union[float, int] = 10_000,
        penalty_time: Union[float, int] = 10_000,
        txd_enable_pin: int = TXD_EN,
        txd_sense_pin: int = TXD_SENSE,
        rxd_sense_pin: int = RXD_SENSE,
    ):
        self.txd_timeout = int(txd_timeout)
        self.rxd_timeout = int(rxd_timeout)
        self.txd_enable = txd_enable_pin
        self.txd_sense = txd_sense_pin
        self.rxd_sense = rxd_sense_pin
        self.penalty_time = penalty_time
        self.penalty = False

    def __enter__(self):
        self.txd_sense_wait()
        self.enable_txd()
        if self.rxd_sense_wait():
            self.penalty = True

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disable_txd()
        if self.penalty:
            self.penalty = False
            time.sleep(self.penalty_time / 1000)

    def enable_txd(self):
        GPIO.output(self.txd_enable, False)

    def disable_txd(self):
        GPIO.output(self.txd_enable, True)

    def rxd_sense_wait(self) -> bool:
        if not GPIO.input(self.rxd_sense):
            result = GPIO.wait_for_edge(self.rxd_sense, GPIO.RISING, timeout=self.rxd_timeout)
            if result is None:
                log.critical("Timeout bei der Antwort")
                return False
            else:
                return True

    def txd_sense_wait(self) -> None:
        while True:
            if (
                GPIO.wait_for_edge(self.txd_sense, GPIO.FALLING, timeout=self.txd_timeout)
                is None
            ):
                break


class SerialServer(Thread):
    def __init__(
        self,
        *,
        port: str,
        baudrate: int,
        parity: int,
        bytesize: int,
        stopbits: int,
        sender_queue: ManyPriorityQueue,
        receiver_queue: Queue,
        retries: int = 3,
    ) -> None:
        super().__init__()
        self.serial = serial.Serial(
            port, baudrate, bytesize, parity, stopbits, timeout=10
        )
        self.sender_queue = sender_queue
        self.receiver_queue = receiver_queue
        self.retries = retries
        self.serial_handshake = SerialTxLock()

    @staticmethod
    def log_query(query: bytes) -> None:
        query_frame = FrameParser.from_bytes(query)
        try:
            f_type = query_frame.frame_type["type"]
            # noinspection PyUnresolvedReferences
            log.debug(f"Anfrage: {f_type.value}")
        except (ValueError, AttributeError):
            pass

    @staticmethod
    def log_answer(rep: FrameParser):
        try:
            # noinspection PyUnresolvedReferences
            frame_name = rep.frame_type["type"].value
            log.debug(f"Antwort: {frame_name}: {rep.values}")
        except (ValueError, AttributeError) as e:
            log.debug(f"Error: {e}")

    def read_data(self):
        data = b"\x00"
        for _ in range(3):
            data = self.serial.read(1)
            if data != b"x\00":
                break
        else:
            return

        rep = FrameParser.from_bytes(data)
        if not rep.is_zero():
            try:
                values = rep.read_reply(self.serial)
            except (TypeError, ValueError, struct.error, serial.SerialException) as e:
                log.debug(e)
            else:
                self.receiver_queue.put((rep.frame_type, values))
                self.log_answer(rep)

    def run(self) -> None:
        while True:
            queries = self.sender_queue.get_many()
            if queries:
                with self.serial_handshake:
                    # time.sleep(0.1)
                    # Anfrage senden
                    self.serial.write(b"".join(queries))
                    self.serial.flush()
                    for query in queries:
                        self.log_query(query)

                    # Daten nach den Anfragen lesen
                    time.sleep(0.3 + 0.2 * len(queries))
                    for _ in queries:
                        self.read_data()

            # Lese restliche Daten
            if self.serial.in_waiting:
                self.read_data()
            time.sleep(0.1)


def send_one_query(query) -> None:
    """
    Eine Anfrage zur Warteschlange schicken
    """
    item = (Priority.query, query)
    # log.debug(f"Priorität {item[0]} | {query}")
    serial_sender_queue.put(item)


def send_many_queries(queries) -> None:
    """
    Mehrere Anfragen aufeinmal zur Warteschlange schicken
    """
    for query in queries:
        item = (Priority.query, query)
        serial_sender_queue.put(item)


def send_command(command_query) -> None:
    item = (Priority.command, command_query)
    serial_sender_queue.put(item)


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
    return make_query(Control.Set, service_bit=0x1, service_bits=1)


def query_voltage() -> bytes:
    """
    Query um die Gesammtspannung abzufragen
    """
    return make_query(Control.Query, service_bit=0x0, service_bits=4)


def query_current() -> bytes:
    """
    Query um den Strom abzufragen
    """
    return make_query(Control.Query, service_bit=0x1, service_bits=4)


def query_load() -> bytes:
    """
    Query um die Ladung abzufragen
    """
    return make_query(Control.Query, service_bit=0x0, service_bits=6)


def query_capacity() -> bytes:
    """
    Query um die Kapazität abzufragen
    """
    return make_query(Control.Query, service_bit=0x1, service_bits=6)


def query_cell_voltage(cell_id) -> bytes:
    """
    Query um die Zellspannung abzufragen.
    Die ID der Zelle fängt bei 0 an und der Regel
    besteht ein 12V Akku aus 4 Zellen.
    """
    return make_query(
        Control.Query, service_bit=0x0, service_bits=7, databytes=bytearray([cell_id])
    )


def query_configuration() -> bytes:
    """
    Query um die Konfiguration des Akkus abzufragen
    """
    return make_query(Control.Query, service_bit=0x0, service_bits=10)


def query_error_flags() -> bytes:
    """
    Query für die Fehlercodes
    """
    return make_query(Control.Query, service_bit=0x0, service_bits=9)


def query_error_history(area) -> bytes:
    """
    Query für den Fehler-Speicher
    """
    data = struct.pack("<H", area)
    return make_query(Control.Query, service_bit=0x0, service_bits=9, databytes=data)


def query_cell_temperature() -> bytes:
    """
    Query um die Zelltenmperatur abzufragen
    """
    return make_query(Control.Query, service_bit=0x1, service_bits=7)


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


def setup_gpio():
    """
    Ein- und Ausgänge konfigurieren und setzen.
    """
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(TXD_EN, GPIO.OUT, initial=GPIO.HIGH)  # /Transmit Data Enable
    GPIO.setup(RXD_SENSE, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)  # Receive Data Sense
    GPIO.setup(TXD_SENSE, GPIO.IN, pull_up_down=GPIO.PUD_UP)  # /Transmit Data Sense


basicConfig(level=INFO)
log = getLogger("Server")
serial_sender_queue = ManyPriorityQueue()
serial_receiver_queue = ManyQueue()

QUERIES_LIVE: QueriesType = [
    (query_voltage(), 15),
    (query_current(), 2),
    (query_load(), 60),
    (query_cell_temperature(), 60),
    *[(query_cell_voltage(n), 60) for n in range(4)],
    (query_error_flags(), 15),
]

QUERIES_NORMAL: QueriesType = [
    (query_voltage(), 60),
    (query_current(), 10),
    (query_load(), 60),
    (query_cell_temperature(), 5 * 60),
    *[(query_cell_voltage(n), 5 * 60) for n in range(4)],
    (query_error_flags(), 60),
]


if __name__ == "__main__":
    setup_gpio()
    log.debug("Starte QueryScheduler")
    query_scheduler = QueryScheduler(QUERIES_NORMAL, QUERIES_LIVE)

    log.debug("Starte seriellen Server")
    serial_server = SerialServer(
        port="/dev/serial0",
        baudrate=1000,
        parity=serial.PARITY_EVEN,
        bytesize=serial.EIGHTBITS,
        stopbits=serial.STOPBITS_ONE,
        sender_queue=serial_sender_queue,
        receiver_queue=serial_receiver_queue,
    )
    serial_server.start()

    log.debug("Starte Befehlsempfänger")
    command_server = CommandLoop(addr="tcp://127.0.0.1:4000")
    command_server.start()

    log.debug("Starte Datenlogger")
    data_logger = DataReader(serial_receiver_queue, query_scheduler)
    data_logger.start()
