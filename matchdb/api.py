import logging
import math
import os
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from http.client import IncompleteRead
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .json_data import JsonObject, JsonValue, decode_json, require_object
from .models import Match

logger = logging.getLogger(__name__)


class OpenDotaClient:
    def __init__(self, interval: float = 1.2, retries: int | None = 4):
        if (
            not math.isfinite(interval)
            or interval < 0
            or (retries is not None and retries < 0)
        ):
            raise ValueError("Интервал и число повторов не могут быть отрицательными")
        self.interval = interval
        self.retries = retries
        self.last_request: float | None = None

    def _get(
        self, endpoint: str, params: tuple[tuple[str, int | str], ...] = ()
    ) -> str:
        query = urlencode(params)
        url = f"https://api.opendota.com/api/{endpoint}"
        if query:
            url += "?" + query
        request = Request(url)
        request.add_header("User-Agent", "opendota-local-analysis/0.1")
        if api_key := os.environ.get("OPENDOTA_API_KEY"):
            request.add_header("Authorization", f"Bearer {api_key}")
        attempt = 0
        rate_limits = 0
        while True:
            if self.last_request is not None:
                time.sleep(
                    max(0, self.interval - (time.monotonic() - self.last_request))
                )
            self.last_request = time.monotonic()
            try:
                with urlopen(request, timeout=30) as response:
                    return response.read().decode("utf-8")
            except HTTPError as error:
                retry_after = self.retry_after(error.headers.get("Retry-After"))
                code = error.code
                error.close()
                if code == 429:
                    delay = max(retry_after, min(60 * 2 ** min(rate_limits, 6), 3600))
                    rate_limits += 1
                    logger.warning(
                        "OpenDota: HTTP 429, ожидание %.0f с перед повтором %s",
                        delay,
                        endpoint,
                    )
                    time.sleep(delay)
                    continue
                if code not in {500, 502, 503, 504} or attempt == self.retries:
                    raise
                delay = max(min(2 ** min(attempt, 6), 60), retry_after)
            except URLError, TimeoutError, ConnectionError, IncompleteRead:
                if attempt == self.retries:
                    raise
                delay = min(2 ** min(attempt, 6), 60)
            logger.warning(
                "OpenDota: временная ошибка, повтор %s через %.0f с", endpoint, delay
            )
            time.sleep(delay)
            attempt += 1

    @staticmethod
    def retry_after(value: str | None) -> float:
        if value is None:
            return 0
        try:
            seconds = float(value)
            return max(0, seconds) if math.isfinite(seconds) else 0
        except ValueError:
            try:
                date = parsedate_to_datetime(value)
                return max(0, (date - datetime.now(UTC)).total_seconds())
            except ValueError, TypeError, OverflowError:
                return 0

    def public_matches(self, before: int | None = None) -> list[Match]:
        payload = self._get(
            "publicMatches",
            (("less_than_match_id", before),) if before is not None else (),
        )
        data = decode_json(payload)
        if not isinstance(data, list):
            raise ValueError("OpenDota вернул некорректный список матчей")
        return [Match.from_object(require_object(value)) for value in data]

    def match(self, match_id: int) -> Match:
        if match_id <= 0:
            raise ValueError("match_id должен быть положительным")
        data = Match.from_json(self._get(f"matches/{match_id}"))
        if data.match_id != match_id:
            raise ValueError(f"OpenDota не вернул данные матча {match_id}")
        return data

    def player_matches(self, account_id: int, offset: int = 0) -> list[Match]:
        if account_id <= 0 or offset < 0:
            raise ValueError("Некорректный аккаунт или смещение истории")
        payload = self._get(
            f"players/{account_id}/matches",
            (
                ("limit", 100),
                ("offset", offset),
                ("lobby_type", 7),
                ("significant", 0),
                ("sort", "start_time"),
            ),
        )
        data = decode_json(payload)
        if not isinstance(data, list):
            raise ValueError("OpenDota вернул некорректную историю игрока")
        matches = []
        for value in data:
            row = require_object(value)
            player = JsonObject(
                (
                    ("player_slot", row.value("player_slot")),
                    ("hero_id", row.value("hero_id")),
                    ("account_id", account_id),
                )
            )
            members: tuple[tuple[str, JsonValue], ...] = (("players", [player]),)
            matches.append(
                Match.from_object(
                    JsonObject(
                        tuple((k, v) for k, v in row.members if k != "players")
                        + members
                    )
                )
            )
        return matches
