#!/usr/bin/env bash
# mcp-profile.sh — Switch Claude Code MCP servers between local and cloud profiles.
#
# Manages user-scope (~/.claude.json) MCP registrations for:
#   - coordination: Agent coordinator (local DB vs Railway HTTP)
#   - newsletter-aggregator: ACA MCP server (local stdio vs Railway SSE)
#
# Usage:
#   scripts/mcp-profile.sh status               # Show current profile for each server
#   scripts/mcp-profile.sh switch local          # Switch all servers to local
#   scripts/mcp-profile.sh switch cloud          # Switch all servers to cloud
#   scripts/mcp-profile.sh switch local coord    # Switch only coordination
#   scripts/mcp-profile.sh switch cloud aca      # Switch only newsletter-aggregator
#
# Configuration:
#   Profiles are defined in scripts/mcp-profiles.json (edit to match your setup).
#   Secrets (API keys, URLs) are resolved from environment variables at switch time.
#
# After switching, restart Claude Code for changes to take effect.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROFILES_FILE="$SCRIPT_DIR/mcp-profiles.json"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

ok()   { echo -e "${GREEN}[OK]${NC}    $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $1"; }
err()  { echo -e "${RED}[ERR]${NC}   $1"; }
info() { echo -e "${CYAN}[INFO]${NC}  $1"; }

usage() {
    cat <<'EOF'
Usage: scripts/mcp-profile.sh <command> [args]

Commands:
  status                          Show current profile for each server
  switch <local|cloud> [server]   Switch servers to a profile
  list                            List available profiles and servers

Servers:
  coord, coordination             Agent coordinator
  aca, newsletter-aggregator      Newsletter aggregator MCP
  (omit to switch all servers)

Environment variables (used by cloud profiles):
  COORDINATION_API_URL            Coordinator HTTP URL (default: https://coord.rotkohl.ai)
  COORDINATION_API_KEY            Coordinator API key
  ACA_MCP_URL                     Newsletter-aggregator MCP SSE URL
  ACA_MCP_ADMIN_KEY               Newsletter-aggregator MCP admin key

Examples:
  scripts/mcp-profile.sh status
  scripts/mcp-profile.sh switch local
  scripts/mcp-profile.sh switch cloud
  scripts/mcp-profile.sh switch cloud coord
  scripts/mcp-profile.sh switch local aca
EOF
}

# ---------------------------------------------------------------------------
# Profile definitions
# ---------------------------------------------------------------------------
# Generates the JSON config for a given server + profile.
# Uses environment variables for secrets so they're never hardcoded.

coord_local_json() {
    local python_bin="$PROJECT_DIR/agent-coordinator/.venv/bin/python"
    local run_mcp="$PROJECT_DIR/agent-coordinator/run_mcp.py"
    local dsn="${POSTGRES_DSN:-postgresql://postgres:postgres@localhost:54322/postgres}"

    cat <<EOF
{
  "type": "stdio",
  "command": "$python_bin",
  "args": ["$run_mcp"],
  "env": {
    "DB_BACKEND": "postgres",
    "POSTGRES_DSN": "$dsn",
    "AGENT_ID": "${AGENT_ID:-claude-code-1}",
    "AGENT_TYPE": "${AGENT_TYPE:-claude_code}"
  }
}
EOF
}

coord_cloud_json() {
    local python_bin="$PROJECT_DIR/agent-coordinator/.venv/bin/python"
    local run_mcp="$PROJECT_DIR/agent-coordinator/run_mcp.py"
    local api_url="${COORDINATION_API_URL:-https://coord.rotkohl.ai}"
    local api_key="${COORDINATION_API_KEY:-}"

    if [[ -z "$api_key" ]]; then
        warn "COORDINATION_API_KEY not set — server will fail to authenticate" >&2
    fi

    cat <<EOF
{
  "type": "stdio",
  "command": "$python_bin",
  "args": ["$run_mcp"],
  "env": {
    "COORDINATION_API_URL": "$api_url",
    "COORDINATION_API_KEY": "$api_key",
    "AGENT_ID": "${AGENT_ID:-claude-code-1}",
    "AGENT_TYPE": "${AGENT_TYPE:-claude_code}"
  }
}
EOF
}

aca_local_json() {
    local aca_dir="${ACA_PROJECT_DIR:-$HOME/Coding/agentic-newsletter-aggregator}"
    local aca_mcp="$aca_dir/.venv/bin/aca-mcp"

    if [[ ! -x "$aca_mcp" ]]; then
        warn "aca-mcp not found at $aca_mcp — install with: cd $aca_dir && uv sync" >&2
    fi

    cat <<EOF
{
  "type": "stdio",
  "command": "$aca_mcp",
  "args": []
}
EOF
}

aca_cloud_json() {
    local aca_url="${ACA_MCP_URL:-}"
    local admin_key="${ACA_MCP_ADMIN_KEY:-}"

    if [[ -z "$aca_url" ]]; then
        err "ACA_MCP_URL not set — cannot configure cloud profile" >&2
        err "Set it to your Railway MCP SSE endpoint (e.g. https://aca.up.railway.app/mcp/sse)" >&2
        return 1
    fi
    if [[ -z "$admin_key" ]]; then
        warn "ACA_MCP_ADMIN_KEY not set — server may reject requests" >&2
    fi

    cat <<EOF
{
  "type": "sse",
  "url": "$aca_url",
  "headers": {
    "X-Admin-Key": "$admin_key"
  }
}
EOF
}

# ---------------------------------------------------------------------------
# Server resolution
# ---------------------------------------------------------------------------
resolve_server() {
    case "${1:-}" in
        coord|coordination)       echo "coordination" ;;
        aca|newsletter-aggregator) echo "newsletter-aggregator" ;;
        "") echo "all" ;;
        *)
            err "Unknown server: $1"
            echo ""
            return 1
            ;;
    esac
}

# ---------------------------------------------------------------------------
# Status command
# ---------------------------------------------------------------------------
detect_profile() {
    local server="$1"

    # Read directly from ~/.claude.json (claude mcp get outputs human-readable text, not JSON)
    python3 -c "
import json, sys, pathlib

claude_json = pathlib.Path.home() / '.claude.json'
if not claude_json.exists():
    print('not-registered')
    sys.exit(0)

data = json.loads(claude_json.read_text())
servers = data.get('mcpServers', {})
server = servers.get('$server')

if not server:
    print('not-registered')
    sys.exit(0)

if '$server' == 'coordination':
    env = server.get('env', {})
    if 'POSTGRES_DSN' in env:
        print('local')
    elif 'COORDINATION_API_URL' in env:
        print('cloud')
    else:
        print('unknown')
elif '$server' == 'newsletter-aggregator':
    t = server.get('type', 'stdio')
    if t == 'stdio':
        print('local')
    elif t in ('sse', 'streamable-http'):
        print('cloud')
    else:
        print('unknown')
else:
    print('unknown')
" 2>/dev/null || echo "unknown"
}

cmd_status() {
    echo ""
    echo -e "${BOLD}MCP Server Profiles${NC}"
    echo "────────────────────────────────────────"

    for server in coordination newsletter-aggregator; do
        local profile
        profile=$(detect_profile "$server")

        case "$profile" in
            local)          echo -e "  $server: ${GREEN}local${NC}" ;;
            cloud)          echo -e "  $server: ${CYAN}cloud${NC}" ;;
            not-registered) echo -e "  $server: ${YELLOW}not registered${NC}" ;;
            *)              echo -e "  $server: ${RED}unknown${NC}" ;;
        esac
    done

    echo "────────────────────────────────────────"
    echo ""
}

# ---------------------------------------------------------------------------
# Switch command
# ---------------------------------------------------------------------------
switch_server() {
    local server="$1"
    local profile="$2"
    local json_func="${server//-/_}"  # newsletter-aggregator → newsletter_aggregator

    # Map to short function name prefix
    case "$server" in
        coordination)          json_func="coord" ;;
        newsletter-aggregator) json_func="aca" ;;
    esac

    local func="${json_func}_${profile}_json"

    # Generate config JSON
    local config
    config=$($func) || return 1

    # Remove existing registration (suppress errors if not registered)
    claude mcp remove --scope user "$server" 2>/dev/null || true

    # Register with new profile
    claude mcp add-json --scope user "$server" "$config" 2>/dev/null
    ok "$server → $profile"
}

cmd_switch() {
    local profile="${1:-}"
    local server_arg="${2:-}"

    if [[ -z "$profile" ]]; then
        err "Usage: mcp-profile.sh switch <local|cloud> [server]"
        exit 1
    fi

    if [[ "$profile" != "local" && "$profile" != "cloud" ]]; then
        err "Profile must be 'local' or 'cloud', got: $profile"
        exit 1
    fi

    local target
    target=$(resolve_server "$server_arg") || exit 1

    echo ""
    echo -e "${BOLD}Switching to ${CYAN}$profile${NC}${BOLD} profile${NC}"
    echo "────────────────────────────────────────"

    if [[ "$target" == "all" || "$target" == "coordination" ]]; then
        switch_server "coordination" "$profile"
    fi

    if [[ "$target" == "all" || "$target" == "newsletter-aggregator" ]]; then
        switch_server "newsletter-aggregator" "$profile"
    fi

    echo "────────────────────────────────────────"
    echo ""
    info "Restart Claude Code for changes to take effect."
}

# ---------------------------------------------------------------------------
# List command
# ---------------------------------------------------------------------------
cmd_list() {
    echo ""
    echo -e "${BOLD}Available MCP Profiles${NC}"
    echo "────────────────────────────────────────"
    echo ""
    echo -e "${BOLD}Servers:${NC}"
    echo "  coordination (coord)            Agent coordinator"
    echo "  newsletter-aggregator (aca)     Newsletter aggregator MCP"
    echo ""
    echo -e "${BOLD}Profiles:${NC}"
    echo "  local    stdio transport, local DB/venv"
    echo "  cloud    HTTP/SSE transport, Railway endpoints"
    echo ""
    echo -e "${BOLD}Coordination:${NC}"
    echo "  local  → stdio via run_mcp.py, POSTGRES_DSN for direct DB"
    echo "  cloud  → stdio via run_mcp.py, COORDINATION_API_URL for HTTP proxy"
    echo ""
    echo -e "${BOLD}Newsletter-aggregator:${NC}"
    echo "  local  → stdio via .venv/bin/aca-mcp"
    echo "  cloud  → SSE via ACA_MCP_URL with X-Admin-Key auth"
    echo "────────────────────────────────────────"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    local cmd="${1:-}"
    shift || true

    case "$cmd" in
        status)  cmd_status ;;
        switch)  cmd_switch "$@" ;;
        list)    cmd_list ;;
        -h|--help|help|"")
            usage
            exit 0
            ;;
        *)
            err "Unknown command: $cmd"
            usage >&2
            exit 1
            ;;
    esac
}

main "$@"
