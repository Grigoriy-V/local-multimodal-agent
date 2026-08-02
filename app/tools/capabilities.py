"""One registry that turns a scoped grant into model-visible tools."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from app.tools.base import Tool, Toolbox
from app.tools.browser import browser_tools
from app.tools.filesystem import filesystem_tools

FILESYSTEM_READ = "filesystem.read"
FILESYSTEM_WRITE = "filesystem.write"
BROWSER_INSPECT = "browser.inspect"
DEFAULT_CAPABILITIES = (FILESYSTEM_READ, FILESYSTEM_WRITE, BROWSER_INSPECT)


@dataclass(frozen=True)
class Capability:
    name: str
    build: Callable[[Path], list[Tool]]


@dataclass(frozen=True)
class CapabilityGrant:
    root: Path
    capabilities: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root).resolve())
        object.__setattr__(self, "capabilities", tuple(dict.fromkeys(self.capabilities)))

    def allows(self, capability: str) -> bool:
        return capability in self.capabilities


def _filesystem_read(root: Path) -> list[Tool]:
    return filesystem_tools(root)[:2]


def _filesystem_write(root: Path) -> list[Tool]:
    return filesystem_tools(root)[2:]


class CapabilityRegistry:
    """Validate grants and expose only the tools they allow."""

    def __init__(
        self,
        workspace: Path,
        capabilities: Iterable[Capability] | None = None,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        if not self.workspace.is_dir():
            raise ValueError(f"the workspace {workspace} is not a directory")
        configured = (
            capabilities
            if capabilities is not None
            else (
                Capability(FILESYSTEM_READ, _filesystem_read),
                Capability(FILESYSTEM_WRITE, _filesystem_write),
                Capability(BROWSER_INSPECT, browser_tools),
            )
        )
        self._capabilities = {capability.name: capability for capability in configured}

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._capabilities)

    def grant(
        self,
        root: str | Path | None = None,
        capabilities: Iterable[str] = DEFAULT_CAPABILITIES,
    ) -> CapabilityGrant:
        supplied = Path(root) if root is not None else self.workspace
        allowed_root = (
            supplied.resolve()
            if supplied.is_absolute()
            else (self.workspace / supplied).resolve()
        )
        if allowed_root != self.workspace and self.workspace not in allowed_root.parents:
            raise PermissionError("capability grant root is outside the workspace")
        if not allowed_root.is_dir():
            raise ValueError("capability grant root is not a directory")
        requested = tuple(dict.fromkeys(capabilities))
        unknown = [name for name in requested if name not in self._capabilities]
        if unknown:
            raise ValueError(f"unknown capabilities: {', '.join(unknown)}")
        return CapabilityGrant(allowed_root, requested)

    def toolbox(
        self, grant: CapabilityGrant, extra_tools: Iterable[Tool] = ()
    ) -> Toolbox:
        checked = self.grant(grant.root, grant.capabilities)
        tools: list[Tool] = []
        for name in checked.capabilities:
            tools.extend(self._capabilities[name].build(checked.root))
        tools.extend(extra_tools)
        names = [tool.name for tool in tools]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"duplicate tool names: {', '.join(duplicates)}")
        return Toolbox(tools)
