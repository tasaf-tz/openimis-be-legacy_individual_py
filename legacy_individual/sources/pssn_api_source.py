"""HTTP source for the legacy PSSN ``combined_household_members.php`` endpoint.

See docs/LEGACY_API_ETL_CODE_RATIONALE.md.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Generator, Optional

import requests
from requests.adapters import HTTPAdapter

try:
    from urllib3.util.retry import Retry
except Exception:  # pragma: no cover
    Retry = None

logger = logging.getLogger(__name__)


def _cfg(config, name, default=None):
    if config is None:
        return default
    if isinstance(config, dict):
        val = config.get(name, default)
    else:
        val = getattr(config, name, default)
    return default if val in (None, "") else val


class LegacyPssnApiSource:
    class Error(Exception):
        pass

    def __init__(self, config=None, session: Optional[requests.Session] = None):
        if config is None:
            from legacy_individual.apps import LegacyIndividualConfig

            config = LegacyIndividualConfig
        self.config = config

        self.base_url = str(_cfg(config, "legacy_api_base_url", "")).rstrip("/")
        self.path = str(
            _cfg(config, "legacy_api_path", "/livePSSN/api/etlapi/combined_household_members.php")
        )
        self.page_size = int(_cfg(config, "legacy_api_page_size", 500))
        self.max_pages = int(_cfg(config, "legacy_api_max_pages", 1000))
        self.connect_timeout = float(_cfg(config, "legacy_api_connect_timeout", 5))
        self.read_timeout = float(_cfg(config, "legacy_api_read_timeout", 60))
        self.retries = int(_cfg(config, "legacy_api_retries", 3))

        self.session = session or self._build_session()

    def _build_session(self) -> requests.Session:
        sess = requests.Session()
        if Retry is not None and self.retries > 0:
            retry_kwargs = dict(
                total=self.retries,
                connect=self.retries,
                read=self.retries,
                backoff_factor=2,
                status_forcelist=[502, 503, 504],
                raise_on_status=False,
            )
            try:
                retry = Retry(allowed_methods=frozenset(["GET"]), **retry_kwargs)
            except TypeError:
                retry = Retry(method_whitelist=frozenset(["GET"]), **retry_kwargs)
            adapter = HTTPAdapter(max_retries=retry)
            sess.mount("http://", adapter)
            sess.mount("https://", adapter)

        self._apply_auth(sess)
        sess.headers.setdefault("Accept", "application/json")
        return sess

    def _apply_auth(self, sess: requests.Session) -> None:
        auth_type = str(_cfg(self.config, "legacy_api_auth_type", "none")).lower()
        if auth_type == "basic":
            user = _cfg(self.config, "legacy_api_username", "")
            pwd = _cfg(self.config, "legacy_api_password", "")
            if user or pwd:
                sess.auth = requests.auth.HTTPBasicAuth(user or "", pwd or "")
        elif auth_type == "bearer":
            token = _cfg(self.config, "legacy_api_bearer_token", "")
            if token:
                sess.headers["Authorization"] = f"Bearer {token}"

    @property
    def url(self) -> str:
        if not self.base_url:
            raise self.Error("legacy_api_base_url is not configured")
        return f"{self.base_url}{self.path}"

    def fetch_page(self, district_code: str, page: int) -> Dict[str, Any]:
        params = {
            "district_code": district_code,
            "page": page,
            "per_page": self.page_size,
        }
        try:
            resp = self.session.get(
                self.url,
                params=params,
                timeout=(self.connect_timeout, self.read_timeout),
            )
        except requests.RequestException as exc:
            raise self.Error(f"Request to legacy PSSN API failed: {exc}") from exc

        if resp.status_code != 200:
            raise self.Error(
                f"Legacy PSSN API returned HTTP {resp.status_code} for "
                f"district {district_code} page {page}"
            )

        try:
            payload = resp.json()
        except ValueError as exc:
            raise self.Error(
                f"Legacy PSSN API returned non-JSON for district {district_code} "
                f"page {page}"
            ) from exc

        if not isinstance(payload, dict):
            raise self.Error("Legacy PSSN API payload is not a JSON object")
        if payload.get("success") is False:
            raise self.Error(
                f"Legacy PSSN API reported success=false for district {district_code}: "
                f"{payload.get('message') or payload.get('error') or 'no detail'}"
            )
        if not isinstance(payload.get("data"), list):
            raise self.Error("Legacy PSSN API payload has no 'data' array")
        return payload

    def pull(self, district_code: str) -> Generator[Dict[str, Any], None, None]:
        if not district_code:
            raise self.Error("district_code is required")

        page = 1
        while page <= self.max_pages:
            payload = self.fetch_page(district_code, page)
            rows = payload.get("data") or []
            returned = payload.get("records_returned", len(rows))
            logger.info(
                "Legacy PSSN API: district=%s page=%s rows=%s",
                district_code,
                page,
                len(rows),
            )
            for row in rows:
                if isinstance(row, dict):
                    yield row

            if not rows or (isinstance(returned, int) and returned < self.page_size):
                return
            page += 1

        logger.warning(
            "Legacy PSSN API: hit max_pages=%s for district=%s; stopping early",
            self.max_pages,
            district_code,
        )
