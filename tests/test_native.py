import unittest
from types import SimpleNamespace as S
from app.core.native_agent import accumulate, stream_native

def chunk(text=None, parts=None, reason=None):
    return S(choices=[S(delta=S(content=text,tool_calls=parts),finish_reason=reason)])
class FakeStream:
    def __init__(self,chunks): self.chunks=chunks; self.closed=False
    async def __aiter__(self):
        for c in self.chunks: yield c
    async def close(self): self.closed=True
class FakeAPI:
    def __init__(self,streams): self.streams=iter(streams); self.requests=[]; self.chat=S(completions=self)
    async def create(self,**kwargs): self.requests.append(list(kwargs['messages'])); return next(self.streams)
class NativeTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_fragments_and_followup(self):
        a=FakeStream([chunk(parts=[S(index=0,id='call_1',function=S(name='query_order',arguments='{"order_'))]),chunk(parts=[S(index=0,id=None,function=S(name=None,arguments='id":"12345"}'))]),chunk(reason='tool_calls')])
        b=FakeStream([chunk(text='尚未'),chunk(text='发货'),chunk(reason='stop')])
        api=FakeAPI([a,b]); events=[e async for e in stream_native(api,'mock','查询订单12345')]
        self.assertEqual(events[0]['data']['result']['status'],'NOT_SHIPPED')
        self.assertEqual(events[-1]['data']['text'],'尚未发货')
        self.assertTrue(a.closed and b.closed)
        self.assertEqual(api.requests[1][-1]['tool_call_id'],'call_1')
