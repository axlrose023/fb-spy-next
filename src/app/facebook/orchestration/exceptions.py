from pathlib import Path


class ProfileLockError(RuntimeError):
    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(f"profile locked: {path}")
