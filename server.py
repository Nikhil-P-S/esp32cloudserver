
import os
import hmac
from collections import deque
from threading import Lock

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI(title="ESP32 Cloud LED Controller")

CLIENT_TOKEN = os.environ.get("CLIENT_TOKEN", "")
DEVICE_TOKEN = os.environ.get("DEVICE_TOKEN", "")

commands = deque()
queue_lock = Lock()
MAX_QUEUE_SIZE = 20


def check_token(provided: str, expected: str):
    if not expected or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid token")


class BlinkRequest(BaseModel):
    action: str


@app.get("/")
def health():
    return {"status": "online", "service": "ESP32 LED Controller"}


@app.post("/command")
def submit_command(
    request: BlinkRequest,
    authorization: str = Header(default="")
):
    check_token(
        authorization.removeprefix("Bearer ").strip(),
        CLIENT_TOKEN
    )

    if request.action != "blink_alternately":
        raise HTTPException(status_code=400, detail="Unsupported action")

    with queue_lock:
        if len(commands) >= MAX_QUEUE_SIZE:
            raise HTTPException(status_code=429, detail="Command queue full")

        command = {
            "action": "blink_alternately",
            "duration_seconds": 5,
            "pins": [18, 19]
        }
        commands.append(command)

    return {"status": "queued", "command": command}


@app.get("/device/next")
def next_command(authorization: str = Header(default="")):
    check_token(
        authorization.removeprefix("Bearer ").strip(),
        DEVICE_TOKEN
    )

    with queue_lock:
        command = commands.popleft() if commands else None

    return {"command": command}
