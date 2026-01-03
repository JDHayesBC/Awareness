#!/bin/bash
# Install Lyra Daemons as user-level systemd services
# Usage: ./install.sh [--uninstall]
#
# Installs two services:
#   lyra-discord    - Discord presence and conversation handling
#   lyra-reflection - Autonomous reflection and maintenance

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get the daemon directory
DAEMON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"

# Service definitions
SERVICES=("lyra-discord" "lyra-reflection")

# Helper functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

uninstall_service() {
    log_info "Uninstalling Lyra daemons..."

    for SERVICE in "${SERVICES[@]}"; do
        log_info "Processing ${SERVICE}..."

        # Stop the service
        if systemctl --user is-active --quiet "${SERVICE}"; then
            log_info "Stopping ${SERVICE}..."
            systemctl --user stop "${SERVICE}"
            log_success "${SERVICE} stopped"
        fi

        # Disable the service
        if systemctl --user is-enabled "${SERVICE}" &>/dev/null; then
            log_info "Disabling ${SERVICE}..."
            systemctl --user disable "${SERVICE}"
            log_success "${SERVICE} disabled"
        fi

        # Remove the service file
        if [ -f "${SYSTEMD_USER_DIR}/${SERVICE}.service" ]; then
            rm -f "${SYSTEMD_USER_DIR}/${SERVICE}.service"
            log_success "${SERVICE}.service removed"
        fi
    done

    # Reload systemd
    systemctl --user daemon-reload
    log_success "Systemd daemon reloaded"

    log_success "Uninstallation complete"
    exit 0
}

# Main installation
install_service() {
    log_info "Installing Lyra daemons as user services"
    log_info "Daemon directory: ${DAEMON_DIR}"

    # Check if daemon directory exists
    if [ ! -d "${DAEMON_DIR}" ]; then
        log_error "Daemon directory not found: ${DAEMON_DIR}"
        exit 1
    fi

    # Check if .env file exists
    if [ ! -f "${DAEMON_DIR}/.env" ]; then
        log_error ".env file not found in ${DAEMON_DIR}"
        log_error "Please copy .env.example to .env and configure it"
        exit 1
    fi

    # Create systemd user directory
    mkdir -p "${SYSTEMD_USER_DIR}"
    log_success "Created systemd user directory"

    # Create logs directory
    mkdir -p "${DAEMON_DIR}/logs"
    log_success "Created logs directory"

    # Install each service
    for SERVICE in "${SERVICES[@]}"; do
        SERVICE_FILE="${SERVICE}.service"

        if [ ! -f "${DAEMON_DIR}/systemd/${SERVICE_FILE}" ]; then
            log_error "Service file not found: ${DAEMON_DIR}/systemd/${SERVICE_FILE}"
            exit 1
        fi

        # Copy service file
        cp "${DAEMON_DIR}/systemd/${SERVICE_FILE}" "${SYSTEMD_USER_DIR}/${SERVICE_FILE}"
        log_success "Copied ${SERVICE_FILE} to ${SYSTEMD_USER_DIR}"
    done

    # Reload systemd
    systemctl --user daemon-reload
    log_success "Systemd daemon reloaded"

    # Enable and start each service
    for SERVICE in "${SERVICES[@]}"; do
        # Enable the service
        systemctl --user enable "${SERVICE}"
        log_success "${SERVICE} enabled"

        # Start the service
        log_info "Starting ${SERVICE}..."
        if systemctl --user start "${SERVICE}"; then
            log_success "${SERVICE} started successfully"
        else
            log_error "Failed to start ${SERVICE}"
            exit 1
        fi
    done

    # Show status
    log_info "Service status:"
    for SERVICE in "${SERVICES[@]}"; do
        echo ""
        echo "=== ${SERVICE} ==="
        systemctl --user status "${SERVICE}" --no-pager 2>&1 | head -10 || true
    done

    log_success "Installation complete!"
    log_info "Use the ./lyra script for easy management:"
    echo "  ./lyra status   - Show daemon status"
    echo "  ./lyra start    - Start daemons"
    echo "  ./lyra stop     - Stop daemons"
    echo "  ./lyra restart  - Restart daemons"
    echo "  ./lyra logs     - Show recent logs"
    echo "  ./lyra follow   - Follow logs live"
}

# Check for uninstall flag
if [ "$1" == "--uninstall" ] || [ "$1" == "-u" ]; then
    uninstall_service
fi

# Run installation
install_service
