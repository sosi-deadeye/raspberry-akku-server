import time
from datetime import timedelta
from threading import Thread
from queue import Queue
from typing import Generator, Tuple


OBSERVER_YIELD = Tuple[timedelta, float]
OBSERVER_TYPE = Generator[OBSERVER_YIELD, None, None]


def observer() -> OBSERVER_TYPE:
    last = time.time()
    while True:
        time.sleep(1)
        now = time.time()
        delta = now - last
        positive, delta = delta > 0, abs(delta)
        if delta > 2:
            td = timedelta(seconds=delta)
            yield td, positive
        last = now


def daemon(queue: Queue) -> None:
    for td in observer():
        queue.put(td)


def start() -> Queue:
    queue: Queue = Queue()
    thread = Thread(target=daemon, args=[queue], daemon=True)
    thread.start()
    return queue
