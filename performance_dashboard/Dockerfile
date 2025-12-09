# ============================================================================
# Multi-stage Dockerfile for Performance Dashboard
# ============================================================================
# STAGE 1: Build the React application
# STAGE 2: Serve the static files with Nginx

# ============================================================================
# STAGE 1: BUILD
# ============================================================================
FROM node:20-alpine AS builder

# Set working directory
WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
# --legacy-peer-deps handles any peer dependency conflicts
RUN npm ci --legacy-peer-deps

# Copy source code
COPY . .

# Build argument for API base URL (passed from docker-compose)
ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

# Build the application
# Vite will embed VITE_API_BASE_URL at build time
RUN npm run build

# ============================================================================
# STAGE 2: PRODUCTION
# ============================================================================
FROM nginx:1.25-alpine

# Copy custom nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy built files from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

# Create a simple health check page
RUN echo "ok" > /usr/share/nginx/html/health

# Expose port 80
EXPOSE 80

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://localhost/health || exit 1

# Start nginx
CMD ["nginx", "-g", "daemon off;"]
