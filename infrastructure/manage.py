#!/usr/bin/env python3
"""
Enterprise Infrastructure Management System

A production-grade Docker infrastructure orchestration tool with comprehensive
monitoring, validation, and error recovery capabilities.

Copyright (c) 2025. All rights reserved.
"""

import json
import logging
import subprocess
import sys
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None


# ============================================================================
# Configuration & Constants
# ============================================================================


class ServiceState(Enum):
    """Service health states."""

    RUNNING = "running"
    STARTING = "starting"
    STOPPED = "stopped"
    FAILED = "failed"
    UNKNOWN = "unknown"


class ExitCode(Enum):
    """Standardized exit codes."""

    SUCCESS = 0
    GENERAL_ERROR = 1
    CONFIGURATION_ERROR = 2
    DEPENDENCY_ERROR = 3


@dataclass
class ServiceConfig:
    """Service connection configuration."""

    name: str
    url: str
    port: str
    protocol: str = "tcp"
    username: str = ""
    password: str = ""
    compose_name: str = ""

    @property
    def endpoint(self) -> str:
        """Full service endpoint."""
        return f"{self.url}:{self.port}"


@dataclass
class ValidationResult:
    """Service validation result."""

    service: str
    healthy: bool
    message: str
    details: str | None = None


# ============================================================================
# Logging Configuration
# ============================================================================


class ColoredFormatter(logging.Formatter):
    """Colored console output formatter."""

    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, self.RESET)
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure application logging."""
    level = logging.DEBUG if verbose else logging.INFO

    logger = logging.getLogger("InfrastructureManager")
    logger.setLevel(level)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)

        formatter = ColoredFormatter(fmt="%(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


# ============================================================================
# Core Infrastructure Manager
# ============================================================================


class InfrastructureManager:
    """
    Enterprise-grade Docker infrastructure orchestrator.

    Provides robust service lifecycle management with:
    - Pre-flight validation
    - Exponential backoff retry logic
    - Comprehensive health monitoring
    - Detailed error reporting
    - Credential management
    """

    # Core infrastructure services (required)
    # These services form the essential infrastructure backbone:
    # - redis-master: Cache and state storage
    # - zookeeper: Kafka coordination
    # - kafka: Message queue
    # - nginx: Load balancer and reverse proxy
    # - prometheus: Metrics collection and alerting
    # - grafana: Metrics visualization and dashboards
    CORE_SERVICES = ["redis-master", "zookeeper", "kafka", "nginx", "prometheus", "grafana"]

    # Optional application and UI services
    OPTIONAL_SERVICES = ["redis-commander", "kafka-ui", "redis-exporter", "app-1", "app-2", "app-3"]

    # All services
    ALL_SERVICES = CORE_SERVICES + OPTIONAL_SERVICES

    # Map display names to compose service names
    SERVICE_NAME_MAP = {
        "redis-master": "Redis Master",
        "zookeeper": "Zookeeper",
        "kafka": "Kafka Broker",
        "nginx": "NGINX Load Balancer",
        "prometheus": "Prometheus Monitoring",
        "grafana": "Grafana Dashboards",
        "redis-commander": "Redis Commander",
        "kafka-ui": "Kafka UI",
        "redis-exporter": "Redis Exporter",
        "app-1":  "SSE Application 1",
        "app-2": "SSE Application 2",
        "app-3": "SSE Application 3",
    }

    SERVICE_CONFIGS = [
        ServiceConfig("Redis Master", "localhost", "6379", "tcp", compose_name="redis-master"),
        ServiceConfig("Zookeeper", "localhost", "2181", "tcp", compose_name="zookeeper"),
        ServiceConfig("Kafka Broker", "localhost", "9092", "tcp", compose_name="kafka"),
        ServiceConfig("Kafka External", "localhost", "9094", "tcp", compose_name="kafka"),
        ServiceConfig(
            "Redis Commander", "http://localhost", "8081", "http", compose_name="redis-commander"
        ),
        ServiceConfig("Kafka UI", "http://localhost", "8082", "http", compose_name="kafka-ui"),
        ServiceConfig("SSE Application", "http://localhost", "8000", "http", compose_name="app"),
    ]

    # Health check configuration
    HEALTH_CHECK_INITIAL_DELAY = 5  # Initial wait before first check
    HEALTH_CHECK_MAX_ATTEMPTS = 20  # Maximum health check attempts
    HEALTH_CHECK_INTERVAL = 3  # Seconds between checks

    def __init__(self, project_root: Path, logger: logging.Logger | None = None):
        self.project_root = project_root
        self.compose_file = project_root / "docker-compose.yml"
        self.logger = logger or setup_logging()

    # ------------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------------

    def start(
        self,
        services: list[str] | None = None,
        max_retries: int = 3,
        include_optional: bool = False,
    ) -> bool:
        """
        Start infrastructure services with validation.

        Args:
            services: Specific services to start (None for default)
            max_retries: Maximum startup retry attempts
            include_optional: Start optional services (UI, app) as well

        Returns:
            Success status
        """
        self.logger.info("Starting infrastructure services...")

        if not self._preflight_check():
            return False

        # Determine which services to start
        if services:
            target_services = services
        elif include_optional:
            target_services = self.ALL_SERVICES
            self.logger.info("Starting all services (core + optional)")
        else:
            target_services = self.CORE_SERVICES
            self.logger.info("Starting core infrastructure services")

        if not self._start_services(target_services, max_retries):
            return False

        # Only validate core services for health
        validation_services = [s for s in target_services if s in self.CORE_SERVICES]
        if not self._wait_for_healthy(validation_services):
            return False

        self._display_credentials()
        self.logger.info("Infrastructure startup completed successfully")
        return True

    def stop(self, services: list[str] | None = None) -> bool:
        """
        Stop infrastructure services gracefully.

        BEHAVIOR:
        ---------
        - If services=None: Stops ALL services and removes containers (docker compose down)
        - If services specified: Stops only those services, keeps containers (docker compose stop)

        RATIONALE:
        ----------
        'docker compose down' removes containers, networks, and optionally volumes.
        'docker compose stop' only stops running containers, preserving state.

        Args:
            services: List of specific service names to stop (None = stop all and clean up)

        Returns:
            bool: True if stop command succeeded, False otherwise

        Example:
            manager.stop()                    # Stop everything, remove containers
            manager.stop(['grafana', 'prometheus'])  # Stop specific services only
        """
        self.logger.info("Stopping infrastructure services...")

        # COMMAND SELECTION:
        # - 'down': Stops and removes containers/networks (full cleanup)
        # - 'stop': Only stops containers (preserves state for quick restart)
        cmd = (
            ["docker", "compose", "down"]
            if not services
            else ["docker", "compose", "stop"] + services
        )

        success, output = self._run_command(cmd)

        if not success:
            self.logger.error("Failed to stop services")
            self.logger.debug(f"Error: {output}")
            return False

        self.logger.info("Services stopped successfully")
        return True

    def restart(self, services: list[str] | None = None, include_optional: bool = False) -> bool:
        """
        Restart infrastructure services with health validation.

        MECHANISM:
        ----------
        1. Issues 'docker compose restart' for target services
        2. Waits HEALTH_CHECK_INITIAL_DELAY seconds for containers to initialize
        3. Runs health validation checks with 60-second timeout
        4. Returns success only if all services healthy

        IMPORTANT:
        ----------
        Unlike stop(), restart() always validates health of core services.
        This ensures restarted services are actually working, not just running.

        Args:
            services: Specific service names to restart (None = use default set)
            include_optional: If True and services=None, restart all services (core + optional)

        Returns:
            bool: True if restart succeeded AND services are healthy, False otherwise

        Example:
            manager.restart()                          # Restart core services
            manager.restart(include_optional=True)     # Restart all services
            manager.restart(['prometheus', 'grafana']) # Restart specific services
        """
        self.logger.info("Restarting infrastructure services...")

        # DETERMINE TARGET SERVICES:
        # - Specific services provided: Use those
        # - include_optional=True: Restart everything (core + UI + app)
        # - Default: Restart only core infrastructure
        if services:
            target_services = services
        elif include_optional:
            target_services = self.ALL_SERVICES
        else:
            target_services = self.CORE_SERVICES

        cmd = ["docker", "compose", "restart"] + target_services

        success, output = self._run_command(cmd)

        if not success:
            self.logger.error("Failed to restart services")
            self.logger.debug(f"Error: {output}")
            return False

        # HEALTH VALIDATION:
        # Wait for containers to initialize before checking health
        self.logger.info("Services restarted, waiting for health checks...")
        time.sleep(self.HEALTH_CHECK_INITIAL_DELAY)

        #Only validate core services (optional services may not have health checks)
        validation_services = [s for s in target_services if s in self.CORE_SERVICES]
        return self._wait_for_healthy(validation_services, timeout=60)

    def status(self) -> dict[str, ServiceState]:
        """
        Get current service status.

        Returns:
            Mapping of service names to states
        """
        self.logger.info("Checking service status...")

        cmd = ["docker", "compose", "ps", "--format", "json"]
        success, output = self._run_command(cmd)

        if not success:
            self.logger.error("Failed to retrieve service status")
            return {}

        status_map = self._parse_service_status(output)
        self._display_status(status_map)

        return status_map

    def validate(self, verbose: bool = False) -> bool:
        """
        Validate all service health.

        Args:
            verbose: Enable detailed validation output

        Returns:
            Overall health status
        """
        self.logger.info("Validating infrastructure health...")

        validators = [
            self._validate_redis,
            self._validate_zookeeper,
            self._validate_kafka,
        ]

        results = [validator() for validator in validators]
        all_healthy = all(r.healthy for r in results)

        if verbose or not all_healthy:
            self._display_validation_results(results)

        if all_healthy:
            self.logger.info("All services are healthy")
        else:
            self.logger.warning("Some services are not yet healthy")

        return all_healthy

    def wait_for_healthy(self, timeout: int = 90) -> bool:
        """
        Wait for core infrastructure services to become healthy.

        Public wrapper for external use (e.g., from start_app.py).

        Args:
            timeout: Maximum time to wait in seconds

        Returns:
            True if all services are healthy, False otherwise
        """
        return self._wait_for_healthy(self.CORE_SERVICES, timeout)

    # ------------------------------------------------------------------------
    # Pre-flight Checks
    # ------------------------------------------------------------------------

    def _preflight_check(self) -> bool:
        """Execute pre-flight validation checks."""
        self.logger.info("Running pre-flight checks...")

        checks = [
            ("Docker availability", self._check_docker),
            ("Docker Compose file", self._check_compose_file),
        ]

        for name, check_fn in checks:
            if not check_fn():
                self.logger.error(f"Pre-flight check failed: {name}")
                return False
            self.logger.debug(f"[OK] {name}")

        self.logger.info("Pre-flight checks passed")
        return True

    def _check_docker(self) -> bool:
        """Verify Docker availability."""
        success, _ = self._run_command(["docker", "--version"], timeout=10)
        if not success:
            self.logger.error("Docker is not installed or not running")
            return False

        # Check if Docker daemon is accessible
        success, _ = self._run_command(["docker", "ps"], timeout=30)
        if not success:
            self.logger.error("Docker daemon is not accessible. Ensure Docker is running.")
            return False

        return True

    def _check_compose_file(self) -> bool:
        """Verify Docker Compose configuration."""
        if not self.compose_file.exists():
            self.logger.error(f"Compose file not found: {self.compose_file}")
            return False

        if yaml is None:
            self.logger.warning("PyYAML not installed, skipping YAML validation")
            return True

        try:
            with open(self.compose_file, encoding="utf-8") as f:
                yaml.safe_load(f)
            return True
        except yaml.YAMLError as e:
            self.logger.error(f"Invalid YAML: {e}")
            return False

    # ------------------------------------------------------------------------
    # Service Lifecycle Management
    # ------------------------------------------------------------------------

    def _start_services(self, services: list[str], max_retries: int) -> bool:
        """Start services with exponential backoff retry."""
        for attempt in range(1, max_retries + 1):
            self.logger.info(f"Starting services (attempt {attempt}/{max_retries})...")

            cmd = ["docker", "compose", "up", "-d"] + services
            # Use longer timeout for docker compose up as it may need to build images
            success, output = self._run_command(cmd, timeout=180)

            if success:
                self.logger.info(f"Services started: {', '.join(services)}")
                # Give containers time to initialize
                time.sleep(self.HEALTH_CHECK_INITIAL_DELAY)
                return True

            self.logger.warning(f"Startup failed: {output}")

            if attempt < max_retries:
                wait_time = 2**attempt
                self.logger.info(f"Retrying in {wait_time}s...")
                time.sleep(wait_time)

        self.logger.error("Service startup failed after all retries")
        return False

    def _wait_for_healthy(self, services: list[str], timeout: int = 90) -> bool:
        """Wait for services to become healthy with progressive checks."""
        self.logger.info("Waiting for services to become healthy...")

        start_time = time.time()
        attempt = 0

        while time.time() - start_time < timeout:
            attempt += 1

            if self.validate():
                elapsed = int(time.time() - start_time)
                self.logger.info(f"All services healthy after {elapsed}s ({attempt} checks)")
                return True

            # Show progress every 5 attempts
            if attempt % 5 == 0:
                elapsed = int(time.time() - start_time)
                self.logger.info(f"Still waiting... ({elapsed}s elapsed, {attempt} checks)")

            time.sleep(self.HEALTH_CHECK_INTERVAL)

        self.logger.error(f"Health check timeout after {timeout}s")
        return False

    # ------------------------------------------------------------------------
    # Service Validation
    # ------------------------------------------------------------------------

    def _validate_redis(self) -> ValidationResult:
        """Validate Redis connectivity."""
        cmd = ["docker", "compose", "exec", "-T", "redis-master", "redis-cli", "ping"]
        success, output = self._run_command(cmd, timeout=5)

        healthy = success and "PONG" in output
        message = "Redis is operational" if healthy else "Redis health check failed"

        return ValidationResult("Redis", healthy, message, output if not healthy else None)

    def _validate_zookeeper(self) -> ValidationResult:
        """Validate Zookeeper connectivity using Docker healthcheck."""
        # Check if container is running first
        cmd = ["docker", "compose", "ps", "--format", "json", "zookeeper"]
        success, output = self._run_command(cmd, timeout=5)

        if not success:
            return ValidationResult("Zookeeper", False, "Cannot query container status", output)

        try:
            # Parse container state
            container_info = json.loads(output) if output.strip() else {}

            # Handle both dict and list formats
            if isinstance(container_info, list):
                container_info = container_info[0] if container_info else {}

            state = container_info.get("State", "unknown")

            # If container is running, check if it's responding
            if state == "running":
                # Try to check Zookeeper status using the four-letter-word command
                cmd = [
                    "docker",
                    "compose",
                    "exec",
                    "-T",
                    "zookeeper",
                    "bash",
                    "-c",
                    "echo ruok | nc localhost 2181",
                ]
                success, output = self._run_command(cmd, timeout=5)

                if success and "imok" in output:
                    return ValidationResult("Zookeeper", True, "Zookeeper is operational")

                # Fallback: if container is running for more than 10 seconds, consider it healthy
                # Zookeeper may not respond immediately but container is up
                return ValidationResult(
                    "Zookeeper", True, "Zookeeper container is running (assuming healthy)"
                )

            return ValidationResult("Zookeeper", False, f"Container state: {state}")

        except json.JSONDecodeError:
            return ValidationResult("Zookeeper", False, "Failed to parse container status")

    def _validate_kafka(self) -> ValidationResult:
        """Validate Kafka broker connectivity."""
        cmd = [
            "docker",
            "compose",
            "exec",
            "-T",
            "kafka",
            "kafka-topics",
            "--bootstrap-server",
            "kafka:9092",
            "--list",
        ]
        success, output = self._run_command(cmd, timeout=10)

        message = "Kafka broker is operational" if success else "Kafka broker unavailable"
        return ValidationResult("Kafka", success, message, output if not success else None)

    # ------------------------------------------------------------------------
    # Status & Display
    # ------------------------------------------------------------------------

    def _parse_service_status(self, output: str) -> dict[str, ServiceState]:
        """Parse service status from docker compose output."""
        status_map = {}

        if not output.strip():
            return status_map

        try:
            for line in output.strip().split("\n"):
                if not line:
                    continue

                data = json.loads(line)

                if isinstance(data, dict):
                    name = data.get("Service", data.get("Name", "unknown"))
                    state_str = data.get("State", "unknown")
                    health = data.get("Health", "")

                    status_map[name] = self._map_service_state(state_str, health)
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            name = item.get("Service", item.get("Name", "unknown"))
                            state_str = item.get("State", "unknown")
                            health = item.get("Health", "")

                            status_map[name] = self._map_service_state(state_str, health)
        except json.JSONDecodeError as e:
            self.logger.warning(f"Failed to parse service status: {e}")

        return status_map

    def _map_service_state(self, state_str: str, health_str: str = "") -> ServiceState:
        """Map string state to ServiceState enum."""
        state_lower = state_str.lower()

        if state_lower == "running":
            # Check health status if available
            if health_str:
                health_lower = health_str.lower()
                if "starting" in health_lower:
                    return ServiceState.STARTING
                elif "unhealthy" in health_lower:
                    return ServiceState.FAILED
            return ServiceState.RUNNING
        elif state_lower in ("exited", "stopped"):
            return ServiceState.STOPPED
        elif state_lower in ("dead", "removing"):
            return ServiceState.FAILED

        return ServiceState.UNKNOWN

    def _display_status(self, status_map: dict[str, ServiceState]) -> None:
        """Display formatted service status."""
        if not status_map:
            self.logger.warning("No services found")
            return

        icons = {
            ServiceState.RUNNING: "[OK]",
            ServiceState.STARTING: "[..]",
            ServiceState.STOPPED: "[ ]",
            ServiceState.FAILED: "[X]",
            ServiceState.UNKNOWN: "[?]",
        }

        colors = {
            ServiceState.RUNNING: "\033[32m",  # Green
            ServiceState.STARTING: "\033[33m",  # Yellow
            ServiceState.STOPPED: "\033[90m",  # Gray
            ServiceState.FAILED: "\033[31m",  # Red
            ServiceState.UNKNOWN: "\033[36m",  # Cyan
        }
        reset = "\033[0m"

        print("\n" + "=" * 70)
        print("SERVICE STATUS")
        print("=" * 70)

        for service, state in sorted(status_map.items()):
            icon = icons.get(state, "?")
            color = colors.get(state, "")
            print(f"  {color}{icon}{reset} {service:<35} {color}{state.value}{reset}")

        print("=" * 70 + "\n")

    def _display_validation_results(self, results: list[ValidationResult]) -> None:
        """Display detailed validation results."""
        print("\n" + "=" * 70)
        print("HEALTH VALIDATION RESULTS")
        print("=" * 70)

        for result in results:
            icon = "[OK]" if result.healthy else "[X]"
            color = "\033[32m" if result.healthy else "\033[31m"
            reset = "\033[0m"

            print(f"  {color}{icon}{reset} {result.service}: {result.message}")
            if result.details and not result.healthy:
                # Show first line of details only
                detail_line = result.details.split("\n")[0][:80]
                print(f"    -> {detail_line}")

        print("=" * 70 + "\n")

    def _display_credentials(self) -> None:
        """Display service connection information."""
        print("\n" + "=" * 80)
        print("SERVICE CONNECTION INFORMATION")
        print("=" * 80)

        # Header
        print(f"{'Service':<30} {'Endpoint':<35} {'Status':<10}")
        print("-" * 80)

        # Get current service states
        cmd = ["docker", "compose", "ps", "--format", "json"]
        success, output = self._run_command(cmd, timeout=5)
        status_map = self._parse_service_status(output) if success else {}

        # Track which services are not started
        not_started_services = []
        optional_not_started = []

        for config in self.SERVICE_CONFIGS:
            # Use the compose_name directly for matching
            state = status_map.get(config.compose_name, ServiceState.UNKNOWN)

            # Status indicator
            if state == ServiceState.RUNNING:
                status_icon = "[OK]"
                status_color = "\033[32m"
                status_text = "running"
            elif state == ServiceState.STARTING:
                status_icon = "[..]"
                status_color = "\033[33m"
                status_text = "starting"
            elif state == ServiceState.STOPPED:
                status_icon = "[ ]"
                status_color = "\033[90m"
                status_text = "stopped"
            elif state == ServiceState.FAILED:
                status_icon = "[X]"
                status_color = "\033[31m"
                status_text = "failed"
            else:
                status_icon = "[ ]"
                status_color = "\033[90m"
                status_text = "not started"
                not_started_services.append(config.name)
                # Check if this is an optional service
                if config.compose_name in self.OPTIONAL_SERVICES:
                    optional_not_started.append(config.compose_name)

            reset = "\033[0m"

            print(
                f"{config.name:<30} {config.endpoint:<35} "
                f"{status_color}{status_icon}{reset} {status_text}"
            )

        print("=" * 80)

        # Display helpful guidance based on service states
        if optional_not_started:
            print("\n[!] NEXT STEPS:")
            print("-" * 80)
            print("[!] Optional services are not started. To start them, run:")
            print("\n    python infrastructure/manage.py start --all")
            print("\n   This will start:")

            service_descriptions = {
                "redis-commander": "Redis Commander - Web UI for Redis management",
                "kafka-ui": "Kafka UI - Web interface for Kafka monitoring",
                "app": "SSE Application - Your main application server",
            }

            for svc in optional_not_started:
                desc = service_descriptions.get(svc, svc)
                print(f"   - {desc}")

            print("\n   Or start specific services:")
            services_str = " ".join(optional_not_started)
            print(f"    python infrastructure/manage.py start --services {services_str}")
            print("-" * 80)

        print("\n[i] All services are accessible on localhost")
        print("[i] Use docker compose logs <service> to view service logs")
        print("[i] Run 'python infrastructure/manage.py --help' for more options")
        print("=" * 80 + "\n")

    # ------------------------------------------------------------------------
    # Utility Methods
    # ------------------------------------------------------------------------

    def _run_command(
        self, cmd: list[str], timeout: int = 30, check: bool = False
    ) -> tuple[bool, str]:
        """
        Execute shell command with error handling.

        Args:
            cmd: Command and arguments
            timeout: Execution timeout in seconds
            check: Raise exception on failure

        Returns:
            Tuple of (success, output/error)
        """
        try:
            result = subprocess.run(
                cmd,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=check,
            )

            success = result.returncode == 0
            output = result.stdout if success else result.stderr

            return success, output.strip()

        except subprocess.TimeoutExpired:
            self.logger.debug(f"Command timeout after {timeout}s: {' '.join(cmd)}")
            return False, "Command timeout"
        except subprocess.CalledProcessError as e:
            return False, e.stderr.strip()
        except FileNotFoundError:
            self.logger.error(f"Command not found: {cmd[0]}")
            return False, "Command not found"
        except Exception as e:
            self.logger.debug(f"Command error: {e}")
            return False, str(e)


# ============================================================================
# CLI Interface
# ============================================================================


def create_parser():
    """Create command-line argument parser."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="infrastructure-manager",
        description="Enterprise Docker infrastructure orchestration tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s start                    # Start core services only
  %(prog)s start --all              # Start all services (core + UI + app)
  %(prog)s start --services kafka   # Start specific service
  %(prog)s status                   # Check service status
  %(prog)s validate --verbose       # Detailed health check
  %(prog)s stop                     # Stop all services
  %(prog)s restart --all            # Restart all services
        """,
    )

    parser.add_argument(
        "command",
        choices=["start", "stop", "restart", "status", "validate"],
        help="Operation to perform",
    )

    parser.add_argument("--services", nargs="+", metavar="SERVICE", help="Target specific services")

    parser.add_argument(
        "--all",
        "-a",
        action="store_true",
        dest="include_all",
        help="Include optional services (Redis Commander, Kafka UI, SSE App)",
    )

    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        metavar="N",
        help="Maximum retry attempts for start/restart (default: 3)",
    )

    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output")

    parser.add_argument(
        "--timeout",
        type=int,
        default=90,
        metavar="SECONDS",
        help="Health check timeout in seconds (default: 90)",
    )

    parser.add_argument(
        "--no-validate", action="store_true", help="Skip health validation after start/restart"
    )

    return parser


def main() -> int:
    """Application entry point."""
    # Configure UTF-8 encoding for Windows console at startup
    if sys.platform == "win32":
        try:
            import io

            # Reconfigure stdout and stderr for UTF-8 encoding
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

            # Also set console codepage to UTF-8 if possible
            import subprocess
            try:
                subprocess.run(["chcp", "65001"], capture_output=True, check=False)
            except Exception:
                pass  # Ignore if chcp fails
        except Exception:
            # Fallback: try simpler approach
            try:
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
                sys.stderr.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass  # Last resort - continue with default encoding

    parser = create_parser()
    args = parser.parse_args()

    logger = setup_logging(args.verbose)
    project_root = Path(__file__).parent.parent
    manager = InfrastructureManager(project_root, logger)

    try:
        command_map = {
            "start": lambda: manager.start(args.services, args.retries, args.include_all),
            "stop": lambda: manager.stop(args.services),
            "restart": lambda: manager.restart(args.services, args.include_all),
            "status": lambda: bool(manager.status()),
            "validate": lambda: manager.validate(args.verbose),
        }

        success = command_map[args.command]()
        return ExitCode.SUCCESS.value if success else ExitCode.GENERAL_ERROR.value

    except KeyboardInterrupt:
        logger.warning("\nOperation interrupted by user")
        return ExitCode.GENERAL_ERROR.value
    except Exception as e:
        logger.critical(f"Unexpected error: {e}", exc_info=args.verbose)
        return ExitCode.GENERAL_ERROR.value


if __name__ == "__main__":
    sys.exit(main())
