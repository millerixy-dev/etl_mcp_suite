#!/bin/sh

set -eu

usage() {
    case "${client-}" in
        codex|trae)
            if [ "$client" = codex ]; then
                printf 'Usage: install-skills-codex.sh [--project-root PATH] [--force] [--with-mcp]\n'
            else
                printf 'Usage: install-skills-trae.sh [--project-root PATH] [--force]\n'
            fi
            ;;
        *)
            program_name=$(basename "$0")
            printf 'Usage: %s <codex|trae> [--project-root PATH] [--force]\n' "$program_name"
            ;;
    esac
}

fail() {
    printf 'Error: %s\n' "$1" >&2
    exit 1
}

warn() {
    printf 'Warning: %s\n' "$1" >&2
}

managed_begin='# BEGIN mcp-stdio managed'
managed_end='# END mcp-stdio managed'
mcp_block_temp=
mcp_output_temp=

cleanup() {
    if [ -n "$mcp_block_temp" ]; then
        rm -f -- "$mcp_block_temp"
    fi
    if [ -n "$mcp_output_temp" ]; then
        rm -f -- "$mcp_output_temp"
    fi
}

trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

if [ "$#" -lt 1 ]; then
    usage >&2
    exit 2
fi

client=$1
shift

case "$client" in
    codex)
        client_directory=.codex
        ;;
    trae)
        client_directory=.trae
        ;;
    *)
        fail "unsupported client '$client'"
        ;;
esac

project_root=
force=0
with_mcp=0

while [ "$#" -gt 0 ]; do
    case "$1" in
        --project-root)
            [ "$#" -ge 2 ] || fail "--project-root requires a path"
            project_root=$2
            shift 2
            ;;
        --force)
            force=1
            shift
            ;;
        --with-mcp)
            [ "$client" = codex ] || fail "--with-mcp is currently supported for Codex only"
            with_mcp=1
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            fail "unknown argument '$1'"
            ;;
    esac
done

if [ -z "$project_root" ]; then
    project_root=$(pwd -P)
elif [ -d "$project_root" ]; then
    project_root=$(CDPATH= cd -- "$project_root" && pwd -P)
else
    fail "project root is not a directory: $project_root"
fi

script_directory=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
repository_root=$(CDPATH= cd -- "$script_directory/.." && pwd -P)
source_root=$repository_root/skills
destination_root=$project_root/$client_directory/skills
managed_skills="hive zeppelin nl2sql"

codex_config=$project_root/.codex/config.toml

if [ "$with_mcp" -eq 1 ] && [ -e "$codex_config" ]; then
    [ ! -L "$codex_config" ] || fail "refusing to replace symlink: $codex_config"
    [ -f "$codex_config" ] || fail "Codex config is not a regular file: $codex_config"

    begin_count=$(awk -v marker="$managed_begin" '$0 == marker { count++ } END { print count + 0 }' "$codex_config")
    end_count=$(awk -v marker="$managed_end" '$0 == marker { count++ } END { print count + 0 }' "$codex_config")
    if [ "$begin_count" -ne "$end_count" ] || [ "$begin_count" -gt 1 ]; then
        fail "Codex config has malformed or duplicate mcp-stdio managed markers: $codex_config"
    fi

    if awk -v begin="$managed_begin" -v end="$managed_end" '
        $0 == begin { inside = 1; next }
        $0 == end { inside = 0; next }
        !inside && $0 ~ /^[[:space:]]*\[mcp_servers\.(hive|zeppelin)\][[:space:]]*(#.*)?$/ {
            conflict = 1
        }
        END { exit conflict ? 0 : 1 }
    ' "$codex_config"; then
        fail "Codex config already has an unmanaged Hive or Zeppelin MCP table: $codex_config"
    fi
fi

for skill_name in $managed_skills; do
    source_skill=$source_root/$skill_name
    [ -f "$source_skill/SKILL.md" ] || fail "canonical skill is missing: $source_skill"

    target_skill=$destination_root/$skill_name
    if [ -L "$target_skill" ]; then
        fail "refusing to overwrite symlink: $target_skill"
    fi
    if [ -e "$target_skill" ] && [ ! -d "$target_skill" ]; then
        fail "managed skill target is not a directory: $target_skill"
    fi
    if [ -d "$target_skill" ] && [ "$force" -ne 1 ]; then
        fail "managed skill already exists: $target_skill (use --force to overwrite)"
    fi
done

uv_tool_bin=
if [ "$with_mcp" -eq 1 ]; then
    command -v uv >/dev/null 2>&1 || fail "uv is required for --with-mcp"
    if ! uv_tool_bin=$(uv tool dir --bin); then
        fail "could not determine the uv tool executable directory"
    fi
    [ -n "$uv_tool_bin" ] || fail "uv reported an empty tool executable directory"
    [ -d "$uv_tool_bin" ] || fail "uv tool executable directory does not exist: $uv_tool_bin"
    uv_tool_bin=$(CDPATH= cd -- "$uv_tool_bin" && pwd -P)
    case ":$PATH:" in
        *":$uv_tool_bin:"*) ;;
        *) fail "uv tool executable directory is not on PATH: $uv_tool_bin" ;;
    esac

    uv tool install --editable "$repository_root" --reinstall
    expected_command=$uv_tool_bin/mcp-stdio
    [ -x "$expected_command" ] || fail "editable uv tool did not install mcp-stdio into $uv_tool_bin"
    resolved_command=$(command -v mcp-stdio || true)
    [ "$resolved_command" = "$expected_command" ] || fail "mcp-stdio does not resolve to the uv tool executable: $expected_command"

    config_directory=$project_root/.codex
    mkdir -p "$config_directory"
    mcp_block_temp=$(mktemp "$config_directory/.mcp-stdio-block.XXXXXX")
    mcp_output_temp=$(mktemp "$config_directory/.config.toml.XXXXXX")

    {
        printf '%s\n' "$managed_begin"
        printf '%s\n' '[mcp_servers.hive]'
        printf '%s\n' 'command = "mcp-stdio"'
        printf '%s\n' 'args = ["--plugin", "hive"]'
        printf '%s\n' 'env_vars = ['
        printf '%s\n' '  "HIVE_HOST",'
        printf '%s\n' '  "HIVE_PORT",'
        printf '%s\n' '  "HIVE_DATABASE",'
        printf '%s\n' '  "HIVE_CACHE_TTL_SECONDS",'
        printf '%s\n' '  "HIVE_USERNAME",'
        printf '%s\n' '  "HIVE_PASSWORD",'
        printf '%s\n' ']'
        printf '\n'
        printf '%s\n' '[mcp_servers.zeppelin]'
        printf '%s\n' 'command = "mcp-stdio"'
        printf '%s\n' 'args = ["--plugin", "zeppelin"]'
        printf '%s\n' 'env_vars = ['
        printf '%s\n' '  "ZEPPELIN_BASE_URL",'
        printf '%s\n' '  "ZEPPELIN_ALLOWED_INTERPRETERS",'
        printf '%s\n' '  "ZEPPELIN_USERNAME",'
        printf '%s\n' '  "ZEPPELIN_PASSWORD",'
        printf '%s\n' ']'
        printf '%s\n' "$managed_end"
    } > "$mcp_block_temp"

    if [ -f "$codex_config" ] && [ "$begin_count" -eq 1 ]; then
        awk -v begin="$managed_begin" -v end="$managed_end" -v block="$mcp_block_temp" '
            $0 == begin {
                while ((getline line < block) > 0) print line
                close(block)
                inside = 1
                next
            }
            inside && $0 == end { inside = 0; next }
            inside { next }
            { print }
        ' "$codex_config" > "$mcp_output_temp"
    else
        if [ -s "$codex_config" ]; then
            awk '{ print }' "$codex_config" > "$mcp_output_temp"
            printf '\n' >> "$mcp_output_temp"
        fi
        awk '{ print }' "$mcp_block_temp" >> "$mcp_output_temp"
    fi

    mv -- "$mcp_output_temp" "$codex_config"
    mcp_output_temp=
    rm -f -- "$mcp_block_temp"
    mcp_block_temp=
fi

mkdir -p "$destination_root"

for skill_name in $managed_skills; do
    source_skill=$source_root/$skill_name
    target_skill=$destination_root/$skill_name
    mkdir -p "$target_skill"
    cp -R "$source_skill/." "$target_skill/"
done

printf 'Installed hive, zeppelin, and nl2sql skills into %s\n' "$destination_root"

if [ "$with_mcp" -eq 1 ]; then
    printf 'Configured Hive and Zeppelin MCP servers in %s\n' "$codex_config"
    for variable_name in HIVE_HOST HIVE_USERNAME HIVE_PASSWORD ZEPPELIN_BASE_URL; do
        case "$variable_name" in
            HIVE_HOST) variable_value=${HIVE_HOST-} ;;
            HIVE_USERNAME) variable_value=${HIVE_USERNAME-} ;;
            HIVE_PASSWORD) variable_value=${HIVE_PASSWORD-} ;;
            ZEPPELIN_BASE_URL) variable_value=${ZEPPELIN_BASE_URL-} ;;
        esac
        if [ -z "$variable_value" ]; then
            warn "runtime environment variable is not set: $variable_name"
        fi
    done
fi
