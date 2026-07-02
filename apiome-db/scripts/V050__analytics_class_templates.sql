-- Analytics Class Templates
-- Adds analytics class templates for page views, custom events, conversions, and A/B testing
-- These templates provide reusable patterns for tracking, measurement, and experimentation

SET search_path TO apiome, public;

-- =============================================================================
-- PageView - Page visit tracking
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'PageView',
    'Page view/visit tracking with URL, referrer, session, and device context.',
    'analytics',
    $JSON${
        "type": "object",
        "description": "Page view/visit tracking record",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the page view"
            },
            "sessionId": {
                "type": ["string", "null"],
                "description": "Session identifier",
                "maxLength": 255,
                "examples": ["sess_abc123", null]
            },
            "userId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "User ID (null for anonymous)"
            },
            "anonymousId": {
                "type": ["string", "null"],
                "description": "Anonymous visitor ID (cookie/localStorage)",
                "maxLength": 255,
                "examples": ["anon_xyz789", null]
            },
            "url": {
                "type": "string",
                "format": "uri",
                "description": "Page URL",
                "maxLength": 2048,
                "examples": ["https://example.com/products", "https://app.example.com/dashboard"]
            },
            "path": {
                "type": ["string", "null"],
                "description": "URL path (without query/hash)",
                "maxLength": 1000,
                "examples": ["/products", "/dashboard", null]
            },
            "title": {
                "type": ["string", "null"],
                "description": "Page title",
                "maxLength": 500,
                "examples": ["Products - Acme Inc", "Dashboard", null]
            },
            "referrer": {
                "type": ["string", "null"],
                "format": "uri",
                "description": "Referrer URL",
                "maxLength": 2048,
                "examples": ["https://google.com", "https://example.com/home", null]
            },
            "referrerSource": {
                "type": ["string", "null"],
                "description": "Referrer source (utm_source, etc.)",
                "maxLength": 100,
                "examples": ["google", "newsletter", "direct", null]
            },
            "referrerMedium": {
                "type": ["string", "null"],
                "description": "Referrer medium (utm_medium)",
                "maxLength": 100,
                "examples": ["organic", "email", "cpc", null]
            },
            "referrerCampaign": {
                "type": ["string", "null"],
                "description": "Referrer campaign (utm_campaign)",
                "maxLength": 255,
                "examples": ["summer_sale", "product_launch", null]
            },
            "deviceType": {
                "type": ["string", "null"],
                "description": "Device type",
                "enum": ["desktop", "mobile", "tablet", "unknown", null],
                "examples": ["desktop", "mobile", null]
            },
            "browser": {
                "type": ["string", "null"],
                "description": "Browser name",
                "maxLength": 100,
                "examples": ["Chrome", "Safari", "Firefox", null]
            },
            "os": {
                "type": ["string", "null"],
                "description": "Operating system",
                "maxLength": 100,
                "examples": ["Mac OS", "Windows", "iOS", null]
            },
            "userAgent": {
                "type": ["string", "null"],
                "description": "User agent string",
                "maxLength": 500,
                "examples": ["Mozilla/5.0...", null]
            },
            "ipAddress": {
                "type": ["string", "null"],
                "description": "IP address (anonymized if required)",
                "maxLength": 45,
                "examples": ["192.168.1.1", null]
            },
            "country": {
                "type": ["string", "null"],
                "description": "Country code from geo IP",
                "maxLength": 10,
                "examples": ["US", "GB", "DE", null]
            },
            "region": {
                "type": ["string", "null"],
                "description": "Region/state",
                "maxLength": 100,
                "examples": ["CA", "England", null]
            },
            "duration": {
                "type": ["integer", "null"],
                "description": "Time on page in seconds",
                "minimum": 0,
                "examples": [45, 120, 0, null]
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional page view metadata",
                "additionalProperties": true,
                "examples": [{"section": "products", "category": "electronics"}, null]
            },
            "occurredAt": {
                "type": "string",
                "format": "date-time",
                "description": "When page view occurred"
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When record was created"
            }
        },
        "required": ["url", "occurredAt", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['pageview', 'analytics', 'tracking', 'visit', 'web'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- AnalyticsEvent - Custom analytics events
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'AnalyticsEvent',
    'Custom analytics event with name, properties, and context.',
    'analytics',
    $JSON${
        "type": "object",
        "description": "Custom analytics event",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the event"
            },
            "eventName": {
                "type": "string",
                "description": "Event name",
                "maxLength": 100,
                "examples": ["button_clicked", "purchase_completed", "signup_started"]
            },
            "sessionId": {
                "type": ["string", "null"],
                "description": "Session identifier",
                "maxLength": 255,
                "examples": ["sess_abc123", null]
            },
            "userId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "User ID (null for anonymous)"
            },
            "anonymousId": {
                "type": ["string", "null"],
                "description": "Anonymous visitor ID",
                "maxLength": 255,
                "examples": ["anon_xyz789", null]
            },
            "properties": {
                "type": ["object", "null"],
                "description": "Event properties/key-value data",
                "additionalProperties": true,
                "examples": [{"button": "signup", "page": "/pricing"}, {"productId": "prod_123", "amount": 99.99}, null]
            },
            "context": {
                "type": ["object", "null"],
                "description": "Event context (page, referrer, etc.)",
                "additionalProperties": true,
                "examples": [{"url": "/pricing", "referrer": "/home"}, null]
            },
            "category": {
                "type": ["string", "null"],
                "description": "Event category",
                "maxLength": 100,
                "examples": ["engagement", "conversion", "ecommerce", null]
            },
            "action": {
                "type": ["string", "null"],
                "description": "Event action",
                "maxLength": 100,
                "examples": ["click", "submit", "purchase", null]
            },
            "label": {
                "type": ["string", "null"],
                "description": "Event label",
                "maxLength": 255,
                "examples": ["Sign Up Button", "Checkout", null]
            },
            "value": {
                "type": ["number", "null"],
                "description": "Numeric value (e.g., revenue, quantity)",
                "examples": [99.99, 2, null]
            },
            "url": {
                "type": ["string", "null"],
                "format": "uri",
                "description": "Page URL where event occurred",
                "maxLength": 2048,
                "examples": ["https://example.com/checkout", null]
            },
            "userAgent": {
                "type": ["string", "null"],
                "description": "User agent string",
                "maxLength": 500,
                "examples": ["Mozilla/5.0...", null]
            },
            "ipAddress": {
                "type": ["string", "null"],
                "description": "IP address (anonymized if required)",
                "maxLength": 45,
                "examples": ["192.168.1.1", null]
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional event metadata",
                "additionalProperties": true,
                "examples": [{"abTest": "pricing_v2", "source": "web"}, null]
            },
            "occurredAt": {
                "type": "string",
                "format": "date-time",
                "description": "When event occurred"
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When record was created"
            }
        },
        "required": ["eventName", "occurredAt", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['event', 'analytics', 'tracking', 'custom', 'measurement'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- Conversion - Funnel conversion data
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'Conversion',
    'Conversion/funnel event with goal, value, and attribution.',
    'analytics',
    $JSON${
        "type": "object",
        "description": "Conversion/funnel conversion record",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the conversion"
            },
            "goalId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Conversion goal ID"
            },
            "goalName": {
                "type": "string",
                "description": "Conversion goal name",
                "maxLength": 100,
                "examples": ["signup", "purchase", "lead", "trial_started"]
            },
            "funnelId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Funnel ID (if part of funnel)"
            },
            "funnelName": {
                "type": ["string", "null"],
                "description": "Funnel name",
                "maxLength": 100,
                "examples": ["signup_funnel", "checkout_funnel", null]
            },
            "stage": {
                "type": ["string", "null"],
                "description": "Funnel stage",
                "maxLength": 100,
                "examples": ["1_landing", "2_signup", "3_checkout", "complete", null]
            },
            "stageOrder": {
                "type": ["integer", "null"],
                "description": "Stage order in funnel (1-based)",
                "minimum": 1,
                "examples": [1, 2, 3, null]
            },
            "sessionId": {
                "type": ["string", "null"],
                "description": "Session identifier",
                "maxLength": 255,
                "examples": ["sess_abc123", null]
            },
            "userId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "User ID"
            },
            "anonymousId": {
                "type": ["string", "null"],
                "description": "Anonymous visitor ID",
                "maxLength": 255,
                "examples": ["anon_xyz789", null]
            },
            "value": {
                "type": ["number", "null"],
                "description": "Conversion value (e.g., revenue)",
                "minimum": 0,
                "examples": [99.99, 0, null]
            },
            "currency": {
                "type": ["string", "null"],
                "description": "Currency code for value",
                "pattern": "^[A-Z]{3}$",
                "examples": ["USD", "EUR", null]
            },
            "quantity": {
                "type": ["integer", "null"],
                "description": "Quantity (e.g., items purchased)",
                "minimum": 0,
                "examples": [1, 2, 0, null]
            },
            "referrerSource": {
                "type": ["string", "null"],
                "description": "Attribution: referrer source",
                "maxLength": 100,
                "examples": ["google", "newsletter", "direct", null]
            },
            "referrerMedium": {
                "type": ["string", "null"],
                "description": "Attribution: referrer medium",
                "maxLength": 100,
                "examples": ["organic", "email", "cpc", null]
            },
            "referrerCampaign": {
                "type": ["string", "null"],
                "description": "Attribution: campaign",
                "maxLength": 255,
                "examples": ["summer_sale", "product_launch", null]
            },
            "attributionModel": {
                "type": ["string", "null"],
                "description": "Attribution model used",
                "enum": ["first_touch", "last_touch", "linear", "time_decay", "position_based", null],
                "examples": ["last_touch", "first_touch", null]
            },
            "properties": {
                "type": ["object", "null"],
                "description": "Conversion properties",
                "additionalProperties": true,
                "examples": [{"orderId": "ord_123", "productIds": ["p1", "p2"]}, null]
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional conversion metadata",
                "additionalProperties": true,
                "examples": [{"abTest": "checkout_v2"}, null]
            },
            "occurredAt": {
                "type": "string",
                "format": "date-time",
                "description": "When conversion occurred"
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When record was created"
            }
        },
        "required": ["goalName", "occurredAt", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['conversion', 'funnel', 'analytics', 'goal', 'attribution'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- ABTest - A/B testing configurations
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'ABTest',
    'A/B test configuration with variants, traffic allocation, and metrics.',
    'analytics',
    $JSON${
        "type": "object",
        "description": "A/B test configuration",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the A/B test"
            },
            "name": {
                "type": "string",
                "description": "Test name",
                "maxLength": 255,
                "minLength": 1,
                "examples": ["Homepage Hero CTA", "Pricing Page Layout", "Checkout Flow"]
            },
            "description": {
                "type": ["string", "null"],
                "description": "Test description",
                "maxLength": 1000,
                "examples": ["Test new CTA button copy vs control", null]
            },
            "status": {
                "type": "string",
                "description": "Test status",
                "enum": ["draft", "running", "paused", "completed", "archived"],
                "default": "draft",
                "examples": ["draft", "running", "completed"]
            },
            "target": {
                "type": ["string", "null"],
                "description": "What is being tested (page, component, feature)",
                "maxLength": 500,
                "examples": ["/pricing", "checkout_button", "homepage_hero", null]
            },
            "variants": {
                "type": "array",
                "description": "Test variants",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": { "type": "string", "maxLength": 100 },
                        "name": { "type": "string", "maxLength": 100 },
                        "weight": { "type": "number", "minimum": 0, "maximum": 1 },
                        "config": { "type": "object", "additionalProperties": true },
                        "isControl": { "type": "boolean", "default": false }
                    },
                    "required": ["id", "name", "weight"]
                },
                "minItems": 2,
                "examples": [
                    [
                        {"id": "control", "name": "Control", "weight": 0.5, "isControl": true},
                        {"id": "variant_a", "name": "Variant A", "weight": 0.5, "isControl": false}
                    ]
                ]
            },
            "trafficAllocation": {
                "type": ["number", "null"],
                "description": "Percentage of traffic in test (0-1)",
                "minimum": 0,
                "maximum": 1,
                "default": 1,
                "examples": [1, 0.5, 0.1, null]
            },
            "primaryMetric": {
                "type": ["string", "null"],
                "description": "Primary success metric",
                "maxLength": 100,
                "examples": ["conversion_rate", "revenue_per_user", "signup_rate", null]
            },
            "secondaryMetrics": {
                "type": ["array", "null"],
                "description": "Secondary metrics to track",
                "items": {
                    "type": "string",
                    "maxLength": 100
                },
                "examples": [["revenue_per_user", "time_on_page"], null]
            },
            "segment": {
                "type": ["object", "null"],
                "description": "Target segment (who sees the test)",
                "additionalProperties": true,
                "examples": [{"country": ["US", "GB"], "newUsers": true}, null]
            },
            "startedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When test started"
            },
            "endedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When test ended"
            },
            "minSampleSize": {
                "type": ["integer", "null"],
                "description": "Minimum sample size per variant before declaring winner",
                "minimum": 1,
                "examples": [1000, 5000, null]
            },
            "confidenceLevel": {
                "type": ["number", "null"],
                "description": "Required confidence level (e.g., 0.95 for 95%)",
                "minimum": 0,
                "maximum": 1,
                "examples": [0.95, 0.99, null]
            },
            "winnerVariantId": {
                "type": ["string", "null"],
                "description": "Winning variant ID (when completed)",
                "maxLength": 100,
                "examples": ["variant_a", null]
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional test metadata",
                "additionalProperties": true,
                "examples": [{"owner": "growth-team", "jira": "GROW-123"}, null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When test was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When test was last updated"
            }
        },
        "required": ["name", "variants", "status", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['abtest', 'ab-test', 'experiment', 'analytics', 'optimization', 'variant'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- Log completion
DO $$
BEGIN
    RAISE NOTICE 'Analytics class templates successfully created: PageView, AnalyticsEvent, Conversion, ABTest';
END $$;
