from pydantic import BaseModel


class APIConfig(BaseModel):
    title: str = "FB Spy API"
    version: str = "1.0.0"
    port: int = 8000
    host: str = "0.0.0.0"
    allowed_hosts: list[str] = ["*"]

    page_max_size: int = 100
    page_default_size: int = 10
