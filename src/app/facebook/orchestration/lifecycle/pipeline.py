from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CalibrationTransition(StrEnum):
    NONE = "none"
    RUN = "run"
    SKIP_PIPELINE_FAILED = "skip_pipeline_failed"


@dataclass(slots=True)
class CollectionPipelineState:
    collect_code: int = 0
    interest_safety_code: int | None = None
    prefilter_code: int | None = None
    isolated_resolution_code: int | None = None
    gate_resolution_code: int | None = None
    enrichment_code: int | None = None
    relevance_code: int | None = None

    @property
    def resolution_succeeded(self) -> bool:
        return _succeeded(self.isolated_resolution_code) and _succeeded(
            self.gate_resolution_code
        )

    @property
    def resolution_failure_code(self) -> int | None:
        return self.gate_resolution_code or self.isolated_resolution_code

    @property
    def resolution_result_code(self) -> int | None:
        if self.resolution_succeeded:
            return 0
        return self.resolution_failure_code

    @property
    def post_collection_failed(self) -> bool:
        return any(
            not _succeeded(code)
            for code in (
                self.interest_safety_code,
                self.prefilter_code,
                self.isolated_resolution_code,
                self.gate_resolution_code,
                self.enrichment_code,
                self.relevance_code,
            )
        )

    def can_start_relevance(
        self,
        *,
        dry_run: bool,
        stop_requested: bool,
        relevance_enabled: bool,
        ads_available: bool,
    ) -> bool:
        return bool(
            self.collect_code == 0
            and _succeeded(self.interest_safety_code)
            and not dry_run
            and not stop_requested
            and relevance_enabled
            and ads_available
        )

    def should_record_disabled_relevance(
        self,
        *,
        interest_safe_collection: bool,
        dry_run: bool,
        relevance_enabled: bool,
    ) -> bool:
        return bool(
            self.collect_code == 0
            and interest_safe_collection
            and not dry_run
            and not relevance_enabled
        )

    def can_import_backend(
        self,
        *,
        import_enabled: bool,
        interest_safe_collection: bool,
        dry_run: bool,
        stop_requested: bool,
    ) -> bool:
        return bool(
            self.collect_code == 0
            and import_enabled
            and not dry_run
            and not stop_requested
            and _succeeded(self.relevance_code)
            and (not interest_safe_collection or self.relevance_code == 0)
        )

    def calibration_transition(
        self,
        *,
        calibration_requested: bool,
        stop_requested: bool,
    ) -> CalibrationTransition:
        if (
            calibration_requested
            and not stop_requested
            and not self.post_collection_failed
        ):
            return CalibrationTransition.RUN
        if calibration_requested and self.post_collection_failed:
            return CalibrationTransition.SKIP_PIPELINE_FAILED
        return CalibrationTransition.NONE


def _succeeded(code: int | None) -> bool:
    return code in {None, 0}
