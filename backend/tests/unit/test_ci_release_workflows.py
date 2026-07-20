"""Structural tests for CI, action pins, and non-publishing workflows."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from musimack_tools.ci import CiAuditError, audit_migrations, audit_repository, audit_workflows

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_ROOT = REPOSITORY_ROOT / ".github" / "workflows"


def test_expected_workflows_and_immutable_action_pins() -> None:
    result = audit_workflows(REPOSITORY_ROOT)
    assert result["workflows"] == 2
    references = result["action_references"]
    assert isinstance(references, list) and references
    assert all(re.fullmatch(r"actions/[a-z-]+@[0-9a-f]{40}", value) for value in references)


def test_ci_has_pr_main_concurrency_and_explicit_runners() -> None:
    value = (WORKFLOW_ROOT / "ci.yml").read_text(encoding="utf-8")
    assert "pull_request:" in value
    assert "push:" in value and "- main" in value
    assert "ubuntu-24.04" in value
    assert "windows-2025" in value
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in value
    assert "persist-credentials: false" in value
    assert "package-manager-cache: false" in value


def test_release_workflow_is_manual_exact_commit_and_nonpublishing() -> None:
    value = (WORKFLOW_ROOT / "release-candidate.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in value
    assert "candidate_identifier:" in value and "commit:" in value
    assert "needs: validate-input" in value
    assert "ref: ${{ inputs.commit }}" in value
    assert "REQUESTED_COMMIT" in value
    assert "retention-days: 5" in value
    assert "name: musimack-release-candidate" in value
    for prohibited in (
        "pull_request_target",
        "contents: write",
        "git tag",
        "git push",
        "gh release",
    ):
        assert prohibited not in value.casefold()


def test_every_action_reference_has_tag_comment_and_is_official() -> None:
    for workflow in WORKFLOW_ROOT.glob("*.yml"):
        for line in workflow.read_text(encoding="utf-8").splitlines():
            if "uses:" not in line:
                continue
            assert re.search(r"uses: actions/[a-z-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+", line)


def test_setup_python_uses_default_no_cache_configuration() -> None:
    setup_python = re.compile(
        r"uses: "
        r"actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1 # v6\.3\.0"
        r"(?P<body>.*?)(?=\n\s+- name:|\Z)",
        re.DOTALL,
    )
    blocks = [
        match.group("body")
        for workflow in WORKFLOW_ROOT.glob("*.yml")
        for match in setup_python.finditer(workflow.read_text(encoding="utf-8"))
    ]
    assert len(blocks) == 3
    assert all("python-version: 3.14.4" in block for block in blocks)
    assert all("cache:" not in block for block in blocks)
    assert all('"false"' not in block and "'false'" not in block for block in blocks)


def test_workflow_audit_rejects_mutable_or_third_party_action(tmp_path: Path) -> None:
    workflows = tmp_path / ".github/workflows"
    workflows.mkdir(parents=True)
    safe = (WORKFLOW_ROOT / "ci.yml").read_text(encoding="utf-8")
    (workflows / "ci.yml").write_text(
        safe.replace(
            "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0", "actions/checkout@v7"
        ),
        encoding="utf-8",
    )
    (workflows / "release-candidate.yml").write_text(
        (WORKFLOW_ROOT / "release-candidate.yml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    with pytest.raises(CiAuditError, match="action_reference_invalid"):
        audit_workflows(tmp_path)


def test_repository_audit_detects_secrets_and_prohibited_artifacts(tmp_path: Path) -> None:
    clean = tmp_path / "safe.txt"
    clean.write_text("safe", encoding="utf-8")
    assert audit_repository(tmp_path) == {"prohibited_artifacts": 0, "secret_matches": 0}
    secret = tmp_path / "secret.txt"
    secret.write_text("-----BEGIN " + "PRIVATE KEY-----", encoding="utf-8")
    with pytest.raises(CiAuditError, match="secret_matches"):
        audit_repository(tmp_path)
    secret.unlink()
    (tmp_path / "generated.sqlite3").write_bytes(b"database")
    with pytest.raises(CiAuditError, match="prohibited_artifacts"):
        audit_repository(tmp_path)


def test_action_pin_record_covers_every_reference() -> None:
    record = (REPOSITORY_ROOT / "docs/action-pins.md").read_text(encoding="utf-8")
    for workflow in WORKFLOW_ROOT.glob("*.yml"):
        for action, sha in re.findall(
            r"uses: (actions/[a-z-]+)@([0-9a-f]{40})", workflow.read_text(encoding="utf-8")
        ):
            assert action in record
            assert sha in record


def test_migration_audit_upgrades_an_empty_database() -> None:
    result = audit_migrations(REPOSITORY_ROOT / "backend")
    assert result == {
        "head_count": 1,
        "head": "0016_site_audit_settings",
        "parent": "0015_sitemap_recommendation_retention",
        "empty_database_upgrade": "passed",
    }


def test_migration_audit_rejects_divergent_heads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DivergentScripts:
        @staticmethod
        def get_heads() -> tuple[str, str]:
            return ("0015_sitemap_recommendation_retention", "0015_divergent")

    monkeypatch.setattr(
        "musimack_tools.ci.ScriptDirectory.from_config",
        staticmethod(lambda _configuration: DivergentScripts()),
    )
    with pytest.raises(CiAuditError, match="migration_heads_invalid"):
        audit_migrations(REPOSITORY_ROOT / "backend")
