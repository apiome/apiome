-- Property Templates: Timestamps Category
-- These templates define common timestamp patterns for tracking time-related data
-- Property names are camelCase, alphanumeric only (a-zA-Z0-9)
-- Follows OpenAPI 3.1 / JSON Schema Draft 2020-12 standards

SET search_path TO odb, public;

-- =============================================================================
-- RECORD LIFECYCLE TIMESTAMPS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'createdAt',
           'Timestamp recording when a record was first created. Automatically set on insert and never modified.',
           'timestamps',
           '{
               "type": "string",
               "format": "date-time",
               "description": "Timestamp when the record was created",
               "examples": ["2024-01-15T09:30:00Z", "2024-06-20T14:45:30.123Z"],
               "readOnly": true
           }',
           ARRAY['created', 'lifecycle', 'audit', 'immutable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'updatedAt',
           'Timestamp recording when a record was last modified. Automatically updated on every change.',
           'timestamps',
           '{
               "type": "string",
               "format": "date-time",
               "description": "Timestamp when the record was last updated",
               "examples": ["2024-01-15T09:30:00Z", "2024-06-20T14:45:30.123Z"],
               "readOnly": true
           }',
           ARRAY['updated', 'modified', 'lifecycle', 'audit'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'deletedAt',
           'Timestamp for soft delete implementation. Null indicates active record; populated indicates deletion time.',
           'timestamps',
           '{
               "type": ["string", "null"],
               "format": "date-time",
               "description": "Timestamp when the record was soft-deleted (null if active)",
               "examples": ["2024-01-15T09:30:00Z", null],
               "readOnly": true
           }',
           ARRAY['deleted', 'soft-delete', 'lifecycle', 'audit', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'archivedAt',
           'Timestamp when a record was archived. Used for records moved to cold storage or marked inactive.',
           'timestamps',
           '{
               "type": ["string", "null"],
               "format": "date-time",
               "description": "Timestamp when the record was archived (null if active)",
               "examples": ["2024-01-15T09:30:00Z", null]
           }',
           ARRAY['archived', 'lifecycle', 'inactive', 'nullable'],
           true,
           true
       );

-- =============================================================================
-- PUBLISHING AND VISIBILITY TIMESTAMPS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'publishedAt',
           'Timestamp when content was made publicly visible. Used for content management and editorial workflows.',
           'timestamps',
           '{
               "type": ["string", "null"],
               "format": "date-time",
               "description": "Timestamp when the content was published (null if unpublished)",
               "examples": ["2024-01-15T09:30:00Z", "2024-06-20T00:00:00Z", null]
           }',
           ARRAY['published', 'content', 'cms', 'visibility', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'unpublishedAt',
           'Timestamp when content was removed from public visibility. Tracks content retraction.',
           'timestamps',
           '{
               "type": ["string", "null"],
               "format": "date-time",
               "description": "Timestamp when the content was unpublished",
               "examples": ["2024-01-15T09:30:00Z", null]
           }',
           ARRAY['unpublished', 'content', 'cms', 'visibility', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'scheduledPublishAt',
           'Future timestamp when content should be automatically published. Used for scheduled content release.',
           'timestamps',
           '{
               "type": ["string", "null"],
               "format": "date-time",
               "description": "Scheduled timestamp for automatic publication",
               "examples": ["2024-12-25T00:00:00Z", "2025-01-01T08:00:00Z", null]
           }',
           ARRAY['scheduled', 'publish', 'content', 'cms', 'future', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'visibilityWindow',
           'Time range during which content is visible. Combines start and end timestamps for scheduled visibility.',
           'timestamps',
           '{
               "type": "object",
               "description": "Time window defining when content is publicly visible",
               "properties": {
                   "visibleFrom": {
                       "type": ["string", "null"],
                       "format": "date-time",
                       "description": "Start of visibility window (null for immediate)"
                   },
                   "visibleUntil": {
                       "type": ["string", "null"],
                       "format": "date-time",
                       "description": "End of visibility window (null for indefinite)"
                   }
               },
               "examples": [
                   {"visibleFrom": "2024-01-01T00:00:00Z", "visibleUntil": "2024-12-31T23:59:59Z"},
                   {"visibleFrom": "2024-06-01T00:00:00Z", "visibleUntil": null}
               ]
           }',
           ARRAY['visibility', 'window', 'scheduled', 'content', 'range'],
           true,
           true
       );

-- =============================================================================
-- APPROVAL AND WORKFLOW TIMESTAMPS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'submittedAt',
           'Timestamp when a record was submitted for review or approval.',
           'timestamps',
           '{
               "type": ["string", "null"],
               "format": "date-time",
               "description": "Timestamp when submitted for review",
               "examples": ["2024-01-15T09:30:00Z", null]
           }',
           ARRAY['submitted', 'workflow', 'approval', 'review', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'approvedAt',
           'Timestamp when a record received approval. Used in review and authorization workflows.',
           'timestamps',
           '{
               "type": ["string", "null"],
               "format": "date-time",
               "description": "Timestamp when the record was approved",
               "examples": ["2024-01-15T14:30:00Z", null]
           }',
           ARRAY['approved', 'workflow', 'approval', 'authorization', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'rejectedAt',
           'Timestamp when a record was rejected in an approval workflow.',
           'timestamps',
           '{
               "type": ["string", "null"],
               "format": "date-time",
               "description": "Timestamp when the record was rejected",
               "examples": ["2024-01-15T14:30:00Z", null]
           }',
           ARRAY['rejected', 'workflow', 'approval', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'reviewedAt',
           'Timestamp when a record was last reviewed, regardless of outcome.',
           'timestamps',
           '{
               "type": ["string", "null"],
               "format": "date-time",
               "description": "Timestamp when the record was last reviewed",
               "examples": ["2024-01-15T14:30:00Z", null]
           }',
           ARRAY['reviewed', 'workflow', 'review', 'nullable'],
           true,
           true
       );

-- =============================================================================
-- EXPIRATION AND VALIDITY TIMESTAMPS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'expiresAt',
           'Timestamp when a record or resource becomes invalid. Used for sessions, tokens, and time-limited data.',
           'timestamps',
           '{
               "type": ["string", "null"],
               "format": "date-time",
               "description": "Timestamp when the record expires (null for no expiration)",
               "examples": ["2024-01-15T09:30:00Z", "2025-12-31T23:59:59Z", null]
           }',
           ARRAY['expires', 'expiration', 'ttl', 'validity', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'validFrom',
           'Timestamp when a record becomes effective. Used for future-dated or scheduled activation.',
           'timestamps',
           '{
               "type": ["string", "null"],
               "format": "date-time",
               "description": "Timestamp when the record becomes valid (null for immediate)",
               "examples": ["2024-01-01T00:00:00Z", null]
           }',
           ARRAY['valid-from', 'effective', 'activation', 'scheduled', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'validUntil',
           'Timestamp when a record stops being effective. Used for time-bounded validity.',
           'timestamps',
           '{
               "type": ["string", "null"],
               "format": "date-time",
               "description": "Timestamp when the record stops being valid (null for indefinite)",
               "examples": ["2024-12-31T23:59:59Z", null]
           }',
           ARRAY['valid-until', 'expiration', 'validity', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'validityPeriod',
           'Complete validity window with start and end timestamps. Used for contracts, subscriptions, and policies.',
           'timestamps',
           '{
               "type": "object",
               "description": "Time period during which the record is considered valid",
               "properties": {
                   "validFrom": {
                       "type": "string",
                       "format": "date-time",
                       "description": "Start of validity period"
                   },
                   "validUntil": {
                       "type": ["string", "null"],
                       "format": "date-time",
                       "description": "End of validity period (null for indefinite)"
                   }
               },
               "required": ["validFrom"],
               "examples": [
                   {"validFrom": "2024-01-01T00:00:00Z", "validUntil": "2024-12-31T23:59:59Z"},
                   {"validFrom": "2024-06-01T00:00:00Z", "validUntil": null}
               ]
           }',
           ARRAY['validity', 'period', 'range', 'contract', 'subscription'],
           true,
           true
       );

-- =============================================================================
-- USER ACTIVITY TIMESTAMPS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'lastLoginAt',
           'Timestamp of user''s most recent authentication. Used for security monitoring and activity tracking.',
           'timestamps',
           '{
               "type": ["string", "null"],
               "format": "date-time",
               "description": "Timestamp of last successful login",
               "examples": ["2024-01-15T09:30:00Z", null],
               "readOnly": true
           }',
           ARRAY['login', 'authentication', 'user-activity', 'security', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'lastActivityAt',
           'Timestamp of user''s most recent action. Used for session management and engagement tracking.',
           'timestamps',
           '{
               "type": ["string", "null"],
               "format": "date-time",
               "description": "Timestamp of last user activity",
               "examples": ["2024-01-15T09:30:00Z", null],
               "readOnly": true
           }',
           ARRAY['activity', 'user-activity', 'session', 'engagement', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'lastSeenAt',
           'Timestamp when user was last observed online. Used for presence indicators and availability.',
           'timestamps',
           '{
               "type": ["string", "null"],
               "format": "date-time",
               "description": "Timestamp when user was last seen online",
               "examples": ["2024-01-15T09:30:00Z", null],
               "readOnly": true
           }',
           ARRAY['last-seen', 'presence', 'online', 'availability', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'passwordChangedAt',
           'Timestamp when user last changed their password. Used for security policies and password expiration.',
           'timestamps',
           '{
               "type": ["string", "null"],
               "format": "date-time",
               "description": "Timestamp when password was last changed",
               "examples": ["2024-01-15T09:30:00Z", null],
               "readOnly": true
           }',
           ARRAY['password', 'security', 'authentication', 'credential', 'nullable'],
           true,
           true
       );

-- =============================================================================
-- EVENT AND ACTION TIMESTAMPS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'startedAt',
           'Timestamp when a process, task, or event began execution.',
           'timestamps',
           '{
               "type": ["string", "null"],
               "format": "date-time",
               "description": "Timestamp when execution started",
               "examples": ["2024-01-15T09:30:00Z", null]
           }',
           ARRAY['started', 'process', 'execution', 'task', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'completedAt',
           'Timestamp when a process, task, or event finished execution.',
           'timestamps',
           '{
               "type": ["string", "null"],
               "format": "date-time",
               "description": "Timestamp when execution completed",
               "examples": ["2024-01-15T10:45:00Z", null]
           }',
           ARRAY['completed', 'finished', 'process', 'execution', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'failedAt',
           'Timestamp when a process or task encountered a failure.',
           'timestamps',
           '{
               "type": ["string", "null"],
               "format": "date-time",
               "description": "Timestamp when execution failed",
               "examples": ["2024-01-15T09:35:00Z", null]
           }',
           ARRAY['failed', 'error', 'process', 'execution', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'cancelledAt',
           'Timestamp when a process or task was cancelled before completion.',
           'timestamps',
           '{
               "type": ["string", "null"],
               "format": "date-time",
               "description": "Timestamp when execution was cancelled",
               "examples": ["2024-01-15T09:32:00Z", null]
           }',
           ARRAY['cancelled', 'aborted', 'process', 'execution', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'executionDuration',
           'Object capturing start, end, and calculated duration of a process execution.',
           'timestamps',
           '{
               "type": "object",
               "description": "Complete execution timing information",
               "properties": {
                   "startedAt": {
                       "type": "string",
                       "format": "date-time",
                       "description": "When execution began"
                   },
                   "completedAt": {
                       "type": ["string", "null"],
                       "format": "date-time",
                       "description": "When execution ended"
                   },
                   "durationMs": {
                       "type": ["integer", "null"],
                       "description": "Duration in milliseconds",
                       "minimum": 0
                   }
               },
               "required": ["startedAt"],
               "examples": [
                   {"startedAt": "2024-01-15T09:30:00Z", "completedAt": "2024-01-15T09:35:00Z", "durationMs": 300000},
                   {"startedAt": "2024-01-15T09:30:00Z", "completedAt": null, "durationMs": null}
               ]
           }',
           ARRAY['duration', 'execution', 'timing', 'performance', 'process'],
           true,
           true
       );

-- =============================================================================
-- SCHEDULING AND RECURRENCE TIMESTAMPS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'scheduledAt',
           'Timestamp when a task or event is scheduled to occur.',
           'timestamps',
           '{
               "type": "string",
               "format": "date-time",
               "description": "Scheduled execution time",
               "examples": ["2024-01-15T09:30:00Z", "2024-12-25T00:00:00Z"]
           }',
           ARRAY['scheduled', 'future', 'task', 'event'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'nextRunAt',
           'Timestamp for the next scheduled execution of a recurring task.',
           'timestamps',
           '{
               "type": ["string", "null"],
               "format": "date-time",
               "description": "Next scheduled execution time",
               "examples": ["2024-01-16T09:30:00Z", null]
           }',
           ARRAY['next-run', 'scheduled', 'recurring', 'cron', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'lastRunAt',
           'Timestamp of the most recent execution of a recurring task.',
           'timestamps',
           '{
               "type": ["string", "null"],
               "format": "date-time",
               "description": "Most recent execution time",
               "examples": ["2024-01-15T09:30:00Z", null],
               "readOnly": true
           }',
           ARRAY['last-run', 'recurring', 'cron', 'history', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'recurringSchedule',
           'Complete recurring schedule with last run, next run, and cron expression.',
           'timestamps',
           '{
               "type": "object",
               "description": "Recurring schedule configuration and state",
               "properties": {
                   "cronExpression": {
                       "type": "string",
                       "description": "Cron expression defining the schedule"
                   },
                   "timezone": {
                       "type": "string",
                       "description": "IANA timezone for schedule interpretation"
                   },
                   "lastRunAt": {
                       "type": ["string", "null"],
                       "format": "date-time",
                       "description": "Most recent execution"
                   },
                   "nextRunAt": {
                       "type": ["string", "null"],
                       "format": "date-time",
                       "description": "Next scheduled execution"
                   }
               },
               "required": ["cronExpression"],
               "examples": [
                   {
                       "cronExpression": "0 9 * * 1-5",
                       "timezone": "America/New_York",
                       "lastRunAt": "2024-01-15T09:00:00Z",
                       "nextRunAt": "2024-01-16T09:00:00Z"
                   },
                   {
                       "cronExpression": "0 0 * * *",
                       "timezone": "UTC",
                       "lastRunAt": null,
                       "nextRunAt": "2024-01-16T00:00:00Z"
                   }
               ]
           }',
           ARRAY['recurring', 'schedule', 'cron', 'timezone'],
           true,
           true
       );

-- =============================================================================
-- NOTIFICATION AND REMINDER TIMESTAMPS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'remindAt',
           'Timestamp when a reminder should be triggered.',
           'timestamps',
           '{
               "type": ["string", "null"],
               "format": "date-time",
               "description": "Scheduled reminder time",
               "examples": ["2024-01-15T09:00:00Z", null]
           }',
           ARRAY['reminder', 'notification', 'alert', 'scheduled', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'notifiedAt',
           'Timestamp when a notification was sent.',
           'timestamps',
           '{
               "type": ["string", "null"],
               "format": "date-time",
               "description": "When notification was dispatched",
               "examples": ["2024-01-15T09:00:00Z", null],
               "readOnly": true
           }',
           ARRAY['notified', 'notification', 'sent', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'acknowledgedAt',
           'Timestamp when a notification or alert was acknowledged by the recipient.',
           'timestamps',
           '{
               "type": ["string", "null"],
               "format": "date-time",
               "description": "When notification was acknowledged",
               "examples": ["2024-01-15T09:05:00Z", null]
           }',
           ARRAY['acknowledged', 'notification', 'alert', 'response', 'nullable'],
           true,
           true
       );

-- =============================================================================
-- DATE-ONLY AND TIME-ONLY FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'date',
           'Calendar date without time component. Used for birthdays, due dates, and date-specific events.',
           'timestamps',
           '{
               "type": "string",
               "format": "date",
               "description": "Calendar date (no time component)",
               "examples": ["2024-01-15", "2024-12-25"]
           }',
           ARRAY['date', 'calendar', 'date-only'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'time',
           'Time of day without date component. Used for daily schedules and recurring time-based events.',
           'timestamps',
           '{
               "type": "string",
               "format": "time",
               "description": "Time of day (no date component)",
               "examples": ["09:30:00", "14:45:30", "23:59:59"]
           }',
           ARRAY['time', 'time-only', 'schedule'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'dateRange',
           'Pair of dates representing a range. Used for reporting periods, date filters, and spans.',
           'timestamps',
           '{
               "type": "object",
               "description": "Date range with start and end dates",
               "properties": {
                   "startDate": {
                       "type": "string",
                       "format": "date",
                       "description": "Start date of the range"
                   },
                   "endDate": {
                       "type": "string",
                       "format": "date",
                       "description": "End date of the range"
                   }
               },
               "required": ["startDate", "endDate"],
               "examples": [
                   {"startDate": "2024-01-01", "endDate": "2024-01-31"},
                   {"startDate": "2024-04-01", "endDate": "2024-06-30"}
               ]
           }',
           ARRAY['date-range', 'period', 'range', 'reporting'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'dateTimeRange',
           'Pair of timestamps representing a precise time range. Used for event scheduling and time-based queries.',
           'timestamps',
           '{
               "type": "object",
               "description": "Date-time range with start and end timestamps",
               "properties": {
                   "startDateTime": {
                       "type": "string",
                       "format": "date-time",
                       "description": "Start of the range"
                   },
                   "endDateTime": {
                       "type": "string",
                       "format": "date-time",
                       "description": "End of the range"
                   }
               },
               "required": ["startDateTime", "endDateTime"],
               "examples": [
                   {"startDateTime": "2024-01-15T09:00:00Z", "endDateTime": "2024-01-15T17:00:00Z"},
                   {"startDateTime": "2024-06-01T00:00:00Z", "endDateTime": "2024-06-30T23:59:59Z"}
               ]
           }',
           ARRAY['datetime-range', 'period', 'range', 'scheduling'],
           true,
           true
       );

-- =============================================================================
-- TIMEZONE-AWARE TIMESTAMPS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'timestampWithOffset',
           'ISO 8601 timestamp with explicit timezone offset. Preserves original timezone context.',
           'timestamps',
           '{
               "type": "string",
               "format": "date-time",
               "description": "Timestamp with timezone offset",
               "examples": ["2024-01-15T09:30:00-05:00", "2024-01-15T14:30:00+00:00", "2024-01-15T23:30:00+09:00"]
           }',
           ARRAY['timestamp', 'timezone', 'offset', 'iso8601'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'localizedTimestamp',
           'Timestamp paired with IANA timezone identifier. Enables accurate local time display and DST handling.',
           'timestamps',
           '{
               "type": "object",
               "description": "Timestamp with IANA timezone for localization",
               "properties": {
                   "utcTimestamp": {
                       "type": "string",
                       "format": "date-time",
                       "description": "UTC timestamp"
                   },
                   "timezone": {
                       "type": "string",
                       "description": "IANA timezone identifier"
                   }
               },
               "required": ["utcTimestamp", "timezone"],
               "examples": [
                   {"utcTimestamp": "2024-01-15T14:30:00Z", "timezone": "America/New_York"},
                   {"utcTimestamp": "2024-07-15T18:00:00Z", "timezone": "Europe/London"}
               ]
           }',
           ARRAY['timestamp', 'timezone', 'iana', 'localization', 'dst'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'timezone',
           'IANA timezone identifier. Used for storing user or location timezone preferences.',
           'timestamps',
           '{
               "type": "string",
               "description": "IANA timezone identifier",
               "examples": ["America/New_York", "Europe/London", "Asia/Tokyo", "UTC"]
           }',
           ARRAY['timezone', 'iana', 'preference', 'localization'],
           true,
           true
       );

-- =============================================================================
-- UNIX TIMESTAMPS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'unixTimestamp',
           'Unix epoch timestamp in seconds. Common format for APIs and legacy system integration.',
           'timestamps',
           '{
               "type": "integer",
               "format": "int64",
               "description": "Unix timestamp in seconds since epoch",
               "examples": [1705315800, 1735689599],
               "minimum": 0
           }',
           ARRAY['unix', 'epoch', 'seconds', 'integer'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'unixTimestampMs',
           'Unix epoch timestamp in milliseconds. Used by JavaScript and high-precision systems.',
           'timestamps',
           '{
               "type": "integer",
               "format": "int64",
               "description": "Unix timestamp in milliseconds since epoch",
               "examples": [1705315800000, 1735689599999],
               "minimum": 0
           }',
           ARRAY['unix', 'epoch', 'milliseconds', 'javascript', 'precision'],
           true,
           true
       );

-- =============================================================================
-- AUDIT AND HISTORY TIMESTAMPS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'auditTimestamps',
           'Complete audit trail timestamps for record lifecycle tracking.',
           'timestamps',
           '{
               "type": "object",
               "description": "Standard audit timestamp fields",
               "properties": {
                   "createdAt": {
                       "type": "string",
                       "format": "date-time",
                       "description": "When the record was created",
                       "readOnly": true
                   },
                   "createdBy": {
                       "type": ["string", "null"],
                       "format": "uuid",
                       "description": "User who created the record"
                   },
                   "updatedAt": {
                       "type": "string",
                       "format": "date-time",
                       "description": "When the record was last updated",
                       "readOnly": true
                   },
                   "updatedBy": {
                       "type": ["string", "null"],
                       "format": "uuid",
                       "description": "User who last updated the record"
                   }
               },
               "required": ["createdAt", "updatedAt"],
               "examples": [
                   {
                       "createdAt": "2024-01-15T09:30:00Z",
                       "createdBy": "550e8400-e29b-41d4-a716-446655440000",
                       "updatedAt": "2024-01-15T14:45:00Z",
                       "updatedBy": "6ba7b810-9dad-11d1-80b4-00c04fd430c8"
                   }
               ]
           }',
           ARRAY['audit', 'lifecycle', 'tracking', 'created', 'updated'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'fullAuditTimestamps',
           'Extended audit timestamps including soft delete tracking.',
           'timestamps',
           '{
               "type": "object",
               "description": "Extended audit timestamp fields with soft delete",
               "properties": {
                   "createdAt": {
                       "type": "string",
                       "format": "date-time",
                       "description": "When the record was created",
                       "readOnly": true
                   },
                   "createdBy": {
                       "type": ["string", "null"],
                       "format": "uuid",
                       "description": "User who created the record"
                   },
                   "updatedAt": {
                       "type": "string",
                       "format": "date-time",
                       "description": "When the record was last updated",
                       "readOnly": true
                   },
                   "updatedBy": {
                       "type": ["string", "null"],
                       "format": "uuid",
                       "description": "User who last updated the record"
                   },
                   "deletedAt": {
                       "type": ["string", "null"],
                       "format": "date-time",
                       "description": "When the record was soft-deleted",
                       "readOnly": true
                   },
                   "deletedBy": {
                       "type": ["string", "null"],
                       "format": "uuid",
                       "description": "User who deleted the record"
                   }
               },
               "required": ["createdAt", "updatedAt"],
               "examples": [
                   {
                       "createdAt": "2024-01-15T09:30:00Z",
                       "createdBy": "550e8400-e29b-41d4-a716-446655440000",
                       "updatedAt": "2024-01-15T14:45:00Z",
                       "updatedBy": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
                       "deletedAt": null,
                       "deletedBy": null
                   }
               ]
           }',
           ARRAY['audit', 'lifecycle', 'tracking', 'soft-delete', 'full'],
           true,
           true
       );

-- =============================================================================
-- DURATION FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'durationSeconds',
           'Duration expressed in seconds. Used for timeouts, intervals, and short durations.',
           'timestamps',
           '{
               "type": "integer",
               "description": "Duration in seconds",
               "examples": [30, 300, 3600],
               "minimum": 0
           }',
           ARRAY['duration', 'seconds', 'interval', 'timeout'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'durationMs',
           'Duration expressed in milliseconds. Used for precise timing and performance measurements.',
           'timestamps',
           '{
               "type": "integer",
               "description": "Duration in milliseconds",
               "examples": [100, 1500, 30000],
               "minimum": 0
           }',
           ARRAY['duration', 'milliseconds', 'precision', 'performance'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'durationIso8601',
           'Duration in ISO 8601 format. Human-readable and standard-compliant duration representation.',
           'timestamps',
           '{
               "type": "string",
               "description": "Duration in ISO 8601 format",
               "examples": ["PT1H30M", "P1D", "PT45S", "P1Y2M3DT4H5M6S"],
               "pattern": "^P(?:\\d+Y)?(?:\\d+M)?(?:\\d+W)?(?:\\d+D)?(?:T(?:\\d+H)?(?:\\d+M)?(?:\\d+(?:\\.\\d+)?S)?)?$"
           }',
           ARRAY['duration', 'iso8601', 'human-readable', 'standard'],
           true,
           true
       );
