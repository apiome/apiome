#!/usr/bin/env bash
#
# get-apiome-installer.sh — serve the Apiome CLI installer at https://get.apiome.dev with nginx,
# and keep it current.
#
# MVP launch step 12 (docs/MVP_LAUNCH.md, blocker B5): `curl -fsSL https://get.apiome.dev | sh` must
# return apiome-cli/install.sh over a certificate that covers get.apiome.dev.
#
# What it does:
#
#   refresh   Download apiome-cli/install.sh from GitHub (branch `main` unless --ref is given),
#             check it really is the installer, and swap it into the web root atomically. The
#             previous copy is kept as install.sh.prev. Nothing changes when the file is the same,
#             and a bad download never replaces a good file.
#   setup     One-time, as root: install this script to /usr/local/sbin, run a first refresh, write
#             the nginx site, obtain a Let's Encrypt certificate (certbot, webroot challenge), then
#             install a timer that runs `refresh` every 15 minutes (systemd, or cron when systemd is
#             absent).
#   status    Show what is being served, its checksum and age, the certificate's expiry and the timer.
#   render    Print the nginx site to stdout without touching anything (to review or hand-edit).
#   uninstall Remove the nginx site and the timer (the web root and certificate are left in place).
#
# Usage (on the host the get.apiome.dev DNS record points at):
#
#   sudo ./get-apiome-installer.sh setup --email ops@apiome.dev
#   sudo get-apiome-installer refresh            # any time; the timer does it every 15 minutes
#   get-apiome-installer status
#   ./get-apiome-installer.sh render              # preview the nginx config
#
# Options (each also settable through the environment variable in brackets):
#
#   --domain <name>     Host name to serve                     [APIOME_INSTALLER_DOMAIN, get.apiome.dev]
#   --ref <git ref>     Branch, tag or commit to serve from    [APIOME_INSTALLER_REF, main]
#   --webroot <dir>     Where install.sh is written            [APIOME_INSTALLER_WEBROOT, /var/www/<domain>]
#   --email <address>   Let's Encrypt contact (setup only)     [APIOME_INSTALLER_EMAIL]
#   --interval <min>    Refresh interval in minutes (setup)    [APIOME_INSTALLER_INTERVAL, 15]
#   --no-tls            Skip certbot; serve plain HTTP only (testing)
#   --repo-raw <url>    Raw-content base URL                   [APIOME_INSTALLER_REPO_RAW,
#                                                               https://raw.githubusercontent.com/apiome/apiome]
#
# Requirements: bash, curl, sha256sum, sh; for setup also nginx and certbot (with root).

set -euo pipefail

# ---------------------------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------------------------

DOMAIN="${APIOME_INSTALLER_DOMAIN:-get.apiome.dev}"
REF="${APIOME_INSTALLER_REF:-main}"
REPO_RAW="${APIOME_INSTALLER_REPO_RAW:-https://raw.githubusercontent.com/apiome/apiome}"
WEBROOT="${APIOME_INSTALLER_WEBROOT:-}"
EMAIL="${APIOME_INSTALLER_EMAIL:-}"
INTERVAL="${APIOME_INSTALLER_INTERVAL:-15}"
TLS=1

# Where `setup` installs this script, so the timer calls a stable path.
INSTALLED_PATH="/usr/local/sbin/get-apiome-installer"
# A marker line the real installer carries; a download without it is refused.
INSTALLER_MARKER="Apiome CLI installer"
# The installer is ~15 KB; anything over this is not it.
MAX_BYTES=1048576
# Unit and cron names.
UNIT_NAME="get-apiome-installer-refresh"
CRON_FILE="/etc/cron.d/${UNIT_NAME}"

# ---------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------

log() { printf '%s [get-apiome-installer] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
die() { log "error: $*" >&2; exit 1; }

require_root() { [ "$(id -u)" -eq 0 ] || die "'$1' must run as root (use sudo)"; }
require_cmd() { command -v "$1" >/dev/null 2>&1 || die "'$1' is required but not installed"; }

# Resolve the web root once the domain is known.
resolve_webroot() { WEBROOT="${WEBROOT:-/var/www/${DOMAIN}}"; }

# The nginx site file: Debian's sites-available (linked from sites-enabled), else conf.d.
nginx_site_path() {
  if [ -d /etc/nginx/sites-available ] && [ -d /etc/nginx/sites-enabled ]; then
    printf '/etc/nginx/sites-available/%s\n' "$DOMAIN"
  else
    printf '/etc/nginx/conf.d/%s.conf\n' "$DOMAIN"
  fi
}

reload_nginx() {
  nginx -t || die "nginx rejected the configuration; nothing was reloaded"
  if command -v systemctl >/dev/null 2>&1; then systemctl reload nginx; else nginx -s reload; fi
}

# ---------------------------------------------------------------------------------------------
# refresh — download, validate, swap in
# ---------------------------------------------------------------------------------------------

# Check a downloaded file is the Apiome installer. Prints the reason and fails otherwise.
validate_installer() {
  local file="$1" size
  size=$(wc -c <"$file" | tr -d ' ')
  [ "$size" -gt 0 ] || { echo "the download is empty"; return 1; }
  [ "$size" -le "$MAX_BYTES" ] || { echo "the download is ${size} bytes, larger than ${MAX_BYTES}"; return 1; }
  [ "$(head -n 1 "$file")" = "#!/bin/sh" ] || { echo "the first line is not '#!/bin/sh'"; return 1; }
  grep -q "$INSTALLER_MARKER" "$file" || { echo "it does not contain '${INSTALLER_MARKER}'"; return 1; }
  sh -n "$file" 2>/dev/null || { echo "it is not valid sh (sh -n failed)"; return 1; }
}

cmd_refresh() {
  require_cmd curl
  require_cmd sha256sum
  resolve_webroot
  mkdir -p "$WEBROOT"
  [ -w "$WEBROOT" ] || die "cannot write to ${WEBROOT} (run as root, or pass --webroot)"

  local url="${REPO_RAW}/${REF}/apiome-cli/install.sh"
  local target="${WEBROOT}/install.sh"
  # Global so the EXIT trap still sees it after `die`; harmless once the file has been moved in.
  REFRESH_TMP=$(mktemp "${WEBROOT}/.install.sh.XXXXXX")
  trap 'rm -f "${REFRESH_TMP:-}"' EXIT
  local tmp="$REFRESH_TMP"

  log "fetching ${url}"
  curl --proto '=https' --tlsv1.2 -fsSL --retry 3 --retry-delay 2 --max-time 60 -o "$tmp" "$url" \
    || die "download failed: ${url}"

  local reason
  if ! reason=$(validate_installer "$tmp"); then
    die "refusing the download (${reason}); still serving the previous install.sh"
  fi

  local new_sum old_sum=""
  new_sum=$(sha256sum "$tmp" | cut -d' ' -f1)
  [ -f "$target" ] && old_sum=$(sha256sum "$target" | cut -d' ' -f1)
  if [ "$new_sum" = "$old_sum" ]; then
    log "unchanged (sha256 ${new_sum:0:12}…, ref ${REF})"
    return 0
  fi

  chmod 0644 "$tmp"
  [ -f "$target" ] && cp -p "$target" "${target}.prev"
  mv -f "$tmp" "$target"  # atomic on the same filesystem: readers see the old or the new file, never half
  printf '%s\n' "$new_sum" >"${WEBROOT}/install.sh.sha256"
  log "updated install.sh (sha256 ${new_sum:0:12}…, ref ${REF}${old_sum:+, previous ${old_sum:0:12}…})"
}

# ---------------------------------------------------------------------------------------------
# nginx site
# ---------------------------------------------------------------------------------------------

# The site. With TLS: port 80 answers ACME challenges and redirects to https; port 443 serves the
# installer. Without a certificate yet (first boot) or with --no-tls: port 80 serves everything.
render_nginx() {
  local with_tls="$1"
  resolve_webroot
  local cert="/etc/letsencrypt/live/${DOMAIN}/fullchain.pem"
  local key="/etc/letsencrypt/live/${DOMAIN}/privkey.pem"

  cat <<NGINX
# Managed by get-apiome-installer.sh — serves the Apiome CLI installer.
# Regenerate with: sudo get-apiome-installer setup (hand edits are overwritten).

server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};

    # Let's Encrypt HTTP-01 challenges (certbot --webroot).
    location ^~ /.well-known/acme-challenge/ {
        root ${WEBROOT};
        default_type text/plain;
    }
NGINX

  if [ "$with_tls" = 1 ]; then
    cat <<NGINX

    location / {
        return 301 https://\$host\$request_uri;
    }
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name ${DOMAIN};

    ssl_certificate     ${cert};
    ssl_certificate_key ${key};
    ssl_protocols       TLSv1.2 TLSv1.3;
NGINX
  fi

  cat <<NGINX

    root ${WEBROOT};

    # \`curl -fsSL https://${DOMAIN}\` and \`…/install.sh\` both return the installer.
    location = / {
        try_files /install.sh =404;
        default_type text/plain;
        charset utf-8;
        add_header Cache-Control "public, max-age=300" always;
        add_header X-Content-Type-Options "nosniff" always;
    }
    location = /install.sh {
        try_files /install.sh =404;
        default_type text/plain;
        charset utf-8;
        add_header Cache-Control "public, max-age=300" always;
        add_header X-Content-Type-Options "nosniff" always;
    }
    location = /install.sh.sha256 {
        default_type text/plain;
        add_header Cache-Control "public, max-age=300" always;
    }

    # Nothing else is served from this host name.
    location / {
        return 404;
    }
}
NGINX
}

write_nginx_site() {
  local with_tls="$1" site
  site=$(nginx_site_path)
  render_nginx "$with_tls" >"$site"
  if [[ "$site" == /etc/nginx/sites-available/* ]]; then
    ln -sf "$site" "/etc/nginx/sites-enabled/${DOMAIN}"
  fi
  log "wrote ${site} ($( [ "$with_tls" = 1 ] && echo 'HTTPS' || echo 'HTTP only'))"
  reload_nginx
}

# ---------------------------------------------------------------------------------------------
# The refresh timer
# ---------------------------------------------------------------------------------------------

install_timer() {
  local args="--domain ${DOMAIN} --ref ${REF} --webroot ${WEBROOT} --repo-raw ${REPO_RAW}"
  if command -v systemctl >/dev/null 2>&1 && [ -d /etc/systemd/system ]; then
    cat >"/etc/systemd/system/${UNIT_NAME}.service" <<UNIT
[Unit]
Description=Refresh the Apiome CLI installer served at ${DOMAIN}
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
ExecStart=${INSTALLED_PATH} refresh ${args}
UNIT
    cat >"/etc/systemd/system/${UNIT_NAME}.timer" <<UNIT
[Unit]
Description=Refresh the Apiome CLI installer every ${INTERVAL} minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=${INTERVAL}min
RandomizedDelaySec=60
Persistent=true

[Install]
WantedBy=timers.target
UNIT
    systemctl daemon-reload
    systemctl enable --now "${UNIT_NAME}.timer"
    log "installed systemd timer ${UNIT_NAME}.timer (every ${INTERVAL} min)"
  else
    printf '*/%s * * * * root %s refresh %s >>/var/log/%s.log 2>&1\n' \
      "$INTERVAL" "$INSTALLED_PATH" "$args" "$UNIT_NAME" >"$CRON_FILE"
    chmod 0644 "$CRON_FILE"
    log "installed cron entry ${CRON_FILE} (every ${INTERVAL} min)"
  fi
}

remove_timer() {
  if command -v systemctl >/dev/null 2>&1 && [ -f "/etc/systemd/system/${UNIT_NAME}.timer" ]; then
    systemctl disable --now "${UNIT_NAME}.timer" || true
    rm -f "/etc/systemd/system/${UNIT_NAME}.timer" "/etc/systemd/system/${UNIT_NAME}.service"
    systemctl daemon-reload
    log "removed systemd timer"
  fi
  if [ -f "$CRON_FILE" ]; then rm -f "$CRON_FILE"; log "removed ${CRON_FILE}"; fi
}

# ---------------------------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------------------------

cmd_setup() {
  require_root setup
  require_cmd nginx
  require_cmd curl
  resolve_webroot
  [ "$INTERVAL" -ge 1 ] 2>/dev/null || die "--interval must be a whole number of minutes"

  install -m 0755 "$0" "$INSTALLED_PATH"
  log "installed ${INSTALLED_PATH}"

  cmd_refresh

  # Serve over HTTP first: certbot's webroot challenge needs port 80 answering for the domain.
  write_nginx_site 0

  if [ "$TLS" = 1 ]; then
    require_cmd certbot
    [ -n "$EMAIL" ] || die "--email is required to obtain a certificate (or pass --no-tls)"
    certbot certonly --webroot -w "$WEBROOT" -d "$DOMAIN" \
      --email "$EMAIL" --agree-tos --non-interactive --keep-until-expiring \
      --deploy-hook "nginx -t && (systemctl reload nginx 2>/dev/null || nginx -s reload)"
    write_nginx_site 1
  fi

  install_timer
  log "done — test with: curl -fsSL $( [ "$TLS" = 1 ] && echo https || echo http )://${DOMAIN} | head -3"
}

cmd_status() {
  resolve_webroot
  local target="${WEBROOT}/install.sh"
  echo "domain:   ${DOMAIN}"
  echo "ref:      ${REF}"
  if [ -f "$target" ]; then
    echo "serving:  ${target} ($(wc -c <"$target" | tr -d ' ') bytes, sha256 $(sha256sum "$target" | cut -c1-12)…)"
    echo "updated:  $(date -u -r "$target" +%Y-%m-%dT%H:%M:%SZ)"
  else
    echo "serving:  nothing yet (${target} missing — run refresh)"
  fi
  local cert="/etc/letsencrypt/live/${DOMAIN}/fullchain.pem"
  if [ -r "$cert" ] && command -v openssl >/dev/null 2>&1; then
    echo "cert:     $(openssl x509 -noout -enddate -in "$cert" | sed 's/notAfter=/expires /')"
  else
    echo "cert:     none readable at ${cert}"
  fi
  if command -v systemctl >/dev/null 2>&1 && systemctl list-timers --all 2>/dev/null | grep -q "$UNIT_NAME"; then
    echo "timer:    $(systemctl list-timers --all 2>/dev/null | grep "$UNIT_NAME" | awk '{print "next run", $1, $2, $3}')"
  elif [ -f "$CRON_FILE" ]; then
    echo "timer:    cron (${CRON_FILE})"
  else
    echo "timer:    not installed"
  fi
}

cmd_uninstall() {
  require_root uninstall
  remove_timer
  local site
  site=$(nginx_site_path)
  rm -f "$site" "/etc/nginx/sites-enabled/${DOMAIN}"
  log "removed ${site}"
  command -v nginx >/dev/null 2>&1 && reload_nginx
  log "left in place: ${WEBROOT:-/var/www/${DOMAIN}}, the certificate, and ${INSTALLED_PATH}"
}

usage() { sed -n '3,40p' "$0" | sed 's/^# \{0,1\}//'; }

# ---------------------------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------------------------

main() {
  local command="${1:-}"
  [ -n "$command" ] || { usage; exit 2; }
  shift
  while [ $# -gt 0 ]; do
    case "$1" in
      --domain) DOMAIN="${2:?--domain needs a value}"; shift 2 ;;
      --ref) REF="${2:?--ref needs a value}"; shift 2 ;;
      --webroot) WEBROOT="${2:?--webroot needs a value}"; shift 2 ;;
      --email) EMAIL="${2:?--email needs a value}"; shift 2 ;;
      --interval) INTERVAL="${2:?--interval needs a value}"; shift 2 ;;
      --repo-raw) REPO_RAW="${2:?--repo-raw needs a value}"; shift 2 ;;
      --no-tls) TLS=0; shift ;;
      -h|--help) usage; exit 0 ;;
      *) die "unknown option: $1 (see --help)" ;;
    esac
  done
  # Refs and domains end up in URLs, file paths and unit files: keep them to safe characters.
  [[ "$REF" =~ ^[A-Za-z0-9._/-]+$ ]] || die "--ref has unexpected characters: ${REF}"
  [[ "$DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]] || die "--domain has unexpected characters: ${DOMAIN}"

  case "$command" in
    refresh) cmd_refresh ;;
    setup) cmd_setup ;;
    status) cmd_status ;;
    render) render_nginx "$TLS" ;;
    uninstall) cmd_uninstall ;;
    -h|--help|help) usage ;;
    *) die "unknown command: ${command} (refresh, setup, status, render, uninstall)" ;;
  esac
}

main "$@"
