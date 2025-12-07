# ============================================================================
# SSL Certificate Generation Script (PowerShell)
# ============================================================================
#
# PURPOSE:
# --------
# Generates self-signed SSL certificates for development use.
# Uses Docker to ensure cross-platform compatibility.
#
# USAGE:
# ------
#   .\generate-cert.ps1
#
# ============================================================================

$ErrorActionPreference = "Stop"

# ============================================================================
# CONFIGURATION
# ============================================================================

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$OutputDir = $ScriptDir
$KeyFile = Join-Path $OutputDir "localhost.key"
$CertFile = Join-Path $OutputDir "localhost.crt"

# Certificate settings
$ValidityDays = 365
$KeySize = 4096
$CertSubject = "/C=US/ST=Dev/L=Dev/O=Dev/CN=localhost"
$SAN = "DNS:localhost,DNS:*.localhost,IP:127.0.0.1"
$DockerImage = "alpine:3"

# ============================================================================
# FUNCTIONS
# ============================================================================

function Write-Header {
    param([string]$Message)
    Write-Host "============================================================================" -ForegroundColor Cyan
    Write-Host $Message -ForegroundColor Cyan
    Write-Host "============================================================================" -ForegroundColor Cyan
    Write-Host ""
}

function Write-Step {
    param([string]$Message)
    Write-Host "-> $Message" -ForegroundColor Yellow
}

function Write-Success {
    param([string]$Message)
    Write-Host "OK $Message" -ForegroundColor Green
}

function Write-Error {
    param([string]$Message)
    Write-Host "ERROR: $Message" -ForegroundColor Red
}

function Test-Docker {
    Write-Step "Checking Docker availability..."
    try {
        docker info | Out-Null
        Write-Success "Docker is available and running"
    }
    catch {
        Write-Error "Docker is not running. Please start Docker Desktop."
        exit 1
    }
}

function Test-ExistingCertificates {
    if ((Test-Path $KeyFile) -or (Test-Path $CertFile)) {
        Write-Host "Certificate files already exist." -ForegroundColor Yellow
        $response = Read-Host "Do you want to overwrite them? (y/N)"
        if ($response -ne "y") {
            exit 0
        }
        
        # Backup
        $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
        if (Test-Path $KeyFile) { Move-Item $KeyFile "${KeyFile}.backup.$timestamp" -Force }
        if (Test-Path $CertFile) { Move-Item $CertFile "${CertFile}.backup.$timestamp" -Force }
        Write-Success "Backed up existing certificates"
    }
}

function New-Certificates {
    Write-Step "Generating SSL certificates..."

    # Create the shell command to run inside Docker
    # We use a single string with proper chaining
    $cmd = "apk add --no-cache openssl > /dev/null 2>&1 && " +
    "openssl req -x509 -newkey rsa:$KeySize -keyout /work/localhost.key -out /work/localhost.crt -days $ValidityDays -nodes -subj '$CertSubject' -addext 'subjectAltName=$SAN' && " +
    "chmod 600 /work/localhost.key && " +
    "chmod 644 /work/localhost.crt"

    try {
        # Run docker command
        # We mount using standard format, Docker on Windows handles the path conversion usually,
        # but pure string path is safest.
        docker run --rm -v "${OutputDir}:/work" $DockerImage sh -c $cmd

        if ($LASTEXITCODE -ne 0) {
            throw "Docker exit code: $LASTEXITCODE"
        }
        Write-Success "Certificates generated"
    }
    catch {
        Write-Error "Failed to generate: $_"
        exit 1
    }
}

function Test-Certificates {
    Write-Step "Verifying certificates..."
    
    if (-not (Test-Path $KeyFile) -or -not (Test-Path $CertFile)) {
        Write-Error "Files check failed"
        exit 1
    }

    $kSize = (Get-Item $KeyFile).Length
    $cSize = (Get-Item $CertFile).Length
    
    # Simple formatting to avoid parser issues
    $kKB = "{0:N2}" -f ($kSize / 1KB)
    $cKB = "{0:N2}" -f ($cSize / 1KB)

    Write-Host "  Key file: $KeyFile ($kKB KB)"
    Write-Host "  Cert file: $CertFile ($cKB KB)"
    Write-Success "Verification complete"
}

# ============================================================================
# MAIN
# ============================================================================

try {
    Write-Header "SSL Certificate Generation"
    Test-Docker
    Test-ExistingCertificates
    New-Certificates
    Test-Certificates
    Write-Host ""
    Write-Host "Top Tip: Run 'docker-compose restart nginx' to apply changes." -ForegroundColor Cyan
}
catch {
    Write-Error $_
    exit 1
}
