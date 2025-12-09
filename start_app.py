#!/usr/bin/env python3
"""
Application Startup Script

This script ensures infrastructure is ready before starting the FastAPI application.

Usage:
    python start_app.py

Author: Senior Solution Architect
Date: 2025-12-05
"""

import sys
from pathlib import Path

from infrastructure.manage import InfrastructureManager

# Add src to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "src"))


def main():
    """Start the application with infrastructure validation."""

    print("=" * 60)
    print("SSE Streaming Microservice - Startup")
    print("=" * 60)
    print()

    # Initialize infrastructure manager
    manager = InfrastructureManager(project_root)

    # Step 1: Check if infrastructure is running
    print("Step 1: Checking infrastructure status...")
    manager.status()

    # Step 2: Stop existing infrastructure to ensure clean state
    print("\nStep 2: Stopping existing infrastructure for clean restart...")
    manager.stop()
    print("[OK] Infrastructure stopped successfully")

    # Step 3: Start infrastructure with fresh state
    print("\nStep 3: Starting infrastructure...")
    if not manager.start():
        print("\n[X] Failed to start infrastructure")
        print("Please check Docker and try again.")
        sys.exit(1)
    print("[OK] Infrastructure started successfully")

    # Step 4: Validate infrastructure health
    print("\nStep 4: Validating infrastructure health...")
    if not manager.wait_for_healthy(timeout=30):
        print("\n[X] Infrastructure is not healthy")
        print("Please check the services and try again.")
        sys.exit(1)

    print("\n[OK] Infrastructure is ready!")
    print()

    # Step 5: Start FastAPI application
    print("Step 5: Starting FastAPI application...")
    print("=" * 60)
    print()

    # Import and run uvicorn
    try:
        import uvicorn
        from core.config.settings import get_settings

        settings = get_settings()

        uvicorn.run(
            "application.app:app",
            host=settings.app.API_HOST,
            port=settings.app.API_PORT,
            reload=settings.app.ENVIRONMENT == "development",
            log_level=settings.logging.LOG_LEVEL.lower()
        )
    except KeyboardInterrupt:
        print("\n\n[!] Shutting down gracefully...")
        sys.exit(0)
    except Exception as e:
        print(f"\n[X] Failed to start application: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
