import asyncio
import unittest
from app.core.llm_gateway import (GatewayError, LLMGateway, Provider, TextResult,
                         CircuitBreaker, SlidingWindowLimiter)

MESSAGES = [{"role": "user", "content": "test"}]

class GatewayTests(unittest.IsolatedAsyncioTestCase):
    def gateway(self, providers, **kwargs):
        options = dict(base_delay=0.001, total_timeout=1, attempt_timeout=0.05)
        options.update(kwargs)
        return LLMGateway(providers, **options)

    async def test_retry_then_success(self):
        count = 0
        async def invoke(_):
            nonlocal count
            count += 1
            if count == 1:
                raise GatewayError("HTTP_503", retryable=True, unhealthy=True)
            return TextResult("ok", "primary")
        result = await self.gateway([Provider("p", invoke)]).ask(MESSAGES)
        self.assertEqual((count, result.text), (2, "ok"))

    async def test_400_no_retry_or_fallback(self):
        calls = []
        async def bad(_):
            calls.append("bad")
            raise GatewayError("HTTP_400")
        async def backup(_):
            calls.append("backup")
            return TextResult("ok", "backup")
        with self.assertRaisesRegex(GatewayError, "HTTP_400"):
            await self.gateway([Provider("p", bad), Provider("b", backup)]).ask(MESSAGES)
        self.assertEqual(calls, ["bad"])

    async def test_breaker_and_fallback(self):
        count = 0
        async def bad(_):
            nonlocal count
            count += 1
            raise GatewayError("HTTP_503", retryable=True, unhealthy=True)
        async def backup(_):
            return TextResult("ok", "backup")
        p = Provider("p", bad, breaker=CircuitBreaker(threshold=2, cooldown=60))
        g = self.gateway([p, Provider("b", backup)])
        self.assertEqual((await g.ask(MESSAGES)).model, "backup")
        self.assertEqual(p.breaker.state, "OPEN")
        self.assertEqual((await g.ask(MESSAGES)).model, "backup")
        self.assertEqual(count, 2)

    async def test_half_open_probe(self):
        breaker = CircuitBreaker(threshold=1, cooldown=0)
        breaker.finish(breaker.permit(), "failure")
        ticket = breaker.permit()
        self.assertEqual(breaker.state, "HALF_OPEN")
        with self.assertRaisesRegex(GatewayError, "CIRCUIT_OPEN"):
            breaker.permit()
        breaker.finish(ticket, "success")
        self.assertEqual(breaker.state, "CLOSED")

    async def test_attempt_timeout(self):
        async def slow(_):
            await asyncio.sleep(1)
            return TextResult("late", "p")
        async def backup(_):
            return TextResult("ok", "backup")
        g = self.gateway([Provider("p", slow), Provider("b", backup)], max_retries=0)
        self.assertEqual((await g.ask(MESSAGES)).model, "backup")

    async def test_total_timeout_during_rate_wait(self):
        async def ok(_):
            return TextResult("ok", "p")
        p = Provider("p", ok, limiter=SlidingWindowLimiter(1, 60))
        g = self.gateway([p], total_timeout=0.05)
        await g.ask(MESSAGES)
        with self.assertRaisesRegex(GatewayError, "TOTAL_TIMEOUT"):
            await g.ask(MESSAGES)

    async def test_concurrency_limit(self):
        active = peak = 0
        async def ok(_):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                await asyncio.sleep(0.01)
                return TextResult("ok", "p")
            finally:
                active -= 1
        g = self.gateway([Provider("p", ok)], concurrency=2)
        await asyncio.gather(*(g.ask(MESSAGES) for _ in range(6)))
        self.assertEqual(peak, 2)

if __name__ == "__main__":
    unittest.main()
