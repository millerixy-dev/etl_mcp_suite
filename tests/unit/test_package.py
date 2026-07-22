from importlib.metadata import entry_points

import mcp_stdio


def test_package_and_console_entry_point_are_importable() -> None:
    assert mcp_stdio.__doc__

    entry_point = next(
        item for item in entry_points(group="console_scripts") if item.name == "mcp-stdio"
    )

    assert entry_point.value == "mcp_stdio.__main__:main"
    assert callable(entry_point.load())
