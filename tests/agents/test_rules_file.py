"""Tests for the shared rules-file injection support."""

from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from harbor.agents.installed.base import BaseInstalledAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

from aws_bench.agents.rules_file import RulesFileMixin
from aws_bench.cli.preflight import PreflightError


class _FakeAgent(RulesFileMixin, BaseInstalledAgent):
    """Concrete agent that records the commands the mixin would exec."""

    RULES_FILE_TARGET = "CLAUDE.md"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.exec_commands: list[str] = []

    @staticmethod
    def name() -> str:
        return "fake"

    def version(self) -> str | None:
        return None

    async def install(self, environment: BaseEnvironment) -> None:
        pass

    async def run(
        self, instruction: str, environment: BaseEnvironment, context: AgentContext
    ) -> None:
        pass

    async def exec_as_agent(
        self,
        environment: BaseEnvironment,
        command: str,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        timeout_sec: int | None = None,
    ) -> MagicMock:
        self.exec_commands.append(command)
        return MagicMock(return_code=0)


class _NoTargetAgent(_FakeAgent):
    RULES_FILE_TARGET = ""


class _NestedTargetAgent(_FakeAgent):
    RULES_FILE_TARGET = ".kiro/steering/aws-agent-rules.md"


@pytest.fixture
def logs_dir(tmp_path: Path) -> Path:
    return tmp_path / "logs"


@pytest.fixture
def rules_file(tmp_path: Path) -> Path:
    path = tmp_path / "aws-agent-rules.md"
    path.write_text("# AWS rules\nUse the AWS MCP Server.\n", encoding="utf-8")
    return path


def _async_environment() -> MagicMock:
    environment = MagicMock()
    environment.exec = AsyncMock(return_value=MagicMock(return_code=0, stdout="", stderr=""))
    return environment


# ── init ──


def test_defaults_to_no_rules_file(logs_dir: Path):
    """Without the kwarg, no rules file is tracked."""
    assert _FakeAgent(logs_dir=logs_dir)._rules_file is None


def test_stores_rules_file_path(logs_dir: Path, rules_file: Path):
    """The host path is stored for later injection."""
    agent = _FakeAgent(logs_dir=logs_dir, rules_file=str(rules_file))
    assert agent._rules_file == str(rules_file)


# ── validation ──


def test_validate_raises_when_rules_file_missing(logs_dir: Path, tmp_path: Path):
    """A requested-but-missing rules file is rejected."""
    agent = _FakeAgent(logs_dir=logs_dir, rules_file=str(tmp_path / "nope.md"))
    with pytest.raises(PreflightError, match="rules_file"):
        agent._validate_rules_file()


def test_validate_rejects_directory(logs_dir: Path, tmp_path: Path):
    """A directory path is not a readable file."""
    agent = _FakeAgent(logs_dir=logs_dir, rules_file=str(tmp_path))
    with pytest.raises(PreflightError, match="rules_file"):
        agent._validate_rules_file()


def test_validate_passes_when_no_rules_file(logs_dir: Path):
    """No rules file requested → validation is a no-op."""
    _FakeAgent(logs_dir=logs_dir)._validate_rules_file()  # does not raise


def test_validate_passes_for_existing_rules_file(logs_dir: Path, rules_file: Path):
    """An existing rules file passes validation."""
    _FakeAgent(logs_dir=logs_dir, rules_file=str(rules_file))._validate_rules_file()


@pytest.mark.asyncio
async def test_setup_validates_before_install(logs_dir: Path, tmp_path: Path):
    """setup() runs validation before delegating to the agent's install."""
    agent = _FakeAgent(logs_dir=logs_dir, rules_file=str(tmp_path / "missing.md"))
    with pytest.raises(PreflightError, match="rules_file"):
        await agent.setup(_async_environment())


# ── write ──


@pytest.mark.asyncio
async def test_write_is_noop_without_rules_file(logs_dir: Path):
    """No rules file → no command is executed."""
    agent = _FakeAgent(logs_dir=logs_dir)
    await agent._write_rules_file(_async_environment())
    assert agent.exec_commands == []


@pytest.mark.asyncio
async def test_write_is_noop_without_target(logs_dir: Path, rules_file: Path):
    """An agent with no rules-file location skips injection."""
    agent = _NoTargetAgent(logs_dir=logs_dir, rules_file=str(rules_file))
    await agent._write_rules_file(_async_environment())
    assert agent.exec_commands == []


@pytest.mark.asyncio
async def test_write_appends_decoded_content_to_target(logs_dir: Path, rules_file: Path):
    """Content is base64-decoded and appended to the target path."""
    agent = _FakeAgent(logs_dir=logs_dir, rules_file=str(rules_file))
    await agent._write_rules_file(_async_environment())

    assert len(agent.exec_commands) == 1
    command = agent.exec_commands[0]
    encoded = base64.b64encode(rules_file.read_bytes()).decode("ascii")
    assert encoded in command
    assert "base64 -d >>" in command
    assert command.rstrip().endswith("CLAUDE.md")


@pytest.mark.asyncio
async def test_write_creates_parent_dir_for_nested_target(logs_dir: Path, rules_file: Path):
    """Nested targets (e.g. Kiro steering) get their parent directory created first."""
    agent = _NestedTargetAgent(logs_dir=logs_dir, rules_file=str(rules_file))
    await agent._write_rules_file(_async_environment())

    command = agent.exec_commands[0]
    assert "mkdir -p .kiro/steering" in command
    assert command.index("mkdir -p") < command.index("base64 -d")


@pytest.mark.asyncio
async def test_write_no_mkdir_for_top_level_target(logs_dir: Path, rules_file: Path):
    """A top-level target needs no directory creation."""
    agent = _FakeAgent(logs_dir=logs_dir, rules_file=str(rules_file))
    await agent._write_rules_file(_async_environment())

    assert "mkdir" not in agent.exec_commands[0]
