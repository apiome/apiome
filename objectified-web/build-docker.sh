#!/bin/bash

# Docker Build and Publish Script for Objectified Web
# This script builds the Docker image and prepares it for publishing to a remote server

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
IMAGE_NAME="objectified-web"
REGISTRY=${DOCKER_REGISTRY:-""}  # Set via environment variable or default to empty
VERSION=${VERSION:-$(date +%Y%m%d-%H%M%S)}
TAG=${TAG:-"latest"}

# Print colored output
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check if Docker is running
check_docker() {
    print_info "Checking Docker installation..."
    if ! command -v docker &> /dev/null; then
        print_error "Docker is not installed. Please install Docker first."
        exit 1
    fi

    if ! docker info &> /dev/null; then
        print_error "Docker daemon is not running. Please start Docker."
        exit 1
    fi

    print_success "Docker is running"
}

# Function to build Docker image
build_image() {
    print_info "Building Docker image..."
    print_info "Image: ${IMAGE_NAME}"
    print_info "Version: ${VERSION}"
    print_info "Tag: ${TAG}"

    # Build for multiple platforms
    docker buildx create --use --name objectified-web-builder 2>/dev/null || docker buildx use objectified-web-builder

    if [ -n "$REGISTRY" ]; then
        FULL_IMAGE="${REGISTRY}/${IMAGE_NAME}"
    else
        FULL_IMAGE="${IMAGE_NAME}"
    fi

    print_info "Building for linux/amd64 and linux/arm64..."
    docker buildx build \
        --platform linux/amd64,linux/arm64 \
        -t "${FULL_IMAGE}:${TAG}" \
        -t "${FULL_IMAGE}:${VERSION}" \
        --load \
        .

    print_success "Docker image built successfully!"
    print_info "Tags: ${FULL_IMAGE}:${TAG}, ${FULL_IMAGE}:${VERSION}"
}

# Function to save image to tar
save_image() {
    if [ -n "$REGISTRY" ]; then
        FULL_IMAGE="${REGISTRY}/${IMAGE_NAME}"
    else
        FULL_IMAGE="${IMAGE_NAME}"
    fi

    OUTPUT_FILE="${IMAGE_NAME}-${VERSION}.tar"

    print_info "Saving Docker image to ${OUTPUT_FILE}..."
    docker save -o "${OUTPUT_FILE}" "${FULL_IMAGE}:${TAG}"

    print_success "Image saved to ${OUTPUT_FILE}"
    print_info "File size: $(du -h ${OUTPUT_FILE} | cut -f1)"
}

# Function to push to registry
push_image() {
    if [ -z "$REGISTRY" ]; then
        print_warning "No registry specified. Skipping push."
        print_info "To push to a registry, set DOCKER_REGISTRY environment variable"
        return
    fi

    FULL_IMAGE="${REGISTRY}/${IMAGE_NAME}"

    print_info "Pushing to registry: ${REGISTRY}"
    docker push "${FULL_IMAGE}:${TAG}"
    docker push "${FULL_IMAGE}:${VERSION}"

    print_success "Image pushed to registry!"
}

# Function to test the image locally
test_image() {
    if [ -n "$REGISTRY" ]; then
        FULL_IMAGE="${REGISTRY}/${IMAGE_NAME}"
    else
        FULL_IMAGE="${IMAGE_NAME}"
    fi

    print_info "Testing Docker image..."
    print_info "Starting container on port 3002..."

    # Stop existing container if running
    docker rm -f objectified-web-test 2>/dev/null || true

    # Run container
    docker run -d \
        --name objectified-web-test \
        -p 3002:3002 \
        "${FULL_IMAGE}:${TAG}"

    print_success "Test container started!"
    print_info "Container name: objectified-web-test"
    print_info "Access at: http://localhost:3002"
    print_info ""
    print_info "To view logs: docker logs -f objectified-web-test"
    print_info "To stop: docker stop objectified-web-test"
    print_info "To remove: docker rm -f objectified-web-test"
}

# Function to display usage
usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -b, --build         Build Docker image only"
    echo "  -s, --save          Build and save image to tar file"
    echo "  -p, --push          Build and push to registry"
    echo "  -t, --test          Build and test locally"
    echo "  -a, --all           Build, save, and push (if registry set)"
    echo "  -h, --help          Display this help message"
    echo ""
    echo "Environment Variables:"
    echo "  DOCKER_REGISTRY     Docker registry URL (e.g., docker.io/username)"
    echo "  VERSION             Image version (default: timestamp)"
    echo "  TAG                 Image tag (default: latest)"
    echo ""
    echo "Examples:"
    echo "  $0 --build                              # Build image locally"
    echo "  $0 --test                               # Build and test locally"
    echo "  DOCKER_REGISTRY=myregistry.com $0 -p    # Build and push to registry"
    exit 0
}

# Main script
main() {
    print_info "=== Objectified Web Docker Build Script ==="
    print_info ""

    # Parse arguments
    ACTION=""
    while [[ $# -gt 0 ]]; do
        case $1 in
            -b|--build)
                ACTION="build"
                shift
                ;;
            -s|--save)
                ACTION="save"
                shift
                ;;
            -p|--push)
                ACTION="push"
                shift
                ;;
            -t|--test)
                ACTION="test"
                shift
                ;;
            -a|--all)
                ACTION="all"
                shift
                ;;
            -h|--help)
                usage
                ;;
            *)
                print_error "Unknown option: $1"
                usage
                ;;
        esac
    done

    # Default action if none specified
    if [ -z "$ACTION" ]; then
        ACTION="build"
    fi

    # Check Docker
    check_docker

    # Execute action
    case $ACTION in
        build)
            build_image
            ;;
        save)
            build_image
            save_image
            ;;
        push)
            build_image
            push_image
            ;;
        test)
            build_image
            test_image
            ;;
        all)
            build_image
            save_image
            if [ -n "$REGISTRY" ]; then
                push_image
            else
                print_warning "No registry specified, skipping push"
            fi
            ;;
    esac

    print_info ""
    print_success "=== Build process completed successfully! ==="
}

# Run main
main "$@"
