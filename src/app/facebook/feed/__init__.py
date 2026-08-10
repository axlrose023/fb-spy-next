from .detection import BAD_DOMAINS, DETECT_JS
from .passive_media import (
    PASSIVE_MEDIA_GUARD_INSTALL_JS,
    install_passive_media_guard,
    passive_media_guard_stats,
    pause_all_videos,
    prepare_passive_media_guard,
)

__all__ = [
    "BAD_DOMAINS",
    "DETECT_JS",
    "PASSIVE_MEDIA_GUARD_INSTALL_JS",
    "install_passive_media_guard",
    "passive_media_guard_stats",
    "pause_all_videos",
    "prepare_passive_media_guard",
]
