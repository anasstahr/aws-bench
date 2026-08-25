"""Tests for the Bedrock-aware Codex agent's rules-file support."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aws_bench.agents.codex import Codex


@pytest.fixture
def logs_dir(tmp_path: Path) -> Path:
    return tmp_path / "logs"


def _fresh_environment() -> MagicMock:
    environment = MagicMock()
    environment.exec = AsyncMock(return_value=MagicMock(return_code=0, stdout="", stderr=""))
    return environment


def _commands(environment: MagicMock) -> list[str]:
    return [c.kwargs.get("command", "") for c in environment.exec.call_args_list]


def test_name_is_codex():
    assert Codex.name() == "codex"


def test_defaults_to_no_rules_file(logs_dir: Path):
    assert Codex(logs_dir=logs_dir)._rules_file is None


@pytest.mark.asyncio
async def test_run_writes_rules_file_as_agents_md(logs_dir: Path, tmp_path: Path):
    """The rules file is injected as AGENTS.md during the run."""
    rules = tmp_path / "aws-agent-rules.md"
    rules.write_text("# AWS rules\n", encoding="utf-8")
    agent = Codex(logs_dir=logs_dir, model_name="gpt-5", rules_file=str(rules))
    environment = _fresh_environment()

    # Non-Bedrock mode keeps the run simple; clear the token that would trigger it.
    with patch.dict("os.environ", {}, clear=True):
        await agent.run("Do the task", environment, MagicMock())

    rules_cmds = [c for c in _commands(environment) if "base64 -d >> AGENTS.md" in c]
    assert rules_cmds


@pytest.mark.asyncio
async def test_run_without_rules_file_writes_no_agents_md(logs_dir: Path):
    agent = Codex(logs_dir=logs_dir, model_name="gpt-5")
    environment = _fresh_environment()

    with patch.dict("os.environ", {}, clear=True):
        await agent.run("Do the task", environment, MagicMock())

    assert not any("AGENTS.md" in c for c in _commands(environment))
