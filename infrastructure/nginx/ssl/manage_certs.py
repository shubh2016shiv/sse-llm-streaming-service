#!/usr/bin/env python3
import os
import platform
import subprocess
import sys
from pathlib import Path

# Configuration
SSL_DIR = Path(__file__).parent.absolute()
KEY_FILE = SSL_DIR / "localhost.key"
CERT_FILE = SSL_DIR / "localhost.crt"

def print_header(msg):
    print(f"\n{'='*60}")
    print(f" {msg}")
    print(f"{'='*60}")

def print_step(msg):
    print(f"\n-> {msg}")

def print_success(msg):
    print(f"OK  {msg}")

def print_error(msg):
    print(f"ERR {msg}")

def check_docker():
    """Pre-flight check: Is Docker running?"""
    print_step("Pre-flight: Checking Docker availability...")
    try:
        # verify docker is installed and running
        subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True
        )
        print_success("Docker is available and running")
        return True
    except subprocess.CalledProcessError:
        print_error("Docker is not running or not accessible.")
        print("    Please start Docker Desktop and try again.")
        return False
    except FileNotFoundError:
        print_error("Docker executable not found in PATH.")
        return False

def run_generation_script():
    """Trigger the platform-specific generation script"""
    print_step("Triggering certificate generation...")

    system = platform.system()
    try:
        if system == "Windows":
            script_path = SSL_DIR / "generate-cert.ps1"
            print(f"    Detected Windows. Running: {script_path.name}")
            # Use PowerShell to run the script. -ExecutionPolicy Bypass is needed usually.
            cmd = ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(script_path)]
            subprocess.run(cmd, check=True)

        else:
            # Linux or macOS
            script_path = SSL_DIR / "generate-cert.sh"
            print(f"    Detected {system}. Running: {script_path.name}")

            # Ensure it is executable
            os.chmod(script_path, 0o755)

            # Run bash script
            subprocess.run(["bash", str(script_path)], check=True)

        print_success("Generation script completed successfully")
        return True

    except subprocess.CalledProcessError as e:
        print_error(f"Generation script failed with exit code {e.returncode}")
        return False
    except Exception as e:
        print_error(f"Unexpected error triggering script: {e}")
        return False

def post_validate():
    """Post-validation: Check files and basic properties"""
    print_step("Post-Validation: Verifying certificates...")

    # 1. Check existence
    if not KEY_FILE.exists() or not CERT_FILE.exists():
        print_error("Certificate files are missing!")
        return False

    # 2. Check sizes
    key_size = KEY_FILE.stat().st_size
    cert_size = CERT_FILE.stat().st_size

    print(f"    Key file:  {KEY_FILE.name} ({key_size/1024:.2f} KB)")
    print(f"    Cert file: {CERT_FILE.name} ({cert_size/1024:.2f} KB)")

    if key_size < 1000 or cert_size < 1000:
        print_error("Files seem too small to be valid 4096-bit certificates.")
        return False

    # 3. Quick content sanity check (starts with correct headers)
    try:
        with open(KEY_FILE) as f:
            key_content = f.read()
            has_private_key = (
                "-----BEGIN PRIVATE KEY-----" in key_content
                or "-----BEGIN RSA PRIVATE KEY-----" in key_content
            )
            if not has_private_key:
                print_error("Key file does not look like a PEM private key")
                return False

        with open(CERT_FILE) as f:
            if "-----BEGIN CERTIFICATE-----" not in f.read():
                print_error("Cert file does not look like a PEM certificate")
                return False
    except Exception as e:
        print_error(f"Could not read files: {e}")
        return False

    print_success("Files exist and pass basic structure checks.")

    # 4. Optional: Deep validation using Docker/OpenSSL (re-using the logic from before)
    print_step("Post-Validation: Deep inspection via Docker...")
    try:
        cmd = [
            "docker", "run", "--rm",
            "-v", f"{SSL_DIR}:/work",
            "alpine:3",
            "sh", "-c",
            (
                "apk add --no-cache openssl > /dev/null 2>&1 && "
                "openssl x509 -in /work/localhost.crt -noout -subject -dates"
            )
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print("    " + result.stdout.strip().replace("\n", "\n    "))
            print_success("Certificate parsed successfully by OpenSSL")
        else:
            print_error("Failed to parse certificate with OpenSSL")
            print(result.stderr)
            return False
    except Exception:
        print("    (Skipping deep Docker validation due to error)")
        # This is non-critical if the previous checks passed and generation passed
        pass

    return True

def main():
    print_header("SSL Certificate Manager")

    # 1. Pre-validation
    if not check_docker():
        sys.exit(1)

    # 2. Trigger Generation
    # We trigger the script which has its own prompts (like overwrite confirmation)
    # So we just let it run interactively
    if not run_generation_script():
        sys.exit(1)

    # 3. Post-validation
    if not post_validate():
        sys.exit(1)

    print_header("Process Complete")
    print("Next Steps:")
    print("  1. Restart NGINX: docker-compose restart nginx")
    print("  2. Test Endpoint: curl -k https://localhost/nginx-health")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nOperation cancelled.")
        sys.exit(130)
