"""Application composition root for the MCP stdio runner.

Bootstrap wires CLI parsing, the explicit plugin registry, configuration
loading, secret-safe logging, and the FastMCP stdio lifecycle. It performs no
network access during import or startup: configuration is validated locally and
upstream connections are opened lazily by tools.
"""

from __future__ import annotations

import argparse
import logging
import os
from collections.abc import Mapping, Sequence

from mcp_stdio.contracts.plugin import PluginRuntime
from mcp_stdio.core.config import ConfigError
from mcp_stdio.core.logging import configure_logging
from mcp_stdio.core.server import StdioMcpServer
from mcp_stdio.registry import get_plugin_definition


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """Parse the runner CLI arguments."""

    parser = argparse.ArgumentParser(
        prog="mcp-stdio",
        description="Run one built-in MCP plugin over stdio.",
    )
    parser.add_argument(
        "--plugin",
        required=True,
        help="Built-in plugin name (hive, zeppelin, or dolphinscheduler).",
    )
    parser.add_argument(
        "--config",
        required=False,
        default=None,
        help=(
            "Path to a versioned YAML or JSON configuration file. Optional; "
            "when omitted, all settings and secrets are read from "
            "<PREFIX>_<FIELD> environment variables."
        ),
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging to stderr (secrets stay redacted).",
    )
    return parser.parse_args(argv)


def construct_runtime(
    args: argparse.Namespace,
    *,
    environ: Mapping[str, str],
) -> PluginRuntime:
    """Select and construct one plugin runtime without network access."""

    definition = get_plugin_definition(args.plugin)
    return definition.create_runtime(args.config, environ=environ)


def main(argv: Sequence[str] | None = None) -> None:
    """Start the configured MCP stdio process."""

    args = parse_args(argv)
    configure_logging(debug=args.debug)
    logger = logging.getLogger("mcp_stdio")

    try:
        runtime = construct_runtime(args, environ=os.environ)
    except ConfigError as error:
        logger.error("%s", error)
        raise SystemExit(2) from None

    configure_logging(debug=args.debug, secret_values=runtime.redaction_values)
    StdioMcpServer(runtime, debug=args.debug).run()
