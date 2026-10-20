
import os
import hmac
import threading
from pathlib import Path
from fastapi.middleware.cors import CORSMiddleware

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

app = FastAPI(title="ESP32 LED Cloud Controller")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "https://portable-ai-iot-controller.onrender.com",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

load_dotenv()

CLIENT_TOKEN = os.environ.get("CLIENT_TOKEN", "")
DEVICE_TOKEN = os.environ.get("DEVICE_TOKEN", "")

lock = threading.Lock()

# Desired LED states; initially both OFF.
desired_state = {
    "led1": False,
    "led2": False,
    "version": 0,
}

device_report = {
    "online": False,
    "led1": False,
    "led2": False,
    "last_seen": None,
}


def authenticate(provided: str, expected: str):
    token = provided.removeprefix("Bearer ").strip()

    if not expected or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid token")


class LEDState(BaseModel):
    led1: bool
    led2: bool


class DeviceReport(BaseModel):
    led1: bool
    led2: bool


@app.get("/")
def dashboard():
    return FileResponse(Path(__file__).with_name("index.html"))


@app.get("/health")
def health():
    return {"status": "online", "service": "ESP32 LED Controller"}


@app.post("/api/leds")
def set_leds(
    body: LEDState,
    authorization: str = Header(default=""),
):
    authenticate(authorization, CLIENT_TOKEN)

    with lock:
        desired_state["led1"] = body.led1
        desired_state["led2"] = body.led2
        desired_state["version"] += 1

        return {
            "status": "accepted",
            "leds": dict(desired_state),
        }


@app.get("/device/state")
def get_device_state(
    authorization: str = Header(default=""),
):
    authenticate(authorization, DEVICE_TOKEN)

    with lock:
        return dict(desired_state)


@app.post("/device/report")
def report_device(
    body: DeviceReport,
    authorization: str = Header(default=""),
):
    authenticate(authorization, DEVICE_TOKEN)

    from datetime import datetime, timezone

    with lock:
        device_report.update({
            "online": True,
            "led1": body.led1,
            "led2": body.led2,
            "last_seen": datetime.now(timezone.utc).isoformat(),
        })

    return {"status": "received"}


@app.get("/api/status")
def get_status(
    authorization: str = Header(default=""),
):
    authenticate(authorization, CLIENT_TOKEN)

    with lock:
        return {
            "desired": dict(desired_state),
            "device": dict(device_report),
        }
