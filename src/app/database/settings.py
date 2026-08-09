from pydantic import BaseModel


class PostgresConfig(BaseModel):
    user: str = "postgres"
    password: str = "postgres"
    host: str = "localhost"
    port: int = 5432
    db: str = "app"


class RedisConfig(BaseModel):
    host: str = "localhost"
    port: int = 6379
    db: int = 0
