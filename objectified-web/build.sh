#!/bin/bash

# Simple Docker Build Script for Objectified Web

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}[INFO]${NC} Building Objectified Web Docker image..."

# Build the Docker image
BUILDPLATFORM="linux/amd64" DOCKER_REGISTRY="registry.objectified.dev" ./build-docker.sh --push
# docker build -t objectified-web:latest .

echo -e "${GREEN}[SUCCESS]${NC} Docker image built successfully!"
echo -e "${BLUE}[INFO]${NC} Image name: objectified-web:latest"
echo -e "${BLUE}[INFO]${NC} To run: docker-compose up -d"
