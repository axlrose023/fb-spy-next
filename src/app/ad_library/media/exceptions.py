class MediaError(Exception):
    """Base error for media use cases."""


class MediaTokenError(MediaError, ValueError):
    pass


class MediaNotFoundError(MediaError, FileNotFoundError):
    pass


class MediaRangeError(MediaError, ValueError):
    def __init__(self, total_size: int | None = None) -> None:
        self.total_size = total_size
        super().__init__("requested media range is not satisfiable")


class MediaStorageError(MediaError, RuntimeError):
    pass
