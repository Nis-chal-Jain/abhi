"""Real-time biosignal dashboard server."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from analysis import AnalysisEngine, Sample
from demo_source import DemoSource
from serial_hub import SerialHub, list_com_ports

ROOT = Path(__file__).parent
STATIC = ROOT / "static"

app = FastAPI(title="Biosignal Dashboard")
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


class PortBody(BaseModel):
    port: str = ""


class FlagBody(BaseModel):
    enabled: bool = True
    start: bool = True

engine = AnalysisEngine()
demo = DemoSource()
lock = threading.Lock()
mode = "idle"  # idle | demo | serial
latest: Dict[str, Any] = {}
link_status: Dict[str, Any] = {
    "connected": False,
    "port": None,
    "message": "Pick a port or start Demo Mode",
    "error": None,
    "reconnect_tries": 0,
    "mode": "idle",
}
recording = False
records: List[Dict[str, Any]] = []
clients: Set[WebSocket] = set()
loop: Optional[asyncio.AbstractEventLoop] = None


def snapshot_from_sample(sample: Sample) -> None:
    global latest
    with lock:
        payload = engine.feed(sample)
        payload["link"] = {**link_status, "mode": mode}
        payload["recording"] = recording
        latest = payload
        if recording:
            records.append(_row(sample, payload))
    if loop is not None:
        asyncio.run_coroutine_threadsafe(_broadcast(payload), loop)


def _row(sample: Sample, payload: Dict[str, Any]) -> Dict[str, Any]:
    live = payload.get("live", {})
    res = payload.get("results", {})
    vig = res.get("vigilance", {})
    att = res.get("attention", {})
    auto = res.get("autonomic", {})
    bands = {b["name"].lower(): b for b in live.get("eeg_bands", [])}
    return {
        "time": datetime.now().isoformat(timespec="seconds"),
        "heart_rate_bpm": sample.hr,
        "rmssd_ms": sample.rmssd,
        "spo2": sample.spo2,
        "ir": sample.ir,
        "finger_on": sample.finger,
        "delta_hz": sample.band_hz.get("delta"),
        "delta_uv": sample.band_uv.get("delta"),
        "theta_hz": sample.band_hz.get("theta"),
        "theta_uv": sample.band_uv.get("theta"),
        "alpha_hz": sample.band_hz.get("alpha"),
        "alpha_uv": sample.band_uv.get("alpha"),
        "beta_hz": sample.band_hz.get("beta"),
        "beta_uv": sample.band_uv.get("beta"),
        "gamma_hz": sample.band_hz.get("gamma"),
        "gamma_uv": sample.band_uv.get("gamma"),
        "eeg_pkpk_uv": sample.eeg_pp,
        "eeg_saturated": sample.eeg_saturated,
        "acc_x_g": sample.ax,
        "acc_y_g": sample.ay,
        "acc_z_g": sample.az,
        "motion_noise_g": sample.motion_noise,
        "moving": sample.moving,
        "temperature_c": sample.temp_c,
        "vigilance_score": vig.get("score"),
        "vigilance_meaning": vig.get("meaning"),
        "attention_trend": att.get("trend"),
        "attention_label": att.get("label"),
        "mood_status": "unavailable_needs_two_forehead_electrodes",
        "autonomic_score": auto.get("score"),
        "autonomic_meaning": auto.get("meaning"),
        "autonomic_agreement": auto.get("agreement"),
        "confidence": payload.get("quality", {}).get("confidence"),
        "quality_message": payload.get("quality", {}).get("message"),
        "motion_warning": payload.get("quality", {}).get("motion_warning"),
    }


def on_serial_sample(sample: Sample) -> None:
    if mode != "serial":
        return
    snapshot_from_sample(sample)


def on_serial_status(st: dict) -> None:
    global link_status
    with lock:
        link_status = {**st, "mode": mode}
    payload = {**latest, "link": {**link_status, "mode": mode}} if latest else {"link": {**link_status, "mode": mode}}
    if loop is not None:
        asyncio.run_coroutine_threadsafe(_broadcast(payload), loop)


hub = SerialHub(on_serial_sample, on_serial_status)


async def _broadcast(payload: Dict[str, Any]) -> None:
    dead = []
    text = json.dumps(payload)
    for ws in list(clients):
        try:
            await ws.send_text(text)
        except Exception:
            dead.append(ws)
    for ws in dead:
        clients.discard(ws)


def demo_loop() -> None:
    while True:
        time.sleep(1.0)
        if mode != "demo":
            continue
        with lock:
            phase = engine._cal_phase
        snapshot_from_sample(demo.sample(phase))


threading.Thread(target=demo_loop, daemon=True).start()


@app.on_event("startup")
async def _startup() -> None:
    global loop
    loop = asyncio.get_event_loop()


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/ports")
async def ports() -> JSONResponse:
    return JSONResponse({"ports": list_com_ports()})


@app.post("/api/connect")
async def connect(body: PortBody) -> JSONResponse:
    global mode
    port = body.port
    if not port:
        return JSONResponse({"ok": False, "error": "Choose a COM port first."}, status_code=400)
    with lock:
        mode = "serial"
    hub.connect(port)
    return JSONResponse({"ok": True, "message": f"Opening {port}..."})


@app.post("/api/disconnect")
async def disconnect() -> JSONResponse:
    global mode, link_status
    hub.disconnect()
    with lock:
        mode = "idle"
        link_status = {
            "connected": False,
            "port": None,
            "message": "Disconnected",
            "error": None,
            "reconnect_tries": 0,
            "mode": "idle",
        }
    return JSONResponse({"ok": True})


@app.post("/api/demo")
async def set_demo(body: FlagBody) -> JSONResponse:
    global mode, link_status, demo, engine
    enabled = bool(body.enabled)
    if enabled:
        hub.disconnect()
        with lock:
            mode = "demo"
            demo = DemoSource()
            engine = AnalysisEngine()
            link_status = {
                "connected": True,
                "port": "DEMO",
                "message": "Demo Mode - fake live data, no board needed",
                "error": None,
                "reconnect_tries": 0,
                "mode": "demo",
            }
        return JSONResponse({"ok": True, "mode": "demo"})
    with lock:
        mode = "idle"
        link_status = {
            "connected": False,
            "port": None,
            "message": "Demo Mode off",
            "error": None,
            "reconnect_tries": 0,
            "mode": "idle",
        }
    return JSONResponse({"ok": True, "mode": "idle"})


@app.post("/api/calibrate")
async def calibrate() -> JSONResponse:
    with lock:
        engine.start_calibration()
    return JSONResponse({"ok": True})


@app.post("/api/record")
async def record(body: FlagBody) -> JSONResponse:
    global recording, records
    start = bool(body.start)
    with lock:
        recording = start
        if start:
            records = []
    return JSONResponse({"ok": True, "recording": recording})


@app.get("/api/export.csv")
async def export_csv() -> Response:
    with lock:
        rows = list(records)
        if not rows and latest:
            # Export the latest snapshot even if user forgot to hit Record
            dummy = Sample(t=time.time())
            live = latest.get("live", {})
            dummy.hr = live.get("heart_rate")
            dummy.temp_c = live.get("temperature_c")
            rows = [_row(dummy, latest)]
    buf = io.StringIO()
    if not rows:
        buf.write("time,note\n")
        buf.write(f"{datetime.now().isoformat(timespec='seconds')},No session data yet. Start Record, then Export.\n")
        data = buf.getvalue()
    else:
        fields = list(rows[0].keys())
        writer = csv.DictWriter(buf, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
        data = buf.getvalue()
    headers = {"Content-Disposition": "attachment; filename=biosignal_session.csv"}
    return Response(content=data, media_type="text/csv", headers=headers)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    clients.add(ws)
    if latest:
        await ws.send_text(json.dumps(latest))
    else:
        await ws.send_text(json.dumps({"link": {**link_status, "mode": mode}, "recording": recording}))
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        clients.discard(ws)
