import asyncio
import json
import time
import re
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from subprocess import call
from typing import List, Optional

import zmq
import requests
from fastapi import Depends, FastAPI, Form, status, HTTPException, UploadFile, File
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.openapi.docs import (
    get_redoc_html,
    get_swagger_ui_html,
    get_swagger_ui_oauth2_redirect_html,
)
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import StreamingResponse, RedirectResponse, FileResponse
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
import nodes
import setapname
import update
import dev_password


TZ_FILE = Path("/etc/timezone")
LOGO = Path("/media/data/logo.png")
DEVELOPER_MODE = False

session = database.Session()
global_hostname = setapname.get_hostname()
templates = Jinja2Templates(directory="templates")
dev_settings_file = Path("/media/data/settings.json")

app = FastAPI(
    title="LiFePo4-Akku",
    version="4.0",
    description="Rest API für des LiFePo4-Akkus",
    docs_url=None,
    redoc_url=None,
)


security = HTTPBasic()


def update_settings(new_settings: dict):
    settings.update(new_settings)
    dev_settings_file.write_text(json.dumps(settings))
    node_server.update_settings(settings)


class Hotspots(BaseModel):
    """
    Verfügbare Wifi-Hotspots abfragen
    """

    aps: list = Field(..., title="SSID", description="Die ssid der gefundenen Hotspots")


class CurrentValues(BaseModel):
    id: int = Field(..., title="Id", description="ID in der Tabelle")
    cycle: int = Field(..., title="Zyklus", description="Zyklus")
    row: int = Field(..., title="Zeile", description="Zeile")
    timestamp: datetime = Field(
        ..., title="Zeitstempel", description="Zeitstempel UTC0"
    )
    capacity: float = Field(..., title="Kapazität", description="Kapazität in Ah")
    voltage: float = Field(..., title="Spannung", description="Spannung in V")
    cell_voltages: List[float] = Field(
        ..., title="Zellspannungen", description="Zellspannungen in V"
    )
    current: float = Field(..., title="Strom", description="Strom in Ah")
    charge: float = Field(..., title="Ladung", description="Ladung in Ah")
    charge_rel: float = Field(..., title="Ladung Relativ", description="Ladung in %")
    power: float = Field(..., title="Leistung", description="Leistung in W")
    temperature: float = Field(
        ..., title="Zelltemperatur", description="Temperatur in °C"
    )
    error: int = Field(..., title="Fehlercode", description="Fehlercode dezimal")
    errors: str = Field(
        ..., title="Fehlercodes", description="Fehlercodes als lesbarer Text"
    )
    lower_cell_voltage: float = Field(None, title="Untere Zellspannung")
    upper_cell_voltage: float = Field(None, title="Obere Zellspannung")
    hostname: str = Field(None, title="Gerätename")


class Error(BaseModel):
    id: int = Field(..., title="ID", description="ID in der Tabelle")
    cycle: int = Field(..., title="ID", description="Zyklus")
    timestamp: str = Field(..., title="Zeitstempel", description="Zeitstempel UTC0")
    error: int = Field(..., title="Fehlercode", description="Fehlercode dezimal")


class Wlan(BaseModel):
    ssid: str
    password: str


class Ap(BaseModel):
    password: str


UnauthorizedException = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Zugriff nur für Hersteller",
    headers={"WWW-Authenticate": "Basic"},
)


@app.get("/api/logo.png")
async def logo():
    if LOGO.exists():
        return FileResponse("/media/data/logo.png", media_type="image/png")
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not installed")


@app.get("/api/developer")
async def developer_access():
    """
    Override read-only mode for Updates
    when developing.

    This function will be removed before release
    """
    global DEVELOPER_MODE
    if not DEVELOPER_MODE:
        DEVELOPER_MODE = True
        call(["mount", "-o", "remount,rw", "/"])
    return RedirectResponse("/")


@app.get("/api/dev-settings")
async def dev_settings(
    request: Request,
    credentials: HTTPBasicCredentials = Depends(security),
):
    if not dev_password.check_password(credentials.password):
        raise UnauthorizedException
    return templates.TemplateResponse(
        "dev-settings.html",
        {
            "request": request,
            "without_charge": settings["without_charge"],
            "branches": update.branches(),
            "current_branch": update.current_branch(),
        },
    )


@app.post("/api/dev-settings")
async def dev_settings_post(
    request: Request,
    credentials: HTTPBasicCredentials = Depends(security),
    without_charge: str = Form(""),
    set_branch: str = Form(""),
    manufacturer_password: str = Form(""),
    upload_logo: UploadFile = File(...),
):
    if not dev_password.check_password(credentials.password):
        raise UnauthorizedException

    if upload_logo is not None:
        with LOGO.open("wb") as logo_disk:
            data = await upload_logo.read()
            await loop.run_in_executor(executor, logo_disk.write, data)

    settings["without_charge"] = bool(without_charge.strip())
    update_settings(settings)
    if manufacturer_password:
        await loop.run_in_executor(executor, dev_password.set_password, manufacturer_password)
    current_branch = await loop.run_in_executor(executor, update.current_branch)
    if set_branch and set_branch != current_branch:
        with read_write_mode():
            await loop.run_in_executor(executor, update.switch, set_branch)
            await loop.run_in_executor(None, update.pull)
            import compileall

            await loop.run_in_executor(executor, compileall.compile_dir, "/home/server/akku")

    return templates.TemplateResponse(
        "dev-settings.html",
        {
            "request": request,
            "without_charge": settings["without_charge"],
            "branches": update.branches(),
            "current_branch": current_branch,
        },
    )


@app.get("/api/statistics")
async def async_statistics(
    cycle: int, history: float = None, rounding: Optional[int] = None
):
    """
    Statistiken eines Zyklus als csv Datei herunterladen.
    """
    headers = {"Content-Disposition": 'attachment; filename="stats.csv"'}
    return StreamingResponse(
        statistiken.get_stats(
            session=session, cycle=cycle, history=history, rounding=rounding
        ),
        headers=headers,
        media_type="text/csv",
    )


@app.get("/api/wlan/list", response_model=Hotspots)
def iwlist():
    """
    Gescannte Netzwerke
    """
    return {"aps": scan_wlan.get_cells()}


def self_live() -> None:
    control.send_multipart([b"CONTROL", b"LIVE"])
    last_check()


def send_live(url: str) -> None:
    try:
        requests.get(url, timeout=1)
    except requests.Timeout:
        pass
    except Exception as e:
        print(repr(e))


async def nodes_live():
    self_live()
    for ip, node in node_server.nodes.items():
        if node["self"]:
            continue
        node_live_url = f"http://{ip}/api/live"
        loop.run_in_executor(None, send_live, node_live_url)


@app.get("/api/live")
def live():
    self_live()
    return True


@app.get("/api/aktuelle_werte", response_model=CurrentValues)
async def get_current_values():
    await nodes_live()
    values = current_values.get_values()
    if (time.monotonic() - values["timestamp"]) > 10:
        return {key: "#" for key in values}
    values["power"] = values["voltage"] * values["current"]
    try:
        values["charge_rel"] = values["charge"] / values["capacity"] * 100
    except ZeroDivisionError:
        values["charge_rel"] = 0
    values["errors"] = errors.get_short(values["error"])
    if values["voltage"] > 16:
        values["lower_cell_voltage"] = min(values["cell_voltages"])
        values["upper_cell_voltage"] = max(values["cell_voltages"])
    else:
        values["lower_cell_voltage"] = None
        values["upper_cell_voltage"] = None
    values["hostname"] = global_hostname
    return values


@app.get("/graph")
async def graph(request: Request):
    async with graph_busy:
        cycle = await loop.run_in_executor(executor, database.get_cycle, session)
    return templates.TemplateResponse(
        "statistik.html",
        {
            "request": request,
            "cycle": cycle,
            "history": 2,
        },
    )


@app.post("/graph")
async def graph(request: Request, cycle: int = Form(...), history: float = Form(...)):
    return templates.TemplateResponse(
        "statistik.html",
        {
            "request": request,
            "cycle": cycle,
            "history": history,
        },
    )


def shutdown_slave(address: str, slave: bool):
    url = f"http://{address}/api/shutdown"

    def inner():
        requests.post(url, params={"slave": slave}, timeout=5)

    return inner


@app.post("/api/shutdown")
async def shutdown(slave: bool = False):
    if not slave:
        futures = []
        for addr, payload in node_server.nodes_sorted.items():
            if payload["self"]:
                continue
            fut = loop.run_in_executor(None, shutdown_slave(addr, slave=True))
            futures.append(fut)
        await asyncio.gather(*futures, return_exceptions=True)
    # Buzzer(5).beep(2, 1, 5)
    loop.call_later(3, call, ["shutdown", "-h", "0"])
    return {"success": True}


@app.get("/api/update")
def git_update(request: Request):
    info = update.get_last_commit()
    return templates.TemplateResponse("update.html", {"request": request, "info": info})


@app.post("/api/update")
def git_update(request: Request):
    with read_write_mode():
        update.pull()
        import compileall

        compileall.compile_dir("/home/server/akku")
    info = update.get_last_commit()
    return templates.TemplateResponse("update.html", {"request": request, "info": info})


@app.get("/api/restart-services")
def restart_services():
    update.restart()
    return RedirectResponse("/")


@app.post("/api/reset-ap-pw")
async def reset_ap_password():
    wlanpw.reset()
    return {"success": True}


@app.get("/api/get-ap-pw")
async def get_ap_pw(request: Request):
    try:
        password = re.search(
            r"wpa_passphrase=(.+)", Path("/etc/hostapd/hostapd.conf").read_text()
        ).group(1)
    except Exception as e:
        return str(e)
    return templates.TemplateResponse(
        "access_point.html", {"request": request, "password": password}
    )


@app.post("/api/set-ap-pw")
async def set_ap_password(request: Request, password: str = Form(...)):
    try:
        wlanpw.set(password)
    except ValueError:
        success = "Das Passwort ist zu kurz"
    else:
        success = "Das Passwort ist erfolgreich gesetzt worden"
    return templates.TemplateResponse(
        "ap-password.html",
        {
            "request": request,
            "password": password,
            "success": success,
        },
    )


@app.get("/api/reset-hostname")
async def reset_hostname(request: Request):
    global global_hostname
    # Path("/media/data/custom_hostname").unlink(missing_ok=True)
    try:
        Path("/media/data/custom_hostname")
    except FileNotFoundError:
        pass
    hostname = setapname.create_hostname()
    setapname.set_all(hostname)
    global_hostname = hostname
    return templates.TemplateResponse(
        "hostname_set.html",
        {"request": request, "hostname": global_hostname},
    )


@app.get("/api/hostname")
async def get_hostname(request: Request):
    return templates.TemplateResponse(
        "hostname_get.html",
        {"request": request, "hostname": global_hostname},
    )


@app.post("/api/hostname")
async def set_hostname(request: Request, hostname: str = Form(...)):
    global global_hostname
    hostname = setapname.filter_name(hostname)
    setapname.set_all(hostname)
    global_hostname = hostname
    Path("/media/data/custom_hostname").touch()
    return templates.TemplateResponse(
        "hostname_set.html",
        {"request": request, "hostname": global_hostname},
    )


@app.get("/api/ispdb/{email}")
async def get_ispdb_smtp(request: Request, email: str):
    task = await loop.run_in_executor(executor, ispdb.get_smtp, email)
    return task


@app.get("/api/notify/{topic}")
async def notify_by_email(topic: str):
    return await loop.run_in_executor(executor, notify.send_report, topic)


@app.get("/api/internet")
async def get_wlan(request: Request):
    data = None
    ssid = ""
    psk = ""
    try:
        data = Path("/etc/wpa_supplicant/wpa_supplicant.conf").read_text()
    except Exception as e:
        return repr(e)

    if data:
        ssid_match = re.search(r'ssid\s*=\s*"(.+)"', data)
        psk_match = re.search(r'#\s*psk\s*=\s*"(.+)"', data)

        if ssid_match and psk_match:
            ssid = ssid_match.group(1)
            psk = psk_match.group(1)

    if Path("/media/data/wifi_mode").read_text().strip() == "wlan0":
        client_mode = "checked"
    else:
        client_mode = ""

    return templates.TemplateResponse(
        "wifi_internet.html",
        {"request": request, "ssid": ssid, "password": psk, "client_mode": client_mode},
    )


@app.post("/api/internet")
async def set_wlan(
    request: Request,
    ssid: str = Form(...),
    password: str = Form(...),
    client_mode: str = Form(""),
):
    try:
        wpa_passphrase.set_network(ssid, password)
    except ValueError:
        success = "Passwort ist zu kurz."
    else:
        success = "SSID und Passwort sind erfolgreich gesetzt worden."
        wifi_mode_config = Path("/media/data/wifi_mode")
        if client_mode:
            wifi_mode_config.write_text("wlan0\n")
        else:
            wifi_mode_config.write_text("ap0\n")
    return templates.TemplateResponse(
        "internet.html",
        {
            "request": request,
            "ssid": ssid,
            "password": password,
            "success": success,
            "client_mode": client_mode,
        },
    )


@app.get("/api/email")
async def get_email(request: Request):
    config = Path("email.json")
    if config.exists():
        settings = json.loads(config.read_text())
    else:
        settings = {
            "email_from": "",
            "email_login": "",
            "email_password": "",
            "email_to": "",
            "email_smtp_server": "",
            "email_smtp_port": 0,
            "email_smtp_ssl": False,
        }
    return templates.TemplateResponse(
        "email.html",
        {
            "request": request,
            **settings,
        },
    )


@app.post("/api/email")
async def post_email(
    request: Request,
    email_from: str = Form(...),
    email_login: str = Form(""),
    email_password: str = Form(...),
    email_to: str = Form(...),
    email_smtp_server: str = Form(""),
    email_smtp_port: int = Form(0),
    email_smtp_ssl: str = Form(False),
):
    smtp_settings = await loop.run_in_executor(executor, ispdb.get_smtp, email_from)
    if smtp_settings:
        if not email_login:
            email_login = smtp_settings["email_login"]
        if not email_smtp_server:
            email_smtp_server = smtp_settings["email_smtp_server"]
        if email_smtp_port == 0:
            email_smtp_port = smtp_settings["email_smtp_port"]
        email_smtp_ssl = smtp_settings["email_smtp_ssl"]
    Path("email.json").write_text(
        json.dumps(
            {
                "email_from": email_from,
                "email_login": email_login,
                "email_password": email_password,
                "email_to": email_to,
                "email_smtp_server": email_smtp_server,
                "email_smtp_port": email_smtp_port,
                "email_smtp_ssl": email_smtp_ssl,
            }
        )
    )
    return templates.TemplateResponse(
        "email.html",
        {
            "request": request,
            "email_from": email_from,
            "email_login": email_login,
            "email_password": email_password,
            "email_to": email_to,
            "email_smtp_server": email_smtp_server,
            "email_smtp_port": email_smtp_port,
            "email_smtp_ssl": email_smtp_ssl,
        },
    )


@app.get("/api/time")
def get_time():
    now = datetime.now().replace(microsecond=0)
    local_time = now.time().isoformat()
    local_date = now.date().isoformat()
    local_timezone = TZ_FILE.read_text().strip()
    return {"time": local_time, "date": local_date, "timezone": local_timezone}


@app.post("/api/time")
async def set_time(request: Request):
    body = await request.json()
    date_iso = body.get("date_iso")
    time_iso = body.get("time_iso")
    timezone = body.get("timezone")
    if any(field is None for field in [date_iso, time_iso, timezone]):
        return {"success": False}
    # _set_time(date_iso, time_iso, timezone)
    await loop.run_in_executor(executor, _set_time, date_iso, time_iso, timezone)
    return {"time": time_iso, "date": date_iso, "timezone": timezone}


@app.post("/api/on")
def battery_on():
    """
    Akku einschalten
    """
    control.send_multipart([b"CONTROL", b"on"])
    return {"success": True}


@app.post("/api/off")
def battery_off():
    """
    Akku ausschalten.
    """
    control.send_multipart([b"CONTROL", b"off"])
    return {"success": True}


@app.post("/api/reset")
def battery_reset():
    """
    Fehlerspeicher vom Akku zurücksetzen.
    """
    control.send_multipart([b"CONTROL", b"reset"])
    return {"success": True}


@app.post("/api/ack")
def battery_ack():
    """
    Fehler quittieren.
    """
    control.send_multipart([b"CONTROL", b"ack"])
    return {"success": True}


@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
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


@app.get("/api/nodes")
async def api_get_nodes(request: Request):
    await nodes_live()
    return node_server.nodes


@app.get("/nodes")
async def get_nodes(request: Request):
    await nodes_live()
    return templates.TemplateResponse(
        "nodes.html",
        {
            "request": request,
            "nodes": node_server.nodes_sorted,
            "total_voltage": current_values.get_values().get("voltage"),
            "settings": settings,
        },
    )


@contextmanager
def read_write_mode():
    if DEVELOPER_MODE:
        yield
        return
    call(["mount", "-o", "remount,rw", "/"])
    yield
    call(["mount", "-o", "remount,ro", "/"])


def last_check():
    with open("/tmp/last_check", "wt") as fd:
        fd.write(str(time.monotonic()))


def _set_time(date_iso: str, time_iso: str, timezone: str):
    dt_str = f"{date_iso}T{time_iso}"
    with read_write_mode():
        call(["date", "+%Y-%m-%dT%H%M%SS", "-s", dt_str])
        TZ_FILE.write_text(timezone + "\n")


if __name__ in ("__main__", "api"):
    ctx = zmq.Context()
    # noinspection PyUnresolvedReferences
    control = ctx.socket(zmq.PUB)
    control.connect("tcp://127.0.0.1:4000")
    print("ZMQ started...")
    graph_busy = asyncio.Semaphore()
    executor = ThreadPoolExecutor(max_workers=2)
    node_server = nodes.NodeServer()
    try:
        settings = json.loads(dev_settings_file.read_text())
    except (FileNotFoundError, ValueError):
        settings = {"without_charge": False}
        dev_settings_file.write_text(json.dumps(settings))
    update_settings(settings)
    node_server.start()
    loop = asyncio.get_event_loop()
