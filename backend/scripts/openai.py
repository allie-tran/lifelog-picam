
import json
import os
from collections.abc import Sequence
from typing import Any, Dict, List, Literal, Optional

from dotenv import load_dotenv
from openai import OpenAI
from openai.types.responses import ResponseInputParam
from scripts.llm import LLM, MixedContent
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
OPENAI_MODEL = "gpt-4.1-nano"
print("Using OpenAI Model Name:", OPENAI_MODEL)

def encode_to_base64(data: bytes) -> str:
    return base64.b64encode(data).decode('utf-8')


class OpenAILLM(LLM):
    # Set up the template messages to use for the completion
    system_instruction: str = "You are a helpful assistant."

    def __init__(self):
        self.client = OpenAI(api_key=API_KEY)
        self.model_name = OPENAI_MODEL

    def generate(self, contents: Any, parse_json=False):
        """
        Generate completions from a list of messages
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

    def generate_from_text(self, text: str, parse_json=False) -> Optional[Dict | str]:
        """
        Generate completions from text
        Then parse the JSON object from the completion
        If the completion is not a JSON object, return the text
        """
        return self.generate([{"type": "text", "text": text}], parse_json=parse_json)

    def generate_from_mixed_media(
        self, data: Sequence[MixedContent], parse_json=False
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
