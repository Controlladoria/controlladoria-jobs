"""
AI Key Pool — Round-robin multi-key management with health tracking

Manages multiple API keys per provider (Gemini / Nova / OpenAI) to:
- Distribute load across keys (round-robin)
- Auto-skip rate-limited keys (exponential backoff)
- Mark unhealthy keys after consecutive errors
- Auto-recover keys after cooldown period
- Provide failover across providers: gemini → nova → openai

Note: Amazon Nova uses IAM credentials, not API keys. It's registered
with a sentinel key ("iam-credentials") so the pool's health tracking
and failover logic still applies uniformly.

Thread-safe via threading.Lock (processor is a singleton shared across requests).
"""

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class APIKeyState:
    """Tracks health and usage of a single API key"""

    key: str
    provider: str  # "gemini", "nova", or "openai"
    model: str
    requests_count: int = 0
    errors_count: int = 0
    consecutive_errors: int = 0
    last_used: float = 0.0
    rate_limited_until: float = 0.0
    is_healthy: bool = True

    @property
    def key_suffix(self) -> str:
        """Last 6 chars for safe logging (never log full key)"""
        return f"...{self.key[-6:]}" if len(self.key) > 6 else "***"

    def is_available(self) -> bool:
        """Key is available if healthy and not currently rate-limited"""
        if not self.is_healthy:
            return False
        if self.rate_limited_until > time.time():
            return False
        return True


class KeyPool:
    """
    Thread-safe round-robin key pool with health tracking.

    Usage:
        pool = KeyPool(unhealthy_threshold=3, recovery_seconds=300)
        pool.register_keys("gemini", ["key1", "key2"], "gemini-flash-lite-latest")
        pool.register_keys("nova", ["iam-credentials"], "us.amazon.nova-lite-v2:0")
        pool.register_keys("openai", ["sk-key1", "sk-key2"], "gpt-5.4-nano")

        key_state = pool.get_next_key("openai")
        if key_state:
            try:
                # ... make API call with key_state.key ...
                pool.report_success(key_state)
            except RateLimitError:
                pool.report_error(key_state, is_rate_limit=True)
            except Exception:
                pool.report_error(key_state, is_rate_limit=False)
    """

    def __init__(
        self,
        unhealthy_threshold: int = 3,
        recovery_seconds: int = 300,
    ):
        self._lock = threading.Lock()
        # provider -> deque of APIKeyState (round-robin rotation)
        self._pools: Dict[str, deque] = {}
        self._unhealthy_threshold = unhealthy_threshold
        self._recovery_seconds = recovery_seconds

    def register_keys(self, provider: str, keys: List[str], model: str) -> None:
        """Register one or more API keys for a provider"""
        with self._lock:
            states = deque(
                APIKeyState(key=k.strip(), provider=provider, model=model)
                for k in keys
                if k.strip()
            )
            if states:
                self._pools[provider] = states
                logger.info(
                    f"KeyPool: registered {len(states)} key(s) for {provider} "
                    f"(model: {model})"
                )

    def get_next_key(self, provider: str) -> Optional[APIKeyState]:
        """
        Get the next available key for a provider (round-robin).

        Skips unhealthy and rate-limited keys.
        Auto-recovers keys whose cooldown has expired.
        Returns None if no keys are available.
        """
        with self._lock:
            pool = self._pools.get(provider)
            if not pool:
                return None

            now = time.time()
            n = len(pool)

            for _ in range(n):
                state = pool[0]
                pool.rotate(-1)  # move front to back (round-robin)

                # Auto-recover: if cooldown has passed, give the key another chance
                if not state.is_healthy and (now - state.last_used) >= self._recovery_seconds:
                    state.is_healthy = True
                    state.consecutive_errors = 0
                    state.rate_limited_until = 0.0
                    logger.info(
                        f"KeyPool: auto-recovered {provider} key {state.key_suffix}"
                    )

                if state.is_available():
                    state.last_used = now
                    return state

            return None  # all keys exhausted / rate-limited

    def report_success(self, key_state: APIKeyState) -> None:
        """Report a successful API call — resets consecutive errors"""
        with self._lock:
            key_state.requests_count += 1
            key_state.consecutive_errors = 0
            # If it was previously unhealthy but recovered, keep it healthy
            key_state.is_healthy = True

    def report_error(self, key_state: APIKeyState, is_rate_limit: bool = False) -> None:
        """
        Report a failed API call.

        Rate-limit errors (429): apply exponential backoff (30s → 60s → 120s → 300s).
        Other errors: increment consecutive counter, mark unhealthy after threshold.
        """
        with self._lock:
            key_state.errors_count += 1
            key_state.consecutive_errors += 1

            if is_rate_limit:
                # Exponential backoff: 30s, 60s, 120s, 300s (capped)
                backoff = min(30 * (2 ** (key_state.consecutive_errors - 1)), 300)
                key_state.rate_limited_until = time.time() + backoff
                logger.warning(
                    f"KeyPool: {key_state.provider} key {key_state.key_suffix} "
                    f"rate-limited, backoff {backoff}s"
                )
            elif key_state.consecutive_errors >= self._unhealthy_threshold:
                key_state.is_healthy = False
                logger.error(
                    f"KeyPool: {key_state.provider} key {key_state.key_suffix} "
                    f"marked UNHEALTHY after {key_state.consecutive_errors} consecutive errors "
                    f"(will auto-recover in {self._recovery_seconds}s)"
                )

    def get_all_providers(self) -> List[str]:
        """Return list of providers that have at least one healthy key"""
        with self._lock:
            now = time.time()
            result = []
            for provider, pool in self._pools.items():
                for state in pool:
                    # Count as available if healthy or if recovery time has passed
                    if state.is_available() or (
                        not state.is_healthy
                        and (now - state.last_used) >= self._recovery_seconds
                    ):
                        result.append(provider)
                        break
            return result

    def has_provider(self, provider: str) -> bool:
        """Check if a provider has any registered keys (regardless of health)"""
        with self._lock:
            return provider in self._pools and len(self._pools[provider]) > 0

    def get_stats(self) -> dict:
        """
        Return monitoring data for admin endpoint.
        Never exposes full API keys — only suffixes.
        """
        with self._lock:
            now = time.time()
            stats = {}
            for provider, pool in self._pools.items():
                keys_info = []
                for state in pool:
                    keys_info.append(
                        {
                            "key_suffix": state.key_suffix,
                            "model": state.model,
                            "requests": state.requests_count,
                            "errors": state.errors_count,
                            "consecutive_errors": state.consecutive_errors,
                            "is_healthy": state.is_healthy,
                            "is_available": state.is_available()
                            or (
                                not state.is_healthy
                                and (now - state.last_used) >= self._recovery_seconds
                            ),
                            "rate_limited_remaining_s": max(
                                0, round(state.rate_limited_until - now, 1)
                            ),
                        }
                    )
                stats[provider] = {
                    "total_keys": len(pool),
                    "healthy_keys": sum(1 for s in pool if s.is_healthy),
                    "available_keys": sum(
                        1
                        for s in pool
                        if s.is_available()
                        or (
                            not s.is_healthy
                            and (now - s.last_used) >= self._recovery_seconds
                        )
                    ),
                    "keys": keys_info,
                }
            return stats


def get_next_ai_credentials(
    key_pool: KeyPool, preferred_provider: str = None
) -> Tuple[str, str, str]:
    """
    Helper for callers outside the processor (cnpj_validator, etc.).

    Returns (provider, api_key, model) from the pool.
    Tries preferred_provider first, then falls back to any available provider.
    Raises ValueError if no keys are available.
    """
    # Try preferred provider first
    if preferred_provider:
        state = key_pool.get_next_key(preferred_provider)
        if state:
            return state.provider, state.key, state.model

    # Fallback: try all providers
    for provider in key_pool.get_all_providers():
        state = key_pool.get_next_key(provider)
        if state:
            return state.provider, state.key, state.model

    raise ValueError("No AI API keys available (all keys exhausted or unhealthy)")
