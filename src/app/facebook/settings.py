import sys
from pathlib import Path

from pydantic import BaseModel


class FacebookConfig(BaseModel):
    data_dir: Path = Path("storage/facebook")
    runner_out_dir: Path = Path("storage/facebook/runs")
    runner_module: str = "app.services.facebook_runner"
    runner_python: str = sys.executable
    octo_host: str = "127.0.0.1"
    octo_port: int = 58888
    octo_profile_uuid: str = "replace-with-octo-profile-uuid"
    octo_headless: bool = False
    octo_api_token: str = ""
    octo_search_tags: str = ""
    default_minutes: float = 10.0
    default_resolve_max: int = 200
    default_collect_scrolls: int = 10000
    default_scroll_px: int = 520
    default_country: str | None = "Turkey"
    media_mount_path: str = "/media"
    relevance_filter_enabled: bool = False
    relevance_filter_concurrency: int = 4
    relevance_filter_taskiq_enabled: bool = True
    relevance_filter_task_timeout_seconds: float = 45.0
    relevance_filter_task_retries: int = 1
    streaming_import_enabled: bool = True
    streaming_import_poll_seconds: float = 1.0
    landing_archive_enabled: bool = True
    landing_archive_timeout_seconds: float = 20.0
    landing_archive_max_resources: int = 120
    video_recording_enabled: bool = True
    video_recording_max_seconds: float = 30.0
    video_recording_fps: int = 8
