# Infrastructure Management

This directory contains scripts for managing the Docker infrastructure.

## Scripts

### `manage.py`

Main infrastructure management script.

**Commands:**
- `start`: Start infrastructure services
- `stop`: Stop infrastructure services  
- `restart`: Restart infrastructure services
- `status`: Show service status
- `validate`: Validate service health

**Usage:**
```bash
# Start infrastructure
python infrastructure/manage.py start

# Start and wait for healthy
python infrastructure/manage.py start --wait

# Check status
python infrastructure/manage.py status

# Validate health
python infrastructure/manage.py validate

# Stop infrastructure
python infrastructure/manage.py stop

# Restart infrastructure
python infrastructure/manage.py restart
```

## Architecture

The infrastructure manager:
1. Uses Docker Compose to manage services
2. Validates service health before reporting success
3. Provides robust error handling
4. Supports targeted service management
