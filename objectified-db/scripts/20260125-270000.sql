-- Scheduling Class Templates
-- Adds scheduling class templates for appointments, availability, calendar integration, and reminders
-- These templates provide reusable patterns for booking and scheduling systems

SET search_path TO odb, public;

-- =============================================================================
-- Appointment - Booking and scheduling
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'Appointment',
    'Appointment booking with participants, time slots, and status tracking.',
    'scheduling',
    $JSON${
        "type": "object",
        "description": "Appointment booking",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the appointment"
            },
            "appointmentNumber": {
                "type": ["string", "null"],
                "description": "Human-readable appointment number",
                "maxLength": 100,
                "examples": ["APT-2026-001", "A123456", null]
            },
            "title": {
                "type": ["string", "null"],
                "description": "Appointment title/subject",
                "maxLength": 255,
                "examples": ["Consultation", "Follow-up Visit", "Annual Checkup", null]
            },
            "description": {
                "type": ["string", "null"],
                "description": "Appointment description/notes",
                "maxLength": 5000,
                "examples": ["Initial consultation for new patient", null]
            },
            "type": {
                "type": ["string", "null"],
                "description": "Appointment type",
                "maxLength": 100,
                "examples": ["consultation", "follow-up", "checkup", "surgery", "therapy", null]
            },
            "status": {
                "type": "string",
                "description": "Appointment status",
                "enum": ["scheduled", "confirmed", "in_progress", "completed", "cancelled", "no_show", "rescheduled"],
                "default": "scheduled",
                "examples": ["scheduled", "confirmed", "completed"]
            },
            "startTime": {
                "type": "string",
                "format": "date-time",
                "description": "Appointment start time"
            },
            "endTime": {
                "type": "string",
                "format": "date-time",
                "description": "Appointment end time"
            },
            "duration": {
                "type": ["integer", "null"],
                "description": "Duration in minutes",
                "minimum": 1,
                "examples": [30, 60, 90, null]
            },
            "timezone": {
                "type": ["string", "null"],
                "description": "Timezone (IANA format)",
                "examples": ["America/New_York", "Europe/London", "UTC", null]
            },
            "organizerId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "User ID who created/organized the appointment"
            },
            "attendeeIds": {
                "type": ["array", "null"],
                "description": "Attendee user IDs",
                "items": {
                    "type": "string",
                    "format": "uuid"
                },
                "examples": [[], null]
            },
            "resourceId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Resource ID (room, equipment, etc.)"
            },
            "serviceId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Service ID being booked"
            },
            "location": {
                "type": ["string", "null"],
                "description": "Location (address, room, virtual link)",
                "maxLength": 500,
                "examples": ["123 Main St, Room 101", "https://zoom.us/j/123456", null]
            },
            "isVirtual": {
                "type": ["boolean", "null"],
                "description": "Whether appointment is virtual/online",
                "default": false,
                "examples": [true, false, null]
            },
            "meetingUrl": {
                "type": ["string", "null"],
                "format": "uri",
                "description": "Virtual meeting URL"
            },
            "recurrenceRule": {
                "type": ["string", "null"],
                "description": "Recurrence rule (RRULE format)",
                "maxLength": 500,
                "examples": ["FREQ=WEEKLY;BYDAY=MO;COUNT=10", null]
            },
            "recurrenceId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Parent recurrence series ID"
            },
            "cancellationReason": {
                "type": ["string", "null"],
                "description": "Reason for cancellation",
                "maxLength": 500,
                "examples": ["Patient request", "Emergency", null]
            },
            "cancelledAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When appointment was cancelled"
            },
            "cancelledBy": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "User ID who cancelled"
            },
            "reminderSent": {
                "type": ["boolean", "null"],
                "description": "Whether reminder was sent",
                "default": false,
                "examples": [true, false, null]
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional appointment metadata",
                "additionalProperties": true,
                "examples": [{"priority": "high", "tags": ["urgent"]}, null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When appointment was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When appointment was last updated"
            }
        },
        "required": ["startTime", "endTime", "status", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['appointment', 'booking', 'scheduling', 'meeting', 'calendar'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- Availability - Time slot management
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'Availability',
    'Time slot availability for resources, services, or users.',
    'scheduling',
    $JSON${
        "type": "object",
        "description": "Time slot availability",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the availability"
            },
            "resourceId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Resource ID (user, service, room, etc.)"
            },
            "resourceType": {
                "type": ["string", "null"],
                "description": "Type of resource",
                "enum": ["user", "service", "room", "equipment", "other", null],
                "examples": ["user", "service", null]
            },
            "startTime": {
                "type": "string",
                "format": "date-time",
                "description": "Availability start time"
            },
            "endTime": {
                "type": "string",
                "format": "date-time",
                "description": "Availability end time"
            },
            "isAvailable": {
                "type": "boolean",
                "description": "Whether time slot is available",
                "default": true,
                "examples": [true, false]
            },
            "isRecurring": {
                "type": ["boolean", "null"],
                "description": "Whether availability repeats",
                "default": false,
                "examples": [true, false, null]
            },
            "recurrenceRule": {
                "type": ["string", "null"],
                "description": "Recurrence rule (RRULE format)",
                "maxLength": 500,
                "examples": ["FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=9;BYMINUTE=0", null]
            },
            "timezone": {
                "type": ["string", "null"],
                "description": "Timezone (IANA format)",
                "examples": ["America/New_York", "Europe/London", "UTC", null]
            },
            "maxBookings": {
                "type": ["integer", "null"],
                "description": "Maximum concurrent bookings allowed",
                "minimum": 1,
                "examples": [1, 5, 10, null]
            },
            "currentBookings": {
                "type": ["integer", "null"],
                "description": "Current number of bookings",
                "minimum": 0,
                "default": 0,
                "examples": [0, 3, 5, null]
            },
            "bufferBefore": {
                "type": ["integer", "null"],
                "description": "Buffer time before (minutes)",
                "minimum": 0,
                "examples": [0, 15, 30, null]
            },
            "bufferAfter": {
                "type": ["integer", "null"],
                "description": "Buffer time after (minutes)",
                "minimum": 0,
                "examples": [0, 15, 30, null]
            },
            "slotDuration": {
                "type": ["integer", "null"],
                "description": "Slot duration in minutes",
                "minimum": 1,
                "examples": [15, 30, 60, null]
            },
            "breakStart": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "Break start time (if applicable)"
            },
            "breakEnd": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "Break end time (if applicable)"
            },
            "reason": {
                "type": ["string", "null"],
                "description": "Reason for unavailability",
                "maxLength": 500,
                "examples": ["Lunch break", "Holiday", "Maintenance", null]
            },
            "isBlocked": {
                "type": ["boolean", "null"],
                "description": "Whether slot is blocked (not bookable)",
                "default": false,
                "examples": [true, false, null]
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional availability metadata",
                "additionalProperties": true,
                "examples": [{"priority": "high", "autoConfirm": true}, null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When availability was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When availability was last updated"
            }
        },
        "required": ["startTime", "endTime", "isAvailable", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['availability', 'scheduling', 'time-slot', 'booking', 'calendar'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- Calendar - Calendar integration
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'Calendar',
    'Calendar integration with external calendar providers and sync settings.',
    'scheduling',
    $JSON${
        "type": "object",
        "description": "Calendar integration",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the calendar"
            },
            "userId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "User ID who owns the calendar"
            },
            "name": {
                "type": ["string", "null"],
                "description": "Calendar name",
                "maxLength": 255,
                "examples": ["Work Calendar", "Personal", "Team Schedule", null]
            },
            "provider": {
                "type": ["string", "null"],
                "description": "Calendar provider",
                "enum": ["google", "outlook", "apple", "ical", "caldav", "other", null],
                "examples": ["google", "outlook", "apple", null]
            },
            "externalCalendarId": {
                "type": ["string", "null"],
                "description": "External calendar ID from provider",
                "maxLength": 255,
                "examples": ["primary", "cal_1234567890", null]
            },
            "syncToken": {
                "type": ["string", "null"],
                "description": "Sync token for incremental sync",
                "maxLength": 500,
                "examples": ["CPD0y...", null]
            },
            "isPrimary": {
                "type": ["boolean", "null"],
                "description": "Whether this is the primary calendar",
                "default": false,
                "examples": [true, false, null]
            },
            "isActive": {
                "type": "boolean",
                "description": "Whether calendar sync is active",
                "default": true,
                "examples": [true, false]
            },
            "syncDirection": {
                "type": ["string", "null"],
                "description": "Sync direction",
                "enum": ["bidirectional", "import", "export", null],
                "default": "bidirectional",
                "examples": ["bidirectional", "import", "export", null]
            },
            "lastSyncedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "Last successful sync time"
            },
            "syncError": {
                "type": ["string", "null"],
                "description": "Last sync error message",
                "maxLength": 1000,
                "examples": ["Invalid credentials", null]
            },
            "timezone": {
                "type": ["string", "null"],
                "description": "Calendar timezone (IANA format)",
                "examples": ["America/New_York", "Europe/London", "UTC", null]
            },
            "color": {
                "type": ["string", "null"],
                "description": "Calendar color (hex code)",
                "pattern": "^#[0-9A-Fa-f]{6}$",
                "examples": ["#4285F4", "#EA4335", null]
            },
            "accessToken": {
                "type": ["string", "null"],
                "description": "OAuth access token (encrypted)",
                "maxLength": 2000,
                "examples": [null]
            },
            "refreshToken": {
                "type": ["string", "null"],
                "description": "OAuth refresh token (encrypted)",
                "maxLength": 2000,
                "examples": [null]
            },
            "tokenExpiresAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When access token expires"
            },
            "webhookUrl": {
                "type": ["string", "null"],
                "format": "uri",
                "description": "Webhook URL for push notifications"
            },
            "webhookSecret": {
                "type": ["string", "null"],
                "description": "Webhook secret for verification",
                "maxLength": 255,
                "examples": [null]
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional calendar metadata",
                "additionalProperties": true,
                "examples": [{"readOnly": false, "selected": true}, null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When calendar was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When calendar was last updated"
            }
        },
        "required": ["isActive", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['calendar', 'scheduling', 'integration', 'sync', 'external'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- =============================================================================
-- Reminder - Appointment reminders
-- =============================================================================

INSERT INTO class_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'Reminder',
    'Appointment reminder with notification settings and delivery tracking.',
    'scheduling',
    $JSON${
        "type": "object",
        "description": "Appointment reminder",
        "properties": {
            "id": {
                "type": "string",
                "format": "uuid",
                "description": "Unique identifier for the reminder"
            },
            "appointmentId": {
                "type": "string",
                "format": "uuid",
                "description": "Associated appointment ID"
            },
            "userId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "User ID to remind"
            },
            "type": {
                "type": ["string", "null"],
                "description": "Reminder type",
                "enum": ["email", "sms", "push", "in_app", "call", "other", null],
                "examples": ["email", "sms", "push", null]
            },
            "triggerTime": {
                "type": "string",
                "format": "date-time",
                "description": "When reminder should be sent"
            },
            "triggerOffset": {
                "type": ["integer", "null"],
                "description": "Minutes before appointment to trigger",
                "examples": [15, 30, 60, 1440, null]
            },
            "status": {
                "type": "string",
                "description": "Reminder status",
                "enum": ["pending", "scheduled", "sent", "delivered", "failed", "cancelled"],
                "default": "pending",
                "examples": ["pending", "scheduled", "sent", "delivered"]
            },
            "subject": {
                "type": ["string", "null"],
                "description": "Reminder subject/title",
                "maxLength": 255,
                "examples": ["Appointment Reminder", "Upcoming: Consultation", null]
            },
            "message": {
                "type": ["string", "null"],
                "description": "Reminder message content",
                "maxLength": 2000,
                "examples": ["Your appointment is scheduled for tomorrow at 2:00 PM", null]
            },
            "templateId": {
                "type": ["string", "null"],
                "format": "uuid",
                "description": "Notification template ID"
            },
            "channel": {
                "type": ["string", "null"],
                "description": "Notification channel",
                "enum": ["email", "sms", "push", "in_app", "webhook", null],
                "examples": ["email", "sms", "push", null]
            },
            "sentAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When reminder was sent"
            },
            "deliveredAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When reminder was delivered"
            },
            "readAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When reminder was read"
            },
            "error": {
                "type": ["string", "null"],
                "description": "Error message if delivery failed",
                "maxLength": 1000,
                "examples": ["Invalid phone number", "Email bounced", null]
            },
            "retryCount": {
                "type": ["integer", "null"],
                "description": "Number of retry attempts",
                "minimum": 0,
                "default": 0,
                "examples": [0, 1, 3, null]
            },
            "maxRetries": {
                "type": ["integer", "null"],
                "description": "Maximum retry attempts",
                "minimum": 0,
                "default": 3,
                "examples": [3, 5, null]
            },
            "isRecurring": {
                "type": ["boolean", "null"],
                "description": "Whether reminder repeats",
                "default": false,
                "examples": [true, false, null]
            },
            "metadata": {
                "type": ["object", "null"],
                "description": "Additional reminder metadata",
                "additionalProperties": true,
                "examples": [{"priority": "high", "customFields": {}}, null]
            },
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "description": "When reminder was created"
            },
            "updatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When reminder was last updated"
            }
        },
        "required": ["appointmentId", "triggerTime", "status", "createdAt"]
    }$JSON$::jsonb,
    ARRAY['reminder', 'scheduling', 'notification', 'appointment', 'alert'],
    true,
    true
)
ON CONFLICT (tenant_id, category, name) DO NOTHING;

-- Log completion
DO $$
BEGIN
    RAISE NOTICE 'Scheduling class templates successfully created: Appointment, Availability, Calendar, Reminder';
END $$;
