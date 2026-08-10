from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.facebook.profiles import Profile
from app.facebook.settings import FacebookConfig

from .invocation_command import (
    CalibrationCommandOptions,
    CalibrationProcessEnvironment,
    build_calibration_command,
)


class CalibrationProcessOptions(CalibrationCommandOptions, Protocol):
    octo_host: str
    octo_port: int
    octo_headless: bool | None


@dataclass(frozen=True, slots=True)
class CalibrationProcessCommandFactory:
    settings: FacebookConfig

    def build(
        self,
        profile: Profile,
        options: CalibrationProcessOptions,
        run_dir: Path,
        ads_paths: list[Path],
        country: str | None,
        *,
        target_offset: int = 0,
        target_limit: int | None = None,
        min_successful_targets: int | None = None,
        max_reactions: int | None = None,
        max_follows: int | None = None,
        max_comments: int | None = None,
        min_interactions: int | None = None,
    ) -> list[str]:
        command: list[str] = build_calibration_command(
            profile,
            options,
            run_dir,
            ads_paths,
            country,
            self._environment(options),
            target_offset=target_offset,
            target_limit=target_limit,
            min_successful_targets=min_successful_targets,
            max_reactions=max_reactions,
            max_follows=max_follows,
            max_comments=max_comments,
            min_interactions=min_interactions,
        )
        return command

    def _environment(
        self,
        options: CalibrationProcessOptions,
    ) -> CalibrationProcessEnvironment:
        return CalibrationProcessEnvironment(
            executable=self.settings.runner_python,
            octo_host=options.octo_host or self.settings.octo_host,
            octo_port=options.octo_port or self.settings.octo_port,
            octo_headless=(
                self.settings.octo_headless
                if options.octo_headless is None
                else options.octo_headless
            ),
        )
