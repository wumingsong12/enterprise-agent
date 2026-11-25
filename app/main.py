import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from app.config import build_gateway
from app.core.conversation import ConversationManager
from app.api.chat import router

@asynccontextmanager
async def lifespan(app):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    gateway, clients = build_gateway()
    app.state.gateway = gateway
    app.state.conversations = ConversationManager()
    app.state.sem = asyncio.Semaphore(5)
    try:
        yield
    finally:
        await asyncio.gather(*(c.close() for c in clients))

app = FastAPI(title='EnterpriseAgent Mini', lifespan=lifespan)
app.include_router(router)

@app.get('/')
async def home():
    return FileResponse(Path(__file__).resolve().parents[1]/'frontend/index.html')

@app.get('/health')
async def health():
    return {'ok':True,'mode':'mock' if app.state.gateway is None else 'real'}
