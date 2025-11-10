# UV Project Setup Guide

## Overview
The Objectified REST API project has been configured to use **uv**, a fast Python package installer and resolver written in Rust. This provides better dependency management, faster installation, and a lockfile for reproducible builds.

## What Was Added

### 1. `pyproject.toml`
Modern Python project configuration file that replaces `setup.py` and defines:
- **Project metadata**: name, version, description
- **Dependencies**: All required packages with version constraints
- **Python version requirement**: >= 3.11
- **Development dependencies**: Testing packages via dependency-groups
- **Build system**: Hatchling for building distributions

### 2. `uv.lock`
Automatically generated lockfile that:
- Pins exact versions of all dependencies and sub-dependencies
- Ensures reproducible installations across different environments
- Contains checksums for security
- Similar to `package-lock.json` (npm) or `Cargo.lock` (Rust)

### 3. `src/app/__main__.py`
Entry point for running the app as a module:
- Allows running with `python -m app` or `uv run -m app`
- Starts the uvicorn server with configured settings
- Respects settings from `.env` file

### 4. `run.sh`
Convenience script for running the server:
- Simple `./run.sh` command
- Automatically uses uv to run the app
- Changes to project directory first

## Installation & Setup

### First Time Setup

1. **Install uv:**
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Add to PATH** (if not done automatically):
   ```bash
   source $HOME/.local/bin/env
   ```

3. **Sync dependencies:**
   ```bash
   cd /home/kenji/Development/objectified/objectified-rest
   uv sync
   ```

This will:
- Create a `.venv` virtual environment
- Install all dependencies from `pyproject.toml`
- Generate/update `uv.lock`

## Running the Server

### Method 1: Direct uv command
```bash
uv run -m app
```

### Method 2: Helper script
```bash
./run.sh
```

### Method 3: Traditional Python
```bash
cd src
python -m app
```

## Common UV Commands

### Install Dependencies
```bash
# Sync all dependencies (including dev)
uv sync

# Install only production dependencies
uv sync --no-dev
```

### Add New Dependency
```bash
# Add to dependencies
uv add package-name

# Add to dev dependencies
uv add --dev package-name
```

### Remove Dependency
```bash
uv remove package-name
```

### Update Dependencies
```bash
# Update all packages
uv sync --upgrade

# Update specific package
uv add package-name --upgrade
```

### Run Scripts
```bash
# Run the app
uv run -m app

# Run pytest
uv run pytest

# Run any Python script
uv run python script.py
```

### Check Outdated Packages
```bash
uv pip list --outdated
```

## Project Structure

```
objectified-rest/
├── pyproject.toml          # Project configuration
├── uv.lock                 # Locked dependencies
├── requirements.txt        # Legacy pip requirements (kept for compatibility)
├── .venv/                  # Virtual environment (created by uv sync)
├── run.sh                  # Convenience run script
├── src/
│   └── app/
│       ├── __init__.py
│       ├── __main__.py     # Entry point for module execution
│       ├── main.py         # FastAPI application
│       ├── config.py
│       ├── database.py
│       ├── models.py
│       └── openapi_generator.py
└── README.md
```

## Benefits of Using uv

### 🚀 Speed
- **10-100x faster** than pip for dependency resolution
- Written in Rust for maximum performance
- Parallel downloads and installations

### 🔒 Reproducibility
- `uv.lock` ensures exact same versions everywhere
- Checksums verify package integrity
- No "works on my machine" issues

### 🎯 Simplicity
- Single command to install everything: `uv sync`
- No need to manage `virtualenv` separately
- Automatic virtual environment creation

### 📦 Modern
- Follows latest Python packaging standards (PEP 621)
- Compatible with `pyproject.toml`
- Works with existing pip workflows

### 🔧 Better Dependency Resolution
- Faster conflict resolution
- More accurate version constraint solving
- Clear error messages

## Configuration Details

### pyproject.toml Sections

```toml
[project]
# Core project metadata
name = "objectified-rest"
version = "1.0.0"
requires-python = ">=3.11"
dependencies = [...]  # Production dependencies

[project.optional-dependencies]
dev = [...]  # Optional dev tools

[dependency-groups]
dev = [...]  # Development dependencies (uv-specific)

[build-system]
# How to build the package
requires = ["hatchling"]
build-backend = "hatchling.build"
```

### Environment Variables

Still configured via `.env` file:
```bash
DATABASE_URL=postgresql://...
HOST=0.0.0.0
PORT=8000
RELOAD=True
```

## Migration from pip

The project supports both workflows:

**Legacy pip workflow** (still works):
```bash
pip install -r requirements.txt
cd src && python run.py
```

**Modern uv workflow** (recommended):
```bash
uv sync
uv run -m app
```

## Troubleshooting

### uv command not found
```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Add to PATH
source $HOME/.local/bin/env

# Or add to your shell rc file:
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
```

### Virtual environment issues
```bash
# Remove and recreate
rm -rf .venv
uv sync
```

### Dependency conflicts
```bash
# Update the lockfile
uv lock --upgrade

# Force reinstall
rm uv.lock
uv sync
```

### Import errors when running
```bash
# Make sure you're running from project root
cd /home/kenji/Development/objectified/objectified-rest
uv run -m app

# Or ensure PYTHONPATH is set
export PYTHONPATH="${PYTHONPATH}:./src"
```

## CI/CD Integration

### GitHub Actions Example
```yaml
- name: Set up uv
  run: curl -LsSf https://astral.sh/uv/install.sh | sh

- name: Install dependencies
  run: uv sync

- name: Run tests
  run: uv run pytest
```

### Docker Integration

```dockerfile
FROM python:3.11-slim

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /app
COPY ../pyproject.toml uv.lock ./
RUN uv sync --no-dev

COPY .. .
CMD ["uv", "run", "-m", "app"]
```

## Additional Resources

- **uv Documentation**: https://docs.astral.sh/uv/
- **PEP 621** (pyproject.toml): https://peps.python.org/pep-0621/
- **Python Packaging Guide**: https://packaging.python.org/

## Summary

✅ **Complete Setup**
- pyproject.toml configured with all dependencies
- uv.lock generated for reproducible builds
- Entry point created for module execution
- Helper script for convenience
- README updated with instructions

🚀 **Ready to Use**
```bash
# Just run:
uv run -m app

# Or:
./run.sh
```

The project is now modernized with uv for faster, more reliable dependency management!

