"""Launch the cadview MCP server from wherever the package is installed.

Gives consumer repos a stable .mcp.json that survives venv layouts:

    { "mcpServers": { "cadview": {
        "command": "uv", "args": ["run", "python", "-m", "cadview.mcp"] } } }

(Plain `python -m cadview.mcp` works too.) Requires node on PATH.
"""
import os
import sys
from pathlib import Path


def main():
    server = Path(__file__).parent / "plugin" / "server.mjs"
    try:
        os.execvp("node", ["node", str(server), *sys.argv[1:]])
    except FileNotFoundError:
        sys.exit("cadview.mcp needs `node` on PATH (any recent version)")


if __name__ == "__main__":
    main()
