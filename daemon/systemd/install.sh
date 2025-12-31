#!/bin/bash
# Install Lyra Discord Daemon as a user-level systemd service
# Usage: ./install.sh [--uninstall]

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get the daemon directory
DAEMON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="lyra-daemon"
SERVICE_FILE="lyra-daemon.service"
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"

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
    log_info "Uninstalling ${SERVICE_NAME}..."

    # Stop the service
    if systemctl --user is-active --quiet "${SERVICE_NAME}"; then
        log_info "Stopping active service..."
        systemctl --user stop "${SERVICE_NAME}"
        log_success "Service stopped"
    fi

    # Disable the service
    if systemctl --user is-enabled "${SERVICE_NAME}" &>/dev/null; then
        log_info "Disabling service..."
        systemctl --user disable "${SERVICE_NAME}"
        log_success "Service disabled"
    fi

    # Remove the service file
    if [ -f "${SYSTEMD_USER_DIR}/${SERVICE_FILE}" ]; then
        rm -f "${SYSTEMD_USER_DIR}/${SERVICE_FILE}"
        log_success "Service file removed"
    fi

    # Reload systemd
    systemctl --user daemon-reload
    log_success "Systemd daemon reloaded"

    log_success "Uninstallation complete"
    exit 0
}

# Main installation
install_service() {
    log_info "Installing ${SERVICE_NAME} as user service"
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

    # Copy service file
    cp "${DAEMON_DIR}/systemd/${SERVICE_FILE}" "${SYSTEMD_USER_DIR}/${SERVICE_FILE}"
    log_success "Copied service file to ${SYSTEMD_USER_DIR}"

    # Create logs directory
    mkdir -p "${DAEMON_DIR}/logs"
    log_success "Created logs directory"

    # Reload systemd
    systemctl --user daemon-reload
    log_success "Systemd daemon reloaded"

    # Enable the service
    systemctl --user enable "${SERVICE_NAME}"
    log_success "Service enabled"

    # Start the service
    log_info "Starting service..."
    if systemctl --user start "${SERVICE_NAME}"; then
        log_success "Service started successfully"
    else
        log_error "Failed to start service"
        exit 1
    fi

    # Show status
    log_info "Service status:"
    systemctl --user status "${SERVICE_NAME}" --no-pager || true

    log_success "Installation complete!"
    log_info "Use the following commands to manage the service:"
    echo "  Start:   systemctl --user start ${SERVICE_NAME}"
    echo "  Stop:    systemctl --user stop ${SERVICE_NAME}"
    echo "  Status:  systemctl --user status ${SERVICE_NAME}"
    echo "  Logs:    journalctl --user -u ${SERVICE_NAME} -f"
    echo "  Restart: systemctl --user restart ${SERVICE_NAME}"
    echo "  Enable:  systemctl --user enable ${SERVICE_NAME}"
    echo "  Disable: systemctl --user disable ${SERVICE_NAME}"
}

# Check for uninstall flag
if [ "$1" == "--uninstall" ] || [ "$1" == "-u" ]; then
    uninstall_service
fi

# Run installation
install_service
