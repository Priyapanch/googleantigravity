# ruff: noqa
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

import os
import sys
import json
import tempfile
import subprocess
import urllib.request
from pathlib import Path

import google.auth
from google.cloud import firestore
from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.code_executors import AgentEngineSandboxCodeExecutor
from google.adk.memory import VertexAiMemoryBankService
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.genai import types

from a2ui.schema.manager import A2uiSchemaManager
from a2ui.basic_catalog.provider import BasicCatalog
from .a2ui_utils import a2ui_after_model_callback

# HARDCODED Project ID as requested to prevent Agent Platform project number issue
PROJECT_ID = "qwiklabs-gcp-01-5875c9c6c131"
LOCATION = "us-east1"
COLLECTION_NAME = "robot_templates"


def _get_agent_engine_resource_name() -> str | None:
    """Reads Agent Engine resource name from deployment_metadata.json."""
    possible_paths = [
        Path(__file__).parent.parent / "deployment_metadata.json",
        Path("/config/Desktop/Session1/simple-agent/deployment_metadata.json"),
    ]
    for p in possible_paths:
        if p.exists():
            try:
                with open(p, "r") as f:
                    data = json.load(f)
                    res = data.get("remote_agent_runtime_id")
                    if res:
                        return res
            except Exception:
                pass
    return None


# Configure Agent Platform Sandbox Code Executor
_agent_engine_resource = _get_agent_engine_resource_name()
_agent_engine_id = (
    _agent_engine_resource.split("/")[-1]
    if _agent_engine_resource
    else "3769642630481182720"
)

code_executor = (
    AgentEngineSandboxCodeExecutor(agent_engine_resource_name=_agent_engine_resource)
    if _agent_engine_resource
    else AgentEngineSandboxCodeExecutor()
)

# Configure Memory Service for future redeployments using Agent Engine Memory Bank
memory_service = VertexAiMemoryBankService(
    project=PROJECT_ID,
    location=LOCATION,
    agent_engine_id=_agent_engine_id,
)


def _get_firestore_client() -> firestore.Client:
    """Helper function to get an authenticated Firestore client with explicit scopes."""
    creds, _ = google.auth.default(
        scopes=[
            "https://www.googleapis.com/auth/cloud-platform",
            "https://www.googleapis.com/auth/datastore",
        ]
    )
    return firestore.Client(project=PROJECT_ID, credentials=creds)


def fetch_api_schema_sample(endpoint: str = "todos") -> str:
    """Fetches real JSON response samples from JSONPlaceholder public API to inspect schemas for test generation.

    Args:
        endpoint: The API resource endpoint ('todos', 'posts', 'users', 'comments'). Defaults to 'todos'.

    Returns:
        Real API JSON data structure for generating accurate RequestsLibrary test cases.
    """
    valid_endpoints = ["todos", "posts", "users", "comments"]
    clean_endpoint = endpoint.lower().strip()
    if clean_endpoint not in valid_endpoints:
        clean_endpoint = "todos"

    url = f"https://jsonplaceholder.typicode.com/{clean_endpoint}/1"
    
    # Read optional API token from environment variable if provided
    api_key = os.environ.get("MOCK_API_KEY", "")

    req = urllib.request.Request(url, headers={"User-Agent": "RobotCodeGenAgent/1.0"})
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            return f"Real API Sample Data from '{url}':\n" + json.dumps(data, indent=2)
    except Exception as e:
        return f"Error fetching API sample from '{url}': {str(e)}"


def execute_robot_test_suite(robot_code: str) -> str:
    """Executes a Robot Framework test suite code string and returns the real-time execution results.

    Args:
        robot_code: The raw Robot Framework test suite code (.robot) to execute.

    Returns:
        The execution logs, pass/fail status, and stdout/stderr from running the Robot Framework test runner.
    """
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".robot", mode="w", delete=False) as tmp_file:
            tmp_file.write(robot_code)
            tmp_path = tmp_file.name

        result = subprocess.run(
            [sys.executable, "-m", "robot.run", tmp_path],
            capture_output=True,
            text=True,
            timeout=30,
        )

        output = f"--- Robot Framework Execution Results ---\nReturn Code: {result.returncode}\n\nSTDOUT:\n{result.stdout}"
        if result.stderr:
            output += f"\nSTDERR:\n{result.stderr}"

        return output
    except subprocess.TimeoutExpired:
        return "Execution timed out after 30 seconds."
    except Exception as e:
        return f"Error executing Robot Framework test suite: {str(e)}"
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def save_robot_template(
    template_id: str,
    name: str,
    category: str,
    library: str,
    description: str,
    code_snippet: str,
) -> str:
    """Saves or updates a Robot Framework test template in the Firestore backend.

    Args:
        template_id: Unique string identifier for the template (e.g. 'custom_login_test').
        name: Human-readable template title.
        category: Category of the test (e.g., 'web_ui', 'api', 'mobile', 'database').
        library: Primary Robot Framework library used ('Browser', 'RequestsLibrary', 'SeleniumLibrary').
        description: Brief description of what the test template covers.
        code_snippet: The complete Robot Framework test code (.robot).

    Returns:
        A confirmation message indicating successful storage in Firestore.
    """
    try:
        db = _get_firestore_client()
        doc_data = {
            "template_id": template_id,
            "name": name,
            "category": category,
            "library": library,
            "description": description,
            "code_snippet": code_snippet,
        }
        db.collection(COLLECTION_NAME).document(template_id).set(doc_data)
        return f"Successfully saved template '{name}' (ID: {template_id}) to Firestore collection '{COLLECTION_NAME}'."
    except Exception as e:
        return f"Error saving template to Firestore: {str(e)}"


def get_robot_templates(category: str = "") -> str:
    """Retrieves Robot Framework test templates from the Firestore backend database.

    Args:
        category: Optional category filter ('web_ui', 'api', etc.). If empty, returns all templates.

    Returns:
        A summary list of test templates found in Firestore.
    """
    try:
        db = _get_firestore_client()
        coll_ref = db.collection(COLLECTION_NAME)
        
        if category.strip():
            query = coll_ref.where("category", "==", category.strip().lower())
            docs = query.stream()
        else:
            docs = coll_ref.stream()

        templates = []
        for doc in docs:
            d = doc.to_dict()
            templates.append(
                f"- ID: {d.get('template_id')}\n  Name: {d.get('name')}\n  Category: {d.get('category')}\n  Library: {d.get('library')}\n  Description: {d.get('description')}\n"
            )

        if not templates:
            return f"No templates found in collection '{COLLECTION_NAME}' for category '{category}'."

        return f"Found {len(templates)} template(s) in Firestore:\n\n" + "\n".join(templates)
    except Exception as e:
        return f"Error reading templates from Firestore: {str(e)}"


def get_robot_template_by_id(template_id: str) -> str:
    """Fetches a specific Robot Framework template and its full code snippet by ID from Firestore.

    Args:
        template_id: The document ID of the template to retrieve (e.g., 'web_login_browser').

    Returns:
        The detailed template data including code snippet, or an error if not found.
    """
    try:
        db = _get_firestore_client()
        doc = db.collection(COLLECTION_NAME).document(template_id).get()
        if not doc.exists:
            return f"Template with ID '{template_id}' was not found in Firestore."
        
        d = doc.to_dict()
        return (
            f"--- Template Details: {d.get('name')} ---\n"
            f"ID: {d.get('template_id')}\n"
            f"Category: {d.get('category')}\n"
            f"Library: {d.get('library')}\n"
            f"Description: {d.get('description')}\n\n"
            f"Code Snippet:\n```robotframework\n{d.get('code_snippet')}\n```"
        )
    except Exception as e:
        return f"Error fetching template '{template_id}' from Firestore: {str(e)}"


def get_library_cheat_sheet(library_name: str) -> str:
    """Retrieves standard keyword references and usage patterns for Robot Framework libraries.

    Args:
        library_name: The name of the library ('Browser', 'RequestsLibrary', 'SeleniumLibrary', 'OperatingSystem', 'Collections').

    Returns:
        A cheat sheet string with common keywords and code patterns for the requested library.
    """
    name = library_name.lower().strip()
    if "browser" in name or "playwright" in name:
        return """
Robot Framework Browser Library (Playwright-based):
*** Settings ***
Library    Browser

Key Keywords:
- New Browser    browser=chromium    headless=False
- New Context    viewport={'width': 1920, 'height': 1080}
- New Page       https://example.com
- Click          id=submit-btn
- Fill Text      css=input[name="username"]    my_user
- Type Secret    css=input[type="password"]    $PASSWORD
- Get Text       css=h1    ==    Welcome
- Get Element States    id=success-msg    contains    visible
- Take Screenshot
- Close Browser
"""
    elif "request" in name or "api" in name:
        return """
Robot Framework RequestsLibrary (API Testing):
*** Settings ***
Library    RequestsLibrary
Library    Collections

Key Keywords:
- Create Session    api_session    https://api.example.com    headers=${headers}
- GET On Session    api_session    /users/1    params=${params}    expected_status=200
- POST On Session   api_session    /users      json=${body}       expected_status=201
- PUT On Session    api_session    /users/1    json=${body}       expected_status=200
- DELETE On Session api_session    /users/1    expected_status=204
- Status Should Be  200    ${response}
- Dictionary Should Contain Key    ${response.json()}    id
"""
    elif "selenium" in name:
        return """
Robot Framework SeleniumLibrary:
*** Settings ***
Library    SeleniumLibrary

Key Keywords:
- Open Browser    https://example.com    chrome
- Input Text      name=username    my_user
- Input Password  name=password    my_pass
- Click Button    xpath=//button[@type='submit']
- Element Should Contain    id=welcome-message    Welcome
- Close Browser
"""
    else:
        return f"Cheat sheet for '{library_name}': Include *** Settings *** with 'Library {library_name}', define *** Variables ***, and write keywords under *** Test Cases ***."


def validate_robot_code_structure(robot_code: str) -> str:
    """Validates basic section structure of a generated Robot Framework test file.

    Args:
        robot_code: The raw Robot Framework code string to validate.

    Returns:
        A validation result message indicating missing or present required section headers.
    """
    code = robot_code.strip()
    has_settings = "*** Settings ***" in code or "***Settings***" in code
    has_test_cases = "*** Test Cases ***" in code or "***Test Cases***" in code
    has_variables = "*** Variables ***" in code or "***Variables***" in code
    has_keywords = "*** Keywords ***" in code or "***Keywords***" in code

    issues = []
    if not has_settings:
        issues.append("Missing '*** Settings ***' section for Library imports.")
    if not has_test_cases:
        issues.append("Missing '*** Test Cases ***' section.")

    if issues:
        return "Validation Warning: " + " ".join(issues)
    
    sections = ["Settings", "Test Cases"]
    if has_variables:
        sections.append("Variables")
    if has_keywords:
        sections.append("Keywords")
        
    return f"Validation Passed! Found valid Robot Framework sections: {', '.join(sections)}."


ROLE_DESCRIPTION = f"""You are a senior Test Automation Engineer specializing in Robot Framework.
Your primary mission is to generate, manage, execute, and store clean, maintainable, production-ready Robot Framework test code (.robot files).

Memory Bank & User Preferences (Cross-Session Memory):
- You have access to Vertex AI Memory Bank via PreloadMemoryTool.
- CRITICAL REQUIREMENT: Always remember, recall, and strictly adhere to all user allergies and health/dietary restrictions (e.g., peanuts, gluten, dairy, shellfish, tree nuts, etc.) across sessions.
- Whenever a user discloses an allergy, health condition, or dietary constraint, treat it as a mandatory memory item to recall and respect in all future interactions and test generation tasks.

Code Sandbox Execution:
- You have access to Agent Platform AgentEngineSandboxCodeExecutor for executing Python snippets safely in a cloud sandbox.

Real API Inspection Tool:
- You have access to `fetch_api_schema_sample` to fetch real API response schemas from public endpoints ('todos', 'users', 'posts', 'comments') to generate accurate Robot Framework test assertions.

Execution Tool:
- You have access to `execute_robot_test_suite` to run generated Robot Framework code locally and report real execution stdout and pass/fail results.

Firestore Database Backend:
- You have access to a Cloud Firestore database collection 'robot_templates' under project '{PROJECT_ID}'.
- Use `get_robot_templates` to list existing templates stored in Firestore.
- Use `get_robot_template_by_id` to view a specific template's code from Firestore.
- Use `save_robot_template` when requested to save a new test suite or template into Firestore.

Supported Core Testing Domains:
1. Web UI Test Automation using the 'Browser' library (Playwright-backed) or 'SeleniumLibrary'.
2. API Test Automation using 'RequestsLibrary' and 'Collections'.

When generating Robot Framework code:
- Always format code blocks with syntax highlighting ```robotframework ... ```.
- Include standard Robot Framework sections in proper order:
  1. *** Settings ***
  2. *** Variables ***
  3. *** Test Cases ***
  4. *** Keywords ***
"""

# Build A2UI system prompt using A2uiSchemaManager version 0.8 and BasicCatalog
a2ui_version = "0.8"
basic_catalog_config = BasicCatalog().get_config(version=a2ui_version)
a2ui_schema_manager = A2uiSchemaManager(version=a2ui_version, catalogs=[basic_catalog_config])
AGENT_INSTRUCTION = a2ui_schema_manager.generate_system_prompt(role_description=ROLE_DESCRIPTION)

root_agent = Agent(
    name="robot_code_gen_agent",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=AGENT_INSTRUCTION,
    code_executor=code_executor,
    after_model_callback=a2ui_after_model_callback,
    tools=[
        PreloadMemoryTool(),
        fetch_api_schema_sample,
        execute_robot_test_suite,
        save_robot_template,
        get_robot_templates,
        get_robot_template_by_id,
        get_library_cheat_sheet,
        validate_robot_code_structure,
    ],
)

app = App(
    root_agent=root_agent,
    name="app",
)
