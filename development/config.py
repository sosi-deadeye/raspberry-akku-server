import json
from datetime import datetime as dt
from datetime import timedelta as td
from configparser import ConfigParser

cfg = ConfigParser()
cfg.read(['default.ini','config.ini'])


def set_run_ts(ts=None, diff=None):
    if not ts:
        ts = dt.utcnow()
    if not diff:
        diff = td(seconds=0)
    cfg['general']['last_run'] = (ts + diff).isoformat()
    with open('config.ini', 'w') as fd:
        cfg.write(fd)


def get_run_ts():
    return dt.fromisoformat(cfg['general']['last_run'])


def set_email():
    with open('email.json') as fd:
        email = json.load(fd)
    cfg['email'].update({k: str(v) for k,v in email.items()})
