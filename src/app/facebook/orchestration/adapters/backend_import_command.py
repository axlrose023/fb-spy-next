from __future__ import annotations

from pathlib import Path

from app.facebook.profiles import Profile

from .command_environment import PythonProcessEnvironment


def build_backend_import_command(
    profile: Profile,
    ads_json_path: Path,
    environment: PythonProcessEnvironment,
) -> list[str]:
    return [
        environment.executable,
        "-m",
        "app.facebook.runs.commands",
        "--ads-json",
        str(ads_json_path),
        "--title",
        f"{profile.display_name} - {ads_json_path.parent.name}",
    ]
