from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.facebook.profiles import Profile
from app.facebook.settings import FacebookConfig

from .backend_import_command import build_backend_import_command
from .collector_command import CollectorCommandOptions, build_collector_command
from .orchestrator_runtime import (
    OctoRuntimeOptions,
    octo_process_environment,
    python_process_environment,
)
from .relevance_commands import (
    EnrichmentCommandOptions,
    IsolatedResolutionCommandOptions,
    build_isolated_landing_resolver_command,
    build_relevance_classifier_command,
    build_relevant_enricher_command,
)


class CollectorProcessOptions(
    CollectorCommandOptions,
    OctoRuntimeOptions,
    Protocol,
):
    pass


class EnrichmentProcessOptions(
    EnrichmentCommandOptions,
    OctoRuntimeOptions,
    Protocol,
):
    pass


class IsolatedResolutionProcessOptions(
    IsolatedResolutionCommandOptions,
    OctoRuntimeOptions,
    Protocol,
):
    pass


@dataclass(frozen=True, slots=True)
class CollectionProcessCommandFactory:
    settings: FacebookConfig

    def collector(
        self,
        profile: Profile,
        options: CollectorProcessOptions,
        run_dir: Path,
    ) -> list[str]:
        command: list[str] = build_collector_command(
            profile,
            options,
            run_dir,
            octo_process_environment(options, self.settings),
        )
        return command

    def classifier(
        self,
        run_dir: Path,
        *,
        stage: str = "standard",
        source: Path | None = None,
        include_video: bool = False,
    ) -> list[str]:
        command: list[str] = build_relevance_classifier_command(
            run_dir,
            python_process_environment(self.settings),
            stage=stage,
            source=source,
            include_video=include_video,
        )
        return command

    def enricher(
        self,
        profile: Profile,
        options: EnrichmentProcessOptions,
        run_dir: Path,
        *,
        source: Path | None = None,
    ) -> list[str]:
        command: list[str] = build_relevant_enricher_command(
            profile,
            options,
            run_dir,
            octo_process_environment(options, self.settings),
            source=source,
        )
        return command

    def isolated_resolver(
        self,
        profile: Profile,
        options: IsolatedResolutionProcessOptions,
        run_dir: Path,
    ) -> list[str]:
        command: list[str] = build_isolated_landing_resolver_command(
            profile,
            options,
            run_dir,
            octo_process_environment(options, self.settings),
        )
        return command

    def backend_import(self, profile: Profile, ads_json_path: Path) -> list[str]:
        command: list[str] = build_backend_import_command(
            profile,
            ads_json_path,
            python_process_environment(self.settings),
        )
        return command
