# Apiome Web - Docker Quick Reference

## 🚀 Quick Commands

### Build & Run
```bash
# Using Docker Compose (Recommended)
docker-compose up -d

# Using Docker CLI
docker build -t apiome-web:latest .
docker run -d --name apiome-web -p 3002:3002 apiome-web:latest

# Using build script
./build-docker.sh --test
```

### View Logs
```bash
docker-compose logs -f              # Docker Compose
docker logs -f apiome-web      # Docker CLI
```

### Stop & Remove
```bash
docker-compose down                 # Docker Compose
docker stop apiome-web && docker rm apiome-web  # Docker CLI
```

## 🔧 Build Scripts

### build.sh - Simple Build
```bash
./build.sh
```
Builds: `apiome-web:latest`

### build-docker.sh - Advanced Build
```bash
./build-docker.sh --build           # Build only
./build-docker.sh --test            # Build and test
./build-docker.sh --save            # Build and save to tar
./build-docker.sh --push            # Build and push to registry
./build-docker.sh --all             # All of the above
```

## 🌐 Access

- **Local:** http://localhost:3002
- **Container Port:** 3002

## 📦 Image Info

- **Name:** apiome-web:latest
- **Size:** ~368MB (compressed)
- **Platform:** linux/amd64, linux/arm64
- **Base:** node:20-alpine
- **User:** nextjs (UID 1001)

## 🔐 Environment Variables

```yaml
NEXT_PUBLIC_BASE_PATH           # Base path (optional)
NEXT_PUBLIC_APP_URL             # App URL
NEXT_PUBLIC_BROWSE_URL          # Browse URL
NEXT_PUBLIC_DOCS_URL            # Docs URL
```

## 📋 Troubleshooting

### Build fails
```bash
docker builder prune
docker build --no-cache -t apiome-web:latest .
```

### Port conflict
```bash
# Use different port
docker run -d -p 8080:3002 apiome-web:latest
```

### View container status
```bash
docker ps -a | grep apiome-web
docker inspect apiome-web
```

## 📚 Documentation

- Full docs: `DOCKER_README.md`
- Setup summary: `DOCKER_SETUP_SUMMARY.md`

## 🆘 Support

- Logs: `docker logs apiome-web`
- Docs: https://docs.apiome.app
- Tutorials: https://www.youtube.com/@objectifieddev
