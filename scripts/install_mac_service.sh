#!/usr/bin/env bash
# Bakoverkompatibel wrapper. Bruk scripts/install_mac_quick_action.sh.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/install_mac_quick_action.sh" "$@"
