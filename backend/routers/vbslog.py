"""VBS interaction logging.

Persists VBS-format (inter-)action events to the `vbs_log` Postgres table and
DRES answer submissions to `dres_submission`, one row per item. Logging is gated
on the frontend (a toggle) — these endpoints just store what the client sends.
The client is identified by IP (server-side), so no team/member IDs are needed.
"""
import logging
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.dependencies import client_ip
from database import get_session
from database.models import DresSubmission, VBSLog

logger = logging.getLogger(__name__)

router = APIRouter()


class VBSEvent(BaseModel):
    timestamp: int  # UNIX ms, when the action took place (client clock)
    category: str  # text | image | sketch | filter | browsing | cooperation
    type: Optional[str] = None  # employed model/method, e.g. jointEmbedding
    value: Optional[str] = None  # query text or browsing action


class VBSLogBatch(BaseModel):
    # DRES task context for per-task attribution during analysis.
    evaluationId: Optional[str] = None
    taskName: Optional[str] = None
    events: List[VBSEvent]


@router.post("/event")
def log_events(
    batch: VBSLogBatch,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
):
    """Insert one row per event. Returns count written."""
    received = int(datetime.now(timezone.utc).timestamp() * 1000)
    ip = client_ip(request)
    rows = [
        VBSLog(
            received=received,  # server clock, for shift/latency analysis
            event_ts=ev.timestamp,
            client_ip=ip,
            evaluation_id=batch.evaluationId,
            task_name=batch.taskName,
            category=ev.category,
            type=ev.type,
            value=ev.value,
        )
        for ev in batch.events
    ]
    session.add_all(rows)
    session.commit()
    logger.info("VBS log: wrote %d event(s)", len(rows))
    return {"written": len(rows)}


class SubmissionBody(BaseModel):
    submittedAt: Optional[int] = None  # client clock ms; server fills if absent
    evaluationId: Optional[str] = None
    taskName: Optional[str] = None
    contentType: str  # image | text
    content: Optional[str] = None
    verdict: Optional[str] = None  # CORRECT | INCORRECT | INVALID | ...


@router.post("/submission")
def log_submission(
    body: SubmissionBody,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
):
    """Record a DRES submission + verdict for later query→find analysis."""
    submitted_at = body.submittedAt or int(datetime.now(timezone.utc).timestamp() * 1000)
    row = DresSubmission(
        submitted_at=submitted_at,
        client_ip=client_ip(request),
        evaluation_id=body.evaluationId,
        task_name=body.taskName,
        content_type=body.contentType,
        content=body.content,
        verdict=body.verdict,
    )
    session.add(row)
    session.commit()
    return {"ok": True}


_PAGE_RE = re.compile(r"(\d+)")


@router.get("/stats")
def stats(
    session: Annotated[Session, Depends(get_session)],
    evaluation_id: Optional[str] = Query(None),
    client_ip: Optional[str] = Query(None),
):
    """Rollups over logged events. Optionally scope to an evaluation/client.

    Returns overall counts plus a per-task breakdown (action funnel, modality
    mix, browse depth, session span, query→find time) and the mean client/server
    clock shift. Query→find joins the first CORRECT DRES submission per task
    against the task's first logged event.
    """
    stmt = select(VBSLog)
    if evaluation_id is not None:
        stmt = stmt.where(VBSLog.evaluation_id == evaluation_id)
    if client_ip is not None:
        stmt = stmt.where(VBSLog.client_ip == client_ip)
    rows = session.execute(stmt).scalars().all()

    # First CORRECT submission time per (evaluation_id, task_name).
    sub_stmt = select(DresSubmission).where(DresSubmission.verdict == "CORRECT")
    if evaluation_id is not None:
        sub_stmt = sub_stmt.where(DresSubmission.evaluation_id == evaluation_id)
    if client_ip is not None:
        sub_stmt = sub_stmt.where(DresSubmission.client_ip == client_ip)
    correct_at: dict = {}
    for s in session.execute(sub_stmt).scalars().all():
        key = (s.evaluation_id, s.task_name)
        prev = correct_at.get(key)
        if prev is None or s.submitted_at < prev:
            correct_at[key] = s.submitted_at

    by_category: Counter = Counter()
    by_type: Counter = Counter()
    shift_sum = 0  # received - event_ts, ms
    tasks: dict = defaultdict(lambda: {
        "evaluationId": None,
        "taskName": None,
        "events": 0,
        "firstEvent": None,
        "lastEvent": None,
        "textQueries": 0,
        "imageQueries": 0,
        "filters": 0,
        "browseActions": 0,
        "maxPage": 0,
    })

    for r in rows:
        by_category[r.category] += 1
        if r.type:
            by_type[r.type] += 1
        shift_sum += r.received - r.event_ts

        key = (r.evaluation_id, r.task_name)
        t = tasks[key]
        t["evaluationId"] = r.evaluation_id
        t["taskName"] = r.task_name
        t["events"] += 1
        t["firstEvent"] = r.event_ts if t["firstEvent"] is None else min(t["firstEvent"], r.event_ts)
        t["lastEvent"] = r.event_ts if t["lastEvent"] is None else max(t["lastEvent"], r.event_ts)
        if r.category == "text":
            t["textQueries"] += 1
        elif r.category == "image":
            t["imageQueries"] += 1
        elif r.category == "filter":
            t["filters"] += 1
        elif r.category == "browsing":
            t["browseActions"] += 1
            if r.type == "rankedList" and r.value:
                m = _PAGE_RE.search(r.value)
                if m:
                    t["maxPage"] = max(t["maxPage"], int(m.group(1)))

    by_task = []
    for key, t in tasks.items():
        span = (
            t["lastEvent"] - t["firstEvent"]
            if t["firstEvent"] is not None and t["lastEvent"] is not None
            else 0
        )
        correct = correct_at.get(key)
        find_ms = (
            correct - t["firstEvent"]
            if correct is not None and t["firstEvent"] is not None
            else None
        )
        by_task.append({
            **t,
            "durationMs": span,
            "correctAt": correct,
            "findTimeMs": find_ms,  # first event → first CORRECT submission
            "solved": correct is not None,
        })
    by_task.sort(key=lambda x: (x["firstEvent"] or 0))

    total = len(rows)
    return {
        "total": total,
        "byCategory": dict(by_category),
        "byType": dict(by_type),
        "clockShiftMs": round(shift_sum / total, 1) if total else 0,
        "byTask": by_task,
    }
