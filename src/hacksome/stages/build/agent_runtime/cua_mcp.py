"""Foundagent VM layer — minimal MCP server: the cua container's "hands".

Exposes ATOMIC Computer Use primitives (screenshot / click / type / key) of a
running cua-ubuntu container to an MCP client (Claude Code). Claude — running on
the user's Claude *subscription* — is the brain and calls these tools directly.

This is deliberately NOT cua-mcp-server: that package wraps a SECOND cua-agent
LLM (litellm, API key) to run whole tasks. Here Claude keeps direct control, so
we stay on the subscription and there is no second model.

Connects to the already-running container's computer-server (port 8000) via the
cua-computer SDK.

The Build agent image copies this module to ``/opt/foundagent/cua_mcp.py`` and
registers it as a stdio MCP server.
"""

import os

from computer import Computer  # type: ignore[import-not-found]
from mcp.server.fastmcp import FastMCP, Image  # type: ignore[import-not-found]

IMAGE = os.environ.get("CUA_IMAGE", "foundagent/cua-ubuntu:latest")
NAME = os.environ.get("CUA_CONTAINER", "founder-01")

mcp = FastMCP("cua-founder")
_computer: Computer | None = None


async def _conn() -> Computer:
    """Lazily connect to the container's computer-server (singleton).

    Two modes via env:
    - CUA_HOST_SERVER=1 → container-side (Claude runs INSIDE the container):
      connect directly to the local computer-server at localhost:8000.
    - default → host-side: drive the named docker container from the host.
    """
    global _computer
    if _computer is None:
        if os.environ.get("CUA_HOST_SERVER", "").lower() in ("1", "true", "yes"):
            c = Computer(
                os_type="linux",
                use_host_computer_server=True,
                api_host=os.environ.get("CUA_API_HOST", "localhost"),
            )
        else:
            c = Computer(os_type="linux", provider_type="docker", image=IMAGE, name=NAME)
        await c.run()
        _computer = c
    return _computer


@mcp.tool()
async def screenshot() -> Image:
    """Capture the container desktop. Returns a PNG image of the current screen."""
    c = await _conn()
    data = await c.interface.screenshot()
    return Image(data=bytes(data), format="png")


@mcp.tool()
async def get_screen_size() -> str:
    """Return the desktop resolution as '{width, height}'."""
    c = await _conn()
    return str(await c.interface.get_screen_size())


@mcp.tool()
async def left_click(x: int, y: int) -> str:
    """Left-click at pixel coordinate (x, y) on the container desktop."""
    c = await _conn()
    await c.interface.left_click(x, y)
    return f"left_click ({x},{y})"


@mcp.tool()
async def double_click(x: int, y: int) -> str:
    """Double-click at pixel coordinate (x, y) (e.g. to open a desktop icon)."""
    c = await _conn()
    await c.interface.double_click(x, y)
    return f"double_click ({x},{y})"


@mcp.tool()
async def type_text(text: str) -> str:
    """Type the given text into the currently focused element."""
    c = await _conn()
    await c.interface.type_text(text)
    return f"typed {len(text)} chars"


@mcp.tool()
async def press_key(key: str) -> str:
    """Press a single key or chord, e.g. 'Return', 'Tab', 'ctrl+l', 'Escape'."""
    c = await _conn()
    await c.interface.press_key(key)
    return f"pressed {key}"


if __name__ == "__main__":
    mcp.run()
