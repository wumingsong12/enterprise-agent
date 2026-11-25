import time
import uuid
import asyncio
from app.core.router import route, ORDER_ID, RouterError
from app.core.llm_gateway import GatewayError
from app.tools.registry import execute_tool

ORDER_INTENTS = {'ORDER_QUERY','CONDITIONAL_REFUND','REFUND_REQUEST'}

def event(kind, **data):
    return {'event':kind,'data':data}

async def run_agent(question, actor, session, gateway=None):
    trace_id = uuid.uuid4().hex
    start = time.monotonic()
    calls = 0
    verified_id = None
    status = 'completed'
    answer = ''
    yield event('model_start', trace_id=trace_id, mode='mock' if gateway is None else 'real')
    try:
        task = await route(question,gateway)
        yield event('task', **task.model_dump())
        ids = set(ORDER_ID.findall(question))
        # Business facts and identity are controlled by Python, not model output.
        if task.intent in ORDER_INTENTS:
            if len(ids) > 1:
                answer, status = '请一次提供一个订单编号。','needs_clarification'
            elif len(ids) == 1:
                order_id = next(iter(ids))
            elif any(x in question for x in ('这个订单','该订单','这笔订单','它')):
                order_id = session.last_order_id
            else:
                order_id = None
            if not answer and not order_id:
                answer, status = '请提供五位订单编号。','needs_clarification'
        if not answer and task.intent in ORDER_INTENTS:
            calls += 1
            yield event('tool_start',name='query_order',call_id='order')
            result = execute_tool('query_order',{'order_id':order_id},actor)
            yield event('tool_result',name='query_order',call_id='order',result=result)
            if not result['ok']:
                answer,status = '订单不存在或当前用户无权查询。','failed_tool'
            else:
                verified_id = order_id
                answer = f"模拟订单 {order_id}：{result['logistics']}。"
                if task.intent in {'CONDITIONAL_REFUND','REFUND_REQUEST'}:
                    if result['status'] == 'NOT_SHIPPED':
                        calls += 1
                        yield event('tool_start',name='get_refund_policy',call_id='policy')
                        policy = execute_tool('get_refund_policy',{'policy_type':'NOT_SHIPPED_REFUND'},actor)
                        yield event('tool_result',name='get_refund_policy',call_id='policy',result=policy)
                        answer += policy['policy']
                    else:
                        answer += '不满足本示例的未发货退款条件；其他退款资格需另行审核。'
                    answer += ' 本助手只读，未提交退款申请。'
        elif not answer and task.intent == 'POLICY_QUERY':
            calls += 1
            yield event('tool_start',name='get_refund_policy',call_id='policy')
            result = execute_tool('get_refund_policy',{'policy_type':task.policy_type},actor)
            yield event('tool_result',name='get_refund_policy',call_id='policy',result=result)
            answer = result['policy']
        elif not answer:
            answer = '我是教学用订单助手，支持订单物流查询、退款政策查询及条件判断，不执行真实退款。'
        if status == 'completed':
            session.commit(question,answer,verified_id)
        yield event('answer',text=answer,trace_id=trace_id)
    except (RouterError,GatewayError) as exc:
        status = 'failed_model'
        yield event('error',code=getattr(exc,'code','INVALID_TASK_OUTPUT'))
    except asyncio.CancelledError:
        raise
    yield event('done',status=status,trace_id=trace_id,tool_calls=calls,elapsed_ms=round((time.monotonic()-start)*1000))
