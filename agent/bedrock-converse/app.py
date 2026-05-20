"""
Zumi Chatbot — FastAPI backend.

Serves:
  GET  /           → Chat UI (static HTML)
  POST /api/chat   → Send message, get Bedrock response + optional image
  POST /api/reset  → Clear conversation history
"""

import logging
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
import config
from hardware_registry import list_robots
from orchestrator import Orchestrator
from layer_config import load_layer_configs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(title="Zumi Chatbot", version="0.2.0")

configs = load_layer_configs()
orchestrator = Orchestrator(configs, robot_id=config.DEFAULT_ROBOT)


class ChatRequest(BaseModel):
    message: str


class SelectRobotRequest(BaseModel):
    robot_id: str


class ChatResponse(BaseModel):
    reply: str
    image_url: str | None = None
    steps: list = []


@app.get("/", response_class=HTMLResponse)
async def index():
    with open("static/index.html") as f:
        return f.read()


@app.post("/api/chat", response_model=ChatResponse)
async def api_chat(req: ChatRequest):
    result = orchestrator.chat(req.message)
    return ChatResponse(
        reply=result["text"],
        image_url=result.get("image_url"),
        steps=result.get("steps", []),
    )


@app.post("/api/reset")
async def api_reset():
    orchestrator.reset()
    return {"status": "ok"}


@app.get("/api/robots")
async def api_robots():
    return list_robots()


@app.get("/api/active-robot")
async def api_active_robot():
    return {
        "robot_id": orchestrator.active_robot_id,
        "display_name": orchestrator.active_display_name,
    }


@app.post("/api/select-robot")
async def api_select_robot(req: SelectRobotRequest):
    try:
        result = orchestrator.select_robot(req.robot_id)
        return result
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
