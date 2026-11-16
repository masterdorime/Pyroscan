"""The provider gateway: cache-first reads, TTL, refresh, status derivation."""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path

from . import cache
from .base import Extent, Provider, ProviderConfig, ProviderError, ProviderResult
from .cache import Derived, derive, read_envelope, write_envelope
from .config import load as load_config
from .registry import build_registry


def _iso(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class Gateway:
    """The only thing the API calls. Adapters know nothing about the cache."""

    def __init__(self, registry: dict[str, tuple[Provider, ...]],
                 cfg: ProviderConfig, *, root: Path | None = None,
                 now_fn=None) -> None:
        self.registry = registry
        self.cfg = cfg
        self.root = root
        self._now = now_fn or (lambda: datetime.now(timezone.utc))
        self._lock = threading.Lock()
        self._inflight: set[tuple[str, str]] = set()

    # -- helpers ---------------------------------------------------------
    def _ttl(self, adapter: Provider) -> int:
        return int(self.cfg.ttl_overrides.get(adapter.key, adapter.ttl_s))

    def _claim(self, pair: tuple[str, str]) -> bool:
        with self._lock:
            if pair in self._inflight:
                return False
            self._inflight.add(pair)
            return True

    def _release(self, pair: tuple[str, str]) -> None:
        with self._lock:
            self._inflight.discard(pair)

    def _envelope(self, key: str, adapter: Provider, observed_at: str | None,
                  data: dict, *, fail_count: int = 0,
                  last_error: str | None = None,
                  last_error_kind: str | None = None,
                  previous: dict | None = None) -> dict:
        now = _iso(self._now())
        env = {
            "schema": 1,
            "key": key,
            "provider": adapter.id,
            "source_label": adapter.source_label,
            "licence": adapter.licence,
            "attribution": adapter.attribution,
            "fetched_at": now if last_error is None else (previous or {}).get("fetched_at"),
            "observed_at": observed_at if last_error is None else (previous or {}).get("observed_at"),
            "last_attempt_at": now,
            "last_error": last_error,
            "last_error_kind": last_error_kind,
            "fail_count": fail_count,
            "data": data,
        }
        return env

    def _result(self, key: str, adapter: Provider, env: dict | None,
                derived: Derived) -> ProviderResult:
        env = env or {}
        return ProviderResult(
            key=key,
            data=env.get("data"),
            source=env.get("provider") or adapter.id,
            source_label=env.get("source_label") or adapter.source_label,
            observed_at=env.get("observed_at"),
            fetched_at=env.get("fetched_at"),
            age_s=derived.age_s,
            ttl_s=self._ttl(adapter),
            status=derived.status,
            reason=derived.reason,
            error=env.get("last_error") if derived.status in ("error", "offline") else None,
            licence=adapter.licence,
            attribution=adapter.attribution,
            simulated=False,
            configured=True,
            fallback_from=None,
        )

    # -- refresh ---------------------------------------------------------
    def _configured(self, adapter: Provider) -> bool:
        return all(getattr(self.cfg, req, None) for req in adapter.requires)

    def _missing_requirement(self, adapter: Provider) -> str:
        for req in adapter.requires:
            if not getattr(self.cfg, req, None):
                return f"{req}_missing"
        return "not_configured"

    def _unconfigured(self, key: str, adapter: Provider) -> ProviderResult:
        return ProviderResult(
            key=key, data=None, source=adapter.id,
            source_label=adapter.source_label, observed_at=None, fetched_at=None,
            age_s=None, ttl_s=self._ttl(adapter), status="unconfigured",
            reason=self._missing_requirement(adapter), error=None,
            licence=adapter.licence, attribution=adapter.attribution,
            simulated=False, configured=False, fallback_from=None,
        )

    def _fixture(self, key: str) -> dict | None:
        path = cache.FIXTURES / key / "fallback.json"
        try:
            import json
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    def _fixture_result(self, key: str, adapter: Provider) -> ProviderResult:
        return ProviderResult(
            key=key, data=self._fixture(key), source="fixture",
            source_label=adapter.source_label, observed_at=None, fetched_at=None,
            age_s=None, ttl_s=self._ttl(adapter), status="error",
            reason="fixture_fallback", error=None, licence=adapter.licence,
            attribution=adapter.attribution, simulated=True, configured=True,
            fallback_from=None,
        )

    def _do_refresh(self, mission_id: str, key: str, extent: Extent) -> ProviderResult:
        chain = self.registry[key]
        previous = read_envelope(mission_id, key, root=self.root)
        failures = 0
        attempted = 0
        last_error: ProviderError | None = None
        failed_ids: list[str] = []

        for adapter in chain:
            if not self._configured(adapter):
                continue
            attempted += 1
            try:
                payload = adapter.fetch(extent, self.cfg)
            except ProviderError as exc:
                failures += 1
                last_error = exc
                failed_ids.append(adapter.id)
                continue
            env = self._envelope(key, adapter, payload.observed_at, payload.data,
                                 fail_count=failures)
            write_envelope(mission_id, key, env, root=self.root)
            result = self._result(key, adapter, env,
                                  derive(env, self._ttl(adapter), now=self._now()))
            if failures and failed_ids:
                result.fallback_from = failed_ids[0]
            return result

        primary = chain[0]
        if attempted == 0:
            return self._unconfigured(key, primary)

        # Every attempt failed. Keep the last good data and mark it offline, but
        # only when there is something to mark: with no cache we must not write a
        # file, or the fixture result would be cached as if it were provider data.
        if previous is not None:
            env = self._envelope(key, primary, None,
                                 previous.get("data") or {},
                                 fail_count=int(previous.get("fail_count") or 0) + 1,
                                 last_error=(last_error.detail if last_error else "unknown"),
                                 last_error_kind=(last_error.kind if last_error else None),
                                 previous=previous)
            write_envelope(mission_id, key, env, root=self.root)
            result = self._result(key, primary, env,
                                  derive(env, self._ttl(primary), now=self._now()))
            result.fallback_from = failed_ids[0] if len(failed_ids) > 1 else None
            return result

        if self._fixture(key) is not None:
            return self._fixture_result(key, primary)

        return ProviderResult(
            key=key, data=None, source=primary.id,
            source_label=primary.source_label, observed_at=None, fetched_at=None,
            age_s=None, ttl_s=self._ttl(primary), status="error",
            reason=(last_error.detail if last_error else "never_fetched"),
            error=(last_error.detail if last_error else None),
            licence=primary.licence, attribution=primary.attribution,
            simulated=False, configured=True, fallback_from=None,
        )

    def refresh_now(self, mission_id: str, key: str, extent: Extent) -> ProviderResult:
        pair = (mission_id, key)
        if not self._claim(pair):
            return self.get(mission_id, key, extent, allow_fetch=False)
        try:
            return self._do_refresh(mission_id, key, extent)
        finally:
            self._release(pair)

    def refresh_async(self, background, mission_id: str, key: str,
                      extent: Extent) -> None:
        pair = (mission_id, key)
        if background is None or not self._claim(pair):
            return
        background.add_task(self._background_refresh, mission_id, key, extent)

    def _background_refresh(self, mission_id: str, key: str, extent: Extent) -> None:
        try:
            self._do_refresh(mission_id, key, extent)
        finally:
            self._release((mission_id, key))

    # -- reads -----------------------------------------------------------
    def _warm(self, mission_id: str, key: str, extent: Extent,
              background) -> ProviderResult | None:
        adapter = self.registry[key][0]
        env = read_envelope(mission_id, key, root=self.root)
        if env is None:
            return None
        derived = derive(env, self._ttl(adapter), now=self._now())
        if derived.status in ("stale", "offline"):
            self.refresh_async(background, mission_id, key, extent)
        return self._result(key, adapter, env, derived)

    def get(self, mission_id: str, key: str, extent: Extent, *,
            allow_fetch: bool = True, force: bool = False,
            background=None) -> ProviderResult:
        if key not in self.registry:
            raise KeyError(key)
        adapter = self.registry[key][0]

        if force and allow_fetch:
            self.refresh_async(background, mission_id, key, extent)

        warm = self._warm(mission_id, key, extent, background if allow_fetch else None)
        if warm is not None:
            return warm

        if not allow_fetch or self.cfg.offline:
            return self._result(key, adapter, None, derive(None, self._ttl(adapter),
                                                           now=self._now()))

        if adapter.allow_inline:
            return self.refresh_now(mission_id, key, extent)

        if background is not None:
            self.refresh_async(background, mission_id, key, extent)
        return self._result(key, adapter, None,
                            Derived("unavailable", "warming", None))

    def status_all(self, mission_id: str, extent: Extent, *,
                   allow_fetch: bool = True, background=None) -> dict[str, ProviderResult]:
        return {
            key: self.get(mission_id, key, extent,
                          allow_fetch=allow_fetch, background=background)
            for key in self.registry
        }


_DEFAULT: Gateway | None = None


def default_gateway() -> Gateway:
    """Process-wide gateway built from the current environment."""
    global _DEFAULT
    if _DEFAULT is None:
        cfg = load_config()
        _DEFAULT = Gateway(build_registry(cfg), cfg)
    return _DEFAULT


def reset_default_gateway() -> None:
    global _DEFAULT
    _DEFAULT = None
