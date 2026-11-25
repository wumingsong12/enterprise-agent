import asyncio
import json
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from app.schemas.message import ChatRequest
from app.core.agent_runtime import run_agent, event

router = APIRouter()

def encode(item):
    return f"event: {item['event']}\ndata: {json.dumps(item['data'],ensure_ascii=False)}\n\n"

@router.post('/chat/stream')
async def chat(body: ChatRequest, request: Request):
    # Local demo only. Never take actor identity from the request JSON.
    actor = 'user_001'
    async def events():
        yield encode(event('queued'))
        sem = request.app.state.sem
        acquired = False
        try:
            async with asyncio.timeout(5):
                await sem.acquire()
            acquired = True
            session = request.app.state.conversations.get(actor,body.session_id)
            async with asyncio.timeout(60):
                async with session.lock:
                    generator = run_agent(body.question,actor,session,request.app.state.gateway)
                    try:
                        async for item in generator:
                            if await request.is_disconnected():
                                return
                            yield encode(item)
                    finally:
                        await generator.aclose()
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            yield encode(event('error',code='TIMEOUT'))
            yield encode(event('done',status='stopped_timeout'))
        except Exception:
            yield encode(event('error',code='SERVER_ERROR'))
            yield encode(event('done',status='failed_server'))
        finally:
            if acquired:
                sem.release()
    return StreamingResponse(events(),media_type='text/event-stream',headers={'Cache-Control':'no-cache, no-transform','X-Accel-Buffering':'no'})
