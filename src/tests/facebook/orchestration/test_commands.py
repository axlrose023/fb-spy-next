from __future__ import annotations

import subprocess
import sys

import pytest

from app.facebook.orchestration.commands import build_parser
from app.services import facebook_orchestrator

pytestmark = pytest.mark.unit


def test_legacy_orchestrator_uses_canonical_parser() -> None:
    assert facebook_orchestrator._build_parser is build_parser


def test_commands_package_does_not_load_legacy_orchestrator() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "import app.facebook.orchestration.commands; "
                "assert 'app.services.facebook_orchestrator' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_run_parser_reads_offer_defaults_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "FACEBOOK_CALIBRATION_OFFER_SUBMIT_ALLOW_DOMAINS",
        " one.test, ,two.test ",
    )
    monkeypatch.setenv(
        "FACEBOOK_CALIBRATION_OFFER_IDENTITY_JSON",
        "/tmp/identity.json",
    )

    args = build_parser().parse_args(["run"])

    assert args.calibration_offer_submit_allow_domain == [
        "one.test",
        "two.test",
    ]
    assert args.calibration_offer_identity_json == "/tmp/identity.json"
