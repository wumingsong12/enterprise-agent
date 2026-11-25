from pydantic import BaseModel, ConfigDict, Field

class ChatRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=True)
    session_id: str = Field(min_length=1,max_length=64,pattern=r'^[a-zA-Z0-9_-]+$')
    question: str = Field(min_length=1,max_length=2000)
