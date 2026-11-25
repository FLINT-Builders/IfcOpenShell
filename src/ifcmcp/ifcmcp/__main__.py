# This file was generated with the assistance of an AI coding tool.
import argparse
import importlib.util
import os
import secrets
import sys

from ifcmcp import __version__


def main():
    parser = argparse.ArgumentParser(
        prog="python3 -m ifcmcp",
        description=(
            "ifcmcp — MCP server for IFC building models.\n\n"
            "Runs a Model Context Protocol server over stdio so that MCP clients\n"
            "can query and edit IFC files without writing them to disk between\n"
            "operations.\n\n"
            "Add to .mcp.json to configure:\n"
            '  {"mcpServers": {"ifc": {"type": "stdio", "command": "python3", "args": ["-m", "ifcmcp"]}}}'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"ifcmcp {__version__}")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help=(
            "MCP transport to use (default: stdio). HTTP transports require a bearer token, "
            "taken from IFCMCP_AUTH_TOKEN or generated and printed at startup"
        ),
    )

    args = parser.parse_args()

    if importlib.util.find_spec("mcp.server.fastmcp") is None:
        print(
            "error: the 'mcp' package is required to run the server.\nInstall it with:  pip install mcp",
            file=sys.stderr,
        )
        sys.exit(1)

    from ifcmcp.server import build_server

    auth_token = None
    if args.transport != "stdio":
        # HTTP transports are reachable by anyone who can connect to the port,
        # so every request must carry this token.
        auth_token = os.environ.get("IFCMCP_AUTH_TOKEN")
        if not auth_token:
            auth_token = secrets.token_urlsafe(32)
            print(
                f"ifcmcp: clients must send the header 'Authorization: Bearer {auth_token}'\n"
                "ifcmcp: set IFCMCP_AUTH_TOKEN to choose the token instead",
                file=sys.stderr,
                flush=True,
            )

    server = build_server(auth_token=auth_token)
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
