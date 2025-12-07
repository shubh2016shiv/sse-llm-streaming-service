# SSL Certificate Setup (Why, How, and What to Check)

## 🚀 Quick Start - Automated Scripts (Recommended)

**Easiest Method:** Use the provided cross-platform scripts that work on Linux, macOS, and Windows:

### On Linux/macOS:
```bash
cd infrastructure/nginx/ssl
./generate-cert.sh
```

### On Windows (PowerShell):
```powershell
cd infrastructure\nginx\ssl
.\generate-cert.ps1
```

**What the scripts do:**
- ✅ Automatically check if Docker is available
- ✅ Back up existing certificates if they exist (with timestamp)
- ✅ Generate certificates using Docker (no local OpenSSL installation needed)
- ✅ Verify the generated certificates are valid
- ✅ Display certificate information
- ✅ Set proper file permissions
- ✅ Provide clear error messages and guidance

**Requirements:** Docker installed and running (works on all platforms)

---

## Manual Generation (Alternative Methods)

## Why you need these files
NGINX runs HTTPS on port 443. It must load a certificate (`localhost.crt`) and private key (`localhost.key`). Without them, the container will fail to start TLS.

## What lives in this folder
- `localhost.crt` – the certificate presented to clients
- `localhost.key` – the private key NGINX uses to terminate TLS
- `README.md` – this guide

## How to generate dev certs (pick one)

### A) Pure Docker (works on Windows/macOS/Linux, no host OpenSSL needed)
```powershell
docker run --rm ^
  -v "//d/Generative AI Portfolio Projects/SSE/infrastructure/nginx/ssl:/work" ^
  alpine:3 sh -c "apk add --no-cache openssl >/dev/null && cd /work && \
    openssl req -x509 -newkey rsa:4096 \
      -keyout localhost.key \
      -out localhost.crt \
      -days 365 -nodes \
      -subj '/C=US/ST=Dev/L=Dev/O=Dev/CN=localhost' \
      -addext 'subjectAltName=DNS:localhost,DNS:*.localhost,IP:127.0.0.1'"
```
- Uses a throwaway Alpine container with OpenSSL
- Writes key/cert into this folder
- Valid 365 days; CN=localhost, SAN covers localhost, *.localhost, 127.0.0.1

### B) Local OpenSSL (Linux/macOS)
```bash
openssl req -x509 -newkey rsa:4096 \
  -keyout localhost.key \
  -out localhost.crt \
  -days 365 -nodes \
  -subj "/C=US/ST=Dev/L=Dev/O=Dev/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,DNS:*.localhost,IP:127.0.0.1"
```

### C) Local OpenSSL (Windows + WSL)
```powershell
wsl openssl req -x509 -newkey rsa:4096 `
  -keyout localhost.key `
  -out localhost.crt `
  -days 365 -nodes `
  -subj "/C=US/ST=Dev/L=Dev/O=Dev/CN=localhost" `
  -addext "subjectAltName=DNS:localhost,DNS:*.localhost,IP:127.0.0.1"
```

## How to verify
1) List files: `ls infrastructure/nginx/ssl` (should show `localhost.crt` and `localhost.key`)
2) Inspect cert: `openssl x509 -in localhost.crt -noout -text | head`
3) Run NGINX: `docker-compose up -d nginx` then `curl -k https://localhost/nginx-health` (expect “NGINX is healthy”)

## Production guidance
- Replace the dev cert with a CA-signed cert (or LetsEncrypt):
  ```bash
  certbot certonly --webroot -w /var/www/html -d yourdomain.com
  # copy fullchain.pem -> localhost.crt, privkey.pem -> localhost.key
  ```
- Set correct permissions on the key: `chmod 600 localhost.key`
- Update `server_name` in `infrastructure/nginx/nginx.conf` to your real domain

## Flow at runtime (for context)
```
Browser -> HTTPS -> NGINX (uses localhost.crt/key) -> upstream app containers (HTTP)
```