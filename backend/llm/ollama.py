import json
import os
from collections.abc import Sequence
from typing import Any, Dict, List, Literal, Optional
import requests
import base64

from dotenv import load_dotenv
from partialjson.json_parser import JSONParser
from pydantic import BaseModel
from pyrate_limiter import Duration, Limiter, Rate
from rich import print

load_dotenv()

DEBUG = True
JSON_START_FLAG = "```json"
JSON_END_FLAG = "```"

parser = JSONParser()
parser.on_extra_token = lambda *_, **__: None

rate = Rate(3, Duration.SECOND)
limiter = Limiter(rate)

# Set up Ollama generation model
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
# MODEL_NAME = "deepseek-r1:8b" # Too long
MODEL_NAME = "llama3.2:3b"
# VLLM_NAME = "qwen3-vl:8b"
VLLM_NAME = "qwen3-vl:30b"


class MixedContent(BaseModel):
    type: Literal["text", "image_url"]
    content: str | bytes


class LLM:
    # Set up the template messages to use for the completion
    system_instruction: str = "You are a helpful assistant, and you follow the word limits strictly."

    def __init__(self):
        self.ollama_host = OLLAMA_HOST
        self.model_name = MODEL_NAME
        self.vlm_name = VLLM_NAME
        self.chat_url = f"{self.ollama_host}/api/chat"

    def generate(self, messages: List[Dict[str, Any]], parse_json=False, vlm=False) -> Optional[Dict | str]:
        """
        Generate completions from a list of messages using Ollama's /api/chat endpoint.
        """
        payload = {
            "model": self.model_name if not vlm else self.vlm_name,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {
                "system": self.system_instruction,
            }
        }

        # NOTE: Ollama's /api/chat endpoint generally doesn't support a separate 'system_instruction'
        # in the options, but instead requires it as the first message in the 'messages' list.
        # However, the user's original class structure uses an instance variable for it.
        # We will follow the standard message format for chat:
        if self.system_instruction:
             # Insert the system instruction as the first message
             # This assumes 'messages' passed to generate() starts with the user's prompt.
             system_message = {"role": "system", "content": self.system_instruction}
             if not messages or messages[0].get("role") != "system":
                 payload["messages"].insert(0, system_message)

        try:
            response = requests.post(self.chat_url, json=payload, timeout=60)
            response.raise_for_status()

            # Ollama's /api/chat response format
            data = response.json()
            llm_response = data.get("message", {}).get("content", "")

        except Exception as e:
            print(f"An error occurred during Ollama generation: {e}")
            return None

        if DEBUG:
            print("Ollama Response:", llm_response)

        if parse_json and llm_response:
            return self.__parse(llm_response)
        else:
            return llm_response

    def __parse(self, response: str) -> Optional[Dict]:
        # The JSON parsing logic remains the same
        while JSON_START_FLAG in response:
            start = response.find(JSON_START_FLAG)
            response = response[start + len(JSON_START_FLAG) :]
            json_object = response
            if JSON_END_FLAG in response:
                end = response.find(JSON_END_FLAG)
                json_object = response[: end]  # Corrected to stop before the end flag
                response = response[end + len(JSON_END_FLAG) :]
            try:
                # Use a stripped version for parsing
                json_object = parser.parse(json_object.strip())
                return json_object
            except json.JSONDecodeError as e:
                print(f"JSON Decode Error: {e}")
                pass
        return None

    def generate_from_text(self, text: str, parse_json=False) -> Optional[Dict | str]:
        """
        Generate completions from text
        """
        # Create a single user message for the /api/chat endpoint
        messages = [{"role": "user", "content": text}]
        return self.generate(messages, parse_json)

    def generate_from_mixed_media(
        self, data: Sequence[MixedContent], parse_json=False
    ) -> Optional[Dict | str]:
        """
        Generate completions from mixed media (text and images) using Ollama's /api/chat endpoint.
        Images are encoded as base64 in the 'images' field of the user message.
        """
        import base64

        text_prompt = ""
        base64_images = []

        # 1. Separate Text and Image Content
        for part in data:
            if part.type == "text":
                # Aggregate all text parts into a single prompt string
                text_prompt += part.content + "\n"
            elif part.type == "image_url" and part.content:
                # 2. Convert image bytes (stored in content) to Base64 string
                if isinstance(part.content, bytes):
                    # We assume get_visual_content passed us bytes
                    encoded_image = base64.b64encode(part.content).decode("utf-8")
                    base64_images.append(encoded_image)
                else:
                    print("Warning: Image content is not bytes. Skipping.")

        # Ensure there is some content before making a request
        if not text_prompt and not base64_images:
            return None

        # 3. Construct the single user message for the Ollama API
        messages = [
            {
                "role": "user",
                # Use a default prompt if only images are provided
                "content": text_prompt.strip() or "Describe the attached images.",
                # This is the key: Ollama puts the list of base64 images here
                "images": base64_images
            }
        ]
        return self.generate(messages, parse_json=parse_json, vlm=True)


def get_visual_content(image_paths: List[str] | List[bytes]) -> List[MixedContent]:
    """
    Get a visual message for Ollama from a list of image paths (reads file bytes).
    This function remains largely the same for file reading.
    """
    if not image_paths:
        return []

    messages = []
    for image_path in image_paths:
        try:
            image_bytes = (
                open(image_path, "rb").read()
                if isinstance(image_path, str)
                else image_path
            )
            # Store image bytes directly in content, as the LLM class handles base64 encoding
            messages.append(MixedContent(type="image_url", content=image_bytes))
        except OSError as e:
            print(f"Error reading image {image_path}: {e}")
            continue
    return messages

llm= LLM()

