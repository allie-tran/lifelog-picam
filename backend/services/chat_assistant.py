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
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import Image as ImageModel
from database.types import ChatMemoryRecord, DaySummaryRecord, ImageRecord
from integrations.llm.openai import openai_llm
from integrations.sessions.redis import bust_day_caches
from schemas import AppliedAction, ChatMemory, ChatMessage, TokenUsage
from tasks import describe_segment_task

logger = logging.getLogger(__name__)

# Max prior transcript messages sent to the LLM per turn (full history is still
# stored + displayed; this only bounds the per-turn prompt cost).
_HISTORY_LIMIT = 8

# Auto-distillation (an extra LLM call) runs only every N user turns, batching
# the messages since the last run so nothing is missed.
_DISTILL_EVERY = 3

_SYSTEM_PROMPT = """You are a lifelog assistant. The user reviews their day, captured \
automatically by a wearable camera + GPS. You help them understand and correct their \
timeline. Be concise and factual.

You can call tools to APPLY edits directly (the user has authorised auto-apply):
- edit_segment_activity: re-describe/relabel a segment when the user says what it \
actually was. Pass the segment_id and a short instruction.
- edit_day_summary_text: replace the day's summary text (Markdown bullets).
- change_location: correct/label the place a segment was at.
- get_segment_details: fetch photo descriptions for specific segments of the current \
day when the one-line segment table isn't detailed enough (e.g. what food was eaten).
- search_lifelog: semantic search across ALL the user's days when the answer isn't in \
the current day's context (e.g. "when did I last see Luca?").
- web_search: look up external facts on the public web (opening hours, what a venue is \
known for) — never for the user's own data.
- manage_memory: remember durable facts the user EXPLICITLY asks you to remember \
(op="add"/"update" with a short key, or op="remove").
- suggest_memory: when the user mentions something durable but did NOT ask you to \
remember it (a person + relationship, a routine, a stable preference, a place's real \
name), propose it. This does NOT save — the user gets a one-tap Save button. Prefer \
this over manage_memory for anything the user didn't explicitly tell you to store.

Obvious durable facts are also captured automatically after the turn, so don't nag; \
use suggest_memory only for genuinely useful, non-obvious facts. Only call a tool when \
the user asks for a change, tells you to remember, or clearly states a durable fact. \
Never invent segment_ids — use the ones in the context below.

ANSWERING STYLE: Prefer answering to asking. When a question is ambiguous, pick the \
most likely interpretation from the context, answer it, and state the assumption you \
made in one short clause ("Assuming the morning trip …"). Ask a clarifying question \
ONLY when the plausible answers differ a lot AND you truly cannot pick a default — and \
then ask at most once. Each segment below has start–end times, a duration, and a \
transport mode when known, so you can compute trip durations (door-to-door = from the \
last segment at the origin to the first at the destination) and travel times directly; \
do the arithmetic instead of asking. If the data genuinely can't answer, say so plainly."""


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
                "description": "Correct the venue a stop segment was at. Re-resolves the "
                               "stop to the named place (matching a real nearby venue when "
                               "possible), not just a display label.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "segment_id": {"type": "integer"},
                        "label": {"type": "string", "description": "The real name of the place."},
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
        {
            "type": "function",
            "function": {
                "name": "get_segment_details",
                "description": "Fetch the photo descriptions (and transport mode) for specific "
                               "segments of the current day. Use when you need detail beyond the "
                               "activity label — e.g. what food was on the table.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "segment_ids": {"type": "array", "items": {"type": "integer"}},
                    },
                    "required": ["segment_ids"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_lifelog",
                "description": "Semantic search across ALL of the user's days for moments "
                               "matching a description (e.g. 'coffee with Luca', 'red bridge'). "
                               "Use when the answer isn't in the current day's context.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "description": "Max results (default 8)."},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the public web for external facts (opening hours, what a "
                               "venue is known for, event info). Not for the user's own data.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "suggest_memory",
                "description": "Propose a durable fact for the user to save with one tap "
                               "(does not store it). Use for facts the user mentioned but "
                               "did not explicitly ask you to remember.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Short stable key, e.g. 'partner_name'."},
                        "text": {"type": "string", "description": "The fact to propose remembering."},
                    },
                    "required": ["key", "text"],
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


def _segment_modes(session: Session, device: str, date: str) -> Dict[int, str]:
    """Most-common transport mode per segment (walk/train/car/…), from ImageGPS.
    Lets the assistant answer travel-time / trip-duration questions."""
    from collections import Counter
    from database.models import ImageGPS
    rows = session.execute(
        select(ImageModel.segment_id, ImageGPS.mode)
        .join(ImageGPS, ImageGPS.image_id == ImageModel.id)
        .where(
            ImageModel.device == device,
            ImageModel.date == date,
            ImageModel.deleted == False,
            ImageModel.segment_id.isnot(None),
            ImageGPS.mode.isnot(None),
        )
    ).all()
    by_seg: Dict[int, List[str]] = {}
    for seg_id, mode in rows:
        by_seg.setdefault(seg_id, []).append(mode)
    return {sid: Counter(ms).most_common(1)[0][0] for sid, ms in by_seg.items()}


def _render_day_context(session: Session, device: str, date: str) -> str:
    """Compact always-on context: the day's summary, places, and a one-line
    segment table (no per-segment descriptions — those are large and fetched on
    demand via get_segment_details, which keeps the per-turn prompt small)."""
    day = DaySummaryRecord.find_one({"device": device, "date": date})
    if not day:
        return f"No summary exists yet for {date}."
    modes = _segment_modes(session, device, date)
    lines = [f"Day {date} — {day.number_of_images} images."]
    if day.summary_text:
        lines.append(f"Current summary:\n{day.summary_text}")
    if day.location_visits:
        lines.append("Places:")
        for v in day.location_visits:
            name = v.location_name or "Unknown place"
            desc = f" — {v.description}" if v.description else ""
            lines.append(f"  [{name}] segments {v.segment_ids}{desc}")
    lines.append(
        "Segments (segment_id · activity · start–end (duration) · place · mode). "
        "Call get_segment_details for the photo descriptions of specific segments:"
    )
    for s in day.segments:
        start = s.start_time.strftime("%H:%M") if s.start_time else "?"
        end = s.end_time.strftime("%H:%M") if s.end_time else "?"
        mins = round((s.duration or 0) / 60)
        place = s.location_name or "-"
        mode = modes.get(s.segment_id or -1)
        mode_part = f" · {mode}" if mode else ""
        lines.append(
            f"  #{s.segment_id} · {s.activity} · {start}–{end} ({mins}m) · {place}{mode_part}"
        )
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
    session: Session, device: str, date: str, args: Dict[str, Any]
) -> str:
    segment_id = args.get("segment_id")
    label = (args.get("label") or "").strip()
    if segment_id is None or not label:
        return "Error: segment_id and label required."

    # Use the name to re-disambiguate the stop's venue (adopt a matching nearby
    # OSM POI, or mint a manual venue) rather than a cosmetic per-user label —
    # this propagates to visits, events grounding and the summary.
    from location.stop_correction import correct_stop_venue
    changed, message = correct_stop_venue(session, device, date, int(segment_id), label)
    if not changed:
        return message

    # Reassigning images changes segment location_name → the visit signature
    # changes on rebuild; clear it + mark text stale so the next fetch rebuilds
    # visits and summary text, and drop the stale geocoded caches.
    bust_day_caches(device, date)
    DaySummaryRecord.update_one(
        {"date": date, "device": device},
        data={"$set": {
            "location_visits_sig": None,
            "text_summary_stale": True,
            "updated": True,
        }},
    )
    return message + " The day's places will refresh shortly."


def upsert_memory(username: str, device: str, key: str, text: str) -> None:
    """Create or update one durable fact. Shared by the tool, auto-distillation,
    and the manual PUT /chat/memory endpoint."""
    filt = {"username": username, "device": device, "key": key}
    if ChatMemoryRecord.find_one(filt):
        ChatMemoryRecord.update_one(
            filt, data={"$set": {"text": text, "updated": datetime.utcnow()}}
        )
    else:
        ChatMemoryRecord(
            username=username, device=device, key=key, text=text,
            updated=datetime.utcnow(),
        ).create()


def _handle_get_segment_details(session: Session, device: str, date: str, args: Dict[str, Any]) -> str:
    """On-demand per-segment photo descriptions (+ mode), so the always-on
    context can stay small. The model calls this only for segments it cares about."""
    ids = args.get("segment_ids") or []
    if not isinstance(ids, list) or not ids:
        return "Error: segment_ids (a list) required."
    ids = [int(i) for i in ids][:20]
    descriptions = _segment_descriptions(session, device, date)
    modes = _segment_modes(session, device, date)
    lines = []
    for sid in ids:
        desc = descriptions.get(sid)
        mode = modes.get(sid)
        if desc or mode:
            extra = f" [{mode}]" if mode else ""
            lines.append(f"#{sid}{extra}: {desc or '(no description)'}")
        else:
            lines.append(f"#{sid}: (no details)")
    return "\n".join(lines)


def _search_lifelog(session: Session, device: str, query: str, k: int):
    """Semantic CLIP search over the whole lifelog (all days). Mirrors the
    text-query path of services.embedding.retrieve_image_with_filters."""
    from services.embedding import (
        apply_transformation,
        get_matrix,
        search_by_embedding,
        search_model,
    )
    emb = search_model.encode_text(query)
    emb = apply_transformation(emb, get_matrix(session, device))
    return search_by_embedding(session, emb, device, k, sort_by="relevance")


def _handle_search_lifelog(session: Session, device: str, args: Dict[str, Any]) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return "Error: query required."
    k = min(int(args.get("limit") or 8), 15)
    try:
        recs = _search_lifelog(session, device, query, k)
    except Exception as e:
        logger.exception("lifelog search failed")
        return f"Search failed: {e}"
    if not recs:
        return f"No moments matched '{query}'."
    lines = []
    for r in recs:
        d = getattr(r, "date", None) or "?"
        t = r.timestamp.strftime("%H:%M") if getattr(r, "timestamp", None) else "?"
        act = getattr(r, "activity", None) or ""
        desc = getattr(r, "activity_description", None) or ""
        lines.append(f"{d} {t} · {act}{(' · ' + desc) if desc else ''}")
    return f"Top matches for '{query}':\n" + "\n".join(lines)


def _handle_web_search(args: Dict[str, Any]) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return "Error: query required."
    try:
        res = openai_llm.web_search(query)
    except Exception as e:
        logger.exception("web search failed")
        return f"Web search failed: {e}"
    return res or "No web results."


def _handle_manage_memory(username: str, device: str, args: Dict[str, Any]) -> str:
    op = args.get("op")
    key = (args.get("key") or "").strip()
    text = (args.get("text") or "").strip()
    if not key:
        return "Error: key required."
    if op == "remove":
        ChatMemoryRecord.delete_many({"username": username, "device": device, "key": key})
        return f"Forgot '{key}'."
    if op in ("add", "update"):
        upsert_memory(username, device, key, text)
        return f"Remembered '{key}'."
    return f"Error: unknown op '{op}'."


def _handle_suggest_memory(args: Dict[str, Any]) -> str:
    """No write — the proposal surfaces in the UI as a one-tap Save chip."""
    key = (args.get("key") or "").strip()
    if not key:
        return "Error: key required."
    return f"Proposed to remember '{key}'."


_QUESTION_WORDS = {
    "what", "when", "where", "who", "whom", "whose", "why", "how", "which",
    "did", "do", "does", "is", "are", "was", "were", "can", "could", "would",
    "will", "should", "have", "has", "had",
}


def _worth_distilling(user_text: str) -> bool:
    """Skip turns unlikely to carry a durable fact — too short, or a bare
    question ("what did I eat?") with no declarative clause. A message that
    mixes a statement with a question ("Luca's my partner. What did we do?")
    still passes because it has more than one sentence."""
    t = user_text.strip()
    words = t.split()
    if len(words) < 4:
        return False
    # A single sentence opening with a question word is treated as a bare
    # question (the '?' is often dropped in chat) — nothing durable to keep.
    sentences = [s for s in re.split(r"[.!?]+", t) if s.strip()]
    if len(sentences) <= 1 and words[0].lower().strip(",") in _QUESTION_WORDS:
        return False
    return True


def maybe_distill(
    username: str, device: str, user_turn_count: int, recent_user_texts: List[str], reply: str
) -> List[ChatMemory]:
    """Run distillation only every _DISTILL_EVERY user turns (an extra LLM call
    per turn is the cost). When it fires it batches the recent user messages so
    facts from the skipped turns aren't lost."""
    if user_turn_count <= 0 or user_turn_count % _DISTILL_EVERY != 0:
        return []
    return distill_and_store(username, device, recent_user_texts, reply)


def distill_and_store(
    username: str, device: str, user_texts: List[str], reply: str
) -> List[ChatMemory]:
    """Ask the LLM for 0-3 durable facts across the recent user messages and
    silently upsert them. Returns the facts stored so the caller can surface them
    ('🧠 remembered …'). Obvious captures happen here; the bot uses suggest_memory
    for the rest."""
    worth = [t for t in user_texts if _worth_distilling(t)]
    if not reply or reply.startswith("⚠️") or not worth:
        return []
    existing = _load_memories(username, device)
    known = "; ".join(f"{m.key}: {m.text}" for m in existing) or "(none)"
    convo = "\n".join(f"User: {t}" for t in worth) + f"\nAssistant (latest reply): {reply}"
    prompt = (
        "From the recent messages below, extract 0-3 DURABLE personal facts worth "
        "remembering long-term: people and their relationship to the user, routines, "
        "stable preferences, custom place names. Ignore one-off/day-specific details, "
        "questions, and anything already known.\n"
        f"Already known: {known}\n"
        f"{convo}\n"
        'Return JSON: {"facts": [{"key": "short_snake_key", "text": "the fact"}]}. '
        "Empty list if nothing durable."
    )
    try:
        res = openai_llm.generate_from_text(prompt, parse_json=True)
    except Exception:
        logger.exception("memory distillation failed")
        return []
    facts = res.get("facts", []) if isinstance(res, dict) else []
    saved: List[ChatMemory] = []
    for f in facts[:3]:
        if not isinstance(f, dict):
            continue
        key = (f.get("key") or "").strip()
        text = (f.get("text") or "").strip()
        if not key or not text:
            continue
        upsert_memory(username, device, key, text)
        saved.append(ChatMemory(username=username, device=device, key=key, text=text))
    return saved


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

    # Only the last few turns go to the LLM — the full transcript is still stored
    # and shown in the UI, but resending it all every turn is the main token sink.
    recent = [
        {"role": m.role, "content": m.content}
        for m in history
        if m.role in ("user", "assistant") and m.content
    ][-_HISTORY_LIMIT:]
    messages: List[Dict[str, Any]] = recent
    messages.append({"role": "user", "content": user_text})

    applied: List[AppliedAction] = []

    def dispatch(name: str, args: Dict[str, Any]) -> str:
        try:
            if name == "edit_segment_activity":
                outcome = _handle_edit_segment_activity(session, device, date or "", args)
            elif name == "edit_day_summary_text":
                outcome = _handle_edit_day_summary_text(device, date or "", args)
            elif name == "change_location":
                outcome = _handle_change_location(session, device, date or "", args)
            elif name == "get_segment_details":
                outcome = _handle_get_segment_details(session, device, date or "", args)
            elif name == "search_lifelog":
                outcome = _handle_search_lifelog(session, device, args)
            elif name == "web_search":
                outcome = _handle_web_search(args)
            elif name == "manage_memory":
                outcome = _handle_manage_memory(username, device, args)
            elif name == "suggest_memory":
                outcome = _handle_suggest_memory(args)
            else:
                return f"Error: unknown tool '{name}'."
        except Exception as e:  # keep the loop alive; report failure to the model
            logger.exception("chat tool %s failed", name)
            outcome = f"Error running {name}: {e}"
        applied.append(AppliedAction(tool=name, args=args, outcome=outcome))
        return outcome

    return system, messages, applied, dispatch
