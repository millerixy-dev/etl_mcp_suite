from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest
import yaml

PROJECT_ROOT = Path(__file__).parents[2]
CANONICAL_SKILLS = {
    "hive": {"list_databases", "list_tables", "get_table_schema"},
    "zeppelin": {
        "list_notebooks",
        "create_notebook",
        "add_paragraph",
        "run_paragraph",
        "get_paragraph_status",
        "get_paragraph_result",
        "cancel_paragraph",
        "restart_interpreter",
    },
    "nl2sql": {
        "list_databases",
        "list_tables",
        "get_table_schema",
        "list_notebooks",
        "create_notebook",
        "add_paragraph",
        "run_paragraph",
        "get_paragraph_status",
        "get_paragraph_result",
    },
}
REQUIRED_GUIDANCE = {
    "hive": {"partition_columns", "[A-Za-z_][A-Za-z0-9_]*", "zeppelin"},
    "zeppelin": {"/agents/", "PENDING", "RUNNING", "FINISHED", "ERROR", "CANCELLED"},
    "nl2sql": {"partition_columns", "SHOW PARTITIONS", "LIMIT", "zeppelin", "hive"},
}
LEGACY_COUPLING_SAMPLES = (
    'run_mcp(server_name="mcp_hive", tool_name="list_databases", args={})',
    'run_mcp(server_name="mcp_zeppelin", tool_name="list_notebooks", args={})',
    'create_notebook {"name":"/trae/test"}',
)
PROHIBITED_COUPLING = (
    "run_mcp",
    "mcp_hive",
    "mcp_zeppelin",
    "/trae/",
    "codex",
    "trae",
    "mcp__",
)
INSTALLERS = (
    ("install-skills-codex.sh", ".codex"),
    ("install-skills-trae.sh", ".trae"),
)
MANAGED_BEGIN = "# BEGIN mcp-stdio managed"
MANAGED_END = "# END mcp-stdio managed"


def load_skill(path: Path) -> tuple[dict[str, object], str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path} is missing YAML frontmatter"

    frontmatter_text, separator, body = text[4:].partition("\n---\n")
    assert separator, f"{path} has unterminated YAML frontmatter"

    raw_frontmatter = cast(object, yaml.safe_load(frontmatter_text))
    assert isinstance(raw_frontmatter, Mapping), f"{path} frontmatter must be a mapping"
    parsed_mapping = cast(Mapping[object, object], raw_frontmatter)
    frontmatter: dict[str, object] = {}
    for key, value in parsed_mapping.items():
        assert isinstance(key, str), f"{path} frontmatter keys must be strings"
        frontmatter[key] = value
    return frontmatter, body


def agent_coupling(text: str) -> set[str]:
    normalized = text.casefold()
    return {marker for marker in PROHIBITED_COUPLING if marker.casefold() in normalized}


def fake_uv_environment(
    tmp_path: Path,
    *,
    tool_bin_on_path: bool = True,
    include_required_runtime_variables: bool = True,
) -> tuple[dict[str, str], Path, Path]:
    fake_bin = tmp_path / "fake-bin"
    tool_bin = tmp_path / "uv-tool-bin"
    reported_tool_bin = tool_bin if tool_bin_on_path else tmp_path / "hidden-tool-bin"
    fake_bin.mkdir()
    tool_bin.mkdir()
    reported_tool_bin.mkdir(exist_ok=True)
    uv_log = tmp_path / "uv.log"
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        """#!/bin/sh
set -eu
printf '%s\\n' "$*" >> "$FAKE_UV_LOG"
if [ "$#" -eq 3 ] && [ "$1" = tool ] && [ "$2" = dir ] && [ "$3" = --bin ]; then
    printf '%s\\n' "$FAKE_UV_TOOL_BIN"
    exit 0
fi
if [ "$#" -eq 5 ] && [ "$1" = tool ] && [ "$2" = install ] && \
    [ "$3" = --editable ] && [ "$5" = --reinstall ]; then
    printf '#!/bin/sh\\nexit 0\\n' > "$FAKE_UV_TOOL_BIN/mcp-stdio"
    chmod +x "$FAKE_UV_TOOL_BIN/mcp-stdio"
    exit 0
fi
exit 64
""",
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)

    path_parts = [str(fake_bin)]
    if tool_bin_on_path:
        path_parts.append(str(tool_bin))
    path_parts.append(os.environ["PATH"])
    environment = {
        **os.environ,
        "PATH": os.pathsep.join(path_parts),
        "FAKE_UV_LOG": str(uv_log),
        "FAKE_UV_TOOL_BIN": str(reported_tool_bin),
    }
    if include_required_runtime_variables:
        environment.update(
            {
                "HIVE_HOST": "example-hive-host",
                "HIVE_USERNAME": "example-hive-user",
                "HIVE_PASSWORD": "example-hive-password",
                "ZEPPELIN_BASE_URL": "https://zeppelin.example.test",
            }
        )
    return environment, uv_log, reported_tool_bin


@pytest.mark.parametrize(("skill_name", "required_tools"), CANONICAL_SKILLS.items())
def test_canonical_skill_is_portable_and_covers_required_tools(
    skill_name: str,
    required_tools: set[str],
) -> None:
    skill_path = PROJECT_ROOT / "skills" / skill_name / "SKILL.md"

    frontmatter, body = load_skill(skill_path)

    assert set(frontmatter) == {"name", "description"}
    assert frontmatter["name"] == skill_name
    description = frontmatter["description"]
    assert isinstance(description, str)
    assert description.startswith("Use when")
    assert not agent_coupling(skill_path.read_text(encoding="utf-8"))
    assert required_tools <= {tool for tool in required_tools if tool in body}
    assert REQUIRED_GUIDANCE[skill_name] <= {
        marker for marker in REQUIRED_GUIDANCE[skill_name] if marker in body
    }


@pytest.mark.parametrize("legacy_sample", LEGACY_COUPLING_SAMPLES)
def test_agent_coupling_detects_legacy_client_markers(legacy_sample: str) -> None:
    coupling = agent_coupling(legacy_sample)

    assert coupling


@pytest.mark.parametrize(("script_name", "client_directory"), INSTALLERS)
def test_installer_defaults_to_current_project_and_preserves_unrelated_skills(
    script_name: str,
    client_directory: str,
    tmp_path: Path,
) -> None:
    installer = PROJECT_ROOT / "scripts" / script_name
    project_root = tmp_path / "target project"
    unrelated_file = project_root / client_directory / "skills" / "custom" / "KEEP.md"
    unrelated_file.parent.mkdir(parents=True)
    unrelated_file.write_text("keep me\n", encoding="utf-8")

    assert installer.is_file()
    assert os.access(installer, os.X_OK)
    completed = subprocess.run(
        [str(installer)],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert unrelated_file.read_text(encoding="utf-8") == "keep me\n"
    for skill_name in CANONICAL_SKILLS:
        source = PROJECT_ROOT / "skills" / skill_name / "SKILL.md"
        installed = project_root / client_directory / "skills" / skill_name / "SKILL.md"
        assert installed.read_bytes() == source.read_bytes()


@pytest.mark.parametrize(("script_name", "client_directory"), INSTALLERS)
def test_installer_requires_force_for_collision_before_copying_any_skill(
    script_name: str,
    client_directory: str,
    tmp_path: Path,
) -> None:
    installer = PROJECT_ROOT / "scripts" / script_name
    project_root = tmp_path / "target"
    colliding_file = project_root / client_directory / "skills" / "hive" / "SKILL.md"
    colliding_file.parent.mkdir(parents=True)
    colliding_file.write_text("local customization\n", encoding="utf-8")

    blocked = subprocess.run(
        [str(installer), "--project-root", str(project_root)],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert blocked.returncode != 0
    assert colliding_file.read_text(encoding="utf-8") == "local customization\n"
    assert not (project_root / client_directory / "skills" / "zeppelin").exists()
    assert not (project_root / client_directory / "skills" / "nl2sql").exists()

    forced = subprocess.run(
        [str(installer), "--project-root", str(project_root), "--force"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert forced.returncode == 0, forced.stderr
    for skill_name in CANONICAL_SKILLS:
        source = PROJECT_ROOT / "skills" / skill_name / "SKILL.md"
        installed = project_root / client_directory / "skills" / skill_name / "SKILL.md"
        assert installed.read_bytes() == source.read_bytes()


@pytest.mark.parametrize(("script_name", "_client_directory"), INSTALLERS)
def test_installer_help_names_the_public_entry_point(
    script_name: str,
    _client_directory: str,
) -> None:
    completed = subprocess.run(
        [str(PROJECT_ROOT / "scripts" / script_name), "--help"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    expected_suffix = " [--with-mcp]" if script_name == "install-skills-codex.sh" else ""
    assert (
        f"Usage: {script_name} [--project-root PATH] [--force]{expected_suffix}"
        in completed.stdout
    )


def test_codex_with_mcp_installs_editable_tool_and_manages_path_free_config(
    tmp_path: Path,
) -> None:
    installer = PROJECT_ROOT / "scripts" / "install-skills-codex.sh"
    project_root = tmp_path / "target"
    config_path = project_root / ".codex" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text('model = "gpt-5"\n', encoding="utf-8")
    environment, uv_log, _tool_bin = fake_uv_environment(tmp_path)

    installed = subprocess.run(
        [str(installer), "--project-root", str(project_root), "--with-mcp"],
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert installed.returncode == 0, installed.stderr
    assert uv_log.read_text(encoding="utf-8").splitlines() == [
        "tool dir --bin",
        f"tool install --editable {PROJECT_ROOT} --reinstall",
    ]
    config = config_path.read_text(encoding="utf-8")
    assert config.startswith('model = "gpt-5"\n')
    assert config.count(MANAGED_BEGIN) == 1
    assert config.count(MANAGED_END) == 1
    assert config.count("[mcp_servers.hive]") == 1
    assert config.count("[mcp_servers.zeppelin]") == 1
    assert 'command = "mcp-stdio"' in config
    assert 'args = ["--plugin", "hive"]' in config
    assert 'args = ["--plugin", "zeppelin"]' in config
    assert "env_vars = [" in config
    for variable_name in (
        "HIVE_HOST",
        "HIVE_USERNAME",
        "HIVE_PASSWORD",
        "ZEPPELIN_BASE_URL",
        "ZEPPELIN_ALLOWED_INTERPRETERS",
    ):
        assert f'"{variable_name}"' in config
    for forbidden in (
        str(PROJECT_ROOT),
        "PYTHONPATH",
        ".venv",
        "example-hive-user",
        "example-hive-password",
        "https://zeppelin.example.test",
    ):
        assert forbidden not in config

    updated = subprocess.run(
        [str(installer), "--project-root", str(project_root), "--force", "--with-mcp"],
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert updated.returncode == 0, updated.stderr
    updated_config = config_path.read_text(encoding="utf-8")
    assert updated_config.startswith('model = "gpt-5"\n')
    assert updated_config.count(MANAGED_BEGIN) == 1
    assert updated_config.count(MANAGED_END) == 1


@pytest.mark.parametrize(
    "conflicting_config",
    (
        '[mcp_servers.hive]\ncommand = "custom-hive"\n',
        f"{MANAGED_BEGIN}\n[mcp_servers.hive]\n",
        (
            f"{MANAGED_BEGIN}\n[mcp_servers.hive]\n{MANAGED_END}\n"
            f"{MANAGED_BEGIN}\n[mcp_servers.zeppelin]\n{MANAGED_END}\n"
        ),
    ),
)
def test_codex_with_mcp_rejects_config_conflicts_before_any_mutation(
    tmp_path: Path,
    conflicting_config: str,
) -> None:
    installer = PROJECT_ROOT / "scripts" / "install-skills-codex.sh"
    project_root = tmp_path / "target"
    config_path = project_root / ".codex" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(conflicting_config, encoding="utf-8")
    environment, uv_log, _tool_bin = fake_uv_environment(tmp_path)

    completed = subprocess.run(
        [
            str(installer),
            "--project-root",
            str(project_root),
            "--force",
            "--with-mcp",
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert config_path.read_text(encoding="utf-8") == conflicting_config
    assert not uv_log.exists()
    assert not (project_root / ".codex" / "skills" / "hive").exists()


def test_codex_with_mcp_requires_uv_tool_bin_on_path_before_mutation(tmp_path: Path) -> None:
    installer = PROJECT_ROOT / "scripts" / "install-skills-codex.sh"
    project_root = tmp_path / "target"
    project_root.mkdir()
    environment, uv_log, _tool_bin = fake_uv_environment(tmp_path, tool_bin_on_path=False)

    completed = subprocess.run(
        [str(installer), "--project-root", str(project_root), "--with-mcp"],
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert uv_log.read_text(encoding="utf-8").splitlines() == ["tool dir --bin"]
    assert not (project_root / ".codex" / "config.toml").exists()
    assert not (project_root / ".codex" / "skills" / "hive").exists()


def test_codex_with_mcp_warns_with_missing_variable_names_only(tmp_path: Path) -> None:
    installer = PROJECT_ROOT / "scripts" / "install-skills-codex.sh"
    project_root = tmp_path / "target"
    project_root.mkdir()
    environment, _uv_log, _tool_bin = fake_uv_environment(
        tmp_path, include_required_runtime_variables=False
    )
    for variable_name in ("HIVE_HOST", "HIVE_USERNAME", "HIVE_PASSWORD", "ZEPPELIN_BASE_URL"):
        environment.pop(variable_name, None)

    completed = subprocess.run(
        [str(installer), "--project-root", str(project_root), "--with-mcp"],
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    for variable_name in ("HIVE_HOST", "HIVE_USERNAME", "HIVE_PASSWORD", "ZEPPELIN_BASE_URL"):
        assert variable_name in completed.stderr
    assert "example-hive-password" not in completed.stderr


def test_trae_installer_rejects_with_mcp(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    project_root.mkdir()

    completed = subprocess.run(
        [
            str(PROJECT_ROOT / "scripts" / "install-skills-trae.sh"),
            "--project-root",
            str(project_root),
            "--with-mcp",
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "Codex" in completed.stderr
    assert not (project_root / ".trae" / "skills" / "hive").exists()


def test_readme_documents_project_local_skill_installers() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    required_guidance = {
        "skills/hive",
        "skills/zeppelin",
        "skills/nl2sql",
        "./scripts/install-skills-codex.sh",
        "./scripts/install-skills-trae.sh",
        ".codex/skills",
        ".trae/skills",
        "--project-root",
        "--force",
        "--with-mcp",
        ".codex/config.toml",
        "uv tool install --editable",
        "env_vars",
        "HIVE_HOST",
        "HIVE_USERNAME",
        "HIVE_PASSWORD",
        "ZEPPELIN_BASE_URL",
        "Trae",
    }

    assert required_guidance <= {item for item in required_guidance if item in readme}


def test_readme_documents_uv_and_current_builtin_plugins() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    required_guidance = {
        "0.11.28",
        "brew install uv",
        "https://astral.sh/uv/install.sh",
        "Zeppelin notebook execution",
        "DolphinScheduler scheduling",
    }

    assert required_guidance <= {item for item in required_guidance if item in readme}
    assert "planned for separate follow-up changes" not in readme


def test_simplified_chinese_readme_is_linked_and_covers_core_usage() -> None:
    english_readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    chinese_readme_path = PROJECT_ROOT / "README.zh-CN.md"

    assert "[简体中文](README.zh-CN.md)" in english_readme
    assert chinese_readme_path.is_file()

    chinese_readme = chinese_readme_path.read_text(encoding="utf-8")
    assert "[English](README.md)" in chinese_readme
    for required_content in (
        "安装 uv（macOS）",
        "mcp-stdio",
        "--with-mcp",
        "Hive",
        "Zeppelin",
        "DolphinScheduler",
        "安全说明",
    ):
        assert required_content in chinese_readme
