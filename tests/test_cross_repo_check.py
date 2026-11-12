"""P16's linked run must not treat DataTalksClub Gate B seals as package evidence.

The DTC donor checkout must also keep full Git history: the unchanged Gate B
operator guard reads a historical workflow blob through `git show`, which
cannot resolve that commit in a shallow checkout (issue 408).
"""

from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/cross-repo-check.yml"


def test_the_dtc_verdict_subtracts_the_link_step_gate_b_artefacts():
    text = WORKFLOW.read_text()

    dtc_job = text.split("ai-shipping-labs:")[0]
    assert "p16-link-artefacts.txt" in dtc_job
    assert "FAIL: test_pyproject_seal_rejects_synthetic_unreviewed_drift" in dtc_job
    assert "FAIL: test_gate_b_operator_contract_is_exact_and_workflow_isolated" in dtc_job


def dtc_donor_checkout_step():
    text = WORKFLOW.read_text()

    dtc_job = text.split("ai-shipping-labs:")[0]
    start = dtc_job.index("Check out DataTalksClub/website")
    return dtc_job[start : dtc_job.index("- uses: astral-sh/setup-uv@v7", start)]


def test_the_dtc_donor_checkout_fetches_full_history_for_the_historical_guard():
    step = dtc_donor_checkout_step()

    assert "repository: DataTalksClub/website" in step
    assert "fetch-depth: 0" in step
    assert "ref: ${{ inputs.dtc_website_ref || '' }}" in step
    assert "path: dtc-website" in step


def test_only_the_dtc_donor_checkout_fetches_full_history():
    text = WORKFLOW.read_text()

    aisl_job = text.split("ai-shipping-labs:", 1)[1]
    assert "fetch-depth" not in aisl_job


def test_the_aisl_job_shards_the_suite_while_keeping_baseline_verdict_semantics():
    text = WORKFLOW.read_text()

    aisl_job = text.split("ai-shipping-labs:", 1)[1]
    assert (
        'name: "AI-Shipping-Labs/website: real test suite against this package '
        '(shard ${{ matrix.shard }}/${{ strategy.job-total }})"'
    ) in aisl_job
    assert "fail-fast: false" in aisl_job
    assert "shard: [1, 2, 3, 4]" in aisl_job
    assert 'TEST_SHARD_COUNT: "4"' in aisl_job
    assert "TEST_SHARD_INDEX: ${{ matrix.shard }}" in aisl_job
    assert (
        'comm -13 "$GITHUB_WORKSPACE/baseline-failures.txt" "$GITHUB_WORKSPACE/linked-failures.txt"'
        in aisl_job
    )
