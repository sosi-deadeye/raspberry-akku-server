import asyncio
import json
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from subprocess import call
from typing import List, Optional

import requests
import zmq
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.openapi.docs import (
    get_redoc_html,
    get_swagger_ui_html,
    get_swagger_ui_oauth2_redirect_html,
)
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import FileResponse, RedirectResponse, StreamingResponse
from starlette.templating import Jinja2Templates

import current_values
import database
import dev_password
import errors
import ispdb
import nodes
import notify
import scan_wlan
import setapname
import statistiken
import update
import wlanpw
import wpa_passphrase

TZ_FILE = Path("/etc/timezone")
LOGO = Path("/media/data/logo.png")
SCRIPT_PATH = Path(__file__).absolute().parent
DATA_PATH = Path("/media/data")
DEVELOPER_MODE = False

session = database.Session()
global_hostname = setapname.get_hostname()
templates = Jinja2Templates(directory="templates")
dev_settings_file = Path("/media/data/settings.json")

app = FastAPI(
    title="LiFePo4-Akku",
    version="4.3.0pre",
    description="Rest API für des LiFePo4-Akkus",
    docs_url=None,
    redoc_url=None,
)

security = HTTPBasic()


def update_settings(new_settings: dict):
    settings.update(new_settings)
    dev_settings_file.write_text(json.dumps(settings))
    node_server.update_settings(settings)


async def reboot_watchdog():
    print("Started reboot watchdog")
    while True:
        await asyncio.sleep(10)
        delay = settings["reboot_delay_seconds"]
        if delay in (None, 0):
            continue
        if time.monotonic() > delay:
            loop.call_later(10, call, ["reboot"])
            break


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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="not installed"
        )


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
    reboot_delay_seconds = settings["reboot_delay_seconds"]
    if reboot_delay_seconds is None:
        reboot_delay_seconds = 0

    normal_voltage_active = "voltage" in settings["query_normal"]
    normal_voltage_delay = settings["query_normal"].get("voltage", 0)
    normal_current_active = "current" in settings["query_normal"]
    normal_current_delay = settings["query_normal"].get("current", 0)
    normal_charge_active = "charge" in settings["query_normal"]
    normal_charge_delay = settings["query_normal"].get("charge", 0)
    normal_temperature_active = "temperature" in settings["query_normal"]
    normal_temperature_delay = settings["query_normal"].get("temperature", 0)
    normal_errorflags_active = "errorflags" in settings["query_normal"]
    normal_errorflags_delay = settings["query_normal"].get("errorflags", 0)
    normal_cell_voltage_0_active = "cell_voltage_0" in settings["query_normal"]
    normal_cell_voltage_0_delay = settings["query_normal"].get("cell_voltage_0", 0)
    normal_cell_voltage_1_active = "cell_voltage_1" in settings["query_normal"]
    normal_cell_voltage_1_delay = settings["query_normal"].get("cell_voltage_1", 0)
    normal_cell_voltage_2_active = "cell_voltage_2" in settings["query_normal"]
    normal_cell_voltage_2_delay = settings["query_normal"].get("cell_voltage_2", 0)
    normal_cell_voltage_3_active = "cell_voltage_3" in settings["query_normal"]
    normal_cell_voltage_3_delay = settings["query_normal"].get("cell_voltage_3", 0)
    normal_lower_cell_voltage_active = "lower_cell_voltage" in settings["query_normal"]
    normal_lower_cell_voltage_delay = settings["query_normal"].get("lower_cell_voltage", 0)
    normal_upper_cell_voltage_active = "upper_cell_voltage" in settings["query_normal"]
    normal_upper_cell_voltage_delay = settings["query_normal"].get("upper_cell_voltage", 0)

    live_voltage_active = "voltage" in settings["query_live"]
    live_voltage_delay = settings["query_live"].get("voltage", 0)
    live_current_active = "current" in settings["query_live"]
    live_current_delay = settings["query_live"].get("current", 0)
    live_charge_active = "charge" in settings["query_live"]
    live_charge_delay = settings["query_live"].get("charge", 0)
    live_temperature_active = "temperature" in settings["query_live"]
    live_temperature_delay = settings["query_live"].get("temperature", 0)
    live_errorflags_active = "errorflags" in settings["query_live"]
    live_errorflags_delay = settings["query_live"].get("errorflags", 0)
    live_cell_voltage_0_active = "cell_voltage_0" in settings["query_live"]
    live_cell_voltage_0_delay = settings["query_live"].get("cell_voltage_0", 0)
    live_cell_voltage_1_active = "cell_voltage_1" in settings["query_live"]
    live_cell_voltage_1_delay = settings["query_live"].get("cell_voltage_1", 0)
    live_cell_voltage_2_active = "cell_voltage_2" in settings["query_live"]
    live_cell_voltage_2_delay = settings["query_live"].get("cell_voltage_2", 0)
    live_cell_voltage_3_active = "cell_voltage_3" in settings["query_live"]
    live_cell_voltage_3_delay = settings["query_live"].get("cell_voltage_3", 0)
    live_lower_cell_voltage_active = "lower_cell_voltage" in settings["query_live"]
    live_lower_cell_voltage_delay = settings["query_live"].get("lower_cell_voltage", 0)
    live_upper_cell_voltage_active = "upper_cell_voltage" in settings["query_live"]
    live_upper_cell_voltage_delay = settings["query_live"].get("upper_cell_voltage", 0)

    return templates.TemplateResponse(
        "dev-settings.html",
        {
            "request": request,
            "without_charge": settings["without_charge"],
            "without_current": settings["without_current"],
            "without_stats": settings["without_stats"],
            "branches": update.branches(),
            "current_branch": update.current_branch(),
            "interconnection": settings["interconnection"],
            "reboot_delay_days": int(reboot_delay_seconds / 60 / 60 / 24),
            "charge_warn_limit": settings["charge_warn_limit"],
            "charge_off_limit": settings["charge_off_limit"],
            "normal_voltage_active": normal_voltage_active,
            "normal_current_active": normal_current_active,
            "normal_charge_active": normal_charge_active,
            "normal_temperature_active": normal_temperature_active,
            "normal_cell_voltage_0_active": normal_cell_voltage_0_active,
            "normal_cell_voltage_1_active": normal_cell_voltage_1_active,
            "normal_cell_voltage_2_active": normal_cell_voltage_2_active,
            "normal_cell_voltage_3_active": normal_cell_voltage_3_active,
            "normal_errorflags_active": normal_errorflags_active,
            "normal_voltage_delay": normal_voltage_delay,
            "normal_current_delay": normal_current_delay,
            "normal_charge_delay": normal_charge_delay,
            "normal_temperature_delay": normal_temperature_delay,
            "normal_cell_voltage_0_delay": normal_cell_voltage_0_delay,
            "normal_cell_voltage_1_delay": normal_cell_voltage_1_delay,
            "normal_cell_voltage_2_delay": normal_cell_voltage_2_delay,
            "normal_cell_voltage_3_delay": normal_cell_voltage_3_delay,
            "normal_errorflags_delay": normal_errorflags_delay,
            "normal_lower_cell_voltage_active": normal_lower_cell_voltage_active,
            "normal_lower_cell_voltage_delay": normal_lower_cell_voltage_delay,
            "normal_upper_cell_voltage_active": normal_upper_cell_voltage_active,
            "normal_upper_cell_voltage_delay": normal_upper_cell_voltage_delay,
            "live_voltage_active": live_voltage_active,
            "live_current_active": live_current_active,
            "live_charge_active": live_charge_active,
            "live_temperature_active": live_temperature_active,
            "live_cell_voltage_0_active": live_cell_voltage_0_active,
            "live_cell_voltage_1_active": live_cell_voltage_1_active,
            "live_cell_voltage_2_active": live_cell_voltage_2_active,
            "live_cell_voltage_3_active": live_cell_voltage_3_active,
            "live_errorflags_active": live_errorflags_active,
            "live_voltage_delay": live_voltage_delay,
            "live_current_delay": live_current_delay,
            "live_charge_delay": live_charge_delay,
            "live_temperature_delay": live_temperature_delay,
            "live_cell_voltage_0_delay": live_cell_voltage_0_delay,
            "live_cell_voltage_1_delay": live_cell_voltage_1_delay,
            "live_cell_voltage_2_delay": live_cell_voltage_2_delay,
            "live_cell_voltage_3_delay": live_cell_voltage_3_delay,
            "live_errorflags_delay": live_errorflags_delay,
            "live_lower_cell_voltage_active": live_lower_cell_voltage_active,
            "live_lower_cell_voltage_delay": live_lower_cell_voltage_delay,
            "live_upper_cell_voltage_active": live_upper_cell_voltage_active,
            "live_upper_cell_voltage_delay": live_upper_cell_voltage_delay,
        },
    )


@app.post("/api/dev-settings")
async def dev_settings_post(
    request: Request,
    credentials: HTTPBasicCredentials = Depends(security),
    without_charge: str = Form(""),
    without_current: str = Form(""),
    without_stats: str = Form(""),
    set_branch: str = Form(""),
    interconnection: str = Form(...),
    manufacturer_password: str = Form(""),
    reboot_delay_days: int = Form(...),
    charge_warn_limit: int = Form(...),
    charge_off_limit: int = Form(...),
    upload_logo: UploadFile = File(...),
    normal_voltage_active: bool = Form(False),
    normal_current_active: bool = Form(False),
    normal_charge_active: bool = Form(False),
    normal_temperature_active: bool = Form(False),
    normal_cell_voltage_0_active: bool = Form(False),
    normal_cell_voltage_1_active: bool = Form(False),
    normal_cell_voltage_2_active: bool = Form(False),
    normal_cell_voltage_3_active: bool = Form(False),
    normal_errorflags_active: bool = Form(False),
    normal_voltage_delay: int = Form(...),
    normal_current_delay: int = Form(...),
    normal_charge_delay: int = Form(...),
    normal_temperature_delay: int = Form(...),
    normal_cell_voltage_0_delay: int = Form(...),
    normal_cell_voltage_1_delay: int = Form(...),
    normal_cell_voltage_2_delay: int = Form(...),
    normal_cell_voltage_3_delay: int = Form(...),
    normal_errorflags_delay: int = Form(...),
    normal_lower_cell_voltage_active: bool = Form(False),
    normal_lower_cell_voltage_delay: int = Form(...),
    normal_upper_cell_voltage_active: bool = Form(False),
    normal_upper_cell_voltage_delay: int = Form(...),
    live_voltage_active: bool = Form(False),
    live_current_active: bool = Form(False),
    live_charge_active: bool = Form(False),
    live_temperature_active: bool = Form(False),
    live_cell_voltage_0_active: bool = Form(False),
    live_cell_voltage_1_active: bool = Form(False),
    live_cell_voltage_2_active: bool = Form(False),
    live_cell_voltage_3_active: bool = Form(False),
    live_errorflags_active: bool = Form(False),
    live_voltage_delay: int = Form(...),
    live_current_delay: int = Form(...),
    live_charge_delay: int = Form(...),
    live_temperature_delay: int = Form(...),
    live_cell_voltage_0_delay: int = Form(...),
    live_cell_voltage_1_delay: int = Form(...),
    live_cell_voltage_2_delay: int = Form(...),
    live_cell_voltage_3_delay: int = Form(...),
    live_errorflags_delay: int = Form(...),
    live_lower_cell_voltage_active: bool = Form(False),
    live_lower_cell_voltage_delay: int = Form(...),
    live_upper_cell_voltage_active: bool = Form(False),
    live_upper_cell_voltage_delay: int = Form(...),
):
    if not dev_password.check_password(credentials.password):
        raise UnauthorizedException

    if upload_logo is not None:
        with LOGO.open("wb") as logo_disk:
            data = await upload_logo.read()
            await loop.run_in_executor(executor, logo_disk.write, data)

    settings["without_charge"] = bool(without_charge.strip())
    settings["without_current"] = bool(without_current.strip())
    settings["without_stats"] = bool(without_stats.strip())
    settings["interconnection"] = interconnection
    settings["reboot_delay_seconds"] = int(reboot_delay_days * 60 * 60 * 24)
    settings["charge_warn_limit"] = int(charge_warn_limit)
    settings["charge_off_limit"] = int(charge_off_limit)

    if normal_voltage_active:
        settings["query_normal"]["voltage"] = normal_voltage_delay
    elif "voltage" in settings["query_normal"]:
        del settings["query_normal"]["voltage"]

    if normal_current_active:
        settings["query_normal"]["current"] = normal_current_delay
    elif "current" in settings["query_normal"]:
        del settings["query_normal"]["current"]

    if normal_charge_active:
        settings["query_normal"]["charge"] = normal_charge_delay
    elif "charge" in settings["query_normal"]:
        del settings["query_normal"]["charge"]

    if normal_temperature_active:
        settings["query_normal"]["temperature"] = normal_temperature_delay
    elif "temperature" in settings["query_normal"]:
        del settings["query_normal"]["temperature"]

    if normal_errorflags_active:
        settings["query_normal"]["errorflags"] = normal_errorflags_delay
    elif "errorflags" in settings["query_normal"]:
        del settings["query_normal"]["errorflags"]

    if normal_cell_voltage_0_active:
        settings["query_normal"]["cell_voltage_0"] = normal_cell_voltage_0_delay
    elif "cell_voltage_0" in settings["query_normal"]:
        del settings["query_normal"]["cell_voltage_0"]

    if normal_cell_voltage_1_active:
        settings["query_normal"]["cell_voltage_1"] = normal_cell_voltage_1_delay
    elif "cell_voltage_1" in settings["query_normal"]:
        del settings["query_normal"]["cell_voltage_1"]

    if normal_cell_voltage_2_active:
        settings["query_normal"]["cell_voltage_2"] = normal_cell_voltage_2_delay
    elif "cell_voltage_2" in settings["query_normal"]:
        del settings["query_normal"]["cell_voltage_2"]

    if normal_cell_voltage_3_active:
        settings["query_normal"]["cell_voltage_3"] = normal_cell_voltage_3_delay
    elif "cell_voltage_3" in settings["query_normal"]:
        del settings["query_normal"]["cell_voltage_3"]

    if normal_lower_cell_voltage_active:
        settings["query_normal"]["lower_cell_voltage"] = normal_lower_cell_voltage_delay
    elif "lower_cell_voltage" in settings["query_normal"]:
        del settings["query_normal"]["lower_cell_voltage"]

    if normal_upper_cell_voltage_active:
        settings["query_normal"]["upper_cell_voltage"] = normal_upper_cell_voltage_delay
    elif "upper_cell_voltage" in settings["query_normal"]:
        del settings["query_normal"]["upper_cell_voltage"]

    if live_voltage_active:
        settings["query_live"]["voltage"] = live_voltage_delay
    elif "voltage" in settings["query_live"]:
        del settings["query_live"]["voltage"]

    if live_current_active:
        settings["query_live"]["current"] = live_current_delay
    elif "current" in settings["query_live"]:
        del settings["query_live"]["current"]

    if live_charge_active:
        settings["query_live"]["charge"] = live_charge_delay
    elif "charge" in settings["query_live"]:
        del settings["query_live"]["charge"]

    if live_temperature_active:
        settings["query_live"]["temperature"] = live_temperature_delay
    elif "temperature" in settings["query_live"]:
        del settings["query_live"]["temperature"]

    if live_errorflags_active:
        settings["query_live"]["errorflags"] = live_errorflags_delay
    elif "errorflags" in settings["query_live"]:
        del settings["query_live"]["errorflags"]

    if live_cell_voltage_0_active:
        settings["query_live"]["cell_voltage_0"] = live_cell_voltage_0_delay
    elif "cell_voltage_0" in settings["query_live"]:
        del settings["query_live"]["cell_voltage_0"]

    if live_cell_voltage_1_active:
        settings["query_live"]["cell_voltage_1"] = live_cell_voltage_1_delay
    elif "cell_voltage_1" in settings["query_live"]:
        del settings["query_live"]["cell_voltage_1"]

    if live_cell_voltage_2_active:
        settings["query_live"]["cell_voltage_2"] = live_cell_voltage_2_delay
    elif "cell_voltage_2" in settings["query_live"]:
        del settings["query_live"]["cell_voltage_2"]

    if live_cell_voltage_3_active:
        settings["query_live"]["cell_voltage_3"] = live_cell_voltage_3_delay
    elif "cell_voltage_3" in settings["query_live"]:
        del settings["query_live"]["cell_voltage_3"]

    if live_lower_cell_voltage_active:
        settings["query_live"]["lower_cell_voltage"] = live_lower_cell_voltage_delay
    elif "lower_cell_voltage" in settings["query_live"]:
        del settings["query_live"]["lower_cell_voltage"]

    if live_upper_cell_voltage_active:
        settings["query_live"]["upper_cell_voltage"] = live_upper_cell_voltage_delay
    elif "upper_cell_voltage" in settings["query_live"]:
        del settings["query_live"]["upper_cell_voltage"]

    update_settings(settings)
    if manufacturer_password:
        await loop.run_in_executor(
            executor, dev_password.set_password, manufacturer_password
        )
    current_branch = await loop.run_in_executor(executor, update.current_branch)
    if set_branch and set_branch != current_branch:
        with read_write_mode():
            await loop.run_in_executor(executor, update.switch, set_branch)
            await loop.run_in_executor(None, update.pull)
            import compileall

            await loop.run_in_executor(
                executor, compileall.compile_dir, "/home/server/akku"
            )
    return templates.TemplateResponse(
        "dev-settings.html",
        {
            "request": request,
            "without_charge": settings["without_charge"],
            "without_current": settings["without_current"],
            "without_stats": settings["without_stats"],
            "branches": update.branches(),
            "current_branch": current_branch,
            "interconnection": interconnection,
            "reboot_delay_days": reboot_delay_days,
            "charge_warn_limit": charge_warn_limit,
            "charge_off_limit": charge_off_limit,
            "normal_voltage_active": normal_voltage_active,
            "normal_current_active": normal_current_active,
            "normal_charge_active": normal_charge_active,
            "normal_temperature_active": normal_temperature_active,
            "normal_cell_voltage_0_active": normal_cell_voltage_0_active,
            "normal_cell_voltage_1_active": normal_cell_voltage_1_active,
            "normal_cell_voltage_2_active": normal_cell_voltage_2_active,
            "normal_cell_voltage_3_active": normal_cell_voltage_3_active,
            "normal_errorflags_active": normal_errorflags_active,
            "normal_voltage_delay": normal_voltage_delay,
            "normal_current_delay": normal_current_delay,
            "normal_charge_delay": normal_charge_delay,
            "normal_temperature_delay": normal_temperature_delay,
            "normal_cell_voltage_0_delay": normal_cell_voltage_0_delay,
            "normal_cell_voltage_1_delay": normal_cell_voltage_1_delay,
            "normal_cell_voltage_2_delay": normal_cell_voltage_2_delay,
            "normal_cell_voltage_3_delay": normal_cell_voltage_3_delay,
            "normal_errorflags_delay": normal_errorflags_delay,
            "normal_lower_cell_voltage_active": normal_lower_cell_voltage_active,
            "normal_lower_cell_voltage_delay": normal_lower_cell_voltage_delay,
            "normal_upper_cell_voltage_active": normal_upper_cell_voltage_active,
            "normal_upper_cell_voltage_delay": normal_upper_cell_voltage_delay,
            "live_voltage_active": live_voltage_active,
            "live_current_active": live_current_active,
            "live_charge_active": live_charge_active,
            "live_temperature_active": live_temperature_active,
            "live_cell_voltage_0_active": live_cell_voltage_0_active,
            "live_cell_voltage_1_active": live_cell_voltage_1_active,
            "live_cell_voltage_2_active": live_cell_voltage_2_active,
            "live_cell_voltage_3_active": live_cell_voltage_3_active,
            "live_errorflags_active": live_errorflags_active,
            "live_voltage_delay": live_voltage_delay,
            "live_current_delay": live_current_delay,
            "live_charge_delay": live_charge_delay,
            "live_temperature_delay": live_temperature_delay,
            "live_cell_voltage_0_delay": live_cell_voltage_0_delay,
            "live_cell_voltage_1_delay": live_cell_voltage_1_delay,
            "live_cell_voltage_2_delay": live_cell_voltage_2_delay,
            "live_cell_voltage_3_delay": live_cell_voltage_3_delay,
            "live_errorflags_delay": live_errorflags_delay,
            "live_lower_cell_voltage_active": live_lower_cell_voltage_active,
            "live_lower_cell_voltage_delay": live_lower_cell_voltage_delay,
            "live_upper_cell_voltage_active": live_upper_cell_voltage_active,
            "live_upper_cell_voltage_delay": live_upper_cell_voltage_delay,
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


@app.post("/api/reset-user-settings")
async def reset_user_settings():
    def copy_defaults():
        # resetting custom hostname
        try:
            (DATA_PATH / "custom_hostname").unlink()
        except FileNotFoundError:
            pass

        # copy default configurations
        source = SCRIPT_PATH / "configurations"
        for file in source.glob("*"):
            shutil.copy(file, DATA_PATH)

    await loop.run_in_executor(None, copy_defaults)
    return {"success": True}


@app.get("/api/reboot-delay")
async def get_reboot_delay():
    try:
        days = int(settings["reboot_delay_seconds"]) / 24 / 60 / 60
    except TypeError:
        return {"days": 0}
    else:
        return {"days": days}


@app.post("/api/reboot-delay")
async def set_reboot_delay(days: int):
    if days >= 1:
        settings["reboot_delay_seconds"] = int(days * 24 * 60 * 60)
    else:
        settings["reboot_delay_seconds"] = None
    update_settings(settings)


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
        (DATA_PATH / "custom_hostname").unlink()
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
    config = Path("/media/data/email.json")
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
    Path("/media/data/email.json").write_text(
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
    return node_server.nodes_sorted


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
    settings_default = {
        "without_charge": False,
        "without_current": False,
        "without_stats": False,
        "interconnection": "parallel_connection",
        "reboot_delay_seconds": 0,
        "charge_warn_limit": 15,
        "charge_off_limit": 10,
        "query_normal": {
            "voltage": 60,
            "current": 10,
            "charge": 60,
            "temperature": 5 * 60,
            "cell_voltage_0": 5 * 60,
            "cell_voltage_1": 5 * 60,
            "cell_voltage_2": 5 * 60,
            "cell_voltage_3": 5 * 60,
            "errorflags": 60,
            "lower_cell_voltage": 5 * 60,
            "upper_cell_voltage": 5 * 60,
        },
        "query_live": {
            "voltage": 15,
            "current": 2,
            "charge": 60,
            "temperature": 60,
            "cell_voltage_0": 60,
            "cell_voltage_1": 60,
            "cell_voltage_2": 60,
            "cell_voltage_3": 60,
            "errorflags": 60,
            "lower_cell_voltage": 10,
            "upper_cell_voltage": 10,
        },
    }
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
        if not all(key in settings for key in settings_default):
            raise ValueError
    except (FileNotFoundError, ValueError):
        settings = settings_default.copy()
        dev_settings_file.write_text(json.dumps(settings))
    update_settings(settings)
    node_server.start()
    loop = asyncio.get_event_loop()
    loop.create_task(reboot_watchdog())
