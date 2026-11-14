"""Unit and regression tests verifying Capstone demonstration reliability,
dashboard schemas, guardrail metric single-counting, and recovery tiering.
"""

import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "Capstone_Scenarios"))


def test_dashboard_json_integrity():
    """Verify all Grafana dashboards are valid JSON and contain expected UIDs."""
    dashboards_dir = REPO_ROOT / "infra" / "observability" / "grafana" / "dashboards"
    assert dashboards_dir.is_dir(), f"Missing dashboards directory at {dashboards_dir}"

    expected_uids = {
        "01_frontend_experience.json": "loanprocessai-frontend",
        "02_backend_golden_signals.json": "loanprocessai-golden-signals",
        "03_llm_and_rag_telemetry.json": "loanprocessai-rag-llm",
        "04_multi_agent_pipeline.json": "loanprocessai-multi-agent",
        "05_guardrails_and_ai_safety.json": "loanprocessai-guardrails",
        "06_sli_slo_overview.json": "loanprocessai-sli-slo",
        "07_live_logs_explorer.json": "loanprocessai-live-logs",
        "08_executive_capstone_overview.json": "loanprocessai-executive-capstone",
    }

    for filename, expected_uid in expected_uids.items():
        file_path = dashboards_dir / filename
        assert file_path.is_file(), f"Expected dashboard {filename} is missing"
        with file_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        assert data.get("uid") == expected_uid, f"Dashboard {filename} has UID '{data.get('uid')}', expected '{expected_uid}'"
        assert "panels" in data and len(data["panels"]) > 0, f"Dashboard {filename} has no panels"


def test_guardrail_metric_single_counting():
    """Verify _guardrail_response does not re-increment Prometheus counters."""
    import ast

    app_path = REPO_ROOT / "backend" / "app.py"
    tree = ast.parse(app_path.read_text(encoding="utf-8"))
    
    guardrail_resp_func = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_guardrail_response":
            guardrail_resp_func = node
            break

    assert guardrail_resp_func is not None, "_guardrail_response function not found in app.py"

    # Walk all function calls inside _guardrail_response and ensure no .inc() or GUARDRAIL_* labels calls
    src_lines = app_path.read_text(encoding="utf-8").splitlines()[guardrail_resp_func.lineno - 1:guardrail_resp_func.end_lineno]
    src_text = "\n".join(src_lines)

    assert "GUARDRAIL_BLOCKS.labels" not in src_text, "GUARDRAIL_BLOCKS must not be incremented in _guardrail_response"
    assert "GUARDRAIL_ACTIONS.labels" not in src_text, "GUARDRAIL_ACTIONS must not be incremented in _guardrail_response"


def test_capstone_recovery_tiering():
    """Verify Capstone recovery levels: Card 07 must be Level 0 (not_required)."""
    from Capstone_Scenarios.capstone_common import CARD_REVERT_MAP

    assert 7 in CARD_REVERT_MAP, "Card 07 missing in CARD_REVERT_MAP"
    card_07_info = CARD_REVERT_MAP[7]
    assert card_07_info["level"] == 0, "Card 07 must be Recovery Level 0 (not_required)"
    assert len(card_07_info["cases"]) == 0, "Card 07 must not reset test cases"
    assert len(card_07_info["env_vars"]) == 0, "Card 07 must not reset env vars"

    # Verify stateful cards have Level 1
    assert CARD_REVERT_MAP[5]["level"] == 1, "Card 05 must be Recovery Level 1"
    assert "SIMULATE_AGENT_STEP_DELAY_MS" in CARD_REVERT_MAP[5]["env_vars"]


def test_docker_run_prefix_normalization():
    """Verify docker_run avoids duplicating docker executable prefix."""
    from scripts.deploy_common import docker_cmd, docker_run
    import unittest.mock as mock

    dcmd = docker_cmd()
    with mock.patch("scripts.deploy_common.run_capture", return_value=(0, "", "")) as mock_run:
        # Case 1: Caller passes [dcmd, "compose", "up"]
        docker_run([dcmd, "compose", "up"])
        mock_run.assert_called_with([dcmd, "compose", "up"], cwd=None, check=True)

        # Case 2: Caller passes ["compose", "up"]
        docker_run(["compose", "up"])
        mock_run.assert_called_with([dcmd, "compose", "up"], cwd=None, check=True)


if __name__ == "__main__":
    print("[RUNNING] Capstone demonstration regression tests...")
    test_dashboard_json_integrity()
    print("  [PASS] All 8 Grafana dashboards verified with valid JSON and expected UIDs.")
    test_guardrail_metric_single_counting()
    print("  [PASS] Guardrail Prometheus metrics verified for single-point accounting.")
    test_capstone_recovery_tiering()
    print("  [PASS] Capstone 3-tier recovery model verified (Card 07 = Level 0).")
    test_docker_run_prefix_normalization()
    print("  [PASS] Docker command wrapper prefix normalization verified.")
    print("[ALL REGRESSION TESTS PASSED]")
