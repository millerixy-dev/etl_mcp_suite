"""Console entry point for the MCP stdio runner."""


def main() -> None:
    """Delegate startup to the composition root."""
    from mcp_stdio.bootstrap import main as bootstrap_main

    bootstrap_main()


if __name__ == "__main__":
    main()
