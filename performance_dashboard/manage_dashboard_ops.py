#!/usr/bin/env python3
"""
Performance Dashboard - Management Operations Script

This script provides comprehensive management operations for the Performance Dashboard
with proper prerequisite checks, status monitoring, and lifecycle management.

Features:
- Docker availability verification
- Backend network and health endpoint checks
- Interactive user prompts (default) or auto-start mode
- Colored terminal output for better UX
- Multiple operations: status, start, stop, restart

Usage:
    python manage_dashboard_ops.py <operation> [options]

Operations:
    status   - Check if dashboard is running
    start    - Start the dashboard with prerequisite checks
    stop     - Stop the running dashboard
    restart  - Restart the dashboard

Examples:
    python manage_dashboard_ops.py status
    python manage_dashboard_ops.py start --auto-start
    python manage_dashboard_ops.py stop
    python manage_dashboard_ops.py restart --skip-build

Author: Professional Implementation
Date: 2025-12-10
"""

import argparse
import subprocess
import sys
import time
import warnings
from pathlib import Path

# Optional dependencies with graceful fallbacks
try:
    import requests
    from urllib3.exceptions import InsecureRequestWarning
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

try:
    import colorama
    from colorama import Fore, Style
    colorama.init(autoreset=True)
    COLORAMA_AVAILABLE = True
except ImportError:
    COLORAMA_AVAILABLE = False
    # Define dummy color constants for fallback
    class DummyFore:
        CYAN = ""
        GREEN = ""
        YELLOW = ""
        RED = ""
        WHITE = ""
    Fore = DummyFore()
    Style = type('Style', (), {'BRIGHT': '', 'RESET_ALL': ''})()


class DashboardManager:
    """Professional dashboard manager with comprehensive lifecycle operations."""

    def __init__(self, auto_start: bool = False, skip_build: bool = False,
                 health_timeout: int = 3):
        self.auto_start = auto_start
        self.skip_build = skip_build
        self.health_timeout = health_timeout
        self.project_root = Path(__file__).parent
        self.parent_dir = self.project_root.parent

    def print_header(self) -> None:
        """Print the startup header."""
        print(f"{Fore.CYAN}{'='*50}")
        print(f"{Fore.CYAN}Performance Dashboard - Professional Start")
        print(f"{Fore.CYAN}{'='*50}")
        print()

    def print_success(self, message: str) -> None:
        """Print a success message."""
        print(f"{Fore.GREEN}✓ {message}")

    def print_warning(self, message: str) -> None:
        """Print a warning message."""
        print(f"{Fore.YELLOW}⚠ {message}")

    def print_error(self, message: str) -> None:
        """Print an error message."""
        print(f"{Fore.RED}✗ {message}")

    def print_info(self, message: str) -> None:
        """Print an informational message."""
        print(f"{Fore.CYAN}ℹ {message}")

    def run_command(self, cmd: list, cwd: Path | None = None,
                   capture_output: bool = True) -> tuple[bool, str, str]:
        """
        Run a shell command and return success status and output.

        Args:
            cmd: Command as list of strings
            cwd: Working directory for command
            capture_output: Whether to capture stdout/stderr

        Returns:
            Tuple of (success: bool, stdout: str, stderr: str)
        """
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd or self.project_root,
                capture_output=capture_output,
                text=True,
                check=False
            )
            return result.returncode == 0, result.stdout, result.stderr
        except FileNotFoundError:
            return False, "", f"Command not found: {' '.join(cmd)}"
        except Exception as e:
            return False, "", str(e)

    def check_docker_running(self) -> bool:
        """Check if Docker daemon is running."""
        self.print_info("Checking if Docker is running...")
        success, _, stderr = self.run_command(["docker", "info"])

        if success:
            self.print_success("Docker is running")
            return True
        else:
            self.print_error("Docker is not running")
            self.print_info("Please start Docker Desktop and try again")
            return False

    def check_backend_network(self) -> bool:
        """Check if the SSE backend network exists."""
        success, _, _ = self.run_command(["docker", "network", "inspect", "sse-network"])
        return success

    def check_backend_health(self) -> tuple[bool, bool]:
        """
        Check backend health via HTTP endpoint.

        Returns:
            Tuple of (network_exists: bool, health_endpoint_accessible: bool)
        """
        network_exists = self.check_backend_network()

        if not network_exists:
            self.print_warning("Backend network 'sse-network' not found")
            return False, False

        self.print_success("Backend network detected")

        # Try to reach the backend health endpoint
        if not REQUESTS_AVAILABLE:
            self.print_warning("requests library not available - skipping health check")
            return True, False

        # Try different health endpoint URLs (HTTP and HTTPS, different paths)
        health_urls = [
            "http://localhost/health",           # PowerShell script default
            "http://localhost:8000/api/v1/health",  # Local development
            "https://localhost/api/v1/health",   # Production HTTPS
            "http://localhost/api/v1/health",    # HTTP production
        ]

        # Suppress SSL warnings for localhost HTTPS requests (development only)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", InsecureRequestWarning)

            for url in health_urls:
                try:
                    response = requests.get(url, timeout=self.health_timeout, verify=False)
                    if response.status_code == 200:
                        self.print_success("Backend is accessible and healthy")
                        return True, True
                except requests.RequestException:
                    continue  # Try next URL

        # If we get here, none of the URLs worked
        self.print_warning("Backend network exists but health check failed for all endpoints")
        return True, False

    def handle_backend_not_running(self) -> bool:
        """
        Handle the case where backend is not running.

        Returns:
            True if we should continue with dashboard startup, False otherwise
        """
        print()
        print(f"{Fore.CYAN}{'='*60}")
        print(f"{Fore.YELLOW}BACKEND NOT RUNNING")
        print(f"{Fore.CYAN}{'='*60}")
        print()
        print(f"{Fore.WHITE}The Performance Dashboard requires the SSE backend to be running.")
        print()
        print(f"{Fore.CYAN}To start the backend, run in a new terminal:")
        print(f"{Fore.WHITE}   cd ..")
        print(f"{Fore.WHITE}   python start_app.py")
        print()
        print(f"{Fore.WHITE}This will start all necessary backend services")
        print(f"{Fore.WHITE}   (NGINX, FastAPI, Redis).")
        print()
        print(f"{Fore.CYAN}{'='*60}")
        print()

        if self.auto_start:
            self.print_info("Auto-start mode enabled - starting backend...")
            return self.start_backend()

        # Interactive prompt
        try:
            response = input("Do you want to start the dashboard anyway? (y/N): ").strip().lower()
            if response in ['y', 'yes']:
                print()
                self.print_warning("Starting dashboard without backend...")
                self.print_info("Note: Dashboard will show 'Disconnected' status")
                self.print_info("   until backend is started.")
                return True
            else:
                print()
                self.print_info("Dashboard startup cancelled. Please start the backend first.")
                return False
        except KeyboardInterrupt:
            print()
            self.print_info("Dashboard startup cancelled.")
            return False

    def start_backend(self) -> bool:
        """Start the backend infrastructure."""
        self.print_info("Starting SSE backend infrastructure...")

        # Navigate to parent directory and run start_app.py
        success, stdout, stderr = self.run_command(
            [sys.executable, "start_app.py"],
            cwd=self.parent_dir
        )

        if success:
            self.print_success("Backend started successfully")
            # Wait a bit for services to be fully ready
            self.print_info("Waiting for backend services to be ready...")
            time.sleep(5)
            return True
        else:
            self.print_error("Failed to start backend")
            if stdout:
                print(f"stdout: {stdout}")
            if stderr:
                print(f"stderr: {stderr}")
            return False

    def build_dashboard(self) -> bool:
        """Build the dashboard Docker image."""
        if self.skip_build:
            self.print_info("Skipping dashboard build (--skip-build flag)")
            return True

        self.print_info("Building dashboard image...")
        success, stdout, stderr = self.run_command(["docker-compose", "build"])

        if success:
            self.print_success("Dashboard image built successfully")
            return True
        else:
            self.print_error("Failed to build dashboard image")
            if stderr:
                print(f"Error details: {stderr}")
            return False

    def start_dashboard(self) -> bool:
        """Start the dashboard container."""
        self.print_info("Starting dashboard container...")
        success, stdout, stderr = self.run_command(["docker-compose", "up", "-d"])

        if success:
            self.print_success("Dashboard container started")
            return True
        else:
            self.print_error("Failed to start dashboard container")
            if stderr:
                print(f"Error details: {stderr}")
            return False

    def wait_for_dashboard(self) -> None:
        """Wait for dashboard to be ready."""
        self.print_info("Waiting for dashboard to start...")
        time.sleep(5)

    def check_dashboard_health(self) -> bool:
        """Check if dashboard is running and healthy."""
        success, stdout, stderr = self.run_command(["docker-compose", "ps"])

        if success and "Up" in stdout:
            return True
        else:
            self.print_error("Dashboard failed to start")
            self.print_info("Check logs: docker-compose logs")
            return False

    def print_success_info(self) -> None:
        """Print success information and helpful commands."""
        print()
        print(f"{Fore.GREEN}🎉 Dashboard is running!")
        print()
        print(f"{Fore.CYAN}📊 Access the dashboard at:")
        print(f"{Fore.WHITE}   http://localhost:3001")
        print()
        print(f"{Fore.CYAN}📝 View logs:")
        print(f"{Fore.WHITE}   docker-compose logs -f")
        print()
        print(f"{Fore.CYAN}🛑 Stop dashboard:")
        print(f"{Fore.WHITE}   docker-compose down")
        print()

    def check_dashboard_status(self) -> bool:
        """Check if dashboard is currently running."""
        self.print_info("Checking dashboard status...")
        success, stdout, _ = self.run_command(["docker-compose", "ps"])

        if success and "Up" in stdout:
            self.print_success("Dashboard is running")
            return True
        else:
            self.print_warning("Dashboard is not running")
            return False

    def stop_dashboard(self) -> bool:
        """Stop the dashboard container."""
        self.print_info("Stopping dashboard container...")
        success, stdout, stderr = self.run_command(["docker-compose", "down"])

        if success:
            self.print_success("Dashboard stopped successfully")
            return True
        else:
            self.print_error("Failed to stop dashboard")
            if stderr:
                print(f"Error details: {stderr}")
            return False

    def run_operation(self, operation: str) -> int:
        """Run the specified operation."""
        self.print_header()

        if operation == "status":
            return 0 if self.check_dashboard_status() else 1

        elif operation == "stop":
            return 0 if self.stop_dashboard() else 1

        elif operation == "start":
            return self.run_start()

        elif operation == "restart":
            # Stop first
            self.print_info("Restarting dashboard...")
            if self.check_dashboard_status():
                if not self.stop_dashboard():
                    return 1
                # Brief pause between stop and start
                time.sleep(2)

            # Then start
            return self.run_start()

        else:
            self.print_error(f"Unknown operation: {operation}")
            return 1

    def run_start(self) -> int:
        """Run the start operation (original functionality)."""

        # Step 1: Check Docker
        if not self.check_docker_running():
            return 1

        # Step 2: Check backend status
        network_exists, backend_healthy = self.check_backend_health()
        backend_running = network_exists and backend_healthy

        # Step 3: Handle backend not running
        if not backend_running:
            if not self.handle_backend_not_running():
                return 0

        print()

        # Step 4: Build dashboard
        if not self.build_dashboard():
            return 1

        print()

        # Step 5: Start dashboard
        if not self.start_dashboard():
            return 1

        # Step 6: Wait and verify
        self.wait_for_dashboard()

        if not self.check_dashboard_health():
            return 1

        # Step 7: Success
        self.print_success_info()
        return 0


def main():
    """Main entry point with argument parsing."""
    parser = argparse.ArgumentParser(
        description="Manage Performance Dashboard operations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Operations:
  status   - Check dashboard status
  start    - Start dashboard with prerequisite checks
  stop     - Stop running dashboard
  restart  - Restart dashboard

Examples:
  python manage_dashboard_ops.py status
  python manage_dashboard_ops.py start --auto-start
  python manage_dashboard_ops.py stop
  python manage_dashboard_ops.py restart --skip-build
  python manage_dashboard_ops.py start --health-timeout 5
        """
    )

    parser.add_argument(
        "operation",
        choices=["status", "start", "stop", "restart"],
        help="Operation to perform"
    )

    parser.add_argument(
        "--auto-start",
        action="store_true",
        help="Automatically start backend if not running (only for start/restart)"
    )

    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Skip Docker image build step (only for start/restart)"
    )

    parser.add_argument(
        "--health-timeout",
        type=int,
        default=3,
        help="Timeout in seconds for backend health checks (default: 3)"
    )

    args = parser.parse_args()

    # Check for required dependencies
    if not REQUESTS_AVAILABLE:
        print(f"{Fore.YELLOW}⚠ Warning: 'requests' library not available.")
        print(f"{Fore.YELLOW}   Install with: pip install requests")
        print(f"{Fore.YELLOW}   Continuing with limited health check capabilities...")
        print()

    if not COLORAMA_AVAILABLE:
        print("Note: Install 'colorama' for colored output: pip install colorama")
        print()

    # Run the manager
    manager = DashboardManager(
        auto_start=args.auto_start,
        skip_build=args.skip_build,
        health_timeout=args.health_timeout
    )

    return manager.run_operation(args.operation)


if __name__ == "__main__":
    sys.exit(main())
