# Build Script Quick Reference

## 🚀 Common Commands

### Basic Build
```bash
./build-docker.sh
```

### Build & Push to Registry
```bash
DOCKER_REGISTRY=myregistry.com ./build-docker.sh --push
```

### Create Deployment Package
```bash
./build-docker.sh --package
```

### Fast Build (Skip Tests)
```bash
./build-docker.sh --no-test
```

## 📦 What Gets Created

| File | Description | When |
|------|-------------|------|
| `deploy-*.sh` | Deployment script | Always |
| `docker-compose.deploy-*.yml` | Compose file | Always |
| `apiome-ui-*.tar.gz` | Compressed image | Default |
| `apiome-ui-deploy-*.tar.gz` | Complete package | With `--package` |

## 🎯 Deployment Workflows

### 1. Deploy with Package (Offline)
```bash
# Build
./build-docker.sh --package

# Transfer
scp apiome-ui-deploy-*.tar.gz server:/opt/

# Deploy on server
cd /opt
tar xzf apiome-ui-deploy-*.tar.gz
cd apiome-ui-deploy-*
cp .env.template .env && nano .env
./deploy.sh
```

### 2. Deploy with Registry (Online)
```bash
# Build & Push
DOCKER_REGISTRY=myregistry.com ./build-docker.sh --push

# Deploy on server
docker pull myregistry.com/apiome-ui:latest
docker run -d -p 3000:3000 --env-file .env myregistry.com/apiome-ui:latest
```

### 3. Deploy with Manual Transfer
```bash
# Build
./build-docker.sh

# Transfer
scp apiome-ui-*.tar.gz server:/opt/

# Deploy on server
gunzip -c apiome-ui-*.tar.gz | docker load
docker run -d -p 3000:3000 --env-file .env apiome-ui:latest
```

## ⚙️ Options

| Option | Description | Example |
|--------|-------------|---------|
| `--tag TAG` | Set image tag | `--tag v1.0.0` |
| `--version VER` | Set version | `--version 1.0.0` |
| `--registry REG` | Set registry | `--registry myregistry.com` |
| `--no-test` | Skip testing | `--no-test` |
| `--no-save` | Skip tar export | `--no-save` |
| `--push` | Push to registry | `--push` |
| `--package` | Create package | `--package` |
| `--help` | Show help | `--help` |

## 🔧 Environment Variables

```bash
export DOCKER_REGISTRY=myregistry.com
export VERSION=1.0.0
export TAG=production
./build-docker.sh
```

## 📋 Build Process Steps

1. ✅ Check Docker installation
2. ✅ Verify required files
3. ✅ Build Docker image
4. ✅ Show image info
5. ✅ Test image (unless --no-test)
6. ✅ Save to tar.gz (unless --no-save)
7. ✅ Push to registry (if --push)
8. ✅ Generate deployment files
9. ✅ Create package (if --package)

## 🎨 Examples

### Development Build
```bash
./build-docker.sh --no-save
```

### Staging Build
```bash
./build-docker.sh --tag staging --push
```

### Production Build
```bash
DOCKER_REGISTRY=prod.registry.com \
./build-docker.sh \
  --tag production \
  --version 1.0.0 \
  --push \
  --package
```

### CI/CD Build
```bash
./build-docker.sh \
  --no-test \
  --push \
  --tag ${CI_COMMIT_TAG}
```

## 🐛 Troubleshooting

| Problem | Solution |
|---------|----------|
| Build fails | `docker build --no-cache .` |
| Test fails | `./build-docker.sh --no-test` |
| Permission denied | `chmod +x build-docker.sh` |
| Registry push fails | `docker login myregistry.com` |
| Port in use | Check port 3001: `lsof -i :3001` |

## 📊 Output Summary

After successful build:
```
=== Build Complete ===

Image: apiome-ui:latest
Version: 20241206-123456

Next Steps:
  1. Test locally: docker run -p 3000:3000 apiome-ui:latest
  2. Deploy with: ./deploy-20241206-123456.sh
  3. Or use: docker-compose -f docker-compose.deploy-20241206-123456.yml up -d
  4. Transfer: apiome-ui-deploy-20241206-123456.tar.gz to remote server
```

## 🔐 Security Checklist

- [ ] Registry authenticated before push
- [ ] Secrets not included in image
- [ ] .env file configured on server
- [ ] Image scanned for vulnerabilities
- [ ] Non-root user in container

## 📚 Documentation

- Full Guide: `BUILD_SCRIPT_GUIDE.md`
- Docker Setup: `DOCKER_README.md`
- Quick Ref: `DOCKER_QUICK_REF.md`

---

**Quick Help**: `./build-docker.sh --help`

