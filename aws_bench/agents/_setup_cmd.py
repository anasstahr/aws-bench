"""Run an operator-supplied command inside the agent container during setup.

Wired from ``--ak setup_cmd="<shell>"`` on the run CLI (or a profile's
``cli_args_append.run``). The command runs as the agent user in the agent's own
container, after the agent is installed and before the task runs. That is the
right place to prime the container — e.g. warm a ``uvx`` MCP-proxy cache so a
slow server connects before the first turn — which a runner-side ``pre_run_cmd``
cannot reach (it runs on the runner host, not in the agent container).

Arbitrary and framework-agnostic; empty by default (no-op).
"""

from __future__ import annotations

from typing import Any

from harbor.environments.base import BaseEnvironment


class AgentSetupCmdMixin:
    """Adds an optional ``setup_cmd`` that runs in-container during agent setup.

    Place FIRST in the MRO (``class Foo(AgentSetupCmdMixin, HarborAgent)``) so
    this ``__init__`` intercepts ``setup_cmd`` before the Harbor base agent,
    which would otherwise reject the unknown kwarg.
    """

    def __init__(self, *args: Any, setup_cmd: str | None = None, **kwargs: Any) -> None:
        self._setup_cmd = setup_cmd
        super().__init__(*args, **kwargs)

    async def run_setup_cmd(self, environment: BaseEnvironment) -> None:
        """Run ``setup_cmd`` in the agent container, if one was supplied."""
        if not self._setup_cmd:
            return
        await self.exec_as_agent(environment, command=self._setup_cmd)  # type: ignore[attr-defined]
