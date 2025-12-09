#!/usr/bin/env python3
"""
SSE Project Service Manager - Shutdown Utility
===============================================

Gracefully stops all Docker services for the SSE Streaming Microservice project.
Follows systemd-style logging conventions for professional service management.

Usage:
    python stop_services.py

Components:
    - Performance Dashboard (frontend)
    - Backend Infrastructure (API, NGINX, Redis, Prometheus, Grafana, Kafka)

Author: Senior Solution Architect
"""

import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


# ANSI color codes for terminal output
class Colors:
    """Terminal color codes following systemd conventions."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    # Status colors
    OK = "\033[1;32m"  # Bold Green
    WARN = "\033[1;33m"  # Bold Yellow
    FAIL = "\033[1;31m"  # Bold Red
    INFO = "\033[1;34m"  # Bold Blue


# Project paths
ROOT_DIR = Path(__file__).parent.absolute()
DASHBOARD_DIR = ROOT_DIR / "performance_dashboard"


def get_timestamp() -> str:
    """Get current timestamp in systemd format."""
    return datetime.now().strftime("%b %d %H:%M:%S")


def print_status(status: str, message: str, detail: str = "") -> None:
    """
    Print a status message in systemd style.

    Args:
        status: Status indicator (OK, WARN, FAIL, INFO)
        message: Main message
        detail: Optional detail message
    """
    timestamp = get_timestamp()

    # Format status with appropriate color
    if status == "OK":
        status_str = f"{Colors.OK}  OK  {Colors.RESET}"
    elif status == "WARN":
        status_str = f"{Colors.WARN} WARN {Colors.RESET}"
    elif status == "FAIL":
        status_str = f"{Colors.FAIL} FAIL {Colors.RESET}"
    elif status == "INFO":
        status_str = f"{Colors.INFO} INFO {Colors.RESET}"
    else:
        status_str = f"[{status}]"

    # Print main message
    print(f"{Colors.DIM}{timestamp}{Colors.RESET} {status_str} {message}")

    # Print detail if provided
    if detail:
        print(f"{Colors.DIM}       {detail}{Colors.RESET}")


def run_command(command: str, cwd: Path, service_name: str) -> tuple[bool, float]:
    """
    Execute a shell command with proper logging.

    Args:
        command: Command to execute
        cwd: Working directory
        service_name: Name of service for logging

    Returns:
        Tuple of (success: bool, duration: float)
    """
    start_time = time.time()

    try:
        subprocess.run(
            command,
            cwd=str(cwd),
            shell=True,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        duration = time.time() - start_time
        return True, duration

    except subprocess.CalledProcessError as e:
        duration = time.time() - start_time
        error_msg = e.stderr.strip()

        # Check if this is a benign error (nothing to stop)
        if "No resource found" in error_msg or "no configuration file" in error_msg.lower():
            print_status(
                "INFO",
                f"{service_name}: No active containers",
                f"Completed in {duration:.2f}s",
            )
            return True, duration

        # Actual error
        print_status("FAIL", f"{service_name}: Failed to stop", f"Error: {error_msg[:100]}")
        return False, duration


def stop_service(
    service_name: str, directory: Path, compose_file: str = "docker-compose.yml"
) -> bool:
    """
    Stop a Docker Compose service.

    Args:
        service_name: Human-readable service name
        directory: Directory containing docker-compose.yml
        compose_file: Name of compose file

    Returns:
        bool: True if successful
    """
    compose_path = directory / compose_file

    # Check if directory exists
    if not directory.exists():
        print_status("WARN", f"{service_name}: Directory not found", f"Path: {directory}")
        return True  # Not an error, just skip

    # Check if compose file exists
    if not compose_path.exists():
        print_status("INFO", f"{service_name}: No compose file found", f"Skipping {compose_file}")
        return True  # Not an error, just skip

    # Announce stopping
    print_status("INFO", f"Stopping {service_name}...", f"Working directory: {directory.name}")

    # Execute docker-compose down
    success, duration = run_command("docker-compose down", directory, service_name)

    if success:
        print_status("OK", f"{service_name}: Stopped successfully", f"Completed in {duration:.2f}s")

    return success


def print_header() -> None:
    """Print service manager header."""
    print(f"\n{Colors.BOLD}SSE Project Service Manager{Colors.RESET}")
    print(f"{Colors.DIM}{'=' * 60}{Colors.RESET}")
    print(f"{Colors.DIM}Initiating graceful shutdown sequence...{Colors.RESET}\n")


def print_footer(total_duration: float, success: bool) -> None:
    """Print shutdown summary."""
    print(f"\n{Colors.DIM}{'=' * 60}{Colors.RESET}")

    if success:
        print_status(
            "OK", "Shutdown sequence completed", f"Total time: {total_duration:.2f}s"
        )
    else:
        print_status(
            "WARN",
            "Shutdown completed with warnings",
            f"Total time: {total_duration:.2f}s",
        )

    print()  # Empty line at end


def main() -> int:
    """
    Main execution flow.

    Returns:
        int: Exit code (0 for success, 1 for failure)
    """
    start_time = time.time()
    all_success = True

    try:
        print_header()

        # Step 1: Stop Dashboard (frontend consumer)
        print_status("INFO", "Phase 1: Frontend Services", "")
        dashboard_success = stop_service(
            service_name="Performance Dashboard", directory=DASHBOARD_DIR
        )
        all_success = all_success and dashboard_success

        # Brief pause between phases (like systemd)
        time.sleep(0.5)

        # Step 2: Stop Backend (infrastructure provider)
        print_status("INFO", "Phase 2: Backend Infrastructure", "")
        backend_success = stop_service(service_name="Backend Services", directory=ROOT_DIR)
        all_success = all_success and backend_success

        # Calculate total duration
        total_duration = time.time() - start_time

        # Print summary
        print_footer(total_duration, all_success)

        return 0 if all_success else 1

    except KeyboardInterrupt:
        print(f"\n\n{Colors.WARN}Shutdown interrupted by user{Colors.RESET}")
        return 130  # Standard exit code for SIGINT

    except Exception as e:
        print_status("FAIL", "Unexpected error occurred", str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
