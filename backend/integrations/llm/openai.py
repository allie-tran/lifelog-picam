
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
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


@dataclass
class TokenUsage:
    prompt: int = 0
    completion: int = 0
    total: int = 0


@dataclass
class ChatResult:
    reply: str
    usage: TokenUsage


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

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        dispatch: Optional[Any] = None,
        system: Optional[str] = None,
        max_tool_rounds: int = 6,
    ) -> "ChatResult":
        """
        Multi-turn chat with optional function-calling. ``messages`` is the prior
        conversation as OpenAI role/content dicts; ``tools`` is a list of tool
        JSON schemas; ``dispatch(name, args) -> str`` executes a tool and returns
        a short result string (the orchestrator owns any side effects / action
        bookkeeping). Runs the tool loop until the model stops calling tools or
        ``max_tool_rounds`` is hit, accumulating token usage across rounds.

        Only implemented for OpenAI (gpt-5-mini) — Gemini/Ollama wrappers do not
        provide ``chat()`` yet.
        """
        convo: List[Dict[str, Any]] = []
        if system:
            convo.append({"role": "system", "content": system})
        convo.extend(messages)

        usage = TokenUsage()

        for _ in range(max_tool_rounds):
            kwargs: Dict[str, Any] = {"model": self.model_name, "messages": convo}
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
            response = self.client.chat.completions.create(**kwargs)

            if response.usage is not None:
                usage.prompt += response.usage.prompt_tokens or 0
                usage.completion += response.usage.completion_tokens or 0
                usage.total += response.usage.total_tokens or 0

            msg = response.choices[0].message
            tool_calls = getattr(msg, "tool_calls", None)
            if not tool_calls:
                return ChatResult(reply=msg.content or "", usage=usage)

            # Echo the assistant tool-call turn back, then append each result.
            convo.append(msg.model_dump(exclude_none=True))
            for call in tool_calls:
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = dispatch(call.function.name, args) if dispatch else "No handler."
                convo.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": str(result),
                })

        # Tool budget exhausted — do one final untooled pass for a text reply.
        final = self.client.chat.completions.create(model=self.model_name, messages=convo)
        if final.usage is not None:
            usage.prompt += final.usage.prompt_tokens or 0
            usage.completion += final.usage.completion_tokens or 0
            usage.total += final.usage.total_tokens or 0
        return ChatResult(reply=final.choices[0].message.content or "", usage=usage)

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
