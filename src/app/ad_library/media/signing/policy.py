import re
from dataclasses import dataclass, field

_PUBLIC_PATH_RE = re.compile(r"/[A-Za-z0-9/_-]+\Z")


@dataclass(frozen=True, slots=True)
class MediaSigningPolicy:
    secret: str = field(repr=False)
    ttl_seconds: int
    public_path: str
    clock_skew_seconds: int = 60

    def __post_init__(self) -> None:
        if not self.secret:
            raise ValueError("media signing secret is required")
        if self.ttl_seconds <= 0:
            raise ValueError("media signing TTL must be positive")
        if (
            self.public_path == "/"
            or "//" in self.public_path
            or _PUBLIC_PATH_RE.fullmatch(self.public_path) is None
        ):
            raise ValueError("media public path must be a safe absolute URL path")
