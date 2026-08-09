from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..models import CalibrationPlan
from ..planning import effective_target_goal


def build_calibration_pass_record(
    *,
    run_dir: Path,
    return_code: int,
    summary: dict[str, Any],
    ads_paths: list[Path],
    plan: CalibrationPlan,
    targets_available: int,
    pass_targets_available: int,
    now: Callable[[], str],
) -> dict[str, Any]:
    successful_targets = int(summary.get("ok") or 0)
    effective_goal = effective_target_goal(plan)
    effective = (
        summary.get("status") == "completed"
        and successful_targets >= effective_goal
        and summary.get("interaction_goal_met") is True
    )
    recorded_at = now()
    return {
        "at": recorded_at,
        "run_dir": str(run_dir),
        "return_code": return_code,
        "summary": summary,
        "started_at": summary.get("started_at"),
        "finished_at": summary.get("finished_at") or now(),
        "ads_json": [str(path) for path in ads_paths],
        "effective": effective,
        "successful_targets": successful_targets,
        "tier": plan.tier,
        "target_limit": plan.target_limit,
        "targets_available": targets_available,
        "pass_targets_available": pass_targets_available,
        "target_goal": plan.target_goal,
        "effective_target_goal": effective_goal,
        "interaction_limits": {
            "max_reactions": plan.max_reactions,
            "max_follows": plan.max_follows,
            "max_comments": plan.max_comments,
            "min_interactions": plan.min_interactions,
        },
    }
