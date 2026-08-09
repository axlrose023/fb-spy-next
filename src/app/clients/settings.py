from pydantic import BaseModel


class GeminiConfig(BaseModel):
    api_key: str = ""
    model: str = "gemini-2.5-flash"
