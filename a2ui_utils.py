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

"""A2UI helper functions for processing model output and converting UI payloads to A2UI parts in ADK callbacks."""

import logging
from typing import Any

from google.adk.models.llm_response import LlmResponse
from google.genai import types as genai_types
from a2ui.parser.parser import parse_response, has_a2ui_parts

logger = logging.getLogger(__name__)


def process_a2ui_response(llm_response: LlmResponse) -> LlmResponse | None:
    """Parses LLM response content and extracts <a2ui-json> blocks into application/a2ui+json parts.

    Args:
        llm_response: The LlmResponse object returned by the model.

    Returns:
        The modified LlmResponse if A2UI blocks were extracted, or None if unchanged.
    """
    if not llm_response or not llm_response.content or not llm_response.content.parts:
        return None

    new_parts: list[genai_types.Part] = []
    modified = False

    for part in llm_response.content.parts:
        if part.text and has_a2ui_parts(part.text):
            modified = True
            parsed_items = parse_response(part.text)
            for item in parsed_items:
                if item.text and item.text.strip():
                    new_parts.append(genai_types.Part.from_text(text=item.text))
                
                raw_json = item.a2ui_raw or getattr(item, "a2a_raw", None)
                if raw_json:
                    if isinstance(raw_json, str):
                        raw_bytes = raw_json.encode("utf-8")
                    elif isinstance(raw_json, bytes):
                        raw_bytes = raw_json
                    else:
                        import json
                        raw_bytes = json.dumps(raw_json).encode("utf-8")

                    new_parts.append(
                        genai_types.Part.from_bytes(
                            data=raw_bytes,
                            mime_type="application/a2ui+json",
                        )
                    )
        else:
            new_parts.append(part)

    if modified:
        llm_response.content.parts = new_parts
        logger.info("Successfully converted <a2ui-json> blocks into application/a2ui+json parts.")
        return llm_response

    return None


async def a2ui_after_model_callback(
    callback_context: Any, llm_response: LlmResponse
) -> LlmResponse | None:
    """ADK after_model_callback to inspect model response and inject A2UI parts.

    Args:
        callback_context: ADK callback context.
        llm_response: The LlmResponse from the model.

    Returns:
        The modified LlmResponse if A2UI content was extracted, else None.
    """
    return process_a2ui_response(llm_response)
