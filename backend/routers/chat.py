"""Chat assistant endpoints.

A conversation the user has about their days. The bot answers questions and
auto-applies edits (segment activity, day summary text, location label) via
tool-calls, and maintains a distilled memory of durable facts. Transcripts
persist per thread; a day thread is keyed ``{device}:{date}`` so re-opening a
day resumes it. Non-streaming (v1).
"""
import logging
import uuid
from datetime import datetime
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import _require_owner
from auth.auth_models import auth_dependency, get_user
from auth.types import AccessLevel
from database import get_session
from database.types import ChatMemoryRecord, ChatThreadRecord
from schemas import (
    ChatMemory,
    ChatMessage,
    ChatMessageRequest,
    ChatThread,
    ChatTurnResponse,
    TokenUsage,
)
from services.chat_assistant import run_chat_turn

logger = logging.getLogger(__name__)

router = APIRouter()


def _resolve_thread_id(device: str, req: ChatMessageRequest) -> str:
    if req.thread_id:
        return req.thread_id
    if req.scope == "day" and req.date:
        return f"{device}:{req.date}"
    return f"global:{device}:{uuid.uuid4().hex[:8]}"


@router.post("/message", summary="Send a chat message; the bot may auto-apply edits",
             response_model=ChatTurnResponse)
def post_message(
    request: ChatMessageRequest,
    device: str,
    user=Depends(get_user),
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Empty message")

    thread_id = _resolve_thread_id(device, request)
    thread = ChatThreadRecord.find_one({"thread_id": thread_id})
    history: List[ChatMessage] = list(thread.messages) if thread else []

    reply, applied, usage = run_chat_turn(
        session,
        device=device,
        username=user.username,
        scope=request.scope,
        date=request.date,
        history=history,
        user_text=request.text,
    )

    now = datetime.utcnow()
    user_msg = ChatMessage(role="user", content=request.text, ts=now)
    bot_msg = ChatMessage(
        role="assistant", content=reply, applied_actions=applied,
        token_usage=usage, ts=now,
    )
    messages = history + [user_msg, bot_msg]

    if thread:
        total = TokenUsage(
            prompt=thread.token_usage.prompt + usage.prompt,
            completion=thread.token_usage.completion + usage.completion,
            total=thread.token_usage.total + usage.total,
        )
        ChatThreadRecord.update_one(
            {"thread_id": thread_id},
            data={"$set": {
                "messages": [m.model_dump(mode="json") for m in messages],
                "token_usage": total.model_dump(),
                "updated": now,
            }},
        )
    else:
        total = usage
        ChatThreadRecord(
            thread_id=thread_id,
            username=user.username,
            device=device,
            scope=request.scope,
            date=request.date,
            messages=messages,
            token_usage=total,
            created=now,
            updated=now,
        ).create()

    return ChatTurnResponse(
        thread_id=thread_id,
        reply=reply,
        applied_actions=applied,
        message_usage=usage,
        total_usage=total,
    )


@router.get("/threads", summary="List chat threads for a device",
            response_model=List[ChatThread])
def list_threads(
    device: str,
    scope: Optional[str] = None,
    user=Depends(get_user),
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):
    _require_owner(access_level)
    filt = {"username": user.username, "device": device}
    if scope:
        filt["scope"] = scope
    threads = list(ChatThreadRecord.find(filt, sort=[("updated", -1)]))
    # Slim: drop message bodies from the list view.
    return [ChatThread(**{**t.model_dump(), "messages": []}) for t in threads]


@router.get("/thread/{thread_id}", summary="Get one chat thread with its transcript",
            response_model=ChatThread)
def get_thread(
    thread_id: str,
    user=Depends(get_user),
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):
    _require_owner(access_level)
    thread = ChatThreadRecord.find_one(
        {"thread_id": thread_id, "username": user.username}
    )
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    return ChatThread(**thread.model_dump())


@router.delete("/thread/{thread_id}", summary="Delete a chat thread")
def delete_thread(
    thread_id: str,
    user=Depends(get_user),
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):
    _require_owner(access_level)
    ChatThreadRecord.delete_many({"thread_id": thread_id, "username": user.username})
    return {"success": True}


@router.get("/memory", summary="List the bot's remembered facts",
            response_model=List[ChatMemory])
def list_memory(
    device: str,
    user=Depends(get_user),
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):
    _require_owner(access_level)
    rows = ChatMemoryRecord.find({"username": user.username, "device": device})
    return [ChatMemory(**m.model_dump()) for m in rows]


@router.delete("/memory/{key}", summary="Forget one remembered fact")
def delete_memory(
    key: str,
    device: str,
    user=Depends(get_user),
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):
    _require_owner(access_level)
    ChatMemoryRecord.delete_many(
        {"username": user.username, "device": device, "key": key}
    )
    return {"success": True}
