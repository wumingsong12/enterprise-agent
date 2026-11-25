"""Lesson 09: single-process, non-streaming text gateway, Python 3.11+."""
import asyncio
import json
import logging
import os
import random
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Awaitable, Callable

logger = logging.getLogger("llm_gateway")


class GatewayError(Exception):
    def __init__(self, code, *, retryable=False, unhealthy=False, retry_after=0.0):
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.unhealthy = unhealthy
        self.retry_after = retry_after


@dataclass
class TextResult:
    text: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    request_id: str | None = None


class SlidingWindowLimiter:
    """Limit admissions to N per rolling period; one event loop only."""
    def __init__(self, limit: int, period: float = 60):
        if limit < 1 or period <= 0:
            raise ValueError("Invalid rate limit")
        self.limit, self.period = limit, period
        self.timestamps = deque()
        self.lock = asyncio.Lock()

    async def acquire(self):
        while True:
            async with self.lock:
                now = time.monotonic()
                while self.timestamps and now - self.timestamps[0] >= self.period:
                    self.timestamps.popleft()
                if len(self.timestamps) < self.limit:
                    self.timestamps.append(now)
                    return
                delay = self.period - (now - self.timestamps[0])
            await asyncio.sleep(max(delay, 0))


class CircuitBreaker:
    """Synchronous state transitions within one asyncio event loop."""
    def __init__(self, threshold=3, cooldown=20):
        self.threshold, self.cooldown = threshold, cooldown
        self.state, self.failures = "CLOSED", 0
        self.opened_at, self.generation = 0.0, 0

    def permit(self):
        if self.state == "OPEN":
            if time.monotonic() - self.opened_at < self.cooldown:
                raise GatewayError("CIRCUIT_OPEN", retryable=True)
            self.state = "HALF_OPEN"  # only one probe allowed
            self.generation += 1
        elif self.state == "HALF_OPEN":
            raise GatewayError("CIRCUIT_OPEN", retryable=True)
        return self.generation

    def _open(self):
        self.state = "OPEN"
        self.opened_at = time.monotonic()
        self.generation += 1

    def finish(self, ticket, outcome):
        # Ignore calls from an older circuit generation.
        if ticket != self.generation:
            return
        if outcome == "success":
            self.failures = 0
            if self.state == "HALF_OPEN":
                self.state = "CLOSED"
                self.generation += 1
        elif outcome == "failure":
            self.failures += 1
            if self.state == "HALF_OPEN" or self.failures >= self.threshold:
                self._open()
        elif self.state == "HALF_OPEN":
            # Cancelled/neutral probe cannot leave the circuit stuck.
            self._open()


@dataclass
class Provider:
    name: str
    invoke: Callable[[list[dict]], Awaitable[TextResult]]
    limiter: SlidingWindowLimiter = field(default_factory=lambda: SlidingWindowLimiter(30))
    breaker: CircuitBreaker = field(default_factory=CircuitBreaker)


class LLMGateway:
    def __init__(self, providers, *, concurrency=3, max_retries=2,
                 attempt_timeout=20, total_timeout=60, base_delay=0.5):
        if not providers or concurrency < 1 or max_retries < 0 or min(attempt_timeout, total_timeout, base_delay) <= 0:
            raise ValueError("Invalid gateway settings")
        self.providers = providers
        self.sem = asyncio.Semaphore(concurrency)
        self.max_retries = max_retries
        self.attempt_timeout = attempt_timeout
        self.total_timeout = total_timeout
        self.base_delay = base_delay

    async def _attempt(self, provider, messages):
        # Limit actual admission to API; rate-limit waiting occupies a slot here.
        async with self.sem:
            await provider.limiter.acquire()
            ticket = provider.breaker.permit()
            outcome = "neutral"
            try:
                async with asyncio.timeout(self.attempt_timeout):
                    result = await provider.invoke(messages)
                outcome = "success"
                return result
            except TimeoutError as exc:
                outcome = "failure"
                raise GatewayError("ATTEMPT_TIMEOUT", retryable=True, unhealthy=True) from exc
            except GatewayError as exc:
                if exc.unhealthy:
                    outcome = "failure"
                raise
            finally:
                provider.breaker.finish(ticket, outcome)

    async def ask(self, messages: list[dict]) -> TextResult:
        trace_id = uuid.uuid4().hex
        last = None
        try:
            # Includes semaphore, rate-limit wait, retry sleep and fallback.
            async with asyncio.timeout(self.total_timeout):
                for provider in self.providers:
                    for attempt in range(self.max_retries + 1):
                        start = time.monotonic()
                        try:
                            result = await self._attempt(provider, messages)
                        except GatewayError as exc:
                            last = exc
                            self._log(trace_id, provider, attempt, start, error=exc.code)
                            if not exc.retryable:
                                raise
                            if exc.code == "CIRCUIT_OPEN" or attempt == self.max_retries:
                                break
                            delay = max(exc.retry_after, random.uniform(0, min(8, self.base_delay * 2 ** attempt)))
                            await asyncio.sleep(delay)  # outside semaphore
                        else:
                            self._log(trace_id, provider, attempt, start, result=result)
                            return result
                raise GatewayError("ALL_PROVIDERS_UNAVAILABLE") from last
        except TimeoutError as exc:
            logger.warning(json.dumps({"trace_id": trace_id, "event": "total_timeout"}))
            raise GatewayError("TOTAL_TIMEOUT") from exc

    @staticmethod
    def _log(trace_id, provider, attempt, start, *, error=None, result=None):
        event = dict(trace_id=trace_id, provider=provider.name, attempt=attempt+1,
                     elapsed_ms=round((time.monotonic()-start)*1000),
                     circuit=provider.breaker.state, error=error)
        if result is not None:
            event.update(model=result.model, prompt_tokens=result.prompt_tokens,
                         completion_tokens=result.completion_tokens, request_id=result.request_id)
        logger.info(json.dumps(event, ensure_ascii=False))


def retry_after_seconds(headers):
    raw = headers.get("retry-after", "")
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        try:
            return max(0.0, (parsedate_to_datetime(raw)-datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return 0.0


def make_provider(name, model, key, base_url, rpm=30):
    """Real OpenAI-compatible transport; imported lazily for offline tests."""
    from openai import AsyncOpenAI, APIConnectionError, APIStatusError
    client = AsyncOpenAI(api_key=key, base_url=base_url, timeout=20, max_retries=0)

    async def invoke(messages):
        kwargs = {"model": model, "messages": messages}
        if model.startswith("qwen4-"):
            kwargs["extra_body"] = {"enable_thinking": False}
        try:
            response = await client.chat.completions.create(**kwargs)
        except APIConnectionError as exc:
            raise GatewayError("CONNECTION_OR_SDK_TIMEOUT", retryable=True, unhealthy=True) from exc
        except APIStatusError as exc:
            status = exc.status_code
            code = getattr(exc, "code", None)
            # Common quota markers; each provider may use different codes.
            if status == 429 and code in {"insufficient_quota", "billing_hard_limit_reached"}:
                raise GatewayError("QUOTA_EXHAUSTED") from exc
            unhealthy = status == 408 or 500 <= status < 600
            raise GatewayError(f"HTTP_{status}", retryable=unhealthy or status == 429,
                               unhealthy=unhealthy, retry_after=retry_after_seconds(exc.response.headers)) from exc
        choice = response.choices[0]
        msg = choice.message
        if choice.finish_reason != "stop" or getattr(msg, "refusal", None) or not (msg.content or "").strip():
            raise GatewayError("INVALID_TEXT_RESPONSE")
        usage = response.usage
        return TextResult(msg.content, response.model or model,
                          usage.prompt_tokens if usage else None,
                          usage.completion_tokens if usage else None,
                          getattr(response, "_request_id", None))

    return Provider(name, invoke, SlidingWindowLimiter(rpm)), client


async def main():
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    providers, clients = [], []
    try:
        for prefix, name in [("LLM_", "primary"), ("FALLBACK_", "fallback")]:
            if name == "fallback" and not os.getenv("FALLBACK_MODEL"):
                continue
            provider, client = make_provider(name, os.environ[prefix+"MODEL"],
                os.environ[prefix+"API_KEY"], os.environ[prefix+"BASE_URL"],
                int(os.getenv(prefix+"RPM", "30")))
            providers.append(provider)
            clients.append(client)
        gateway = LLMGateway(providers)
        result = await gateway.ask([{"role": "user", "content": "用三句话解释 RAG。"}])
        print(result)
    except GatewayError as exc:
        print("请求失败:", exc.code)
    finally:
        await asyncio.gather(*(client.close() for client in clients))


if __name__ == "__main__":
    asyncio.run(main())
