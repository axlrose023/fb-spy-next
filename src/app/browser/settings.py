from pydantic import BaseModel


class PlaywrightConfig(BaseModel):
    enabled: bool = False
    headless: bool = True
    max_browsers: int = 2
    contexts_per_browser: int = 5
    browser_args: list[str] = [
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--no-sandbox",
    ]


class ViewportConfig(BaseModel):
    width_min: int = 1280
    width_max: int = 1920
    height_min: int = 800
    height_max: int = 1080


class UserAgentConfig(BaseModel):
    browsers: list[str] = ["Chrome", "Edge"]
    fallback: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )
