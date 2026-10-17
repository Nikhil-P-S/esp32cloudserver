
import os
import uuid
from collections import deque
from threading import Lock
from pathlib import Path

from fastapi.middleware.cors import CORSMiddleware

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from groq import Groq

# Load the .env file beside this Python file.
load_dotenv(Path(__file__).with_name(".env"))

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DEVICE_TOKEN = os.getenv("DEVICE_TOKEN")
CLIENT_TOKEN = os.getenv("CLIENT_TOKEN")

if not all([GROQ_API_KEY, DEVICE_TOKEN, CLIENT_TOKEN]):
    raise RuntimeError(
        "Missing GROQ_API_KEY, DEVICE_TOKEN or CLIENT_TOKEN in .env"
    )

llm = Groq(api_key=GROQ_API_KEY)
app = FastAPI(title="Portable AI IoT Controller")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5500",
        "http://127.0.0.1:5500",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Client-Token"],
)

commands = deque()
results = {}
lock = Lock()

MAX_QUEUE_SIZE = 20


class Instruction(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class HardwareCommand(BaseModel):
    led_action: str
    blink_count: int = Field(ge=1, le=10)
    interval_ms: int = Field(ge=100, le=1000)
    fan_action: str


def authenticate(received, expected):
    if received != expected:
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication token"
        )


def interpret_instruction(text):
    prompt = f"""
Convert the user instruction into JSON only.

Required schema:
{{
  "led_action": "on" | "off" | "blink" | "unchanged",
  "blink_count": integer from 1 to 10,
  "interval_ms": integer from 100 to 1000,
  "fan_action": "on" | "off" | "unchanged"
}}

Rules:
- Never generate Python code or shell commands.
- Use blink_count=3 when no count is specified.
- Use interval_ms=300 when no interval is specified.
- Use unchanged for hardware not mentioned.
- Only support LED and fan actions.
- For unrelated instructions, use unchanged for both actions.

User instruction:
{text}
"""

    response = llm.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": "Return valid JSON only."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0
    )

    raw = response.choices[0].message.content
    command = HardwareCommand.model_validate_json(raw)

    if command.led_action not in {
        "on", "off", "blink", "unchanged"
    }:
        raise ValueError("Unsupported LED action")

    if command.fan_action not in {
        "on", "off", "unchanged"
    }:
        raise ValueError("Unsupported fan action")

    return command


@app.get("/health")
def health():
    return {"status": "online"}


@app.post("/api/command")
def submit_command(
    body: Instruction,
    x_client_token: str = Header()
):
    authenticate(x_client_token, CLIENT_TOKEN)

    try:
        command = interpret_instruction(body.text)
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="LLM interpretation failed; check server logs"
        )

    if (
        command.led_action == "unchanged"
        and command.fan_action == "unchanged"
    ):
        raise HTTPException(
            status_code=400,
            detail="No supported hardware action detected"
        )

    command_id = str(uuid.uuid4())

    with lock:
        if len(commands) >= MAX_QUEUE_SIZE:
            raise HTTPException(
                status_code=429,
                detail="Command queue is full"
            )

        commands.append({
            "id": command_id,
            "command": command.model_dump()
        })
        results[command_id] = {"status": "queued"}

    return {
        "id": command_id,
        "status": "queued",
        "interpreted_command": command.model_dump()
    }


@app.get("/api/device/next")
def next_command(
    x_device_token: str = Header()
):
    authenticate(x_device_token, DEVICE_TOKEN)

    with lock:
        if not commands:
            return {"command": None}

        item = commands.popleft()
        results[item["id"]] = {"status": "running"}

    return {"command": item}


@app.post("/api/device/result/{command_id}")
def report_result(
    command_id: str,
    body: dict,
    x_device_token: str = Header()
):
    authenticate(x_device_token, DEVICE_TOKEN)

    with lock:
        if command_id not in results:
            raise HTTPException(
                status_code=404,
                detail="Unknown command"
            )

        results[command_id] = {
            "status": "completed",
            "result": body
        }

    return {"status": "recorded"}


@app.get("/api/result/{command_id}")
def get_result(
    command_id: str,
    x_client_token: str = Header()
):
    authenticate(x_client_token, CLIENT_TOKEN)

    with lock:
        result = results.get(command_id)

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Unknown command"
        )

    return result
