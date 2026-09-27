# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""FastAPI Proxy for Deployed Agent Engine (Agent Platform).

Proxying requests to the remote Agent Engine using Google OAuth authentication.
"""

import os
import json
import logging
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Dict, Any

import google.auth
import google.auth.transport.requests
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agent_proxy")

# Read AGENT_ENGINE_RESOURCE_NAME and AGENT_DIRECTORY
def _resolve_agent_engine_resource() -> str:
    if env_res := os.environ.get("AGENT_ENGINE_RESOURCE_NAME"):
        return env_res
    
    metadata_file = Path(__file__).parent.parent / "deployment_metadata.json"
    if metadata_file.exists():
        try:
            with open(metadata_file, "r") as f:
                data = json.load(f)
                if runtime_id := data.get("remote_agent_runtime_id"):
                    return runtime_id
        except Exception:
            pass
            
    return "projects/294974517657/locations/us-east1/reasoningEngines/3769642630481182720"


AGENT_ENGINE_RESOURCE_NAME = _resolve_agent_engine_resource()
AGENT_DIRECTORY = os.environ.get("AGENT_DIRECTORY", "app")

# Extract location from AGENT_ENGINE_RESOURCE_NAME
# e.g., projects/294974517657/locations/us-east1/reasoningEngines/3769642630481182720 -> us-east1
_parts = AGENT_ENGINE_RESOURCE_NAME.split("/")
LOCATION = _parts[3] if len(_parts) >= 4 else "us-east1"
PASSTHROUGH_BASE_URL = f"https://{LOCATION}-aiplatform.googleapis.com/reasoningEngines/v1/{AGENT_ENGINE_RESOURCE_NAME}/api"

app = FastAPI(title="Agent Platform Chat UI Proxy")


def _get_auth_headers() -> Dict[str, str]:
    """Generates GCP OAuth Bearer Token headers."""
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    auth_req = google.auth.transport.requests.Request()
    creds.refresh(auth_req)
    return {
        "Authorization": f"Bearer {creds.token}",
        "Content-Type": "application/json",
    }


class ChatRequest(BaseModel):
    message: str
    user_id: str = "default_user"
    session_id: Optional[str] = None


@app.get("/api/info")
async def get_info():
    """Returns deployment configuration info."""
    return {
        "agent_engine_resource_name": AGENT_ENGINE_RESOURCE_NAME,
        "agent_directory": AGENT_DIRECTORY,
        "location": LOCATION,
        "passthrough_base_url": PASSTHROUGH_BASE_URL,
    }


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    """Proxies user message to the deployed Agent Engine and streams response SSE back to the frontend."""
    headers = _get_auth_headers()

    # Create session if session_id is not provided
    session_id = req.session_id
    if not session_id:
        session_create_url = f"{PASSTHROUGH_BASE_URL}/apps/{AGENT_DIRECTORY}/users/{req.user_id}/sessions"
        session_req = urllib.request.Request(
            session_create_url,
            data=b"{}",
            headers=headers,
            method="POST"
        )
        try:
            with urllib.request.urlopen(session_req) as resp:
                session_data = json.loads(resp.read().decode("utf-8"))
                session_id = session_data.get("id")
        except Exception as e:
            logger.error(f"Failed to create session on remote agent: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to create agent session: {str(e)}")

    # Prepare payload for /run_sse
    run_url = f"{PASSTHROUGH_BASE_URL}/run_sse"
    payload = {
        "app_name": AGENT_DIRECTORY,
        "user_id": req.user_id,
        "session_id": session_id,
        "newMessage": {
            "role": "user",
            "parts": [{"text": req.message}]
        }
    }

    def generate_sse():
        run_req = urllib.request.Request(
            run_url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST"
        )
        try:
            with urllib.request.urlopen(run_req) as resp:
                # Include session_id header line first for client state tracking
                yield f"event: session_id\ndata: {json.dumps({'session_id': session_id})}\n\n"
                for line in resp:
                    chunk = line.decode("utf-8")
                    yield chunk
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8")
            yield f"event: error\ndata: {json.dumps({'error': err_body})}\n\n"
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(generate_sse(), media_type="text/event-stream")


# Mount static files directory for plain HTML/CSS/JS Chat UI
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def root():
    index_file = static_dir / "index.html"
    if index_file.exists():
        return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Agent Proxy Running</h1><p>Frontend static files missing.</p>")
