import time
from datetime import datetime as dt
from datetime import timedelta as td

from database import session, Charge, get_cycle
import config


def correct_time(diff, last):
    cycle = get_cycle()
    query = session.query(Charge).filter(Charge.cycle == cycle, Charge.timestamp <= last)
    for element in query.all():
        print(element.timestamp, end=' ')
        element.timestamp += diff
        print(element.timestamp)
        session.merge(element)
    session.commit()


def watch_timechange(max_diff=61):
    last = time.time()
    config.set_run_ts()
    while True:
        now = time.time()
        diff = abs(now - last)
        if diff > max_diff:
            print('Change detected')
            diff = td(seconds=now - last - 1)
            print(last, now, diff)
            ts = config.get_run_ts()
            config.set_run_ts(ts=ts, diff=diff)
            correct_time(diff, dt.utcfromtimestamp(last))
        last = time.time()
        time.sleep(1)

#correct_time(32, td(hours=10), dt(2019,12,8))

watch_timechange()
