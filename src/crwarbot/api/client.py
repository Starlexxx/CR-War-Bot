from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from crwarbot.api.models import Clan, CurrentRiverRace, RiverRaceLog
from crwarbot.api.rate_limiter import RateLimiter


class ApiError(Exception):
    pass


class NotFound(ApiError):
    pass


class _RetryableHttpError(ApiError):
    pass


def normalize_tag(tag: str) -> str:
    t = tag.strip().upper()
    if not t.startswith("#"):
        t = "#" + t
    return t


def _encode_tag(tag: str) -> str:
    return quote(normalize_tag(tag), safe="")


class SupercellClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        rate_limiter: RateLimiter | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._rl = rate_limiter or RateLimiter(rate_per_sec=5, max_concurrent=3)
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict | list:
        url = f"{self._base}{path}"

        async for attempt in AsyncRetrying(
            retry=retry_if_exception_type(_RetryableHttpError),
            stop=stop_after_attempt(4),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            reraise=True,
        ):
            with attempt:
                async with self._rl:
                    resp = await self._client.request(method, url, **kwargs)
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code == 404:
                    raise NotFound(f"{method} {path} -> 404")
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise _RetryableHttpError(f"{method} {path} -> {resp.status_code}")
                raise ApiError(f"{method} {path} -> {resp.status_code}: {resp.text}")
        raise ApiError("retry loop exited without value")  # pragma: no cover

    async def get_clan(self, tag: str) -> Clan:
        data = await self._request("GET", f"/clans/{_encode_tag(tag)}")
        return Clan.model_validate(data)

    async def get_current_river_race(self, tag: str) -> CurrentRiverRace:
        data = await self._request("GET", f"/clans/{_encode_tag(tag)}/currentriverrace")
        return CurrentRiverRace.model_validate(data)

    async def get_river_race_log(self, tag: str, limit: int = 20) -> RiverRaceLog:
        data = await self._request(
            "GET",
            f"/clans/{_encode_tag(tag)}/riverracelog",
            params={"limit": limit},
        )
        return RiverRaceLog.model_validate(data)
