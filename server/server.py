
import os
import secrets
from collections import deque
from threading import Lock

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Literal

load_dotenv()

CLIENT_TOKEN = os.getenv("CLIENT_TOKEN")
DEVICE_TOKEN = os.getenv("DEVICE_TOKEN")

if not CLIENT_TOKEN or not DEVICE_TOKEN:
    raise RuntimeError("Set CLIENT_TOKEN and DEVICE_TOKEN in .env")

app = FastAPI(title="ESP32 Cloud LED Controller")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        # Add your deployed frontend origin here.
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Client-Token"],
)

commands = deque()
lock = Lock()


class LEDCommand(BaseModel):
    gpio: Literal[18]
    action: Literal["on", "off", "blink"]
    blink_count: int = Field(default=3, ge=1, le=10)
    interval_ms: int = Field(default=300, ge=100, le=1000)


def check_token(received, expected):
    if not secrets.compare_digest(received, expected):
        raise HTTPException(status_code=401, detail="Invalid token")


@app.get("/")
def home():
    return {"status": "online", "service": "ESP32 LED Controller"}


@app.get("/health")
def health():
    return {"status": "online"}


@app.post("/api/command")
def submit_command(
    body: LEDCommand,
    x_client_token: str = Header(alias="X-Client-Token"),
):
    check_token(x_client_token, CLIENT_TOKEN)

    with lock:
        if len(commands) >= 20:
            raise HTTPException(status_code=429, detail="Queue full")

        commands.append(body.model_dump())

    return {"status": "queued", "command": body.model_dump()}


@app.get("/api/device/next")
def device_next(
    x_device_token: str = Header(alias="X-Device-Token"),
):
    check_token(x_device_token, DEVICE_TOKEN)

    with lock:
        if not commands:
            return {"command": None}

        command = commands.popleft()

    return {"command": command}
