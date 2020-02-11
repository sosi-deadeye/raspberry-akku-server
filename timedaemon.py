import time
from datetime import timedelta
from threading import Thread
from queue import Queue


def observer():
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


def daemon(queue):
    for timedelta in observer():
        queue.put(timedelta)

def start():
    queue = Queue()
    thread = Thread(target=daemon, args=[queue], daemon=True)
    thread.start()
    return queue
