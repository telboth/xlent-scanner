from __future__ import annotations

from pathlib import Path

CHECKOUT = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
SETUP_UV = "astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9"


def test_github_workflows_use_pinned_node24_actions() -> None:
    workflow_dir = Path(__file__).parents[1] / ".github" / "workflows"
    workflows = [
        (workflow_dir / "quality.yml").read_text(encoding="utf-8"),
        (workflow_dir / "build-release.yml").read_text(encoding="utf-8"),
    ]

    for workflow in workflows:
        assert "FORCE_JAVASCRIPT_ACTIONS_TO_NODE24" not in workflow
        assert "actions/checkout@v4" not in workflow
        assert "astral-sh/setup-uv@v5" not in workflow
        assert CHECKOUT in workflow
        assert SETUP_UV in workflow
        assert workflow.count("prune-cache: true") == workflow.count(SETUP_UV)
