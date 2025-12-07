#!/bin/bash
# ============================================================================
# SSL Certificate Generation Script
# ============================================================================
#
# PURPOSE:
# --------
# Generates self-signed SSL certificates for development use.
# Uses Docker to ensure cross-platform compatibility (Linux, macOS, Windows).
#
# WHAT IT DOES:
# -------------
# 1. Checks if certificates already exist
# 2. Uses Docker with Alpine Linux to run OpenSSL
# 3. Generates a 4096-bit RSA private key
# 4. Creates a self-signed certificate valid for 365 days
# 5. Includes Subject Alternative Names (SAN) for localhost
#
# USAGE:
# ------
#   ./generate-cert.sh
#
# REQUIREMENTS:
# -------------
# - Docker installed and running
# - Write permissions to the ssl/ directory
#
# OUTPUT:
# -------
# - localhost.key: Private key (keep this secret!)
# - localhost.crt: Certificate file
#
# ============================================================================

set -euo pipefail  # Exit on error, undefined vars, pipe failures

# ============================================================================
# CONFIGURATION
# ============================================================================

# Script directory (where this script is located)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Output directory (same as script directory)
OUTPUT_DIR="$SCRIPT_DIR"

# Certificate files
KEY_FILE="$OUTPUT_DIR/localhost.key"
CERT_FILE="$OUTPUT_DIR/localhost.crt"

# Certificate validity (days)
VALIDITY_DAYS=365

# Key size (bits)
KEY_SIZE=4096

# Certificate subject
CERT_SUBJECT="/C=US/ST=Dev/L=Dev/O=Dev/CN=localhost"

# Subject Alternative Names (SAN)
SAN="DNS:localhost,DNS:*.localhost,IP:127.0.0.1"

# Docker image to use
DOCKER_IMAGE="alpine:3"

# ============================================================================
# FUNCTIONS
# ============================================================================

print_header() {
    echo "============================================================================"
    echo "$1"
    echo "============================================================================"
    echo ""
}

print_step() {
    echo "→ $1"
}

print_success() {
    echo "✓ $1"
}

print_error() {
    echo "✗ ERROR: $1" >&2
}

print_warning() {
    echo "⚠ WARNING: $1"
}

# Check if Docker is available
check_docker() {
    if ! command -v docker &> /dev/null; then
        print_error "Docker is not installed or not in PATH"
        echo ""
        echo "Please install Docker:"
        echo "  - Linux: https://docs.docker.com/engine/install/"
        echo "  - macOS: https://docs.docker.com/desktop/install/mac-install/"
        echo "  - Windows: https://docs.docker.com/desktop/install/windows-install/"
        exit 1
    fi

    if ! docker info &> /dev/null; then
        print_error "Docker daemon is not running"
        echo ""
        echo "Please start Docker and try again."
        exit 1
    fi

    print_success "Docker is available and running"
}

# Check if certificates already exist
check_existing_certs() {
    if [[ -f "$KEY_FILE" ]] || [[ -f "$CERT_FILE" ]]; then
        print_warning "Certificate files already exist:"
        [[ -f "$KEY_FILE" ]] && echo "  - $KEY_FILE"
        [[ -f "$CERT_FILE" ]] && echo "  - $CERT_FILE"
        echo ""
        read -p "Do you want to overwrite them? (y/N): " -n 1 -r
        echo ""
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_step "Skipping certificate generation"
            exit 0
        fi
        print_step "Backing up existing certificates..."
        [[ -f "$KEY_FILE" ]] && mv "$KEY_FILE" "${KEY_FILE}.backup.$(date +%Y%m%d_%H%M%S)"
        [[ -f "$CERT_FILE" ]] && mv "$CERT_FILE" "${CERT_FILE}.backup.$(date +%Y%m%d_%H%M%S)"
        print_success "Existing certificates backed up"
    fi
}

# Generate certificates using Docker
generate_certificates() {
    print_step "Generating SSL certificates using Docker..."
    echo ""

    # Convert Windows path to Docker-compatible path if needed
    # Docker on Windows needs forward slashes
    if [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "cygwin" ]]; then
        # Windows (Git Bash, Cygwin)
        DOCKER_PATH=$(cygpath -w "$OUTPUT_DIR" | sed 's/\\/\//g')
        DOCKER_PATH="/${DOCKER_PATH}"
    else
        # Linux, macOS
        DOCKER_PATH="$OUTPUT_DIR"
    fi

    # Run OpenSSL in Docker container
    docker run --rm \
        -v "${DOCKER_PATH}:/work" \
        "$DOCKER_IMAGE" \
        sh -c "
            # Install OpenSSL
            apk add --no-cache openssl > /dev/null 2>&1
            
            # Generate private key and certificate
            openssl req -x509 \
                -newkey rsa:${KEY_SIZE} \
                -keyout /work/localhost.key \
                -out /work/localhost.crt \
                -days ${VALIDITY_DAYS} \
                -nodes \
                -subj '${CERT_SUBJECT}' \
                -addext 'subjectAltName=${SAN}'
            
            # Set proper permissions (readable by owner only)
            chmod 600 /work/localhost.key
            chmod 644 /work/localhost.crt
            
            echo 'Certificates generated successfully'
        "

    if [[ $? -ne 0 ]]; then
        print_error "Failed to generate certificates"
        exit 1
    fi

    print_success "Certificates generated successfully"
}

# Verify generated certificates
verify_certificates() {
    print_step "Verifying generated certificates..."

    if [[ ! -f "$KEY_FILE" ]] || [[ ! -f "$CERT_FILE" ]]; then
        print_error "Certificate files not found after generation"
        exit 1
    fi

    # Check file sizes (basic sanity check)
    KEY_SIZE_BYTES=$(stat -f%z "$KEY_FILE" 2>/dev/null || stat -c%s "$KEY_FILE" 2>/dev/null || echo "0")
    CERT_SIZE_BYTES=$(stat -f%z "$CERT_FILE" 2>/dev/null || stat -c%s "$CERT_FILE" 2>/dev/null || echo "0")

    if [[ $KEY_SIZE_BYTES -lt 1000 ]] || [[ $CERT_SIZE_BYTES -lt 1000 ]]; then
        print_error "Certificate files appear to be too small (may be corrupted)"
        exit 1
    fi

    print_success "Certificate files verified"
    echo "  Key file: $KEY_FILE ($(numfmt --to=iec-i --suffix=B $KEY_SIZE_BYTES 2>/dev/null || echo "${KEY_SIZE_BYTES} bytes"))"
    echo "  Cert file: $CERT_FILE ($(numfmt --to=iec-i --suffix=B $CERT_SIZE_BYTES 2>/dev/null || echo "${CERT_SIZE_BYTES} bytes"))"
}

# Display certificate information
display_cert_info() {
    print_step "Certificate information:"
    echo ""

    # Use Docker to read certificate info (if openssl not available locally)
    if command -v openssl &> /dev/null; then
        openssl x509 -in "$CERT_FILE" -noout -text | grep -A 2 "Subject:\|Issuer:\|Validity\|Subject Alternative Name" || true
    else
        docker run --rm \
            -v "${OUTPUT_DIR}:/work" \
            "$DOCKER_IMAGE" \
            sh -c "apk add --no-cache openssl > /dev/null 2>&1 && openssl x509 -in /work/localhost.crt -noout -text | grep -A 2 'Subject:\|Issuer:\|Validity\|Subject Alternative Name'" || true
    fi
}

# Display security notes
display_security_notes() {
    echo ""
    print_header "Security Notes"
    echo "IMPORTANT:"
    echo "  • These are SELF-SIGNED certificates for development only"
    echo "  • Browsers will show security warnings (this is expected)"
    echo "  • DO NOT use these certificates in production"
    echo "  • The private key (localhost.key) should be kept secret"
    echo "  • For production, use certificates from a trusted CA (Let's Encrypt, etc.)"
    echo ""
    echo "File Permissions:"
    echo "  • Private key: 600 (read/write owner only)"
    echo "  • Certificate: 644 (readable by all, writable by owner)"
    echo ""
}

# ============================================================================
# MAIN EXECUTION
# ============================================================================

main() {
    print_header "SSL Certificate Generation"
    echo "This script will generate self-signed SSL certificates for development."
    echo ""

    # Pre-flight checks
    check_docker
    check_existing_certs
    echo ""

    # Generate certificates
    generate_certificates
    echo ""

    # Verify certificates
    verify_certificates
    echo ""

    # Display certificate info
    display_cert_info
    echo ""

    # Security notes
    display_security_notes

    print_header "Certificate Generation Complete"
    echo "Files generated:"
    echo "  • $KEY_FILE"
    echo "  • $CERT_FILE"
    echo ""
    echo "Next steps:"
    echo "  1. Restart nginx to load new certificates: docker-compose restart nginx"
    echo "  2. Test HTTPS endpoint: curl -k https://localhost/nginx-health"
    echo ""
}

# Run main function
main

