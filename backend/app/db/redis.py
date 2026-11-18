from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Set, Tuple

from redis.asyncio import Redis

from app.core.config import settings

# Atomic Lua script executed in Redis on every GET /{short_code} (<0.5ms, zero DB hits).
# KEYS[1] = link:{short_code}
# KEYS[2] = analytics:buffer
# ARGV[1] = current unix timestamp (int)
# ARGV[2] = analytics JSON event string
# ARGV[3] = dead tombstone TTL (seconds, e.g. 900)
# Returns array: {status_tag, url_or_empty, link_id_or_empty}
REDIRECT_LUA_SCRIPT = """
local link_key = KEYS[1]
local buf_key = KEYS[2]
local now_ts = tonumber(ARGV[1])
local event_json = ARGV[2]
local dead_ttl = tonumber(ARGV[3])

if redis.call('EXISTS', link_key) == 0 then
    return {'MISS', '', ''}
end

local scan_status = redis.call('HGET', link_key, 'scan_status')
if scan_status == 'DEAD' then
    return {'DEAD', '', ''}
end

local expires_at = tonumber(redis.call('HGET', link_key, 'expires_at') or '0')
if expires_at > 0 and now_ts >= expires_at then
    redis.call('HSET', link_key, 'scan_status', 'DEAD')
    redis.call('EXPIRE', link_key, dead_ttl)
    return {'DEAD', '', ''}
end

if scan_status == 'PENDING' or scan_status == 'SCANNING' then
    return {'SCANNING', '', ''}
end

if scan_status ~= 'SAFE' then
    return {'DEAD', '', ''}
end

local url = redis.call('HGET', link_key, 'url') or ''
local link_id = redis.call('HGET', link_key, 'link_id') or ''
local remaining = tonumber(redis.call('HGET', link_key, 'remaining') or '-1')

if remaining == 0 then
    redis.call('HSET', link_key, 'scan_status', 'DEAD')
    redis.call('EXPIRE', link_key, dead_ttl)
    return {'DEAD', '', ''}
end

if remaining > 0 then
    local new_rem = remaining - 1
    redis.call('HSET', link_key, 'remaining', tostring(new_rem))
    if new_rem == 0 then
        redis.call('HSET', link_key, 'scan_status', 'DEAD')
        redis.call('EXPIRE', link_key, dead_ttl)
    end
end

redis.call('RPUSH', buf_key, link_id .. '|' .. event_json)
return {'REDIRECT', url, link_id}
"""


class InMemoryRedisEngine:
    """Thread/coroutine-safe in-memory Redis fallback executing identical Lua/atomic logic."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._strings: Dict[str, str] = {}
        self._hashes: Dict[str, Dict[str, str]] = {}
        self._lists: Dict[str, Deque[str]] = {}
        self._sets: Dict[str, Set[str]] = {}
        self._expiries: Dict[str, float] = {}

    def _purge_if_expired(self, key: str) -> None:
        exp = self._expiries.get(key)
        if exp is not None and time.time() >= exp:
            self._expiries.pop(key, None)
            self._strings.pop(key, None)
            self._hashes.pop(key, None)
            self._lists.pop(key, None)
            self._sets.pop(key, None)

    def _purge_all_expired(self) -> None:
        now = time.time()
        expired = [k for k, exp in self._expiries.items() if now >= exp]
        for k in expired:
            self._expiries.pop(k, None)
            self._strings.pop(k, None)
            self._hashes.pop(k, None)
            self._lists.pop(k, None)
            self._sets.pop(k, None)

    async def ping(self) -> bool:
        return True

    async def execute_redirect_lua(
        self,
        link_key: str,
        buf_key: str,
        now_ts: int,
        event_json: str,
        dead_ttl: int,
    ) -> Tuple[str, str, str]:
        async with self._lock:
            self._purge_if_expired(link_key)
            if link_key not in self._hashes:
                return ("MISS", "", "")

            h = self._hashes[link_key]
            scan_status = h.get("scan_status", "")
            if scan_status == "DEAD":
                return ("DEAD", "", "")

            expires_at = int(h.get("expires_at") or "0")
            if expires_at > 0 and now_ts >= expires_at:
                h["scan_status"] = "DEAD"
                self._expiries[link_key] = time.time() + dead_ttl
                return ("DEAD", "", "")

            if scan_status in ("PENDING", "SCANNING"):
                return ("SCANNING", "", "")

            if scan_status != "SAFE":
                return ("DEAD", "", "")

            url = h.get("url", "")
            link_id = h.get("link_id", "")
            remaining = int(h.get("remaining", "-1"))

            if remaining == 0:
                h["scan_status"] = "DEAD"
                self._expiries[link_key] = time.time() + dead_ttl
                return ("DEAD", "", "")

            if remaining > 0:
                new_rem = remaining - 1
                h["remaining"] = str(new_rem)
                if new_rem == 0:
                    h["scan_status"] = "DEAD"
                    self._expiries[link_key] = time.time() + dead_ttl

            lst = self._lists.setdefault(buf_key, deque())
            lst.append(f"{link_id}|{event_json}")
            return ("REDIRECT", url, link_id)

    async def hset(self, key: str, mapping: Dict[str, Any], ttl: Optional[int] = None) -> None:
        async with self._lock:
            self._purge_if_expired(key)
            target = self._hashes.setdefault(key, {})
            for k, v in mapping.items():
                target[str(k)] = str(v)
            if ttl is not None and ttl > 0:
                self._expiries[key] = time.time() + ttl
            elif ttl is None and key not in self._expiries:
                pass

    async def hgetall(self, key: str) -> Dict[str, str]:
        async with self._lock:
            self._purge_if_expired(key)
            return dict(self._hashes.get(key, {}))

    async def delete(self, *keys: str) -> int:
        async with self._lock:
            deleted = 0
            for key in keys:
                existed = (
                    key in self._strings
                    or key in self._hashes
                    or key in self._lists
                    or key in self._sets
                )
                self._strings.pop(key, None)
                self._hashes.pop(key, None)
                self._lists.pop(key, None)
                self._sets.pop(key, None)
                self._expiries.pop(key, None)
                if existed:
                    deleted += 1
            return deleted

    async def set_str(self, key: str, value: str, ttl: Optional[int] = None, nx: bool = False) -> bool:
        async with self._lock:
            self._purge_if_expired(key)
            if nx and key in self._strings:
                return False
            self._strings[key] = value
            if ttl is not None and ttl > 0:
                self._expiries[key] = time.time() + ttl
            else:
                self._expiries.pop(key, None)
            return True

    async def get_str(self, key: str) -> Optional[str]:
        async with self._lock:
            self._purge_if_expired(key)
            return self._strings.get(key)

    async def incr_with_window(self, key: str, window_seconds: int) -> int:
        async with self._lock:
            self._purge_if_expired(key)
            cur = int(self._strings.get(key, "0")) + 1
            self._strings[key] = str(cur)
            if key not in self._expiries:
                self._expiries[key] = time.time() + window_seconds
            return cur

    async def lpush(self, key: str, value: str) -> int:
        async with self._lock:
            self._purge_if_expired(key)
            lst = self._lists.setdefault(key, deque())
            lst.appendleft(value)
            return len(lst)

    async def rpush(self, key: str, value: str) -> int:
        async with self._lock:
            self._purge_if_expired(key)
            lst = self._lists.setdefault(key, deque())
            lst.append(value)
            return len(lst)

    async def lpop_batch(self, key: str, count: int) -> List[str]:
        async with self._lock:
            self._purge_if_expired(key)
            lst = self._lists.get(key)
            if not lst:
                return []
            items: List[str] = []
            for _ in range(min(count, len(lst))):
                items.append(lst.popleft())
            return items

    async def llen(self, key: str) -> int:
        async with self._lock:
            self._purge_if_expired(key)
            return len(self._lists.get(key, ()))

    async def sadd(self, key: str, *values: str) -> int:
        async with self._lock:
            self._purge_if_expired(key)
            s = self._sets.setdefault(key, set())
            before = len(s)
            s.update(values)
            return len(s) - before

    async def srem(self, key: str, *values: str) -> int:
        async with self._lock:
            self._purge_if_expired(key)
            s = self._sets.get(key)
            if not s:
                return 0
            before = len(s)
            s.difference_update(values)
            return before - len(s)

    async def sismember(self, key: str, value: str) -> bool:
        async with self._lock:
            self._purge_if_expired(key)
            return value in self._sets.get(key, set())

    async def delete_by_prefix(self, prefix: str) -> int:
        async with self._lock:
            self._purge_all_expired()
            targets = [
                k
                for k in (
                    set(self._strings)
                    | set(self._hashes)
                    | set(self._lists)
                    | set(self._sets)
                )
                if k.startswith(prefix)
            ]
            for k in targets:
                self._strings.pop(k, None)
                self._hashes.pop(k, None)
                self._lists.pop(k, None)
                self._sets.pop(k, None)
                self._expiries.pop(k, None)
            return len(targets)

    async def stats(self) -> Dict[str, Any]:
        async with self._lock:
            self._purge_all_expired()
            total_keys = len(
                set(self._strings) | set(self._hashes) | set(self._lists) | set(self._sets)
            )
            return {
                "mode": "in-memory-fallback",
                "connected": True,
                "keys": total_keys,
                "used_memory_human": "in-memory",
            }


class RedisStore:
    """Unified Redis store supporting real Redis (with Lua) and local memory fallback."""

    def __init__(self) -> None:
        self._client: Optional[Redis] = None
        self._lua_sha: Optional[str] = None
        self._memory = InMemoryRedisEngine()
        self._using_memory = False

    async def connect(self) -> None:
        if settings.allow_memory_fallback and settings.environment == "test":
            self._using_memory = True
            return

        client = Redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=1.5,
            socket_timeout=2.0,
        )
        try:
            await client.ping()
            self._client = client
            self._lua_sha = await client.script_load(REDIRECT_LUA_SCRIPT)
            self._using_memory = False
        except Exception:
            await client.aclose()
            if settings.allow_memory_fallback:
                self._client = None
                self._using_memory = True
            else:
                raise

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def reset_memory_for_tests(self) -> None:
        self._memory = InMemoryRedisEngine()
        self._using_memory = True
        self._client = None

    @property
    def is_memory_mode(self) -> bool:
        return self._using_memory or self._client is None

    async def ping(self) -> bool:
        if self.is_memory_mode:
            return await self._memory.ping()
        try:
            return bool(await self._client.ping())  # type: ignore[union-attr]
        except Exception:
            return False

    async def execute_redirect_lua(
        self,
        short_code: str,
        event_payload: Dict[str, Any],
        dead_ttl: int = 900,
    ) -> Tuple[str, str, str]:
        link_key = f"link:{short_code}"
        buf_key = "analytics:buffer"
        now_ts = int(time.time())
        event_json = json.dumps(event_payload, separators=(",", ":"))

        if self.is_memory_mode:
            return await self._memory.execute_redirect_lua(
                link_key, buf_key, now_ts, event_json, dead_ttl
            )

        assert self._client is not None
        try:
            if not self._lua_sha:
                self._lua_sha = await self._client.script_load(REDIRECT_LUA_SCRIPT)
            res = await self._client.evalsha(
                self._lua_sha,
                2,
                link_key,
                buf_key,
                str(now_ts),
                event_json,
                str(dead_ttl),
            )
        except Exception:
            res = await self._client.eval(
                REDIRECT_LUA_SCRIPT,
                2,
                link_key,
                buf_key,
                str(now_ts),
                event_json,
                str(dead_ttl),
            )
        return (str(res[0]), str(res[1]), str(res[2]))

    async def hset(self, key: str, mapping: Dict[str, Any], ttl: Optional[int] = None) -> None:
        if self.is_memory_mode:
            await self._memory.hset(key, mapping, ttl=ttl)
            return
        assert self._client is not None
        str_map = {str(k): str(v) for k, v in mapping.items()}
        await self._client.hset(key, mapping=str_map)
        if ttl is not None and ttl > 0:
            await self._client.expire(key, ttl)

    async def hgetall(self, key: str) -> Dict[str, str]:
        if self.is_memory_mode:
            return await self._memory.hgetall(key)
        assert self._client is not None
        return await self._client.hgetall(key)

    async def delete(self, *keys: str) -> int:
        if not keys:
            return 0
        if self.is_memory_mode:
            return await self._memory.delete(*keys)
        assert self._client is not None
        return int(await self._client.delete(*keys))

    async def set_str(self, key: str, value: str, ttl: Optional[int] = None, nx: bool = False) -> bool:
        if self.is_memory_mode:
            return await self._memory.set_str(key, value, ttl=ttl, nx=nx)
        assert self._client is not None
        res = await self._client.set(key, value, ex=ttl, nx=nx)
        return bool(res)

    async def get_str(self, key: str) -> Optional[str]:
        if self.is_memory_mode:
            return await self._memory.get_str(key)
        assert self._client is not None
        return await self._client.get(key)

    async def incr_with_window(self, key: str, window_seconds: int) -> int:
        if self.is_memory_mode:
            return await self._memory.incr_with_window(key, window_seconds)
        assert self._client is not None
        val = await self._client.incr(key)
        if val == 1:
            await self._client.expire(key, window_seconds)
        return int(val)

    async def lpush(self, key: str, value: str) -> int:
        if self.is_memory_mode:
            return await self._memory.lpush(key, value)
        assert self._client is not None
        return int(await self._client.lpush(key, value))

    async def rpush(self, key: str, value: str) -> int:
        if self.is_memory_mode:
            return await self._memory.rpush(key, value)
        assert self._client is not None
        return int(await self._client.rpush(key, value))

    async def lpop_batch(self, key: str, count: int) -> List[str]:
        if self.is_memory_mode:
            return await self._memory.lpop_batch(key, count)
        assert self._client is not None
        pipe = self._client.pipeline()
        pipe.lrange(key, 0, count - 1)
        pipe.ltrim(key, count, -1)
        items, _ = await pipe.execute()
        return list(items or [])

    async def llen(self, key: str) -> int:
        if self.is_memory_mode:
            return await self._memory.llen(key)
        assert self._client is not None
        return int(await self._client.llen(key))

    async def sadd(self, key: str, *values: str) -> int:
        if not values:
            return 0
        if self.is_memory_mode:
            return await self._memory.sadd(key, *values)
        assert self._client is not None
        return int(await self._client.sadd(key, *values))

    async def srem(self, key: str, *values: str) -> int:
        if not values:
            return 0
        if self.is_memory_mode:
            return await self._memory.srem(key, *values)
        assert self._client is not None
        return int(await self._client.srem(key, *values))

    async def sismember(self, key: str, value: str) -> bool:
        if self.is_memory_mode:
            return await self._memory.sismember(key, value)
        assert self._client is not None
        return bool(await self._client.sismember(key, value))

    async def delete_by_prefix(self, prefix: str) -> int:
        if self.is_memory_mode:
            return await self._memory.delete_by_prefix(prefix)
        assert self._client is not None
        deleted = 0
        batch: List[str] = []
        async for key in self._client.scan_iter(match=f"{prefix}*", count=200):
            batch.append(key)
            if len(batch) >= 200:
                deleted += int(await self._client.delete(*batch))
                batch.clear()
        if batch:
            deleted += int(await self._client.delete(*batch))
        return deleted

    async def get_json(self, key: str) -> Optional[Any]:
        raw = await self.get_str(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    async def set_json(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        await self.set_str(key, json.dumps(value, default=str), ttl=ttl)

    async def info_stats(self) -> Dict[str, Any]:
        if self.is_memory_mode:
            return await self._memory.stats()
        assert self._client is not None
        try:
            mem_info = await self._client.info("memory")
            dbsize = await self._client.dbsize()
            return {
                "mode": "redis",
                "connected": True,
                "keys": int(dbsize),
                "used_memory_human": mem_info.get("used_memory_human", "unknown"),
            }
        except Exception:
            return {"mode": "redis", "connected": False, "keys": 0, "used_memory_human": "n/a"}


redis_store = RedisStore()
