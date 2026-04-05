# Objectified: Shield - Feature Roadmap

> Advanced security and threat protection platform for APIs and data schemas, providing runtime protection, vulnerability management, threat intelligence, and compliance automation. Shield safeguards the entire API lifecycle—from schema design through production traffic—ensuring APIs are secure by design and protected at runtime.
>
> **Revenue Model**: Per-API protection pricing (free tier: 1 API), enterprise security bundles with SLA guarantees
>
> **Tech Stack**: NextJS App Router, Radix UI, PostgreSQL, Redis (rate limiting, session store), ClickHouse (security event analytics), ML pipeline for anomaly detection, OpenAPI 3.1

---

## MVP Definition

- OWASP API Top 10 vulnerability scanning for Objectified schemas
- Injection vulnerability detection (SQL, NoSQL, XSS, command injection patterns)
- Sensitive data exposure analysis with PII field detection
- API firewall with schema-aware request validation and blocking
- Rate limiting per API key, endpoint, and IP address
- Real-time security event dashboard with severity indicators
- Secret rotation tracking with expiry alerts
- REST API for all security operations (OpenAPI 3.1 documented)

---

## Epic 1: Vulnerability Scanner

### Summary Table

| #   | Title                                 | Description                                                                   | Labels                                    | Parallel |
|-----|---------------------------------------|-------------------------------------------------------------------------------|-------------------------------------------|----------|
| 1.1 (#1247) | OWASP API Top 10 Scan Engine          | Automated scanning for OWASP API Security Top 10 vulnerabilities              | `enhancement`, `mvp`, `shield`, `rest`    | Yes      |
| 1.2 (#1248) | Injection Vulnerability Detection     | Detect SQL, NoSQL, XSS, and command injection patterns in schema definitions  | `enhancement`, `mvp`, `shield`, `rest`    | Yes      |
| 1.3 (#1249) | Sensitive Data Exposure Analysis      | Identify PII and sensitive fields that may be inadvertently exposed           | `enhancement`, `mvp`, `shield`, `rest`    | Yes      |
| 1.4 (#1250) | Authentication & Authorization Gaps   | Detect missing or weak auth configurations across API endpoints               | `enhancement`, `shield`, `rest`           | Yes      |
| 1.5 (#1251) | Scan Scheduling & Report Generation   | Automated scan scheduling with comprehensive vulnerability reports            | `enhancement`, `shield`, `rest`           | No       |

### Detailed Issue Descriptions

#### 1.1 (#1247) — OWASP API Top 10 Scan Engine

The OWASP API Security Top 10 scan engine analyzes Objectified schemas and API definitions against the OWASP API Security Top 10 vulnerability categories. For each category, the engine applies a set of detection rules that examine schema structure, endpoint definitions, authentication configuration, and data flow patterns. The categories covered are: Broken Object Level Authorization (BOLA), Broken Authentication, Broken Object Property Level Authorization, Unrestricted Resource Consumption, Broken Function Level Authorization, Unrestricted Access to Sensitive Business Flows, Server-Side Request Forgery, Security Misconfiguration, Improper Inventory Management, and Unsafe Consumption of APIs.

Each detection rule produces findings with: vulnerability category (OWASP reference), severity (critical, high, medium, low, info), affected resource (schema, endpoint, field), detailed description of the vulnerability, evidence (what triggered the finding), remediation guidance (step-by-step fix), and references (OWASP documentation links). Findings are deduplicated across scans—a previously detected vulnerability maintains a stable finding ID for tracking.

The scan engine is extensible: custom detection rules can be defined using a rule DSL that specifies conditions (field patterns, endpoint patterns, configuration checks) and finding templates. This enables organizations to add industry-specific or organization-specific security checks beyond the OWASP baseline.

```
OWASP API Top 10 Scan Results
Schema: Payment API v2.3.0

┌─────┬──────────────────────────┬──────────┬──────────────────────┐
│  #  │ Vulnerability            │ Severity │ Affected Resource    │
├─────┼──────────────────────────┼──────────┼──────────────────────┤
│  1  │ BOLA: Missing object-    │ CRITICAL │ GET /orders/{id}     │
│     │ level auth check         │          │                      │
├─────┼──────────────────────────┼──────────┼──────────────────────┤
│  2  │ Unrestricted Resource:   │ HIGH     │ GET /transactions    │
│     │ No pagination limit      │          │                      │
├─────┼──────────────────────────┼──────────┼──────────────────────┤
│  3  │ Security Misconfig:      │ HIGH     │ All endpoints        │
│     │ Missing rate limiting    │          │                      │
├─────┼──────────────────────────┼──────────┼──────────────────────┤
│  4  │ Sensitive Data: PII      │ MEDIUM   │ /users response      │
│     │ in response (SSN field)  │          │ body                 │
├─────┼──────────────────────────┼──────────┼──────────────────────┤
│  5  │ Improper Inventory:      │ LOW      │ /debug/* endpoints   │
│     │ Debug endpoints exposed  │          │                      │
└─────┴──────────────────────────┴──────────┴──────────────────────┘

Summary: 1 Critical · 2 High · 1 Medium · 1 Low
```

**Acceptance Criteria:**
- Scan endpoint: `POST /api/v1/shield/scans` accepts schema_id, returns scan_id for async processing
- Detection rules covering all 10 OWASP API Security categories with at least 3 rules per category
- Finding format: owasp_category, severity, resource, description, evidence, remediation, references
- Finding deduplication: stable finding_id across scans for tracking resolution progress
- Custom rule support via rule DSL for organization-specific security checks
- Scan results API: `GET /api/v1/shield/scans/{scanId}/findings` with pagination and severity filter

**Tech Stack:** Rule engine for vulnerability detection, NextJS API routes, PostgreSQL for findings storage, OpenAPI 3.1 for scan API

Part of Epic: Vulnerability Scanner

---

#### 1.2 (#1248) — Injection Vulnerability Detection

Injection vulnerabilities in API schemas manifest as fields that accept user input without adequate validation constraints, creating vectors for SQL injection, NoSQL injection, XSS, and command injection attacks. The detector analyzes each string field in a schema for: missing or weak input validation (no pattern, maxLength, or format constraints), patterns that could carry injection payloads (unconstrained string fields used in query parameters, path parameters, or request bodies), and fields whose names suggest database query involvement (e.g., `filter`, `query`, `search`, `sort`, `order_by`).

The analysis goes beyond simple pattern matching by understanding context: a `name` field with maxLength 100 and an alphanumeric pattern is low risk, while a `filter` field with no constraints that is documented as accepting "flexible query syntax" is high risk. The detector generates injection test payloads tailored to each field's context and suggests appropriate validation constraints.

Each finding includes a severity rating based on the exploitability and impact: a path parameter vulnerable to injection is critical (server-side execution context), while a response body field is lower risk (client-side only). Remediation recommendations include specific JSON Schema constraints to add (pattern, maxLength, enum) and code-level validation suggestions.

**Acceptance Criteria:**
- Detect string fields without validation constraints (no pattern, maxLength, or enum) in request schemas
- Risk scoring based on field context: path parameter > query parameter > request body > response body
- Injection categories detected: SQL injection, NoSQL injection, XSS, command injection, LDAP injection
- High-risk field name detection: fields named filter, query, search, sort, order_by, sql, command, exec
- Remediation recommendations: specific JSON Schema constraints (pattern, maxLength) and sanitization advice
- Injection test payload generation: produce sample payloads for manual testing of each finding

**Tech Stack:** Schema analysis engine, injection pattern database, NextJS API routes, PostgreSQL for findings

Part of Epic: Vulnerability Scanner

---

#### 1.3 (#1249) — Sensitive Data Exposure Analysis

Sensitive data exposure occurs when API responses include fields containing PII (Personally Identifiable Information), financial data, authentication credentials, or other sensitive information without adequate protection. The analyzer scans all response schemas (and request schemas for unnecessary data collection) to identify sensitive fields using multiple signals: field name patterns (ssn, social_security, password, credit_card, cvv, date_of_birth), JSON Schema format hints (email, phone), and AI-assisted semantic analysis of field descriptions.

Detected sensitive fields are classified by sensitivity level: critical (passwords, tokens, credit card numbers, SSN), high (email, phone, date of birth, government IDs), medium (name, address, IP address), and low (preferences, timestamps). Each finding recommends protective measures: remove from response (critical), mask/redact (high), minimize/encrypt (medium), or document handling policy (low).

The analyzer also checks for mass assignment vulnerabilities: request schemas that accept more fields than necessary, potentially allowing attackers to set sensitive fields (e.g., `is_admin`, `role`, `balance`) that should be server-controlled. Response over-exposure is flagged when an endpoint returns fields that no consumer contract requires (connecting with Test Lab's contract data when available).

**Acceptance Criteria:**
- Sensitive field detection using name patterns, format hints, and AI-powered description analysis
- Sensitivity classification: critical, high, medium, low with category-specific protective measures
- Mass assignment detection: identify request schema fields that should be server-controlled (is_admin, role, balance)
- Response over-exposure: flag response fields not referenced by any consumer contract (when contract data available)
- Finding format: field_path, sensitivity_level, detection_method, recommended_protection, compliance_relevance
- Analysis API: `POST /api/v1/shield/analyze/sensitive-data` accepts schema_id, returns categorized findings

**Tech Stack:** Pattern matching engine, Ollama for semantic field analysis, NextJS API routes, PostgreSQL for findings, cross-reference with Test Lab contract data

Part of Epic: Vulnerability Scanner

---

#### 1.4 (#1250) — Authentication & Authorization Gaps

This detector identifies API endpoints that lack proper authentication or have weak authorization configurations. It analyzes the OpenAPI security definitions, endpoint-level security overrides, and common anti-patterns to find gaps. Checks include: endpoints without any security scheme defined, endpoints using only API key authentication without additional authorization, endpoints that expose administrative functionality without role-based access control, and inconsistent auth patterns (most endpoints require auth but some don't).

The detector evaluates authentication strength: API key only (medium risk), OAuth2 without PKCE (medium risk for SPAs), basic auth over non-HTTPS (critical risk), and no authentication (critical risk for non-public endpoints). Authorization analysis checks for: missing object-level authorization (users can access other users' resources), missing function-level authorization (regular users can access admin endpoints), and overly permissive CORS configurations.

A "Security Posture" summary provides an aggregate view: percentage of endpoints with strong auth, percentage with weak auth, and percentage with no auth. The posture score feeds into the overall Shield security score. Remediation includes specific OpenAPI security scheme configurations to add and middleware patterns to implement.

**Acceptance Criteria:**
- Detect endpoints without security scheme definitions in OpenAPI specs
- Authentication strength scoring: none (critical), basic (high), api_key_only (medium), oauth2 (low), oauth2+roles (secure)
- BOLA detection: identify CRUD endpoints on user-owned resources without object-level auth documentation
- Function-level auth: flag admin/management endpoints accessible without elevated roles
- CORS analysis: flag overly permissive CORS (allow-origin: *) on authenticated endpoints
- Security posture summary: percentage of endpoints by auth strength, aggregate posture score

**Tech Stack:** OpenAPI parser, schema analysis, NextJS API routes, PostgreSQL for findings, Radix UI for security posture visualization

Part of Epic: Vulnerability Scanner

---

#### 1.5 (#1251) — Scan Scheduling & Report Generation

Security scanning should run automatically and continuously, not just when manually triggered. The scheduling module enables configuring recurring scans on different cadences: continuous (scan on every schema publish), daily (full scan of all schemas at a configured time), weekly (comprehensive scan with trend analysis), and on-demand (manual trigger from UI or API). Different scan profiles can run on different schedules—a quick OWASP check runs continuously, while a deep analysis runs weekly.

The report generator produces comprehensive security reports from scan results. Reports include: executive summary (overall security posture, change since last report, critical findings count), detailed findings (organized by severity, with full descriptions and remediation), trend analysis (are we improving?), compliance mapping (which findings affect which compliance frameworks), and remediation tracking (which previously found issues have been fixed).

Reports support multiple audiences: a one-page executive summary for leadership, a detailed technical report for engineering teams, and a compliance-formatted report for auditors. All reports are timestamped and stored for audit purposes. Distribution integrates with email and Slack for automated delivery.

**Acceptance Criteria:**
- Scan schedule CRUD: `POST /api/v1/shield/scans/schedules` with profile, cadence (continuous/daily/weekly), and target schemas
- Continuous scanning: webhook triggers scan on schema publish events automatically
- Report generation: `POST /api/v1/shield/reports` with date range, format (pdf/html), and audience (executive/technical/compliance)
- Report content: executive summary, detailed findings, trend analysis, compliance mapping, remediation tracking
- Trend tracking: finding count by severity over time, mean-time-to-remediate, new vs resolved findings
- Automated distribution: email and Slack delivery on report generation with configurable recipients

**Tech Stack:** Cron scheduler for recurring scans, Puppeteer for PDF rendering, NextJS API routes, PostgreSQL for schedule and report storage, notification service

Part of Epic: Vulnerability Scanner

---

## Epic 2: Runtime Protection Engine

### Summary Table

| #   | Title                                 | Description                                                                   | Labels                                    | Parallel |
|-----|---------------------------------------|-------------------------------------------------------------------------------|-------------------------------------------|----------|
| 2.1 (#1253) | API Firewall with Schema-Aware Rules  | Inline request/response validation against schemas with blocking capabilities | `enhancement`, `mvp`, `shield`, `rest`    | Yes      |
| 2.2 (#1254) | Rate Limiting Engine                  | Configurable rate limiting per API key, endpoint, IP, and tenant               | `enhancement`, `mvp`, `shield`, `rest`    | Yes      |
| 2.3 (#1255) | Bot Detection & Mitigation            | Identify and block automated bot traffic using behavioral analysis            | `enhancement`, `shield`, `rest`           | Yes      |
| 2.4 (#1256) | DDoS Protection for API Endpoints     | Distributed denial-of-service detection and mitigation for API traffic        | `enhancement`, `shield`, `rest`           | No       |
| 2.5 (#1257) | Runtime Security Event Dashboard      | Real-time dashboard showing blocked requests, threats, and security events    | `enhancement`, `mvp`, `shield`            | Yes      |

### Detailed Issue Descriptions

#### 2.1 (#1253) — API Firewall with Schema-Aware Rules

The API firewall sits in the request path and validates all incoming requests against the Objectified schema definitions before they reach the application logic. Unlike generic WAFs that use signature-based detection, Shield's firewall understands the API's data model: it validates request bodies against the exact JSON Schema, ensures query parameters match defined types and constraints, validates path parameters against patterns, and checks Content-Type headers. Requests that fail validation are blocked with a 400 response and detailed error messages.

The firewall operates in three modes: monitor (log violations but allow traffic), block (reject violating requests), and strict (block and additionally reject requests with unexpected extra fields not defined in the schema). Mode is configurable per endpoint, enabling gradual rollout—start in monitor mode to baseline the violation rate, then switch to block mode. A bypass allowlist supports specific IP addresses or API keys for debugging.

Custom firewall rules extend beyond schema validation: block requests with specific header values, require specific headers (e.g., `X-Request-ID`), enforce HTTPS, validate JWT token claims, and implement request size limits. Rules are evaluated in priority order and can match on method, path pattern, headers, and body content. The firewall logs all decisions (allow/block) as security events for the analytics pipeline.

```
┌──────────────────────────────────────────────────────────┐
│                    Request Flow                           │
│                                                          │
│  Client Request                                          │
│       │                                                  │
│       ▼                                                  │
│  ┌─────────────────┐                                     │
│  │  Rate Limiter    │── 429 ──▶ Blocked                  │
│  └────────┬────────┘                                     │
│           ▼                                              │
│  ┌─────────────────┐                                     │
│  │  Bot Detector    │── 403 ──▶ Blocked                  │
│  └────────┬────────┘                                     │
│           ▼                                              │
│  ┌─────────────────┐                                     │
│  │  Schema Firewall │── 400 ──▶ Blocked                  │
│  │  (validate req   │                                    │
│  │   against schema) │                                   │
│  └────────┬────────┘                                     │
│           ▼                                              │
│  ┌─────────────────┐                                     │
│  │  Custom Rules    │── 403 ──▶ Blocked                  │
│  └────────┬────────┘                                     │
│           ▼                                              │
│  ┌─────────────────┐                                     │
│  │  Application     │                                    │
│  │  Logic           │──▶ Response                        │
│  └─────────────────┘                                     │
└──────────────────────────────────────────────────────────┘
```

**Acceptance Criteria:**
- Request body validation against Objectified JSON Schema with detailed error response on violation
- Query parameter and path parameter type validation against schema definitions
- Three operating modes: monitor (log only), block (reject violations), strict (reject unexpected fields)
- Mode configurable per endpoint via `PUT /api/v1/shield/firewall/endpoints/{id}/mode`
- Custom rule engine: match on method, path pattern, headers, body; actions: allow, block, log
- Bypass allowlist for IP addresses and API keys configurable via admin API

**Tech Stack:** Request interceptor middleware, JSON Schema validation (fast: ajv), Redis for rule caching, NextJS API routes for configuration, security event logging

Part of Epic: Runtime Protection Engine

---

#### 2.2 (#1254) — Rate Limiting Engine

The rate limiting engine protects APIs from abuse by enforcing configurable request limits across multiple dimensions. Limits are defined as rules: each rule specifies a dimension (API key, IP address, endpoint, tenant, or combination), a window (sliding or fixed), a limit (requests per window), and an action on breach (reject with 429, throttle/delay, or escalate to block). Multiple rules can apply simultaneously—a request must satisfy all applicable rules.

The engine uses Redis for distributed rate limit state, supporting deployment across multiple application instances. The sliding window algorithm provides smooth rate limiting without the burst-at-boundary problem of fixed windows. Each rate limit response includes standard headers: `X-RateLimit-Limit` (the limit), `X-RateLimit-Remaining` (requests remaining), `X-RateLimit-Reset` (when the window resets, Unix timestamp), and `Retry-After` (seconds until requests are allowed, on 429 responses).

Rate limit configuration supports inheritance: tenant-level defaults apply to all endpoints unless overridden by endpoint-specific rules. Burst allowance permits temporary spikes: a 100 req/min limit with burst=20 allows 120 requests in a burst before enforcement. Rate limit analytics show: top rate-limited consumers, rate limit hit rate by endpoint, and temporal patterns (when do rate limits trigger most).

**Acceptance Criteria:**
- Rate limit rules: configurable dimension (api_key, ip, endpoint, tenant), window (sliding/fixed), limit, action (reject/throttle/block)
- Distributed state via Redis: consistent rate limiting across multiple application instances
- Standard response headers: X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset, Retry-After
- Rule inheritance: tenant defaults overridable by endpoint-specific rules
- Burst allowance: configurable burst buffer above base limit for temporary spikes
- Rate limit management API: CRUD at `/api/v1/shield/rate-limits` with per-endpoint and per-consumer configuration

**Tech Stack:** Redis for distributed counters (sliding window log algorithm), NextJS middleware, rate limit header injection, Radix UI for configuration UI

Part of Epic: Runtime Protection Engine

---

#### 2.3 (#1255) — Bot Detection & Mitigation

Bot detection distinguishes legitimate automated API clients (partner integrations, monitoring tools) from malicious bots (scrapers, credential stuffers, vulnerability scanners). The detection engine uses a layered approach: fingerprinting (TLS fingerprint, HTTP/2 settings, header order patterns), behavioral analysis (request timing regularity, navigation patterns, session behavior), and reputation scoring (IP reputation databases, known bot user agents, ASN reputation).

Legitimate automation is whitelisted via API key association: when an API consumer registers as an integration, their traffic is marked as "known automation" and exempted from bot detection. Unknown automation is scored on a 0-100 bot probability scale. Requests scoring above a configurable threshold (default: 80) are blocked with a 403 response. Requests scoring between the warning threshold (default: 50) and the block threshold are flagged for review.

The bot detection dashboard shows: percentage of traffic classified as human/known-bot/suspicious-bot, top bot signatures detected (user agents, IP ranges, behavioral patterns), bot traffic trends over time, and the impact of bot mitigation (percentage of malicious traffic blocked). A review queue shows flagged requests for security analysts to investigate and mark as legitimate or confirm as malicious, improving the detection model over time.

**Acceptance Criteria:**
- Detection layers: TLS/HTTP fingerprinting, behavioral analysis (timing, patterns), IP/ASN reputation scoring
- Bot probability score (0-100) per request with configurable block threshold (default 80) and warning threshold (default 50)
- Known automation allowlist: API keys marked as integrations exempted from bot detection
- 403 response for blocked bots with configurable response body (honeypot redirection or standard error)
- Review queue for flagged requests (score between warning and block threshold) with analyst feedback loop
- Bot analytics API: `GET /api/v1/shield/bots/analytics` returns traffic classification, top signatures, and trends

**Tech Stack:** TLS fingerprinting library, behavioral analysis engine, IP reputation database (free: AbuseIPDB), Redis for session state, NextJS API routes

Part of Epic: Runtime Protection Engine

---

#### 2.4 (#1256) — DDoS Protection for API Endpoints

DDoS protection detects and mitigates distributed denial-of-service attacks targeting API endpoints. The system monitors traffic patterns in real-time, establishing baselines for normal traffic volume per endpoint and detecting anomalies that suggest coordinated attack traffic. Detection signals include: sudden traffic spikes exceeding baseline by configurable multiplier (default: 5x), traffic from many unique IPs hitting the same endpoint simultaneously, geographic distribution anomalies (traffic from countries that normally generate zero traffic), and request pattern uniformity (identical payloads from many sources).

When an attack is detected, the system escalates through mitigation levels: Level 1 (activate aggressive rate limiting for the targeted endpoint), Level 2 (enable CAPTCHA/challenge for suspected attack IPs), Level 3 (geo-block traffic from anomalous regions), Level 4 (activate emergency endpoint disable with cached response). Each level is configurable, and escalation happens automatically based on attack severity or manually by security operators.

The DDoS protection dashboard shows: current threat level per endpoint (normal/elevated/under-attack), attack timeline (when attacks started, peaked, and were mitigated), traffic volume comparison (normal vs attack), and mitigation effectiveness (percentage of attack traffic blocked while allowing legitimate traffic). Post-attack reports are generated automatically for incident review.

**Acceptance Criteria:**
- Baseline traffic monitoring: establish per-endpoint normal traffic volume (7-day rolling average)
- Attack detection: configurable spike multiplier (default 5x baseline), geographic anomaly, pattern uniformity
- Escalation levels: rate limiting → challenge → geo-block → endpoint disable, with auto-escalation
- Dashboard: per-endpoint threat level, attack timeline, traffic comparison, mitigation effectiveness
- Attack alert notifications via email, Slack, and PagerDuty (if configured) on detection
- Post-attack report: auto-generated with attack duration, volume, source distribution, and mitigation timeline

**Tech Stack:** Real-time traffic analysis on ClickHouse streaming data, Redis for attack state, NextJS page for dashboard, notification service, geographic IP database

Part of Epic: Runtime Protection Engine

---

#### 2.5 (#1257) — Runtime Security Event Dashboard

The security event dashboard provides real-time visibility into all Shield protection activities: firewall blocks, rate limit triggers, bot detections, DDoS mitigations, and authentication failures. The dashboard is designed for security operations center (SOC) usage with auto-refreshing displays, severity-based color coding, and quick-action capabilities.

The layout includes: a threat summary bar (total events in last hour by severity), a real-time event stream (scrolling log of security events with timestamp, type, source IP, endpoint, and action taken), a geographic heat map (attack source locations on a world map), and a top offenders table (IPs/API keys with the most security events). Each section auto-refreshes every 10 seconds.

Event drill-down shows the full context of a security event: the raw request (sanitized for display), the rule that triggered, the action taken, related events from the same source (session/IP history), and quick actions (block IP permanently, add to allowlist, create an investigation). An investigation workflow allows security analysts to group related events, add notes, and track resolution.

**Acceptance Criteria:**
- Threat summary bar: event counts by severity (critical/high/medium/low) for last hour with trend arrows
- Real-time event stream: scrolling display of security events with type, source, endpoint, action, timestamp
- Geographic heat map: attack source visualization on world map with country-level aggregation
- Top offenders table: top 20 IPs/API keys by security event count with quick-block action
- Auto-refresh every 10 seconds with visual refresh indicator; pause button for investigation
- Event drill-down: full request context, triggering rule, related events, quick actions (block/allow/investigate)

**Tech Stack:** NextJS page (`app/(platform)/shield/dashboard/page.tsx`), server-sent events for real-time stream, Recharts for geographic map, Radix UI Table for offenders, ClickHouse for event queries

Part of Epic: Runtime Protection Engine

---

## Epic 3: Threat Intelligence & Anomaly Detection

### Summary Table

| #   | Title                                 | Description                                                                   | Labels                                      | Parallel |
|-----|---------------------------------------|-------------------------------------------------------------------------------|---------------------------------------------|----------|
| 3.1 (#1259) | ML-Based Anomaly Detection Engine     | Machine learning model for detecting unusual API usage patterns               | `enhancement`, `shield`, `ai-generated`     | Yes      |
| 3.2 (#1260) | Threat Feed Integration               | Ingest and correlate with external threat intelligence feeds                  | `enhancement`, `shield`, `rest`             | Yes      |
| 3.3 (#1261) | Attack Pattern Recognition            | Detect known attack sequences and automated scanning tools                   | `enhancement`, `shield`, `rest`             | Yes      |
| 3.4 (#1262) | Real-Time Alerting & Escalation       | Configurable alerting rules with severity-based escalation chains            | `enhancement`, `shield`, `rest`             | No       |
| 3.5 (#1263) | Threat Investigation Workbench        | Investigation tools for security analysts to explore and correlate threats    | `enhancement`, `shield`                     | No       |

### Detailed Issue Descriptions

#### 3.1 (#1259) — ML-Based Anomaly Detection Engine

The anomaly detection engine uses machine learning to identify unusual API usage patterns that may indicate security threats, data exfiltration, privilege escalation, or account compromise. Unlike rule-based detection (which catches known patterns), ML-based detection identifies novel threats by learning "normal" behavior and flagging deviations.

The model is trained on each tenant's historical API usage data, building per-consumer behavioral profiles. Features include: request volume patterns (time-of-day, day-of-week distributions), endpoint usage patterns (which endpoints are accessed and in what order), payload characteristics (request body sizes, field distributions), geographic patterns (usual login locations), and session patterns (session duration, actions per session). An isolation forest algorithm detects data points that deviate significantly from the learned profile.

Anomalies are scored by severity and categorized: volume anomaly (unusual request rate), behavioral anomaly (unusual endpoint access sequence), geographic anomaly (access from new country), temporal anomaly (access at unusual time), and data anomaly (unusual payload size or content patterns). Each anomaly generates an alert with context: what was expected, what was observed, and how far it deviates from normal. Low-confidence anomalies are logged but not alerted to avoid alert fatigue.

**Acceptance Criteria:**
- Per-consumer behavioral profile built from 30-day historical data with weekly model refresh
- Anomaly categories: volume, behavioral, geographic, temporal, data with per-category sensitivity tuning
- Anomaly scoring: severity (critical/high/medium/low) based on deviation magnitude and anomaly category
- Alert suppression: configurable minimum confidence threshold (default 0.8) to reduce false positives
- Training pipeline: automated data extraction, feature engineering, model training, and deployment
- Anomaly API: `GET /api/v1/shield/anomalies?consumerId=&from=&to=` with severity and category filters

**Tech Stack:** Python ML pipeline (scikit-learn isolation forest), feature engineering from ClickHouse, model serving via REST endpoint, NextJS page for anomaly dashboard

Part of Epic: Threat Intelligence & Anomaly Detection

---

#### 3.2 (#1260) — Threat Feed Integration

Threat intelligence feeds provide curated data about known malicious IPs, domains, attack tools, and vulnerabilities. Shield integrates with external threat feeds to enrich security events with threat context: "This IP is listed in the AbuseIPDB with 95% confidence as a web attack source." Feed data is ingested on a configurable schedule, normalized into a standard format, and stored in a local threat database for fast lookup.

Supported feed types include: IP reputation feeds (AbuseIPDB, GreyNoise, AlienVault OTX), domain/URL reputation feeds, known vulnerability databases (CVE, NVD), attack tool signatures (Nuclei templates, known scanner fingerprints), and custom organizational feeds (internal blacklists, partner-shared threat data). Each feed source is configurable with: endpoint URL, authentication, polling interval, and trustworthiness weight (how much weight to give this feed's assessments).

Correlation enriches every security event with matching threat intelligence: when a request arrives from an IP that appears in threat feeds, the security event includes the feed data (reputation score, threat categories, last seen date, reported country). This enables smarter decision-making in the firewall and rate limiter—a request from a known malicious IP gets stricter treatment than one from a clean IP.

**Acceptance Criteria:**
- Feed connector framework: configurable URL, auth, polling interval, and normalization mapping per feed
- Built-in integrations: AbuseIPDB, GreyNoise Community, AlienVault OTX (free tier)
- Custom feed support: import CSV/JSON files or configure custom REST API endpoints
- Local threat database: fast lookup (sub-millisecond) for IP, domain, and hash queries
- Event enrichment: security events annotated with matching threat intelligence automatically
- Feed management API: CRUD at `/api/v1/shield/threat-feeds` with health status and last sync time per feed

**Tech Stack:** Feed poller background workers, Redis for fast lookup cache, PostgreSQL for feed metadata, NextJS API routes for management

Part of Epic: Threat Intelligence & Anomaly Detection

---

#### 3.3 (#1261) — Attack Pattern Recognition

Attack pattern recognition identifies coordinated attack sequences and known scanning tool signatures in API traffic. Rather than detecting individual suspicious requests (handled by the firewall and anomaly detection), this module identifies multi-request patterns: credential stuffing (many login attempts with different credentials from the same IP or botnet), API enumeration (sequential probing of endpoints or IDs), vulnerability scanning (requests matching known scanner tool fingerprints like Nuclei, Burp Suite, OWASP ZAP), and data exfiltration (systematic downloading of all records via pagination).

Pattern detection uses sliding window analysis: examining sequences of requests within configurable time windows (1 minute, 5 minutes, 1 hour) to identify suspicious sequences. Patterns are defined as templates: "more than N requests to endpoint X with different values for parameter Y within Z minutes" matches credential stuffing. A library of pre-built patterns covers common attack types.

When a pattern is detected, the system creates a "threat event" linking all contributing requests. The threat event includes: pattern type, confidence score, contributing request IDs, source information (IP, API key, user agent), and recommended response. Automatic response actions can be configured per pattern: escalate rate limiting, block source IP temporarily, require additional authentication, or alert security team.

**Acceptance Criteria:**
- Pattern library: pre-built patterns for credential stuffing, API enumeration, vulnerability scanning, data exfiltration
- Sliding window analysis: configurable windows (1min, 5min, 1hr) for detecting multi-request attack sequences
- Scanner fingerprinting: detect Nuclei, Burp Suite, OWASP ZAP, sqlmap, and other common scanning tools
- Threat event creation: group contributing requests, assign pattern type, confidence, and recommended response
- Auto-response: configurable per-pattern actions (escalate rate limit, temp-block, require auth, alert)
- Pattern management API: CRUD for custom patterns at `/api/v1/shield/patterns` with pattern template DSL

**Tech Stack:** Stream processing for sliding window analysis, pattern matching engine, scanner fingerprint database, NextJS API routes, PostgreSQL for pattern and threat event storage

Part of Epic: Threat Intelligence & Anomaly Detection

---

#### 3.4 (#1262) — Real-Time Alerting & Escalation

The alerting system ensures security events reach the right people at the right time through configurable alert rules and escalation chains. Alert rules define: trigger conditions (event type, severity threshold, count threshold within time window), notification channels (email, Slack, PagerDuty, webhook), recipients (individual users, teams, on-call schedules), and deduplication settings (suppress duplicate alerts within configurable window).

Escalation chains handle situations where initial alerts are not acknowledged. A chain specifies: initial notification (email to security team), first escalation after N minutes without acknowledgment (Slack channel + PagerDuty), second escalation after M minutes (page security manager + VP Engineering). Each step in the chain has an acknowledgment requirement—acknowledging an alert stops the escalation.

Alert fatigue management is critical: the system implements intelligent grouping (related alerts within a time window are grouped into a single notification), suppression (alerts that fire more than N times per hour are auto-suppressed with a summary notification), and severity escalation (if a low-severity alert fires repeatedly, it auto-promotes to medium severity). Alert metrics track: alert volume, acknowledgment time, false positive rate, and alert-to-incident conversion rate.

**Acceptance Criteria:**
- Alert rule CRUD: `POST /api/v1/shield/alerts/rules` with trigger conditions, channels, recipients, deduplication
- Notification channels: email, Slack, PagerDuty, webhook with per-channel configuration
- Escalation chains: multi-step escalation with configurable timeout and acknowledgment requirements
- Alert acknowledgment API: `POST /api/v1/shield/alerts/{id}/acknowledge` stops escalation
- Intelligent grouping: related alerts within 5-minute window grouped into single notification
- Suppression: auto-suppress alerts exceeding configurable frequency (default: >10/hour) with summary notification

**Tech Stack:** Background alert processor, Slack API, PagerDuty API, SMTP for email, NextJS API routes, PostgreSQL for alert rules and state, Redis for deduplication tracking

Part of Epic: Threat Intelligence & Anomaly Detection

---

#### 3.5 (#1263) — Threat Investigation Workbench

The investigation workbench provides security analysts with tools to explore, correlate, and understand security threats. The workbench centers on a timeline view showing all security events for a selected scope (IP address, API key, consumer, endpoint, or time range). Analysts can zoom in/out on the timeline, filter by event type and severity, and select events to view full details.

A correlation graph visualizes relationships between security events: which IPs are associated with which API keys, which endpoints are targeted by the same source, and which attack patterns share infrastructure. The graph helps analysts understand the scope of an attack and identify all affected resources. Nodes are colored by severity, and edges show the relationship type (same IP, same API key, same session, same pattern).

The workbench supports saved investigations: analysts can create a named investigation, add relevant events and notes, assign a status (open, investigating, mitigated, closed), and share with team members. Investigations serve as the incident record for security events, linking to blocked IPs, updated firewall rules, and resolution actions. Investigation summaries can be exported as PDF reports for compliance documentation.

**Acceptance Criteria:**
- Timeline view: security events on a zoomable timeline with filters for event type, severity, and source
- Correlation graph: visualize relationships between IPs, API keys, endpoints, and attack patterns
- Event detail panel: full request context, threat intelligence enrichment, related events, and analyst notes
- Saved investigations: create, assign status, add events/notes, share with team, track resolution
- Investigation export: PDF report with timeline, events, analyst notes, and resolution actions
- Investigation API: CRUD at `/api/v1/shield/investigations` with event attachment and status management

**Tech Stack:** NextJS page (`app/(platform)/shield/investigations/page.tsx`), D3.js for correlation graph, timeline component, Radix UI Dialog for investigation creation, PDF generation

Part of Epic: Threat Intelligence & Anomaly Detection

---

## Epic 4: Secrets & Compliance Management

### Summary Table

| #   | Title                                 | Description                                                                   | Labels                                    | Parallel |
|-----|---------------------------------------|-------------------------------------------------------------------------------|-------------------------------------------|----------|
| 4.1 (#1265) | API Key Vault & Management            | Secure storage and lifecycle management for API keys and credentials          | `enhancement`, `mvp`, `shield`, `rest`    | Yes      |
| 4.2 (#1266) | Secret Rotation Automation            | Automated key rotation with zero-downtime deployment and consumer notification | `enhancement`, `shield`, `rest`          | No       |
| 4.3 (#1267) | Credential Leak Detection             | Monitor external sources for leaked API keys and credentials                  | `enhancement`, `shield`, `rest`           | Yes      |
| 4.4 (#1268) | Compliance Monitoring & Audit Trails  | Continuous compliance monitoring with evidence collection and audit reports   | `enhancement`, `shield`, `rest`           | Yes      |
| 4.5 (#1269) | Zero-Trust Access Policies            | Implement least-privilege access with just-in-time permissions and context-aware auth | `enhancement`, `shield`, `rest`    | No       |

### Detailed Issue Descriptions

#### 4.1 (#1265) — API Key Vault & Management

The API key vault provides secure, centralized management for all API keys, tokens, and credentials used within the Objectified platform. Keys are stored encrypted at rest (AES-256-GCM) with envelope encryption: each key is encrypted with a data encryption key (DEK), and each DEK is encrypted with a master key stored in a hardware security module (HSM) or cloud KMS. Key material is never logged, displayed in full (only last 4 characters shown), or included in API responses after creation.

The vault supports key lifecycle management: creation (generate or import), activation (enable for use), rotation (issue new key, deprecate old), revocation (immediately disable), and deletion (permanent removal after retention period). Each key has metadata: name, description, owner, creation date, expiry date, associated permissions (which APIs/endpoints the key can access), and usage constraints (IP allowlist, rate limits, time-of-day restrictions).

The management UI provides a key inventory view showing all keys with status indicators (active/expiring/expired/revoked), usage statistics (last used date, request count in last 30 days), and quick actions (rotate, revoke, edit permissions). A "Create Key" wizard guides administrators through setting permissions and constraints. Key usage is logged as security events for audit purposes.

**Acceptance Criteria:**
- Key storage with AES-256-GCM encryption at rest using envelope encryption with cloud KMS
- Key lifecycle API: create, activate, rotate, revoke, delete at `/api/v1/shield/keys`
- Key display policy: only last 4 characters shown after creation, full key returned only at creation time
- Key metadata: name, owner, expiry, permissions (endpoint access list), constraints (IP allowlist, rate limits)
- Key inventory UI with status indicators, usage stats, and quick actions (rotate/revoke/edit)
- Usage audit: all key operations logged as security events with actor, action, and timestamp

**Tech Stack:** AES-256-GCM encryption, cloud KMS integration (AWS KMS or similar), NextJS API routes, PostgreSQL for key metadata, Radix UI Table for inventory, Radix UI Dialog for create wizard

Part of Epic: Secrets & Compliance Management

---

#### 4.2 (#1266) — Secret Rotation Automation

Secret rotation replaces active API keys with new ones on a configurable schedule without service disruption. The rotation process follows a zero-downtime pattern: (1) Generate new key, (2) Activate new key alongside old key (grace period), (3) Notify consumers to switch to the new key, (4) After grace period, revoke old key. The grace period is configurable (default: 7 days) and allows consumers time to update their integrations.

Rotation triggers are configurable: scheduled (every N days, recommended: 90 days), on-demand (manual trigger), or event-driven (rotate immediately if a compromise is suspected). A rotation policy defines the schedule, grace period, notification settings, and auto-revocation behavior. Policies can be applied to individual keys or groups of keys.

Consumer notification includes: in-app notification, email to the key owner, webhook to a registered URL (enabling automated key update in consumer systems), and Slack/Teams message. The notification includes: the new key ID (but not the key material—consumers must retrieve the new key via the secure API), the grace period deadline, and instructions for updating their configuration. A rotation dashboard shows: keys approaching rotation, keys in grace period, keys past due for rotation, and rotation history.

**Acceptance Criteria:**
- Rotation policy configuration: schedule (N days), grace_period_days, auto_revoke, notification_channels
- Zero-downtime rotation: old and new keys both active during grace period
- Rotation triggers: scheduled (cron), manual (`POST /api/v1/shield/keys/{id}/rotate`), and event-driven (compromise flag)
- Consumer notifications: in-app, email, webhook, Slack with rotation deadline and instructions
- Rotation dashboard: keys approaching rotation, in grace period, past due, and rotation history timeline
- Automated revocation of old keys after grace period with configurable warning notifications at 50% and 75% of grace period

**Tech Stack:** Background scheduler for rotation, notification service integration, NextJS page for rotation dashboard, PostgreSQL for rotation state, webhook delivery

Part of Epic: Secrets & Compliance Management

---

#### 4.3 (#1267) — Credential Leak Detection

Credential leak detection monitors external sources for exposed API keys and credentials. When a key is detected in a public location (GitHub repository, Pastebin, public log files), the system immediately alerts the key owner and optionally triggers automatic rotation. Early detection minimizes the window of exposure.

Monitoring sources include: GitHub (commit scanning via GitHub's secret scanning partnership program or self-hosted scanning of public repos mentioning the organization), Pastebin and similar paste sites (via monitoring APIs), StackOverflow and forum posts (periodic scanning), and internal sources (application logs, error reports, debug output that might accidentally include keys). Scanning uses pattern matching against known key formats (prefix patterns, length, character set).

When a leak is detected, the system creates a "leak event" with: the key ID, source URL, detection timestamp, exposure scope (public/semi-public/internal), and recommended actions. Automatic response actions are configurable: notify only (default), auto-rotate (generate new key, notify consumers, revoke old key immediately), or auto-revoke (immediately disable the key without generating a replacement). A leak history view shows all detected leaks with resolution status and time-to-remediation metrics.

**Acceptance Criteria:**
- Monitoring for exposed keys via GitHub (commits and issues), paste sites, and internal log scanning
- Pattern matching for key formats with configurable key prefix patterns for custom key formats
- Leak event creation: key_id, source_url, detected_at, exposure_scope, severity, recommended_actions
- Auto-response configuration per key: notify_only, auto_rotate, auto_revoke (configurable per key or policy)
- Leak alert: immediate notification to key owner and security team via email, Slack, and PagerDuty
- Leak history: `GET /api/v1/shield/leaks` with resolution status, time-to-remediate, and source distribution

**Tech Stack:** GitHub secret scanning integration, external monitoring API clients, background scanner, NextJS API routes, notification service, PostgreSQL for leak events

Part of Epic: Secrets & Compliance Management

---

#### 4.4 (#1268) — Compliance Monitoring & Audit Trails

Compliance monitoring continuously evaluates the security posture against regulatory frameworks (SOC 2, HIPAA, GDPR, PCI-DSS, ISO 27001) and organizational security policies. For each framework, a set of controls maps to Shield's capabilities: "SOC 2 CC6.1: Logical Access Security" maps to authentication gap detection, rate limiting, and key management. The compliance dashboard shows: overall compliance percentage per framework, status per control (compliant, non-compliant, partially compliant), and remediation guidance for gaps.

The audit trail captures every security-relevant action in an immutable, append-only log: key creation/rotation/revocation, firewall rule changes, rate limit changes, alert acknowledgments, investigation actions, and user access to security features. Each audit entry includes: action, actor (user ID), timestamp, resource affected, previous value, new value, and source IP. The audit log cannot be modified or deleted by any user, including administrators.

Compliance evidence collection automates the process of gathering proof for audits. When an auditor requests evidence for a specific control (e.g., "Show me that API keys are rotated every 90 days"), the system generates an evidence package: the rotation policy configuration, rotation history for all keys, and any exceptions with documented approvals. Evidence packages are exported as signed PDF bundles with integrity checksums.

**Acceptance Criteria:**
- Compliance dashboard: per-framework compliance percentage with per-control status (SOC 2, HIPAA, GDPR, PCI-DSS)
- Control mapping: Shield capabilities mapped to compliance framework controls with gap identification
- Immutable audit log: append-only storage for all security actions with tamper detection (hash chain)
- Audit entry format: action, actor, timestamp, resource, previous_value, new_value, source_ip
- Evidence package generation: `POST /api/v1/shield/compliance/evidence` with framework and control ID returns signed PDF
- Compliance drift detection: alert when a previously compliant control becomes non-compliant due to configuration change

**Tech Stack:** PostgreSQL append-only table for audit log (no UPDATE/DELETE permissions), hash chain for tamper detection, NextJS page (`app/(platform)/shield/compliance/page.tsx`), PDF generation for evidence packages

Part of Epic: Secrets & Compliance Management

---

#### 4.5 (#1269) — Zero-Trust Access Policies

Zero-trust access policies implement the principle of "never trust, always verify" for API access. Instead of granting broad access based on authentication alone, every request is evaluated against contextual factors: who is requesting (identity and role), what they're requesting (which endpoint and resource), when (time of day, day of week), where (geographic location, network), and how (device, client type). Access is granted only when all contextual factors match the defined policy.

Just-in-time (JIT) access provisioning replaces permanent access: users request elevated permissions for a specific purpose and duration. The request goes through an approval workflow (auto-approve for low-risk, manager approve for medium-risk, security team approve for high-risk). Once approved, the elevated permissions activate and automatically expire after the specified duration. All JIT access is logged for audit purposes.

Policy definitions use a declarative format: "Allow ROLE=analyst to READ endpoints matching /api/v1/reports/* FROM ip_range=10.0.0.0/8 DURING weekdays 09:00-18:00 UTC." The policy evaluation engine checks all applicable policies for each request and applies the most restrictive match. A policy simulation mode allows testing new policies against historical traffic before enforcement.

**Acceptance Criteria:**
- Context-aware access policies: evaluate identity, role, endpoint, time, location, and client type per request
- Declarative policy language with conditions on role, endpoint pattern, IP range, time window, and geo-location
- JIT access workflow: request, approval (auto/manager/security based on risk level), time-limited activation, auto-expire
- JIT access log: all elevated access requests, approvals, activations, and expirations tracked
- Policy simulation: `POST /api/v1/shield/policies/simulate` tests policy against historical traffic and returns impact report
- Policy management API: CRUD at `/api/v1/shield/policies` with version history and rollback capability

**Tech Stack:** Policy evaluation engine (OPA/Rego-inspired), NextJS API routes, PostgreSQL for policy storage and JIT access records, Radix UI for policy builder UI, approval workflow engine

Part of Epic: Secrets & Compliance Management

---

## Parallel Work Guide

The following issues can be worked on simultaneously within and across epics:

**Epic 1 — Vulnerability Scanner:**
- Issues 1.1, 1.2, 1.3, and 1.4 can all be developed in parallel (OWASP scan, injection detection, sensitive data, and auth gaps are independent detection modules)
- Issue 1.5 depends on 1.1-1.4 (scheduling and reports aggregate results from all detectors)

**Epic 2 — Runtime Protection Engine:**
- Issues 2.1, 2.2, 2.3, and 2.5 can be developed in parallel (firewall, rate limiter, bot detection, and dashboard are independent)
- Issue 2.4 depends on 2.2 (DDoS protection builds on rate limiting infrastructure)

**Epic 3 — Threat Intelligence & Anomaly Detection:**
- Issues 3.1, 3.2, and 3.3 can be developed in parallel (ML anomaly detection, threat feeds, and pattern recognition are independent)
- Issue 3.4 depends on 3.1, 3.2, 3.3 (alerting consumes events from all detection engines)
- Issue 3.5 depends on 3.4 (investigation workbench uses alerts as entry points)

**Epic 4 — Secrets & Compliance:**
- Issues 4.1, 4.3, and 4.4 can be developed in parallel (key vault, leak detection, and compliance monitoring are independent)
- Issue 4.2 depends on 4.1 (rotation requires the key vault)
- Issue 4.5 depends on 4.1 (zero-trust policies use key vault for identity)

**Cross-Epic Parallelism:**
- Epics 1 and 2 can begin simultaneously (scanning and runtime protection are independent)
- Epic 3 benefits from Epic 2 (anomaly detection uses runtime event data) but can start with synthetic events
- Epic 4 (issues 4.1, 4.3, 4.4) can start in parallel with any other epic
- The runtime security dashboard (2.5) integrates data from all epics—start with Epic 2 data, add Epic 3 and 4 as they complete
