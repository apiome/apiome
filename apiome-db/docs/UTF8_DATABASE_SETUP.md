# PostgreSQL UTF-8 Database Setup

## Problem
The error `invalid byte sequence in US-ASCII` occurs when:
1. The database encoding is not UTF-8, OR
2. The client connection encoding is not set to UTF-8, OR
3. The tool reading the SQL files (like `sem-apply`) is not configured for UTF-8

## Solution

### 1. Check Current Database Encoding

```sql
-- Check database encoding
SELECT datname, pg_encoding_to_char(encoding) as encoding 
FROM pg_database 
WHERE datname = 'apiome';

-- Check server encoding
SHOW server_encoding;

-- Check client encoding
SHOW client_encoding;
```

### 2. Create Database with UTF-8 Encoding

If creating a new database, ensure UTF-8 encoding:

```sql
CREATE DATABASE apiome
    WITH 
    ENCODING = 'UTF8'
    LC_COLLATE = 'en_US.UTF-8'
    LC_CTYPE = 'en_US.UTF-8'
    TEMPLATE = template0;
```

### 3. Set Client Encoding for Sessions

Add to your connection or session:

```sql
SET client_encoding = 'UTF8';
```

Or set it in the connection string:
```
postgresql://user:password@host:port/apiome?client_encoding=UTF8
```

### 4. For sem-apply Tool

The issue is likely with `sem-apply` reading files. Set the environment variable before running:

```bash
# For macOS/Linux
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

# Then run sem-apply
sem-apply ...
```

Or run in one line:
```bash
LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 sem-apply ...
```

### 5. For Ruby-based tools (like sem-apply if it's Ruby)

If `sem-apply` is a Ruby tool, you may need:

```bash
    export RUBYOPT="-Eutf-8"
    ```

Or add to your shell profile (~/.zshrc or ~/.bashrc):
```bash
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8
export RUBYOPT="-Eutf-8"
```

### 6. Verify File Encoding

Check that your SQL files are UTF-8 encoded:

```bash
file scripts/20251226-141200.sql
# Should show: UTF-8 Unicode text

# If not, convert it:
iconv -f ISO-8859-1 -t UTF-8 scripts/20251226-141200.sql > scripts/20251226-141200_utf8.sql
mv scripts/20251226-141200_utf8.sql scripts/20251226-141200.sql
```

### 7. PostgreSQL Configuration (postgresql.conf)

Ensure these settings in `postgresql.conf`:

```
client_encoding = utf8
```

## Quick Fix Commands

```bash
# Set environment for current session
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

# Verify environment
locale

# Run sem-apply with UTF-8
LANG=en_US.UTF-8 sem-apply [your-arguments]
```

## Fixing "perl: warning: Setting locale failed"

This error means the UTF-8 locale is not installed on your system.

### macOS Fix

```bash
# Add to ~/.zshrc (or ~/.bashrc)
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

# Apply immediately
source ~/.zshrc
```

### Linux (Ubuntu/Debian) Fix

```bash
# Generate the locale
sudo locale-gen en_US.UTF-8

# Set as default
sudo update-locale LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8

# Or install locale package
sudo apt-get install locales
sudo dpkg-reconfigure locales
# Select en_US.UTF-8

# Apply to current session
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8
```

### Linux (RHEL/CentOS/Fedora) Fix

```bash
# Install locale
sudo dnf install glibc-langpack-en
# or
sudo yum install glibc-langpack-en

# Set environment
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8
```

### Verify Locale is Working

```bash
# Check current locale settings
locale

# Should show something like:
# LANG=en_US.UTF-8
# LC_ALL=en_US.UTF-8
# ...

# Check available locales
locale -a | grep -i utf
```

### Permanent Fix (Add to Shell Profile)

Add these lines to your `~/.zshrc` or `~/.bashrc`:

```bash
# UTF-8 Locale Settings
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8
export LANGUAGE=en_US.UTF-8
```

Then reload:
```bash
source ~/.zshrc  # or source ~/.bashrc
```

## Docker/Container Environments

If running PostgreSQL in Docker, ensure the container has UTF-8 locale:

```dockerfile
ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8
```

Or in docker-compose.yml:
```yaml
environment:
  - LANG=en_US.UTF-8
  - LC_ALL=en_US.UTF-8
  - POSTGRES_INITDB_ARGS=--encoding=UTF-8
```

