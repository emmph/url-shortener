from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy import case, insert, update

from app.core.config import settings
from app.db import session as db_session
from app.db.redis import redis_store
from app.models.click_event import ClickEvent
from app.models.link import Link

logger = logging.getLogger(__name__)
ANALYTICS_BUFFER_KEY = "analytics:buffer"


async def flush_analytics_batch(batch_size: int = 500) -> int:
    """Drain up to `batch_size` click events from Redis and flush to DB in one transaction."""
    # Pop buffered click events from Redis
    raw_items = await redis_store.lpop_batch(ANALYTICS_BUFFER_KEY, batch_size)
    if not raw_items:
        return 0

    events_to_insert: List[Dict[str, Any]] = []
    clicks_by_link: Dict[int, int] = defaultdict(int)

    for raw in raw_items:
        try:
            prefix_link_id = 0
            json_str = raw
            # Unpack "link_id|{json}" pushed by Lua script
            if "|" in raw:
                head, tail = raw.split("|", 1)
                if head.isdigit():
                    prefix_link_id = int(head)
                    json_str = tail
            data = json.loads(json_str)
            link_id = prefix_link_id or int(data.get("link_id") or 0)
            if link_id <= 0:
                continue
            ts_val = float(data.get("ts") or datetime.now(timezone.utc).timestamp())
            clicked_at = datetime.fromtimestamp(ts_val, tz=timezone.utc)
            clicks_by_link[link_id] += 1
            events_to_insert.append(
                {
                    "link_id": link_id,
                    "clicked_at": clicked_at,
                    "ip_hash": str(data.get("ip_hash") or "anon")[:32],
                    "device_type": str(data.get("dev") or "unknown")[:16],
                    "browser": str(data.get("br") or "Other")[:32],
                    "referer": (str(data["ref"])[:255] if data.get("ref") else None),
                }
            )
        except Exception:
            continue

    if not events_to_insert:
        return 0

    # Flush click rows and counter increments in a single DB transaction
    async with db_session.AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(insert(ClickEvent), events_to_insert)

            for link_id, delta in clicks_by_link.items():
                stmt = (
                    update(Link)
                    .where(Link.id == link_id)
                    .values(
                        clicks_count=Link.clicks_count + delta,
                        is_active=case(
                            (
                                (Link.max_clicks.is_not(None)) & (Link.clicks_count + delta >= Link.max_clicks),
                                False,
                            ),
                            else_=Link.is_active,
                        ),
                    )
                )
                await session.execute(stmt)

    return len(events_to_insert)


async def run_analytics_flusher_loop(stop_event: asyncio.Event) -> None:
    """Background coroutine flushing buffered clicks every N seconds."""
    while not stop_event.is_set():
        try:
            await flush_analytics_batch(settings.analytics_batch_size)
        except Exception as exc:
            logger.warning("analytics_flusher error: %s", exc)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.analytics_flush_interval)
        except asyncio.TimeoutError:
            pass

    # Drain remaining clicks on graceful shutdown
    try:
        while await flush_analytics_batch(settings.analytics_batch_size) > 0:
            pass
    except Exception as exc:
        logger.warning("analytics_flusher shutdown drain error: %s", exc)
