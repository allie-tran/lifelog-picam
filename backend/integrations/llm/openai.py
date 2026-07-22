
import json
import os
from collections.abc import Sequence
from typing import Any, Dict, List, Literal, Optional

from dotenv import load_dotenv
from openai import OpenAI
from openai.types.responses import ResponseInputParam
from integrations.llm.gemini import LLM, MixedContent
from google.genai.types import Content, Part  # type: ignore
from partialjson.json_parser import JSONParser
from pydantic import BaseModel
from pyrate_limiter import Duration, Limiter, Rate
from rich import print
import base64

load_dotenv()

DEBUG = False
JSON_START_FLAG = "```json"
JSON_END_FLAG = "```"

parser = JSONParser()
parser.on_extra_token = lambda *_, **__: None

rate = Rate(3, Duration.SECOND)
limiter = Limiter(rate)

# Set up ChatGPT generation model
API_KEY = os.environ.get("OPENAI_API_KEY", "")
# OPENAI_MODEL = os.environ.get("OPENAI_MODEL_NAME", "")
# OPENAI_MODEL = "gpt-5.4-mini"
OPENAI_MODEL = "gpt-5-mini"  # default to gpt-5.4-mini if not set in env
print("Using OpenAI Model Name:", OPENAI_MODEL)

def encode_to_base64(data: bytes) -> str:
    return base64.b64encode(data).decode('utf-8')


class OpenAILLM(LLM):
    # Set up the template messages to use for the completion
    system_instruction: str = "You are a helpful assistant."

    def __init__(self):
        self.client = OpenAI(api_key=API_KEY)
        self.model_name = OPENAI_MODEL

    def generate(self, contents: Any, parse_json=False, use_search: bool = False):
        """
        Generate completions from a list of messages.
        ``use_search`` is accepted for interface parity; chat.completions has no
        grounding, so grounded lookups must go through ``web_search`` instead.
        """
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[{
                "role": "user",
                "content": contents
            }],
        )
        completion = response.choices[0].message.content
        print("OpenAI Response:", completion)
        if DEBUG:
            print("LLM Completion:", completion)
        if parse_json and completion is not None:
            parsed = self.__parse(completion)
            if parsed is not None:
                return parsed
            else:
                print("Warning: Could not parse JSON from completion.")
        return completion

    def __parse(self, response: str) -> Optional[Dict]:
        """
        Extract a JSON object from a completion, tolerating truncation via
        partialjson. Unlike the Gemini wrapper this does not assume a ```json
        fence: chat models (gpt-5-mini) usually return raw JSON, so we strip an
        optional fence and otherwise fall back to the outermost {...} span.
        """
        if not response:
            return None
        text = response.strip()
        if "```" in text:
            # ```json ... ``` or ``` ... ``` — take the fenced body
            fence = text.split("```")[1]
            if fence.startswith("json"):
                fence = fence[len("json"):]
            text = fence.strip()
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        blob = text[start:end + 1]
        try:
            return parser.parse(blob)
        except Exception:
            print("Warning: Could not parse JSON from completion.")
            return None

    def web_search(self, prompt: str) -> Optional[str]:
        """
        Grounded text generation using OpenAI's built-in web_search tool
        (Responses API). Returns plain text, or None on error.
        """
        try:
            response = self.client.responses.create(
                model=self.model_name,
                tools=[{"type": "web_search"}],
                input=prompt,
            )
            return response.output_text
        except Exception as e:
            print(f"OpenAI web_search failed: {e}")
            return None

    def generate_from_text(
        self, text: str, parse_json=False, use_search: bool = False
    ) -> Optional[Dict | str]:
        """
        Generate completions from text
        Then parse the JSON object from the completion
        If the completion is not a JSON object, return the text
        """
        if use_search:
            return self.web_search(text)
        return self.generate([{"type": "text", "text": text}], parse_json=parse_json)

    def generate_from_mixed_media(
        self, data: Sequence[MixedContent], parse_json=False, use_search: bool = False
    ) -> Optional[Dict | str]:
        parts: List[Any] = []
        for part in data:
            if part.type == "text":
                parts.append({"type": "text", "text": part.content})
            elif part.type == "image_url":
                assert isinstance(part.content, bytes), "Image content must be bytes"
                parts.append({"type": "image_url", "image_url": { "url": f"data:image/jpeg;base64,{encode_to_base64(part.content)}"}})
        return self.generate(parts, parse_json=parse_json)

openai_llm = OpenAILLM()
