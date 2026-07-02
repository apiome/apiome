# Apiome: NGINX Infrastructure - Feature Roadmap

> Hardened NGINX configuration layer providing security, performance, and reliability guarantees for the Apiome platform. Covers SSL/TLS tuning, security headers, rate limiting, DDoS mitigation, access control, logging, and fail2ban integration.
>
> **Revenue Model**: Infrastructure cost reduction through better caching and connection pooling; reduced security incident costs; compliance enablement for enterprise tiers
>
> **Tech Stack**: NGINX (latest stable), Let's Encrypt/Certbot, fail2ban, GeoIP2 module, OpenSSL, logrotate

---

## MVP Definition

- TLS 1.2/1.3 only with strong cipher suites and HSTS enabled
- Core security headers (X-Frame-Options, X-Content-Type-Options, CSP, Referrer-Policy)
- Rate limiting and concurrent connection limits per IP
- Block access to sensitive file extensions and dotfiles
- Detailed access logging with rotation configured
- NGINX running as non-root user with minimal module footprint

---

## Epic 1 (#1984): SSL/TLS & Security Headers Hardening

### Summary Table

| #   | Title                                    | Description                                                                     | Labels                                      | MVP | Parallel |
|-----|------------------------------------------|---------------------------------------------------------------------------------|---------------------------------------------|-----|----------|
| 1.1 (#1985) | Harden SSL/TLS Settings                  | Configure strong cipher suites, enable TLS 1.2/1.3 only, disable legacy versions | `enhancement`, `mvp`, `nginx`, `security`  | Yes | No       |
| 1.2 (#1986) | Enable HSTS with Long max-age            | Set HTTP Strict Transport Security header with a long max-age and includeSubDomains | `enhancement`, `mvp`, `nginx`, `security` | Yes | Yes      |
| 1.3 (#1987) | Implement OCSP Stapling                  | Enable OCSP stapling for faster TLS handshakes and certificate validation       | `enhancement`, `nginx`, `security`          | No  | Yes      |
| 1.4 (#1988) | Configure SSL Session Caching            | Enable SSL session cache and tickets to reduce TLS handshake overhead           | `enhancement`, `nginx`, `security`          | No  | Yes      |
| 1.5 (#1989) | Add X-Frame-Options Header               | Prevent clickjacking by setting X-Frame-Options: SAMEORIGIN across all responses | `enhancement`, `mvp`, `nginx`, `security`  | Yes | Yes      |
| 1.6 (#1990) | Add X-Content-Type-Options Header        | Prevent MIME sniffing with nosniff directive                                    | `enhancement`, `mvp`, `nginx`, `security`  | Yes | Yes      |
| 1.7 (#1991) | Add X-XSS-Protection Header             | Legacy browser XSS protection header for clients that support it                | `enhancement`, `nginx`, `security`          | No  | Yes      |
| 1.8 (#1992) | Implement Content-Security-Policy        | Define and enforce CSP header; iteratively tighten policy without breaking UX   | `enhancement`, `mvp`, `nginx`, `security`  | Yes | No       |
| 1.9 (#1993) | Add Referrer-Policy Header              | Set strict-origin-when-cross-origin to prevent referrer leakage                 | `enhancement`, `mvp`, `nginx`, `security`  | Yes | Yes      |
| 1.10 (#1994) | Add Permissions-Policy Header           | Restrict browser feature access (camera, microphone, geolocation, etc.)         | `enhancement`, `nginx`, `security`          | No  | Yes      |
| 1.11 (#1995) | Remove / Obscure Server Header          | Hide NGINX version from Server response header to reduce fingerprinting          | `enhancement`, `mvp`, `nginx`, `security`  | Yes | Yes      |

### Detailed Issue Descriptions

#### 1.1 (#1985) — Harden SSL/TLS Settings

Upgrade NGINX's SSL configuration to enforce modern cryptography. Disable TLS 1.0 and TLS 1.1 entirely; set `ssl_protocols TLSv1.2 TLSv1.3`. Configure `ssl_ciphers` to prefer ECDHE key exchange with CHACHA20-POLY1305 and AES-GCM. Set `ssl_prefer_server_ciphers on` so the server's cipher order is used rather than the client's. Verify with SSLLabs and aim for an A+ grade.

```
ssl_protocols TLSv1.2 TLSv1.3;
ssl_ciphers 'ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:
             ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256';
ssl_prefer_server_ciphers on;
```

**Acceptance Criteria:**
- `ssl_protocols` includes only TLSv1.2 and TLSv1.3
- SSLLabs scan returns A+ (or A at minimum with documented justification)
- Cipher list excludes RC4, DES, MD5, and export-grade ciphers
- Configuration deployed and validated in staging before production rollout

**Tech Stack:** NGINX ssl module, OpenSSL ≥ 1.1.1, SSLLabs API for validation

Part of Epic: SSL/TLS & Security Headers Hardening

---

#### 1.2 (#1986) — Enable HSTS with Long max-age

Add the `Strict-Transport-Security` header with a `max-age` of at least one year (31536000 seconds), `includeSubDomains`, and `preload` once the domain is submitted to the HSTS preload list. This instructs browsers to always use HTTPS and prevents protocol downgrade attacks.

**Acceptance Criteria:**
- Header present on all HTTPS responses: `Strict-Transport-Security: max-age=31536000; includeSubDomains; preload`
- No HTTP responses served to end users (HTTP redirects to HTTPS at the load balancer level)
- Verified with curl and security header scanning tools

**Parallel Group:** SECURITY-HEADERS
**Can run alongside:** 1.3, 1.4, 1.5, 1.6, 1.7, 1.9, 1.10, 1.11

Part of Epic: SSL/TLS & Security Headers Hardening

---

#### 1.8 (#1992) — Implement Content-Security-Policy

CSP requires careful policy design to avoid breaking the application. Start with `Content-Security-Policy-Report-Only` in reporting mode, collect violations, then progressively tighten the policy. The final policy should restrict script sources to known CDNs and self, block inline scripts via nonce, and restrict frame ancestors to `'none'`.

```
Content-Security-Policy:
  default-src 'self';
  script-src 'self' 'nonce-{RANDOM}' https://cdn.example.com;
  style-src 'self' 'unsafe-inline';
  img-src 'self' data: https:;
  font-src 'self';
  frame-ancestors 'none';
  base-uri 'self';
  form-action 'self';
```

**Acceptance Criteria:**
- Report-only mode deployed and violation reports collected for ≥ 1 week before enforcement
- Enforcement mode does not break any existing UI functionality
- Nonce-based script allowlisting implemented in Next.js middleware
- CSP header scanner returns no critical violations

Part of Epic: SSL/TLS & Security Headers Hardening

---

## Epic 2 (#1996): Request Filtering, Rate Limiting & DDoS Protection

### Summary Table

| #   | Title                                    | Description                                                                      | Labels                                 | MVP | Parallel |
|-----|------------------------------------------|----------------------------------------------------------------------------------|----------------------------------------|-----|----------|
| 2.1 (#1997) | Limit Request Body Size                  | Set client_max_body_size globally and per-location to prevent oversized requests | `enhancement`, `mvp`, `nginx`         | Yes | Yes      |
| 2.2 (#2028) | Configure Connection Timeouts            | Set client_body_timeout and client_header_timeout to drop slow clients           | `enhancement`, `mvp`, `nginx`         | Yes | Yes      |
| 2.3 (#1998) | Limit Concurrent Connections per IP      | Use limit_conn_zone and limit_conn to cap connections per client IP              | `enhancement`, `mvp`, `nginx`         | Yes | No       |
| 2.4 (#1999) | Configure Request Rate Limiting          | Implement limit_req_zone with burst allowance for API and auth endpoints         | `enhancement`, `mvp`, `nginx`         | Yes | No       |
| 2.5 (#2000) | Block Suspicious User Agents             | Deny requests from known bad bots, scrapers, and vulnerability scanners          | `enhancement`, `nginx`, `security`    | No  | Yes      |
| 2.6 (#2001) | Block Sensitive File Extensions          | Return 404/403 for .git, .env, .sql, .bak, and similar sensitive paths          | `enhancement`, `mvp`, `nginx`, `security` | Yes | Yes  |
| 2.7 (#2002) | Limit Allowed HTTP Methods               | Only permit GET, POST, PUT, PATCH, DELETE, OPTIONS; return 405 otherwise         | `enhancement`, `nginx`, `security`    | No  | Yes      |
| 2.8 (#2003) | Install Torblock                         | Block known Tor exit nodes using the torblock NGINX module                       | `enhancement`, `nginx`, `security`    | No  | Yes      |
| 2.9 (#2004) | Enable proxy_buffering                   | Enable upstream proxy buffering to protect backend from slow clients             | `enhancement`, `nginx`                | No  | Yes      |
| 2.10 (#2005) | Configure keepalive_timeout             | Tune keepalive_timeout to release idle connections and reduce resource exhaustion | `enhancement`, `nginx`               | No  | Yes      |

### Detailed Issue Descriptions

#### 2.3 (#1998) — Limit Concurrent Connections per IP

Define a shared memory zone keyed on `$binary_remote_addr` and apply a per-location connection limit. API routes should allow up to 20 concurrent connections per IP; auth routes should cap at 5 to limit credential stuffing.

```
limit_conn_zone $binary_remote_addr zone=perip:10m;

server {
    location /api/ {
        limit_conn perip 20;
    }
    location /auth/ {
        limit_conn perip 5;
    }
}
```

**Acceptance Criteria:**
- Connections beyond the limit receive `503 Service Unavailable`
- Zone size (10m) supports at least 160,000 tracked IP addresses simultaneously
- Limit applies per upstream `$binary_remote_addr`, not per proxy chain hop

**Tech Stack:** NGINX `ngx_http_limit_conn_module`

Part of Epic: Request Filtering, Rate Limiting & DDoS Protection

---

#### 2.4 (#1999) — Configure Request Rate Limiting

Implement tiered rate limiting: a global zone for all traffic and a stricter zone for authentication endpoints. Use `burst` to allow short spikes without immediately returning 429, and `nodelay` for strict auth enforcement.

```
limit_req_zone $binary_remote_addr zone=api:10m rate=100r/s;
limit_req_zone $binary_remote_addr zone=auth:10m rate=5r/m;

location /api/ {
    limit_req zone=api burst=50 nodelay;
}
location /auth/ {
    limit_req zone=auth burst=3 nodelay;
}
```

**Acceptance Criteria:**
- Rate limit responses return `429 Too Many Requests` with a `Retry-After` header
- Auth endpoint rejects brute force (> 5 requests/minute per IP returns 429)
- Burst allowance does not allow sustained above-limit throughput

Part of Epic: Request Filtering, Rate Limiting & DDoS Protection

---

## Epic 3 (#2006): Access Control & Logging

### Summary Table

| #   | Title                                        | Description                                                                    | Labels                                 | MVP | Parallel |
|-----|----------------------------------------------|--------------------------------------------------------------------------------|----------------------------------------|-----|----------|
| 3.1 (#2007) | Restrict Admin Endpoints by IP Whitelist     | Allow /admin routes only from trusted CIDR ranges                              | `enhancement`, `nginx`, `security`    | No  | Yes      |
| 3.2 (#2008) | Block Dotfiles and Hidden Directories        | Return 403 for any request path starting with a dot                            | `enhancement`, `mvp`, `nginx`, `security` | Yes | Yes  |
| 3.3 (#2009) | Disable Directory Listing                    | Set autoindex off globally to prevent directory traversal                      | `enhancement`, `mvp`, `nginx`, `security` | Yes | Yes  |
| 3.4 (#2010) | Block Known Malicious IP Ranges via GeoIP    | Use GeoIP2 module to block requests from high-risk countries or known bad ASNs | `enhancement`, `nginx`, `security`    | No  | Yes      |
| 3.5 (#2011) | Enable Detailed Access Logging               | Configure custom log format capturing latency, upstream, request ID            | `enhancement`, `mvp`, `nginx`         | Yes | No       |
| 3.6 (#2012) | Configure Log Rotation                       | Set up logrotate for NGINX access and error logs to prevent disk exhaustion    | `enhancement`, `mvp`, `nginx`         | Yes | No       |
| 3.7 (#2013) | Separate Log for Rate-Limited Requests       | Route rate-limited and blocked request logs to a dedicated log file            | `enhancement`, `nginx`                | No  | Yes      |

### Detailed Issue Descriptions

#### 3.5 (#2011) — Enable Detailed Access Logging

Replace the default NGINX combined log format with a custom JSON-structured format that includes: request duration (`$request_time`), upstream response time (`$upstream_response_time`), upstream address, HTTP status, request ID header, and client IP. This enables structured log ingestion into Elasticsearch or similar.

```
log_format json_combined escape=json
  '{'
    '"time":"$time_iso8601",'
    '"remote_addr":"$remote_addr",'
    '"method":"$request_method",'
    '"uri":"$request_uri",'
    '"status":$status,'
    '"request_time":$request_time,'
    '"upstream_time":"$upstream_response_time",'
    '"request_id":"$http_x_request_id"'
  '}';

access_log /var/log/nginx/access.log json_combined;
```

**Acceptance Criteria:**
- All requests produce JSON-structured log entries
- Log entries include `request_time` and `upstream_response_time` fields
- Error log level set to `warn` (not `info`) in production
- Log format validated by parsing sample output with `jq`

Part of Epic: Access Control & Logging

---

## Epic 4 (#2014): Performance, Infrastructure Security & fail2ban

### Summary Table

| #   | Title                                      | Description                                                                    | Labels                            | MVP | Parallel |
|-----|--------------------------------------------|--------------------------------------------------------------------------------|-----------------------------------|-----|----------|
| 4.1 (#2015) | Enable Gzip Compression                    | Enable gzip for text/html, text/css, application/json, and JS responses        | `enhancement`, `nginx`           | No  | Yes      |
| 4.2 (#2016) | Configure Browser Caching Headers          | Set Cache-Control and Expires headers for static assets                        | `enhancement`, `nginx`           | No  | Yes      |
| 4.3 (#2017) | Configure Connection Pooling               | Set keepalive connections to upstream backends in proxy_pass blocks            | `enhancement`, `nginx`           | No  | Yes      |
| 4.4 (#2018) | Enable HTTP/2                              | Enable http2 on all TLS virtual hosts for multiplexing and header compression  | `enhancement`, `nginx`           | No  | Yes      |
| 4.5 (#2019) | Evaluate HTTP/3 (QUIC) Support             | Assess NGINX QUIC build, benchmark vs HTTP/2, define rollout criteria          | `enhancement`, `nginx`           | No  | No       |
| 4.6 (#2020) | Run NGINX as Non-Root User                 | Configure worker processes to run as the nginx system user, not root           | `enhancement`, `mvp`, `nginx`, `security` | Yes | Yes |
| 4.7 (#2021) | Restrict NGINX Config File Permissions     | Set config files to 640 owned by root:nginx; deny world-readable access        | `enhancement`, `mvp`, `nginx`, `security` | Yes | Yes |
| 4.8 (#2022) | Disable Unnecessary NGINX Modules          | Audit compiled-in modules and rebuild or configure to disable unused ones      | `enhancement`, `nginx`, `security` | No | Yes     |
| 4.9 (#2023) | fail2ban: Jail for 401/403 Responses       | Detect repeated 401/403 in access log and ban offending IPs via iptables       | `enhancement`, `nginx`, `security` | No | No      |
| 4.10 (#2024) | fail2ban: Jail for Excessive 404s          | Detect scanner behaviour (many 404s) and apply progressive bans                | `enhancement`, `nginx`, `security` | No | Yes     |
| 4.11 (#2025) | fail2ban: Jail for Rate-Limited Requests   | Ban IPs that continuously trigger NGINX rate limiting (429 in access log)      | `enhancement`, `nginx`, `security` | No | Yes     |
| 4.12 (#2026) | fail2ban: Ban Duration Escalation          | Configure recidivism tracking so repeat offenders receive exponentially longer bans | `enhancement`, `nginx`, `security` | No | No |
| 4.13 (#2027) | fail2ban: Whitelist Trusted IPs            | Whitelist monitoring servers, CI/CD runners, and internal ranges in fail2ban   | `enhancement`, `nginx`, `security` | No | Yes     |

### Detailed Issue Descriptions

#### 4.9 (#2023) — fail2ban: Jail for 401/403 Responses

Create a custom fail2ban jail that monitors the NGINX access log for repeated 401 and 403 responses from the same IP address. Trigger a ban after 10 failures within a 60-second window; initial ban duration is 10 minutes. Store jail configuration in `/etc/fail2ban/jail.d/nginx-auth.conf`.

```
[nginx-auth]
enabled  = true
port     = http,https
filter   = nginx-auth
logpath  = /var/log/nginx/access.log
maxretry = 10
findtime = 60
bantime  = 600
```

**Acceptance Criteria:**
- fail2ban correctly identifies and bans IPs after 10 auth failures within 60 seconds
- Ban is applied at the iptables level (verified with `iptables -L`)
- Ban is logged to `/var/log/fail2ban.log`
- filter regex tested against sample access log lines (no false positives)

**Depends on:** 3.5 (access log must exist with parseable format)

Part of Epic: Performance, Infrastructure Security & fail2ban

---

#### 4.12 (#2026) — fail2ban: Ban Duration Escalation

Implement recidivism logic so that an IP banned multiple times within a rolling window receives exponentially longer bans. First ban: 10 minutes. Second ban within 24 hours: 1 hour. Third ban: 24 hours. Fourth+: permanent until manual review.

```
[nginx-auth-repeat]
enabled  = true
filter   = nginx-auth
logpath  = /var/log/nginx/access.log
maxretry = 3
findtime = 86400
bantime  = 86400
```

**Acceptance Criteria:**
- Second offense within 24 hours bans for ≥ 1 hour
- Permanent-ban list is stored in a file reviewable by admins
- Admin runbook documents manual unban procedure
- Whitelist IPs (4.13) are excluded before escalation logic runs

**Depends on:** 4.9, 4.10, 4.11 (base jails must exist)

Part of Epic: Performance, Infrastructure Security & fail2ban
