"""P16's linked run must not treat DataTalksClub Gate B seals as package evidence."""

from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/cross-repo-check.yml"


def test_the_dtc_verdict_subtracts_the_link_step_gate_b_artefacts():
    text = WORKFLOW.read_text()

    dtc_job = text.split("ai-shipping-labs:")[0]
    assert "p16-link-artefacts.txt" in dtc_job
    assert "FAIL: test_pyproject_seal_rejects_synthetic_unreviewed_drift" in dtc_job
    assert "FAIL: test_gate_b_operator_contract_is_exact_and_workflow_isolated" in dtc_job
