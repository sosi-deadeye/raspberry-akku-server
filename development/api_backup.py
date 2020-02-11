import csv
import io
import json
from subprocess import call
from collections import defaultdict

from fastapi import FastAPI
from pydantic import BaseModel, Schema
from starlette.responses import PlainTextResponse

import zmq


app = FastAPI(
    title='Akku',
    version='0.1.1',
    description='Rest API für den Akku')

# queries = (
#     query_current, query_voltage, query_capacity,
#     query_load, query_error_flags, query_cell_temperature,
# )



class Mock:
    topics = ("Capacity","Load Ah","Voltage","Current","Cell voltage 1","Cell voltage 2","Cell voltage 3","Cell voltage 4","Cell temperature","Error flags")
    def __getitem__(self, key):
        return 123.456
    def items(self):
        return [(t, [0, 123.456]) for t in self.topics]


def get_statistic():
    try:
        with open('/root/akku/stats.json') as fd:
            return json.load(fd)
    except:
        return Mock()


class Spannung(BaseModel):
    """
    Spannung abfragen
    """
    spannungen: list = Schema(..., title='Gesammtspannung', description='Enthält eine Liste mit den gemessenen Gesamtspannungen')


class Strom(BaseModel):
    """
    Strom abfragen
    """
    ströme: list = Schema(..., title='Gesammtstrom', description='Enthält eine Liste mit den gemessenen Gesamtströmen')


class Kapazität(BaseModel):
    """
    Kapazität abfragen
    """
    kapazitäten: list = Schema(..., title='Kapazität', description='Enthält eine Liste mit den gemessenen Kapazitäten')


@app.get("/api/spannung", response_model=Spannung)
async def spannung():
    """
    Gespeicherte Spannungen ausgeben.
    """
    return {'spannungen': get_statistic()['Voltage']}


@app.get("/api/strom", response_model=Strom)
async def strom():
    """
    Gespeicherte Ströme ausgeben.
    """
    return {'ströme': get_statistic()['Current']}


@app.get("/api/kapazität", response_model=Kapazität)
async def kapazität():
    """
    Gespeicherte Kapazitäten ausgeben.
    """
    return {'kapazitäten': get_statistic()['Capacity']}


@app.get("/api/aktuelle_werte")
async def aktuelle_werte():
    last_values = {k: v[-1] for k, v in get_statistic().items()}
    return last_values


@app.post('/api/shutdown')
async def shutdown():
    print('Poweroff')
    call('poweroff')
    return True


@app.get('/api/csv')
async def get_csv():
    """
    Gesammte Statistik als CSV herunterladen
    """
    data = get_statistic()
    csv_file = io.StringIO()
    csv_writer = csv.writer(csv_file, delimiter=',')
    header = list(data.keys())
    csv_writer.writerow(header)
    values = zip(*data.values())
    for vals in values:
        csv_writer.writerow(vals)
    csv_file.seek(0)
    content = csv_file.read()
    return PlainTextResponse(content)


@app.post('/api/on')
def battery_on():
    """
    Akku einschalten
    """
    control.send_multipart([b'CONTROL', b'on'])


@app.post('/api/off')
def battery_on():
    """
    Akku einschalten
    """
    control.send_multipart([b'CONTROL', b'off'])


@app.post('/api/reset')
def battery_reset():
    """
    Fehlerspeicher vom Akku zurücksetzen.
    """
    control.send_multipart([b'CONTROL', b'reset'])


if __name__ == 'api':
    ctx = zmq.Context()
    control = ctx.socket(zmq.PUB)
    control.connect('tcp://127.0.0.1:4000')
    print('ZMQ started...')
