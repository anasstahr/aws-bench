"""Shared support for injecting an agent rules file into a trial.

Most coding agents read a project-level *rules file* on startup and treat its
contents as persistent instructions for the session — the AWS Agent Toolkit
publishes a recommended one that steers agents toward the AWS MCP Server,
skill discovery, and infrastructure-as-code. See
https://docs.aws.amazon.com/agent-toolkit/latest/userguide/rules-files.html

The file name and location are per-agent (``CLAUDE.md``, ``AGENTS.md``,
``.kiro/steering/*.md``, ...). :class:`RulesFileMixin` centralizes the shared
plumbing: a ``rules_file`` constructor kwarg (a *host* path, threaded from
``--ak rules_file=...``), early validation, and writing the content to the
agent's expected location inside the trial environment before the run.

Each agent subclass sets :attr:`RulesFileMixin.RULES_FILE_TARGET` to the path
it reads, *relative to the directory the agent runs in*. Every ``exec`` in a
trial shares the same working directory, so a relative target lands in the
agent's project root regardless of the image's absolute working directory —
matching the "project root" semantics of the AWS documentation. The content is
appended (``>>``), never clobbering a rules file a task may already ship.
"""

from __future__ import annotations

import base64
import posixpath
import shlex
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from aws_bench.cli.preflight import PreflightError

if TYPE_CHECKING:
    # At type-check time, borrow BaseInstalledAgent's members (exec_as_agent,
    # logger, setup, ...); at runtime this is a plain mixin over object so it
    # composes with any agent via cooperative multiple inheritance.
    from harbor.agents.installed.base import BaseInstalledAgent as _Base
    from harbor.environments.base import BaseEnvironment
else:
    _Base = object


class RulesFileMixin(_Base):
    """Adds an optional ``rules_file`` to an installed agent.

    Subclasses must set :attr:`RULES_FILE_TARGET` to the agent's rules-file
    path, relative to the directory the agent runs in.
    """

    # Relative path the agent reads its rules from (e.g. "CLAUDE.md"). Empty
    # means the agent has no rules-file location and injection is a no-op.
    RULES_FILE_TARGET: ClassVar[str] = ""

    def __init__(self, *args: Any, rules_file: str | None = None, **kwargs: Any) -> None:
        """Store the host path to the rules file, if any, then defer to the agent.

        Args:
            *args: Forwarded to the wrapped agent.
            rules_file: Host path to a rules file whose contents are injected
                into the agent's environment before the run. ``None`` disables
                injection.
            **kwargs: Forwarded to the wrapped agent.
        """
        self._rules_file = rules_file
        super().__init__(*args, **kwargs)

    def _validate_rules_file(self) -> None:
        """Fail fast (before install) if a rules file was requested but is missing."""
        if self._rules_file and not Path(self._rules_file).is_file():
            raise PreflightError(
                f"rules_file {self._rules_file!r} was passed but is not a readable file. "
                "Pass a path to an existing rules file, e.g. "
                "--ak rules_file=/path/to/aws-agent-rules.md"
            )

    async def setup(self, environment: BaseEnvironment) -> None:
        """Validate the rules file before the (slow) agent install runs."""
        self._validate_rules_file()
        await super().setup(environment)

    async def _write_rules_file(self, environment: BaseEnvironment) -> None:
        """Append the rules file's contents to the agent's rules location.

        No-op when no rules file was requested or the agent declares no target.
        Content is base64-encoded on the host and decoded in the container so
        arbitrary text (quotes, newlines, ``$``) survives intact.
        """
        if not self._rules_file or not self.RULES_FILE_TARGET:
            return

        content = Path(self._rules_file).read_text(encoding="utf-8")
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        target = self.RULES_FILE_TARGET
        parent = posixpath.dirname(target)

        mkdir = f"mkdir -p {shlex.quote(parent)} && " if parent else ""
        command = f"{mkdir}printf %s {shlex.quote(encoded)} | base64 -d >> {shlex.quote(target)}"
        await self.exec_as_agent(environment, command=command)
