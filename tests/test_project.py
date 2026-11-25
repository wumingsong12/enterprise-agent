import os
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.tools.registry import execute_tool
from app.core.conversation import ConversationManager
from app.core.agent_runtime import run_agent
from app.core.router import route, RouterError
from app.core.llm_gateway import TextResult

class FakeGateway:
    def __init__(self, texts): self.texts=iter(texts); self.calls=0
    async def ask(self,messages):
        self.calls+=1
        return TextResult(next(self.texts),'mock')

class Tests(unittest.IsolatedAsyncioTestCase):
    async def collect(self,q,session=None,actor='user_001',gateway=None):
        session=session or ConversationManager().get(actor,'a')
        return [e async for e in run_agent(q,actor,session,gateway)]
    async def test_conditional(self):
        e=await self.collect('如果订单12345没发货，告诉我能否退款')
        self.assertEqual([x['data']['name'] for x in e if x['event']=='tool_start'],['query_order','get_refund_policy'])
        self.assertEqual(e[-1]['data']['status'],'completed')
    async def test_shipped(self):
        e=await self.collect('如果订单23456没发货，告诉我能否退款')
        self.assertEqual(e[-1]['data']['tool_calls'],1)
        self.assertIn('不满足',e[-2]['data']['text'])
    async def test_permission(self):
        e=await self.collect('查询订单88888')
        self.assertEqual(e[-1]['data']['status'],'failed_tool')
        self.assertNotIn('尚未交给',str(e))
    async def test_missing(self):
        e=await self.collect('查询订单')
        self.assertEqual(e[-1]['data']['status'],'needs_clarification')
        self.assertEqual(e[-1]['data']['tool_calls'],0)
    async def test_context_isolation(self):
        m=ConversationManager(); a=m.get('user_001','a'); b=m.get('user_001','b')
        await self.collect('查询订单12345',a)
        e=await self.collect('这个订单能否退款',a)
        self.assertEqual(e[-1]['data']['tool_calls'],2)
        e=await self.collect('这个订单能否退款',b)
        self.assertEqual(e[-1]['data']['status'],'needs_clarification')
        self.assertIsNot(a,m.get('user_002','a'))
    async def test_router_repair(self):
        g=FakeGateway(['{}','{"intent":"ORDER_QUERY","order_id":"12345","policy_type":"GENERAL_REFUND"}'])
        t=await route('查询订单12345',g)
        self.assertEqual(t.order_id,'12345'); self.assertEqual(g.calls,2)
    async def test_fabricated_id(self):
        bad='{"intent":"ORDER_QUERY","order_id":"88888","policy_type":"GENERAL_REFUND"}'
        with self.assertRaises(RouterError): await route('查询订单12345',FakeGateway([bad,bad]))
    def test_registry(self):
        self.assertEqual(execute_tool('delete_database',{},'user_001')['error'],'UNKNOWN_TOOL')
        self.assertEqual(execute_tool('query_order',{'order_id':12345},'user_001')['error'],'INVALID_TOOL_ARGUMENTS')
    def test_sse(self):
        with patch.dict(os.environ,{'APP_MODE':'mock'}), TestClient(app) as c:
            r=c.post('/chat/stream',json={'session_id':'test','question':'查询订单12345'})
            self.assertEqual(r.status_code,200)
            self.assertIn('event: tool_result',r.text); self.assertIn('event: done',r.text)
            self.assertEqual(c.post('/chat/stream',json={'session_id':'x','question':'','actor':'user_002'}).status_code,422)
