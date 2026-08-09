from pydantic import BaseModel

DEFAULT_JWT_SECRET = "change-me-in-production"


class JwtConfig(BaseModel):
    secret_key: str = DEFAULT_JWT_SECRET
    algorithm: str = "HS256"
    access_token_expires_in_minutes: int = 30
    refresh_expires_in_minutes: int = 1440  # 1 day
