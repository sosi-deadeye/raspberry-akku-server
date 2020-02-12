import asyncio
import base64
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from subprocess import call
from typing import List

import zmq
from fastapi import FastAPI, Form
from fastapi.openapi.docs import (
    get_redoc_html,
    get_swagger_ui_html,
    get_swagger_ui_oauth2_redirect_html,
)
from gpiozero import Buzzer
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import StreamingResponse
from starlette.templating import Jinja2Templates

import current_values
import database
import errors
import ispdb
import notify
import scan_wlan
import statistiken
import wlanpw
import wpa_passphrase

session = database.Session()
templates = Jinja2Templates(directory='templates')

app = FastAPI(
    title='LiFePo4-Akku',
    version='3.0.0',
    description='Rest API für des LiFePo4-Akkus',
    docs_url=None, redoc_url=None,
)


class Hotspots(BaseModel):
    """
    Verfügbare Wifi-Hotspots abfragen
    """
    aps: list = Field(..., title='SSID', description='Die ssid der gefundenen Hotspots')


class CurrentValues(BaseModel):
    id: int = Field(..., title='Id', description='ID in der Tabelle')
    cycle: int = Field(..., title='Zyklus', description='Zyklus')
    row: int = Field(..., title='Zeile', description='Zeile')
    timestamp: datetime = Field(..., title='Zeitstempel', description='Zeitstempel UTC0')
    capacity: float = Field(..., title='Kapazität', description='Kapazität in Ah')
    voltage: float = Field(..., title='Spannung', description='Spannung in V')
    cell_voltages: List[float] = Field(..., title='Zellspannungen', description='Zellspannungen in V')
    current: float = Field(..., title='Strom', description='Strom in Ah')
    charge: float = Field(..., title='Ladung', description='Ladung in Ah')
    charge_rel: float = Field(..., title='Ladung Relativ', description='Ladung in %')
    power: float = Field(..., title='Leistung', description='Leistung in W')
    temperature: float = Field(..., title='Zelltemperatur', description='Temperatur in °C')
    error: int = Field(..., title='Fehlercode', description='Fehlercode dezimal')
    errors: str = Field(..., title='Fehlercodes', description='Fehlercodes als lesbarer Text')


class Error(BaseModel):
    id: int = Field(..., title='ID', description='ID in der Tabelle')
    cycle: int = Field(..., title='ID', description='Zyklus')
    timestamp: str = Field(..., title='Zeitstempel', description='Zeitstempel UTC0')
    error: int = Field(..., title='Fehlercode', description='Fehlercode dezimal')


class Wlan(BaseModel):
    ssid: str
    password: str


class Ap(BaseModel):
    password: str


@app.get("/api/statistics")
async def async_statistics(cycle: int):
    """
    Statistiken eines Zyklus als csv Datei herunterladen.
    """
    headers = {'Content-Disposition': 'attachment; filename="stats.csv"'}
    return StreamingResponse(database.get_stats(cycle), headers=headers, media_type='text/csv')


@app.get("/api/wlan/list", response_model=Hotspots)
def iwlist():
    """
    Gescannte Netzwerke
    """
    return {'aps': scan_wlan.get_cells()}


@app.get("/api/aktuelle_werte", response_model=CurrentValues)
def get_current_values():
    control.send_multipart([b'CONTROL', b'LIVE'])
    # values = database.get_current()
    # Werte via mmmap abrufen
    values = current_values.get_values()
    values['power'] = values['voltage'] * values['current']
    try:
        values['charge_rel'] = values['charge'] / values['capacity'] * 100
    except ZeroDivisionError:
        values['charge_rel'] = 0
    values['errors'] = errors.get_short(values['error'])
    return values


@app.get('/graph')
def graph(request: Request):
    with graph_busy:
        cycle = database.get_cycle(session)
        img = statistiken.plot(session, cycle, 2)
        return templates.TemplateResponse(
            'statistik.html',
            {
                'request': request,
                'base64_svg': base64.b64encode(img).decode(),
                'cycle': cycle,
                'history': 2
            }
        )


@app.post('/graph')
def graph(request: Request, cycle: int = Form(...), history: float = Form(...)):
    with graph_busy:
        img = statistiken.plot(session, cycle, history)
        return templates.TemplateResponse(
            'statistik.html',
            {
                'request': request,
                'base64_svg': base64.b64encode(img).decode(),
                'cycle': cycle,
                'history': history
            }
        )


@app.post('/api/shutdown')
async def shutdown():
    print('Poweroff')
    Buzzer(5).beep(2, 1, 5)
    call(['shutdown', '-h', '0'])
    return {'success': True}


@app.post('/api/reset-ap-pw')
async def reset_password():
    wlanpw.reset()
    return {'success': True}


@app.get('/api/get-ap-pw')
async def get_ap_pw(request: Request):
    try:
        password = re.search(r'wpa_passphrase=(.+)', Path('/etc/hostapd/hostapd.conf').read_text()).group(1)
    except Exception as e:
        return str(e)
    return templates.TemplateResponse(
        'access_point.html',
        {
            'request': request,
            'password': password
        }
    )


@app.post('/api/set-ap-pw')
async def reset_password(request: Request, password: str = Form(...)):
    try:
        wlanpw.set(password)
    except ValueError:
        success = 'Das Passwort ist zu kurz'
    else:
        success = 'Das Passwort ist erfolgreich gesetzt worden'
    return templates.TemplateResponse(
        'ap-password.html',
        {
            'request': request,
            'password': password,
            'success': success,
        }
    )


@app.get('/api/ispdb/{email}')
async def get_isbdb_smtp(request: Request, email: str):
    task = loop.run_in_executor(executor, ispdb.get_smtp, email)
    return task


@app.get('/api/notify/{topic}')
async def notify_by_email(topic: str):
    await loop.run_in_executor(executor, notify.send_report, topic)
    return topic


@app.get('/api/internet')
async def get_wlan(request: Request):
    try:
        data = Path('/etc/wpa_supplicant/wpa_supplicant.conf').read_text()
        ssid = re.search(r'ssid=(.+)', data).group(1).replace('"', '')
        password = re.search(r'# psk=(.+)', data).group(1).replace('"', '')
    except Exception as e:
        return str(e)
    return templates.TemplateResponse(
        'wifi_internet.html',
        {
            'request': request,
            'ssid': ssid,
            'password': password,
        }
    )


@app.post('/api/internet')
async def set_wlan(request: Request, ssid: str = Form(...), password: str = Form(...)):
    try:
        wpa_passphrase.set_network(ssid, password)
    except ValueError:
        success = 'Passwort ist zu kurz.'
    else:
        success = 'SSID und Passwort sind erfolgreich gesetzt worden.'
    return templates.TemplateResponse(
        'internet.html',
        {
            'request': request,
            'ssid': ssid,
            'password': password,
            'success': success,
        }
    )


@app.get('/api/email')
async def get_email(request: Request):
    config = Path('email.json')
    if config.exists():
        settings = json.loads(config.read_text())
    else:
        settings = {
            'email_from': '',
            'email_login': '',
            'email_password': '',
            'email_to': '',
            'email_smtp_server': '',
            'email_smtp_port': 0,
            'email_smtp_ssl': False,
        }
    return templates.TemplateResponse(
        'email.html',
        {
            'request': request,
            **settings,
        }
    )


@app.post('/api/email')
async def post_email(request: Request,
                     email_from: str = Form(...),
                     email_login: str = Form(''),
                     email_password: str = Form(...),
                     email_to: str = Form(...),
                     email_smtp_server: str = Form(''),
                     email_smtp_port: int = Form(0),
                     email_smtp_ssl: str = Form(False),
                     ):
    smtp_settings = await loop.run_in_executor(executor, ispdb.get_smtp, email_from)
    if smtp_settings:
        if not email_login:
            email_login = smtp_settings['email_login']
        if not email_smtp_server:
            email_smtp_server = smtp_settings['email_smtp_server']
        if email_smtp_port == 0:
            email_smtp_port = smtp_settings['email_smtp_port']
        email_smtp_ssl = smtp_settings['email_smtp_ssl']
    Path('email.json').write_text(json.dumps(
        {
            'email_from': email_from,
            'email_login': email_login,
            'email_password': email_password,
            'email_to': email_to,
            'email_smtp_server': email_smtp_server,
            'email_smtp_port': email_smtp_port,
            'email_smtp_ssl': email_smtp_ssl,
        }
    ))
    return templates.TemplateResponse(
        'email.html',
        {
            'request': request,
            'email_from': email_from,
            'email_login': email_login,
            'email_password': email_password,
            'email_to': email_to,
            'email_smtp_server': email_smtp_server,
            'email_smtp_port': email_smtp_port,
            'email_smtp_ssl': email_smtp_ssl,
        }
    )


@app.post('/api/on')
def battery_on():
    """
    Akku einschalten
    """
    control.send_multipart([b'CONTROL', b'on'])
    return {'success': True}


@app.post('/api/off')
def battery_off():
    """
    Akku ausschalten.
    """
    control.send_multipart([b'CONTROL', b'off'])
    return {'success': True}


@app.post('/api/reset')
def battery_reset():
    """
    Fehlerspeicher vom Akku zurücksetzen.
    """
    control.send_multipart([b'CONTROL', b'reset'])
    return {'success': True}


@app.post('/api/ack')
def battery_ack():
    """
    Fehler quittieren.
    """
    control.send_multipart([b'CONTROL', b'ack'])
    return {'success': True}


@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    print('Hi, docs override..')
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=app.title + " - Swagger UI",
        oauth2_redirect_url=app.swagger_ui_oauth2_redirect_url,
        swagger_js_url="/vendor/fastapi/swagger-ui-bundle.js",
        swagger_css_url="/vendor/fastapi/swagger-ui.css",
    )


@app.get(app.swagger_ui_oauth2_redirect_url, include_in_schema=False)
async def swagger_ui_redirect():
    return get_swagger_ui_oauth2_redirect_html()


@app.get("/redoc", include_in_schema=False)
async def redoc_html():
    return get_redoc_html(
        openapi_url=app.openapi_url,
        title=app.title + " - ReDoc",
        redoc_js_url="/vendor/fastapi/redoc.standalone.js",
    )


if __name__ in ('__main__', 'api'):
    ctx = zmq.Context()
    # noinspection PyUnresolvedReferences
    control = ctx.socket(zmq.PUB)
    control.connect('tcp://127.0.0.1:4000')
    print('ZMQ started...')
    graph_busy = threading.Semaphore()
    executor = ThreadPoolExecutor(max_workers=2)
    loop = asyncio.get_event_loop()
