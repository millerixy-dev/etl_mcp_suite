#!/bin/sh

set -eu

script_directory=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
exec "$script_directory/install-agent-skills.sh" codex "$@"
