"""Chat assistant orchestrator.

Runs one conversational turn: builds a system prompt (role + distilled memory +
day/period context), exposes a set of write tools the model can call to
auto-apply edits, and returns the reply plus the actions it took and token
usage. Non-streaming (v1). Provider is OpenAI (gpt-5-mini) — the only wrapper
that implements ``chat()`` / function-calling today.

Tool handlers deliberately mirror existing write paths so behaviour stays
consistent with the manual UI:
  * edit_segment_activity → same path as routers/day_summary.change_segment_activity
  * change_location       → same upsert as routers/location.upsert_label
"""
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from database.models import Image as ImageModel
from database.models import LocationLabel
from database.types import ChatMemoryRecord, DaySummaryRecord, ImageRecord
from integrations.llm.openai import openai_llm
from integrations.sessions.redis import bust_day_caches
from schemas import AppliedAction, ChatMessage, TokenUsage
from tasks import describe_segment_task

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a lifelog assistant. The user reviews their day, captured \
automatically by a wearable camera + GPS. You help them understand and correct their \
timeline. Be concise and factual.

You can call tools to APPLY edits directly (the user has authorised auto-apply):
- edit_segment_activity: re-describe/relabel a segment when the user says what it \
actually was. Pass the segment_id and a short instruction.
- edit_day_summary_text: replace the day's summary text (Markdown bullets).
- change_location: correct/label the place a segment was at.
- manage_memory: remember durable facts the user tells you (people, routines, naming \
preferences). Use op="add"/"update" with a short key, or op="remove".

Only call a tool when the user actually asks for a change or tells you something worth \
remembering. Never invent segment_ids — use the ones in the context below."""


# ---------------------------------------------------------------------------
# Tool schemas (OpenAI function-calling format)
# ---------------------------------------------------------------------------
def _tool_schemas() -> List[Dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "edit_segment_activity",
                "description": "Re-describe/relabel one segment using a free-text instruction.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "segment_id": {"type": "integer"},
                        "instructions": {
                            "type": "string",
                            "description": "What the segment actually was / how to relabel it.",
                        },
                    },
                    "required": ["segment_id", "instructions"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "edit_day_summary_text",
                "description": "Replace the day's summary text with new Markdown bullets.",
                "parameters": {
                    "type": "object",
                    "properties": {"new_text": {"type": "string"}},
                    "required": ["new_text"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "change_location",
                "description": "Set a personal label/name for the place a segment was at.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "segment_id": {"type": "integer"},
                        "label": {"type": "string", "description": "The name/label for the place."},
                        "label_kind": {
                            "type": "string",
                            "enum": ["home", "work", "other"],
                            "description": "Category of the place.",
                        },
                    },
                    "required": ["segment_id", "label"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "manage_memory",
                "description": "Add, update, or remove a durable fact about the user.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "op": {"type": "string", "enum": ["add", "update", "remove"]},
                        "key": {"type": "string", "description": "Short stable key, e.g. 'gym_name'."},
                        "text": {"type": "string", "description": "The fact (omit for remove)."},
                    },
                    "required": ["op", "key"],
                },
            },
        },
    ]


# ---------------------------------------------------------------------------
# Context / memory rendering
# ---------------------------------------------------------------------------
def _load_memories(username: str, device: str) -> List[ChatMemoryRecord]:
    return list(ChatMemoryRecord.find({"username": username, "device": device}))


def _render_memory(memories: List[ChatMemoryRecord]) -> str:
    if not memories:
        return ""
    lines = [f"- {m.key}: {m.text}" for m in memories]
    return "Known facts about the user:\n" + "\n".join(lines)


def _segment_descriptions(session: Session, device: str, date: str) -> Dict[int, str]:
    """Per-segment factual descriptions (the LLM's 1-2 sentence annotation, e.g.
    what food/drink is visible). Stored identically on every image of a segment,
    so one DISTINCT query per segment suffices."""
    rows = session.execute(
        select(ImageModel.segment_id, ImageModel.activity_description)
        .where(
            ImageModel.device == device,
            ImageModel.date == date,
            ImageModel.deleted == False,
            ImageModel.segment_id.isnot(None),
            ImageModel.activity_description.isnot(None),
        )
        .distinct()
    ).all()
    out: Dict[int, str] = {}
    for seg_id, desc in rows:
        if desc and seg_id not in out:
            out[seg_id] = desc
    return out


def _render_day_context(session: Session, device: str, date: str) -> str:
    day = DaySummaryRecord.find_one({"device": device, "date": date})
    if not day:
        return f"No summary exists yet for {date}."
    descriptions = _segment_descriptions(session, device, date)
    lines = [f"Day {date} — {day.number_of_images} images."]
    if day.summary_text:
        lines.append(f"Current summary:\n{day.summary_text}")
    if day.location_visits:
        lines.append("Places:")
        for v in day.location_visits:
            name = v.location_name or "Unknown place"
            desc = f" — {v.description}" if v.description else ""
            lines.append(f"  [{name}] segments {v.segment_ids}{desc}")
    lines.append("Segments (segment_id · activity · time · place · description):")
    for s in day.segments:
        t = s.start_time.strftime("%H:%M") if s.start_time else "?"
        place = s.location_name or "-"
        desc = descriptions.get(s.segment_id or -1, "")
        desc_part = f" · {desc}" if desc else ""
        lines.append(f"  #{s.segment_id} · {s.activity} · {t} · {place}{desc_part}")
    return "\n".join(lines)


def _render_period_context(session: Session, device: str, date: Optional[str]) -> str:
    # Global/period scope: point the model at whatever period record matches the
    # anchor date if given; otherwise stay general.
    if not date:
        return "No specific date in focus. Ask the user which day to look at."
    return _render_day_context(session, device, date)


# ---------------------------------------------------------------------------
# Tool handlers — each returns a short result string for the model.
# ---------------------------------------------------------------------------
def _handle_edit_segment_activity(
    session: Session, device: str, date: str, args: Dict[str, Any]
) -> str:
    segment_id = args.get("segment_id")
    instructions = args.get("instructions", "")
    if segment_id is None:
        return "Error: segment_id required."
    thumbnails = [
        img.thumbnail
        for img in ImageRecord.find(
            session,
            segment_id=segment_id,
            date=date,
            deleted=False,
            device=device,
            sort="image_path",
            sort_desc=False,
        )
    ]
    if not thumbnails:
        return f"Error: segment {segment_id} not found on {date}."
    describe_segment_task.delay(
        device,
        date,
        thumbnails,
        segment_id,
        extra_info=[
            f"Camera viewer instruction: {instructions}. Incorporate this into the description.",
        ],
    )
    DaySummaryRecord.update_one(
        {"date": date, "device": device}, data={"$set": {"updated": True}}
    )
    return f"Queued re-description of segment {segment_id}. It will update shortly."


def _handle_edit_day_summary_text(device: str, date: str, args: Dict[str, Any]) -> str:
    new_text = args.get("new_text", "").strip()
    if not new_text:
        return "Error: new_text required."
    DaySummaryRecord.update_one(
        {"date": date, "device": device},
        data={"$set": {"summary_text": new_text, "text_summary_generated_at": datetime.utcnow()}},
    )
    return "Day summary updated."


def _handle_change_location(
    session: Session, username: str, device: str, date: str, args: Dict[str, Any]
) -> str:
    segment_id = args.get("segment_id")
    label = (args.get("label") or "").strip()
    label_kind = args.get("label_kind") or "other"
    if segment_id is None or not label:
        return "Error: segment_id and label required."
    location_id = session.execute(
        select(ImageModel.location_id)
        .where(
            ImageModel.device == device,
            ImageModel.date == date,
            ImageModel.segment_id == segment_id,
            ImageModel.location_id.isnot(None),
        )
        .limit(1)
    ).scalar_one_or_none()
    if location_id is None:
        return f"Error: segment {segment_id} has no resolved location to label."
    # Mirror routers.location.upsert_label — user-scoped label upsert.
    session.execute(
        insert(LocationLabel)
        .values(
            id=uuid.uuid4(),
            username=username,
            location_id=location_id,
            label=label,
            label_kind=label_kind,
        )
        .on_conflict_do_update(
            constraint="uq_location_label_user_loc",
            set_={"label": label, "label_kind": label_kind},
        )
    )
    session.commit()

    # Force the day summary to pick up the new label. Segment/nav/browse caches
    # are keyed by geocoded name, and the location-visit layer reuses stored
    # visits whenever ``location_visits_sig`` matches — which it always does on a
    # relabel (the sig is built from the *unlabeled* segment names). Clearing the
    # sig + marking the text stale makes the next fetch rebuild the visits (which
    # DO honour the user's label) and regenerate the summary text.
    bust_day_caches(device, date)
    DaySummaryRecord.update_one(
        {"date": date, "device": device},
        data={"$set": {
            "location_visits_sig": None,
            "text_summary_stale": True,
            "updated": True,
        }},
    )
    return (
        f"Labeled the place for segment {segment_id} as '{label}'. "
        "The day's places will refresh shortly."
    )


def _handle_manage_memory(username: str, device: str, args: Dict[str, Any]) -> str:
    op = args.get("op")
    key = (args.get("key") or "").strip()
    text = (args.get("text") or "").strip()
    if not key:
        return "Error: key required."
    filt = {"username": username, "device": device, "key": key}
    if op == "remove":
        ChatMemoryRecord.delete_many(filt)
        return f"Forgot '{key}'."
    if op in ("add", "update"):
        existing = ChatMemoryRecord.find_one(filt)
        if existing:
            ChatMemoryRecord.update_one(
                filt, data={"$set": {"text": text, "updated": datetime.utcnow()}}
            )
        else:
            ChatMemoryRecord(
                username=username, device=device, key=key, text=text,
                updated=datetime.utcnow(),
            ).create()
        return f"Remembered '{key}'."
    return f"Error: unknown op '{op}'."


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def run_chat_turn(
    session: Session,
    device: str,
    username: str,
    scope: str,
    date: Optional[str],
    history: List[ChatMessage],
    user_text: str,
) -> Tuple[str, List[AppliedAction], TokenUsage]:
    """Run one turn. Returns (reply, applied_actions, message_usage)."""
    system, messages, applied, dispatch = _build_turn(
        session, device, username, scope, date, history, user_text
    )
    result = openai_llm.chat(
        messages, tools=_tool_schemas(), dispatch=dispatch, system=system
    )
    usage = TokenUsage(
        prompt=result.usage.prompt,
        completion=result.usage.completion,
        total=result.usage.total,
    )
    return result.reply, applied, usage


def stream_turn(
    session: Session,
    device: str,
    username: str,
    scope: str,
    date: Optional[str],
    history: List[ChatMessage],
    user_text: str,
):
    """Streaming variant of ``run_chat_turn``. Generator yielding event dicts:
      {"type": "delta", "text": str}
      {"type": "tool", "action": AppliedAction}
      {"type": "usage", "usage": TokenUsage}
    The final usage event lets the caller persist the transcript."""
    system, messages, _applied, dispatch = _build_turn(
        session, device, username, scope, date, history, user_text
    )
    for ev in openai_llm.chat_stream(
        messages, tools=_tool_schemas(), dispatch=dispatch, system=system
    ):
        if ev["type"] == "delta":
            yield {"type": "delta", "text": ev["text"]}
        elif ev["type"] == "tool":
            yield {"type": "tool", "action": AppliedAction(
                tool=ev["name"], args=ev.get("args", {}), outcome=ev.get("outcome", ""),
            )}
        elif ev["type"] == "usage":
            u = ev["usage"]
            yield {"type": "usage", "usage": TokenUsage(
                prompt=u.prompt, completion=u.completion, total=u.total,
            )}


def _build_turn(
    session: Session,
    device: str,
    username: str,
    scope: str,
    date: Optional[str],
    history: List[ChatMessage],
    user_text: str,
):
    """Shared setup for both turn runners: system prompt (memory + context),
    the OpenAI message list, and a tool dispatcher. Returns
    (system, messages, applied_actions_list, dispatch)."""
    memories = _load_memories(username, device)
    if scope == "day" and date:
        context = _render_day_context(session, device, date)
    else:
        context = _render_period_context(session, device, date)

    system = _SYSTEM_PROMPT
    mem = _render_memory(memories)
    if mem:
        system += "\n\n" + mem
    system += "\n\n--- Context ---\n" + context

    messages: List[Dict[str, Any]] = [
        {"role": m.role, "content": m.content}
        for m in history
        if m.role in ("user", "assistant") and m.content
    ]
    messages.append({"role": "user", "content": user_text})

    applied: List[AppliedAction] = []

    def dispatch(name: str, args: Dict[str, Any]) -> str:
        try:
            if name == "edit_segment_activity":
                outcome = _handle_edit_segment_activity(session, device, date or "", args)
            elif name == "edit_day_summary_text":
                outcome = _handle_edit_day_summary_text(device, date or "", args)
            elif name == "change_location":
                outcome = _handle_change_location(session, username, device, date or "", args)
            elif name == "manage_memory":
                outcome = _handle_manage_memory(username, device, args)
            else:
                return f"Error: unknown tool '{name}'."
        except Exception as e:  # keep the loop alive; report failure to the model
            logger.exception("chat tool %s failed", name)
            outcome = f"Error running {name}: {e}"
        applied.append(AppliedAction(tool=name, args=args, outcome=outcome))
        return outcome

    return system, messages, applied, dispatch
