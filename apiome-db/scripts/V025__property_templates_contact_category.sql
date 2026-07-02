-- Property Templates: Contact Category
-- These templates define common patterns for storing contact information
-- Property names are camelCase, alphanumeric only (a-zA-Z0-9)
-- Follows OpenAPI 3.1 / JSON Schema Draft 2020-12 standards

SET search_path TO apiome, public;

-- =============================================================================
-- EMAIL FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'email',
           'Email address.',
           'contact',
           '{
               "type": "string",
               "format": "email",
               "description": "Email address",
               "examples": ["john.doe@example.com", "contact@company.org", "info@domain.co.uk"],
               "maxLength": 254
           }',
           ARRAY['email', 'address', 'basic'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'emailNullable',
           'Optional email address.',
           'contact',
           '{
               "type": ["string", "null"],
               "format": "email",
               "description": "Optional email address",
               "examples": ["john.doe@example.com", null],
               "maxLength": 254
           }',
           ARRAY['email', 'address', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'emailVerified',
           'Email address with verification status.',
           'contact',
           '{
               "type": "object",
               "description": "Email with verification status",
               "properties": {
                   "address": {
                       "type": "string",
                       "format": "email",
                       "description": "Email address",
                       "maxLength": 254
                   },
                   "isVerified": {
                       "type": "boolean",
                       "description": "Whether email is verified",
                       "default": false
                   },
                   "verifiedAt": {
                       "type": ["string", "null"],
                       "format": "date-time",
                       "description": "When email was verified"
                   }
               },
               "required": ["address", "isVerified"],
               "examples": [
                   {"address": "john.doe@example.com", "isVerified": true, "verifiedAt": "2024-01-15T10:00:00Z"},
                   {"address": "new.user@example.com", "isVerified": false, "verifiedAt": null}
               ]
           }',
           ARRAY['email', 'verified', 'status', 'composite'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'emailType',
           'Type classification for an email address.',
           'contact',
           '{
               "type": "string",
               "description": "Type of email address",
               "enum": ["personal", "work", "school", "other"],
               "examples": ["personal", "work"],
               "default": "personal"
           }',
           ARRAY['email', 'type', 'enum', 'classification'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'labeledEmail',
           'Email address with type and label.',
           'contact',
           '{
               "type": "object",
               "description": "Email with type and label",
               "properties": {
                   "address": {
                       "type": "string",
                       "format": "email",
                       "description": "Email address",
                       "maxLength": 254
                   },
                   "type": {
                       "type": "string",
                       "description": "Email type",
                       "enum": ["personal", "work", "school", "other"],
                       "default": "personal"
                   },
                   "label": {
                       "type": ["string", "null"],
                       "description": "Custom label",
                       "maxLength": 100
                   },
                   "isPrimary": {
                       "type": "boolean",
                       "description": "Whether this is the primary email",
                       "default": false
                   }
               },
               "required": ["address"],
               "examples": [
                   {"address": "john@company.com", "type": "work", "label": "Main Office", "isPrimary": true},
                   {"address": "john.personal@gmail.com", "type": "personal", "label": null, "isPrimary": false}
               ]
           }',
           ARRAY['email', 'labeled', 'typed', 'composite'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'emailList',
           'Array of email addresses.',
           'contact',
           '{
               "type": "array",
               "description": "List of email addresses",
               "items": {
                   "type": "string",
                   "format": "email",
                   "maxLength": 254
               },
               "uniqueItems": true,
               "examples": [
                   ["john@example.com", "john.doe@company.com"],
                   ["support@company.com", "sales@company.com", "info@company.com"]
               ]
           }',
           ARRAY['email', 'list', 'array', 'multiple'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'emailContacts',
           'Array of typed email contacts.',
           'contact',
           '{
               "type": "array",
               "description": "List of typed email contacts",
               "items": {
                   "type": "object",
                   "properties": {
                       "address": {
                           "type": "string",
                           "format": "email",
                           "maxLength": 254
                       },
                       "type": {
                           "type": "string",
                           "enum": ["personal", "work", "school", "other"]
                       },
                       "label": {
                           "type": ["string", "null"]
                       },
                       "isPrimary": {
                           "type": "boolean",
                           "default": false
                       },
                       "isVerified": {
                           "type": "boolean",
                           "default": false
                       }
                   },
                   "required": ["address"]
               },
               "examples": [
                   [
                       {"address": "john@work.com", "type": "work", "label": null, "isPrimary": true, "isVerified": true},
                       {"address": "john@gmail.com", "type": "personal", "label": null, "isPrimary": false, "isVerified": true}
                   ]
               ]
           }',
           ARRAY['email', 'contacts', 'array', 'typed'],
           true,
           true
       );

-- =============================================================================
-- PHONE NUMBER FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'phone',
           'Phone number in E.164 or local format.',
           'contact',
           '{
               "type": "string",
               "description": "Phone number",
               "examples": ["+14155551234", "+442071234567", "(415) 555-1234", "020 7123 4567"],
               "minLength": 1,
               "maxLength": 30
           }',
           ARRAY['phone', 'number', 'basic'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'phoneNullable',
           'Optional phone number.',
           'contact',
           '{
               "type": ["string", "null"],
               "description": "Optional phone number",
               "examples": ["+14155551234", null],
               "maxLength": 30
           }',
           ARRAY['phone', 'number', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'phoneE164',
           'Phone number in E.164 international format.',
           'contact',
           '{
               "type": "string",
               "description": "Phone number in E.164 format",
               "examples": ["+14155551234", "+442071234567", "+33123456789", "+81312345678"],
               "pattern": "^\\+[1-9]\\d{1,14}$",
               "minLength": 8,
               "maxLength": 16
           }',
           ARRAY['phone', 'e164', 'international', 'standard'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'phoneUS',
           'US phone number.',
           'contact',
           '{
               "type": "string",
               "description": "US phone number",
               "examples": ["(415) 555-1234", "415-555-1234", "4155551234", "+1 415 555 1234"],
               "pattern": "^(\\+1\\s?)?(\\([0-9]{3}\\)|[0-9]{3})[\\s.-]?[0-9]{3}[\\s.-]?[0-9]{4}$",
               "maxLength": 20
           }',
           ARRAY['phone', 'us', 'domestic', 'format'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'phoneUK',
           'UK phone number.',
           'contact',
           '{
               "type": "string",
               "description": "UK phone number",
               "examples": ["020 7123 4567", "07700 900123", "+44 20 7123 4567", "+44 7700 900123"],
               "maxLength": 20
           }',
           ARRAY['phone', 'uk', 'domestic', 'format'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'phoneType',
           'Type classification for a phone number.',
           'contact',
           '{
               "type": "string",
               "description": "Type of phone number",
               "enum": ["mobile", "home", "work", "fax", "pager", "main", "other"],
               "examples": ["mobile", "work", "home"],
               "default": "mobile"
           }',
           ARRAY['phone', 'type', 'enum', 'classification'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'phoneInfo',
           'Complete phone number with type and formatting.',
           'contact',
           '{
               "type": "object",
               "description": "Phone number with metadata",
               "properties": {
                   "number": {
                       "type": "string",
                       "description": "Phone number",
                       "maxLength": 30
                   },
                   "e164": {
                       "type": ["string", "null"],
                       "description": "E.164 formatted number",
                       "pattern": "^\\+[1-9]\\d{1,14}$"
                   },
                   "type": {
                       "type": "string",
                       "description": "Phone type",
                       "enum": ["mobile", "home", "work", "fax", "pager", "main", "other"],
                       "default": "mobile"
                   },
                   "label": {
                       "type": ["string", "null"],
                       "description": "Custom label",
                       "maxLength": 100
                   },
                   "countryCode": {
                       "type": ["string", "null"],
                       "description": "ISO country code",
                       "pattern": "^[A-Z]{2}$"
                   },
                   "isPrimary": {
                       "type": "boolean",
                       "description": "Whether this is the primary phone",
                       "default": false
                   },
                   "isVerified": {
                       "type": "boolean",
                       "description": "Whether phone is verified",
                       "default": false
                   },
                   "canSms": {
                       "type": ["boolean", "null"],
                       "description": "Whether phone can receive SMS"
                   }
               },
               "required": ["number"],
               "examples": [
                   {
                       "number": "(415) 555-1234",
                       "e164": "+14155551234",
                       "type": "mobile",
                       "label": null,
                       "countryCode": "US",
                       "isPrimary": true,
                       "isVerified": true,
                       "canSms": true
                   }
               ]
           }',
           ARRAY['phone', 'info', 'complete', 'composite'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'labeledPhone',
           'Phone number with type and label.',
           'contact',
           '{
               "type": "object",
               "description": "Phone with type and label",
               "properties": {
                   "number": {
                       "type": "string",
                       "description": "Phone number",
                       "maxLength": 30
                   },
                   "type": {
                       "type": "string",
                       "description": "Phone type",
                       "enum": ["mobile", "home", "work", "fax", "pager", "main", "other"],
                       "default": "mobile"
                   },
                   "label": {
                       "type": ["string", "null"],
                       "description": "Custom label",
                       "maxLength": 100
                   },
                   "isPrimary": {
                       "type": "boolean",
                       "description": "Whether this is the primary phone",
                       "default": false
                   }
               },
               "required": ["number"],
               "examples": [
                   {"number": "+14155551234", "type": "mobile", "label": null, "isPrimary": true},
                   {"number": "+14155559876", "type": "work", "label": "Direct Line", "isPrimary": false}
               ]
           }',
           ARRAY['phone', 'labeled', 'typed', 'composite'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'phoneList',
           'Array of phone numbers.',
           'contact',
           '{
               "type": "array",
               "description": "List of phone numbers",
               "items": {
                   "type": "string",
                   "maxLength": 30
               },
               "examples": [
                   ["+14155551234", "+14155559876"],
                   ["(415) 555-1234", "(415) 555-9876"]
               ]
           }',
           ARRAY['phone', 'list', 'array', 'multiple'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'phoneContacts',
           'Array of typed phone contacts.',
           'contact',
           '{
               "type": "array",
               "description": "List of typed phone contacts",
               "items": {
                   "type": "object",
                   "properties": {
                       "number": {
                           "type": "string",
                           "maxLength": 30
                       },
                       "type": {
                           "type": "string",
                           "enum": ["mobile", "home", "work", "fax", "pager", "main", "other"]
                       },
                       "label": {
                           "type": ["string", "null"]
                       },
                       "isPrimary": {
                           "type": "boolean",
                           "default": false
                       }
                   },
                   "required": ["number"]
               },
               "examples": [
                   [
                       {"number": "+14155551234", "type": "mobile", "label": null, "isPrimary": true},
                       {"number": "+14155559876", "type": "work", "label": "Office", "isPrimary": false}
                   ]
               ]
           }',
           ARRAY['phone', 'contacts', 'array', 'typed'],
           true,
           true
       );

-- =============================================================================
-- MOBILE PHONE FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'mobile',
           'Mobile/cell phone number.',
           'contact',
           '{
               "type": "string",
               "description": "Mobile phone number",
               "examples": ["+14155551234", "+447700900123", "415-555-1234"],
               "maxLength": 30
           }',
           ARRAY['mobile', 'cell', 'phone', 'basic'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'mobileNullable',
           'Optional mobile phone number.',
           'contact',
           '{
               "type": ["string", "null"],
               "description": "Optional mobile phone number",
               "examples": ["+14155551234", null],
               "maxLength": 30
           }',
           ARRAY['mobile', 'cell', 'phone', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'mobileE164',
           'Mobile phone number in E.164 format.',
           'contact',
           '{
               "type": "string",
               "description": "Mobile phone in E.164 format",
               "examples": ["+14155551234", "+447700900123", "+33612345678"],
               "pattern": "^\\+[1-9]\\d{1,14}$",
               "minLength": 8,
               "maxLength": 16
           }',
           ARRAY['mobile', 'e164', 'international', 'standard'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'mobileVerified',
           'Mobile phone with verification status.',
           'contact',
           '{
               "type": "object",
               "description": "Mobile phone with verification",
               "properties": {
                   "number": {
                       "type": "string",
                       "description": "Mobile number",
                       "maxLength": 30
                   },
                   "e164": {
                       "type": ["string", "null"],
                       "description": "E.164 formatted number"
                   },
                   "isVerified": {
                       "type": "boolean",
                       "description": "Whether mobile is verified",
                       "default": false
                   },
                   "verifiedAt": {
                       "type": ["string", "null"],
                       "format": "date-time",
                       "description": "When mobile was verified"
                   },
                   "canSms": {
                       "type": "boolean",
                       "description": "Can receive SMS",
                       "default": true
                   },
                   "canWhatsApp": {
                       "type": ["boolean", "null"],
                       "description": "Has WhatsApp"
                   }
               },
               "required": ["number"],
               "examples": [
                   {
                       "number": "+14155551234",
                       "e164": "+14155551234",
                       "isVerified": true,
                       "verifiedAt": "2024-01-15T10:00:00Z",
                       "canSms": true,
                       "canWhatsApp": true
                   }
               ]
           }',
           ARRAY['mobile', 'verified', 'sms', 'composite'],
           true,
           true
       );

-- =============================================================================
-- FAX FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'fax',
           'Fax number.',
           'contact',
           '{
               "type": "string",
               "description": "Fax number",
               "examples": ["+14155551234", "(415) 555-1234", "+442071234567"],
               "maxLength": 30
           }',
           ARRAY['fax', 'number', 'basic'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'faxNullable',
           'Optional fax number.',
           'contact',
           '{
               "type": ["string", "null"],
               "description": "Optional fax number",
               "examples": ["+14155551234", null],
               "maxLength": 30
           }',
           ARRAY['fax', 'number', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'faxE164',
           'Fax number in E.164 format.',
           'contact',
           '{
               "type": "string",
               "description": "Fax number in E.164 format",
               "examples": ["+14155551234", "+442071234567"],
               "pattern": "^\\+[1-9]\\d{1,14}$",
               "minLength": 8,
               "maxLength": 16
           }',
           ARRAY['fax', 'e164', 'international', 'standard'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'labeledFax',
           'Fax number with label.',
           'contact',
           '{
               "type": "object",
               "description": "Fax with label",
               "properties": {
                   "number": {
                       "type": "string",
                       "description": "Fax number",
                       "maxLength": 30
                   },
                   "label": {
                       "type": ["string", "null"],
                       "description": "Custom label",
                       "maxLength": 100
                   },
                   "isPrimary": {
                       "type": "boolean",
                       "description": "Whether this is the primary fax",
                       "default": false
                   }
               },
               "required": ["number"],
               "examples": [
                   {"number": "+14155551234", "label": "Main Office", "isPrimary": true},
                   {"number": "+14155559876", "label": "Billing Dept", "isPrimary": false}
               ]
           }',
           ARRAY['fax', 'labeled', 'composite'],
           true,
           true
       );

-- =============================================================================
-- URL AND WEBSITE FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'website',
           'Website URL.',
           'contact',
           '{
               "type": "string",
               "format": "uri",
               "description": "Website URL",
               "examples": ["https://www.example.com", "https://company.io", "https://blog.example.org"],
               "maxLength": 2000
           }',
           ARRAY['website', 'url', 'web', 'basic'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'websiteNullable',
           'Optional website URL.',
           'contact',
           '{
               "type": ["string", "null"],
               "format": "uri",
               "description": "Optional website URL",
               "examples": ["https://www.example.com", null],
               "maxLength": 2000
           }',
           ARRAY['website', 'url', 'web', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'websiteType',
           'Type classification for a website.',
           'contact',
           '{
               "type": "string",
               "description": "Type of website",
               "enum": ["personal", "work", "blog", "portfolio", "company", "other"],
               "examples": ["personal", "company"],
               "default": "personal"
           }',
           ARRAY['website', 'type', 'enum', 'classification'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'labeledWebsite',
           'Website URL with type and label.',
           'contact',
           '{
               "type": "object",
               "description": "Website with type and label",
               "properties": {
                   "url": {
                       "type": "string",
                       "format": "uri",
                       "description": "Website URL",
                       "maxLength": 2000
                   },
                   "type": {
                       "type": "string",
                       "description": "Website type",
                       "enum": ["personal", "work", "blog", "portfolio", "company", "other"],
                       "default": "personal"
                   },
                   "label": {
                       "type": ["string", "null"],
                       "description": "Custom label",
                       "maxLength": 100
                   },
                   "isPrimary": {
                       "type": "boolean",
                       "description": "Whether this is the primary website",
                       "default": false
                   }
               },
               "required": ["url"],
               "examples": [
                   {"url": "https://www.company.com", "type": "company", "label": "Corporate Site", "isPrimary": true},
                   {"url": "https://blog.example.com", "type": "blog", "label": null, "isPrimary": false}
               ]
           }',
           ARRAY['website', 'labeled', 'typed', 'composite'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'websiteList',
           'Array of website URLs.',
           'contact',
           '{
               "type": "array",
               "description": "List of website URLs",
               "items": {
                   "type": "string",
                   "format": "uri",
                   "maxLength": 2000
               },
               "uniqueItems": true,
               "examples": [
                   ["https://www.example.com", "https://blog.example.com"],
                   ["https://company.com", "https://docs.company.com"]
               ]
           }',
           ARRAY['website', 'list', 'array', 'multiple'],
           true,
           true
       );

-- =============================================================================
-- SOCIAL MEDIA FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'socialHandle',
           'Social media handle/username.',
           'contact',
           '{
               "type": "string",
               "description": "Social media handle",
               "examples": ["johndoe", "@johndoe", "john.doe"],
               "minLength": 1,
               "maxLength": 100
           }',
           ARRAY['social', 'handle', 'username', 'basic'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'socialPlatform',
           'Social media platform type.',
           'contact',
           '{
               "type": "string",
               "description": "Social media platform",
               "enum": ["twitter", "x", "facebook", "instagram", "linkedin", "github", "youtube", "tiktok", "snapchat", "pinterest", "reddit", "discord", "telegram", "whatsapp", "mastodon", "threads", "bluesky", "other"],
               "examples": ["twitter", "linkedin", "github"]
           }',
           ARRAY['social', 'platform', 'enum', 'type'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'socialProfile',
           'Social media profile with platform and handle.',
           'contact',
           '{
               "type": "object",
               "description": "Social media profile",
               "properties": {
                   "platform": {
                       "type": "string",
                       "description": "Platform name",
                       "enum": ["twitter", "x", "facebook", "instagram", "linkedin", "github", "youtube", "tiktok", "snapchat", "pinterest", "reddit", "discord", "telegram", "whatsapp", "mastodon", "threads", "bluesky", "other"]
                   },
                   "handle": {
                       "type": "string",
                       "description": "Username or handle",
                       "maxLength": 100
                   },
                   "url": {
                       "type": ["string", "null"],
                       "format": "uri",
                       "description": "Full profile URL"
                   },
                   "isPrimary": {
                       "type": "boolean",
                       "description": "Whether this is the primary profile",
                       "default": false
                   }
               },
               "required": ["platform", "handle"],
               "examples": [
                   {"platform": "twitter", "handle": "johndoe", "url": "https://twitter.com/johndoe", "isPrimary": true},
                   {"platform": "linkedin", "handle": "john-doe", "url": "https://linkedin.com/in/john-doe", "isPrimary": false}
               ]
           }',
           ARRAY['social', 'profile', 'handle', 'composite'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'socialProfiles',
           'Array of social media profiles.',
           'contact',
           '{
               "type": "array",
               "description": "List of social media profiles",
               "items": {
                   "type": "object",
                   "properties": {
                       "platform": {
                           "type": "string",
                           "enum": ["twitter", "x", "facebook", "instagram", "linkedin", "github", "youtube", "tiktok", "snapchat", "pinterest", "reddit", "discord", "telegram", "whatsapp", "mastodon", "threads", "bluesky", "other"]
                       },
                       "handle": {
                           "type": "string",
                           "maxLength": 100
                       },
                       "url": {
                           "type": ["string", "null"],
                           "format": "uri"
                       }
                   },
                   "required": ["platform", "handle"]
               },
               "examples": [
                   [
                       {"platform": "twitter", "handle": "johndoe", "url": "https://twitter.com/johndoe"},
                       {"platform": "github", "handle": "johndoe", "url": "https://github.com/johndoe"},
                       {"platform": "linkedin", "handle": "john-doe", "url": "https://linkedin.com/in/john-doe"}
                   ]
               ]
           }',
           ARRAY['social', 'profiles', 'array', 'multiple'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'twitter',
           'Twitter/X handle.',
           'contact',
           '{
               "type": ["string", "null"],
               "description": "Twitter/X handle (without @)",
               "examples": ["johndoe", "company", null],
               "pattern": "^[a-zA-Z0-9_]{1,15}$",
               "maxLength": 15
           }',
           ARRAY['twitter', 'x', 'social', 'handle'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'linkedin',
           'LinkedIn profile identifier.',
           'contact',
           '{
               "type": ["string", "null"],
               "description": "LinkedIn profile ID or vanity URL",
               "examples": ["john-doe", "johndoe123", "in/john-doe", null],
               "maxLength": 100
           }',
           ARRAY['linkedin', 'social', 'professional'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'github',
           'GitHub username.',
           'contact',
           '{
               "type": ["string", "null"],
               "description": "GitHub username",
               "examples": ["johndoe", "company-org", null],
               "pattern": "^[a-zA-Z0-9]([a-zA-Z0-9-]{0,37}[a-zA-Z0-9])?$",
               "maxLength": 39
           }',
           ARRAY['github', 'social', 'developer'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'instagram',
           'Instagram handle.',
           'contact',
           '{
               "type": ["string", "null"],
               "description": "Instagram handle (without @)",
               "examples": ["johndoe", "company.official", null],
               "pattern": "^[a-zA-Z0-9_.]{1,30}$",
               "maxLength": 30
           }',
           ARRAY['instagram', 'social', 'handle'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'facebook',
           'Facebook profile or page identifier.',
           'contact',
           '{
               "type": ["string", "null"],
               "description": "Facebook profile or page ID",
               "examples": ["johndoe", "companypage", "100001234567890", null],
               "maxLength": 100
           }',
           ARRAY['facebook', 'social', 'handle'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'youtube',
           'YouTube channel identifier.',
           'contact',
           '{
               "type": ["string", "null"],
               "description": "YouTube channel ID or handle",
               "examples": ["@johndoe", "UCxxxxxxxxxxxxxxxxxx", "johndoe", null],
               "maxLength": 100
           }',
           ARRAY['youtube', 'social', 'video'],
           true,
           true
       );

-- =============================================================================
-- MESSENGER AND CHAT FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'messengerType',
           'Instant messenger platform type.',
           'contact',
           '{
               "type": "string",
               "description": "Messenger platform",
               "enum": ["whatsapp", "telegram", "signal", "slack", "discord", "skype", "wechat", "line", "viber", "messenger", "teams", "zoom", "other"],
               "examples": ["whatsapp", "slack", "telegram"]
           }',
           ARRAY['messenger', 'chat', 'type', 'enum'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'messengerContact',
           'Instant messenger contact details.',
           'contact',
           '{
               "type": "object",
               "description": "Messenger contact",
               "properties": {
                   "platform": {
                       "type": "string",
                       "description": "Messenger platform",
                       "enum": ["whatsapp", "telegram", "signal", "slack", "discord", "skype", "wechat", "line", "viber", "messenger", "teams", "zoom", "other"]
                   },
                   "handle": {
                       "type": "string",
                       "description": "Username, phone, or ID",
                       "maxLength": 100
                   },
                   "displayName": {
                       "type": ["string", "null"],
                       "description": "Display name on platform",
                       "maxLength": 100
                   },
                   "isPrimary": {
                       "type": "boolean",
                       "description": "Whether this is the primary messenger",
                       "default": false
                   }
               },
               "required": ["platform", "handle"],
               "examples": [
                   {"platform": "whatsapp", "handle": "+14155551234", "displayName": null, "isPrimary": true},
                   {"platform": "telegram", "handle": "@johndoe", "displayName": "John Doe", "isPrimary": false},
                   {"platform": "slack", "handle": "john.doe", "displayName": "John Doe", "isPrimary": false}
               ]
           }',
           ARRAY['messenger', 'chat', 'contact', 'composite'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'messengerContacts',
           'Array of messenger contacts.',
           'contact',
           '{
               "type": "array",
               "description": "List of messenger contacts",
               "items": {
                   "type": "object",
                   "properties": {
                       "platform": {
                           "type": "string",
                           "enum": ["whatsapp", "telegram", "signal", "slack", "discord", "skype", "wechat", "line", "viber", "messenger", "teams", "zoom", "other"]
                       },
                       "handle": {
                           "type": "string",
                           "maxLength": 100
                       },
                       "displayName": {
                           "type": ["string", "null"]
                       }
                   },
                   "required": ["platform", "handle"]
               },
               "examples": [
                   [
                       {"platform": "whatsapp", "handle": "+14155551234", "displayName": null},
                       {"platform": "telegram", "handle": "@johndoe", "displayName": "John"},
                       {"platform": "slack", "handle": "john.doe", "displayName": "John Doe"}
                   ]
               ]
           }',
           ARRAY['messenger', 'chat', 'contacts', 'array'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'whatsapp',
           'WhatsApp phone number.',
           'contact',
           '{
               "type": ["string", "null"],
               "description": "WhatsApp phone number (E.164 format preferred)",
               "examples": ["+14155551234", "+447700900123", null],
               "maxLength": 20
           }',
           ARRAY['whatsapp', 'messenger', 'phone'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'telegram',
           'Telegram username.',
           'contact',
           '{
               "type": ["string", "null"],
               "description": "Telegram username (without @)",
               "examples": ["johndoe", "company_bot", null],
               "pattern": "^[a-zA-Z][a-zA-Z0-9_]{4,31}$",
               "maxLength": 32
           }',
           ARRAY['telegram', 'messenger', 'handle'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'skype',
           'Skype username.',
           'contact',
           '{
               "type": ["string", "null"],
               "description": "Skype username",
               "examples": ["john.doe", "live:johndoe", null],
               "maxLength": 100
           }',
           ARRAY['skype', 'messenger', 'handle'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'slack',
           'Slack member ID or display name.',
           'contact',
           '{
               "type": ["string", "null"],
               "description": "Slack member ID or display name",
               "examples": ["U01234ABCDE", "john.doe", null],
               "maxLength": 100
           }',
           ARRAY['slack', 'messenger', 'workspace'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'discord',
           'Discord username.',
           'contact',
           '{
               "type": ["string", "null"],
               "description": "Discord username",
               "examples": ["johndoe", "john.doe", null],
               "maxLength": 32
           }',
           ARRAY['discord', 'messenger', 'gaming'],
           true,
           true
       );

-- =============================================================================
-- COMPOSITE CONTACT OBJECTS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'contactInfo',
           'Basic contact information with email and phone.',
           'contact',
           '{
               "type": "object",
               "description": "Basic contact information",
               "properties": {
                   "email": {
                       "type": ["string", "null"],
                       "format": "email",
                       "description": "Email address"
                   },
                   "phone": {
                       "type": ["string", "null"],
                       "description": "Phone number"
                   },
                   "mobile": {
                       "type": ["string", "null"],
                       "description": "Mobile phone number"
                   },
                   "fax": {
                       "type": ["string", "null"],
                       "description": "Fax number"
                   },
                   "website": {
                       "type": ["string", "null"],
                       "format": "uri",
                       "description": "Website URL"
                   }
               },
               "examples": [
                   {
                       "email": "john@example.com",
                       "phone": "+14155551234",
                       "mobile": "+14155559876",
                       "fax": null,
                       "website": "https://johndoe.com"
                   }
               ]
           }',
           ARRAY['contact', 'info', 'basic', 'composite'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'contactInfoExtended',
           'Extended contact information with multiple entries.',
           'contact',
           '{
               "type": "object",
               "description": "Extended contact information",
               "properties": {
                   "emails": {
                       "type": "array",
                       "description": "Email addresses",
                       "items": {
                           "type": "object",
                           "properties": {
                               "address": {"type": "string", "format": "email"},
                               "type": {"type": "string", "enum": ["personal", "work", "school", "other"]},
                               "isPrimary": {"type": "boolean", "default": false},
                               "isVerified": {"type": "boolean", "default": false}
                           },
                           "required": ["address"]
                       }
                   },
                   "phones": {
                       "type": "array",
                       "description": "Phone numbers",
                       "items": {
                           "type": "object",
                           "properties": {
                               "number": {"type": "string"},
                               "type": {"type": "string", "enum": ["mobile", "home", "work", "fax", "pager", "main", "other"]},
                               "isPrimary": {"type": "boolean", "default": false}
                           },
                           "required": ["number"]
                       }
                   },
                   "websites": {
                       "type": "array",
                       "description": "Websites",
                       "items": {
                           "type": "object",
                           "properties": {
                               "url": {"type": "string", "format": "uri"},
                               "type": {"type": "string", "enum": ["personal", "work", "blog", "portfolio", "company", "other"]},
                               "isPrimary": {"type": "boolean", "default": false}
                           },
                           "required": ["url"]
                       }
                   },
                   "socialProfiles": {
                       "type": "array",
                       "description": "Social media profiles",
                       "items": {
                           "type": "object",
                           "properties": {
                               "platform": {"type": "string"},
                               "handle": {"type": "string"},
                               "url": {"type": ["string", "null"], "format": "uri"}
                           },
                           "required": ["platform", "handle"]
                       }
                   },
                   "messengers": {
                       "type": "array",
                       "description": "Messenger contacts",
                       "items": {
                           "type": "object",
                           "properties": {
                               "platform": {"type": "string"},
                               "handle": {"type": "string"}
                           },
                           "required": ["platform", "handle"]
                       }
                   }
               },
               "examples": [
                   {
                       "emails": [
                           {"address": "john@work.com", "type": "work", "isPrimary": true, "isVerified": true},
                           {"address": "john@gmail.com", "type": "personal", "isPrimary": false, "isVerified": true}
                       ],
                       "phones": [
                           {"number": "+14155551234", "type": "mobile", "isPrimary": true},
                           {"number": "+14155559876", "type": "work", "isPrimary": false}
                       ],
                       "websites": [
                           {"url": "https://johndoe.com", "type": "personal", "isPrimary": true}
                       ],
                       "socialProfiles": [
                           {"platform": "linkedin", "handle": "john-doe", "url": "https://linkedin.com/in/john-doe"}
                       ],
                       "messengers": [
                           {"platform": "slack", "handle": "john.doe"}
                       ]
                   }
               ]
           }',
           ARRAY['contact', 'info', 'extended', 'complete', 'composite'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'businessContact',
           'Business/professional contact information.',
           'contact',
           '{
               "type": "object",
               "description": "Business contact information",
               "properties": {
                   "company": {
                       "type": ["string", "null"],
                       "description": "Company name",
                       "maxLength": 200
                   },
                   "department": {
                       "type": ["string", "null"],
                       "description": "Department",
                       "maxLength": 100
                   },
                   "title": {
                       "type": ["string", "null"],
                       "description": "Job title",
                       "maxLength": 100
                   },
                   "email": {
                       "type": ["string", "null"],
                       "format": "email",
                       "description": "Work email"
                   },
                   "phone": {
                       "type": ["string", "null"],
                       "description": "Work phone"
                   },
                   "extension": {
                       "type": ["string", "null"],
                       "description": "Phone extension",
                       "maxLength": 10
                   },
                   "mobile": {
                       "type": ["string", "null"],
                       "description": "Work mobile"
                   },
                   "fax": {
                       "type": ["string", "null"],
                       "description": "Fax number"
                   },
                   "website": {
                       "type": ["string", "null"],
                       "format": "uri",
                       "description": "Company website"
                   },
                   "linkedin": {
                       "type": ["string", "null"],
                       "description": "LinkedIn profile"
                   }
               },
               "examples": [
                   {
                       "company": "Acme Corp",
                       "department": "Engineering",
                       "title": "Senior Developer",
                       "email": "john.doe@acme.com",
                       "phone": "+14155551234",
                       "extension": "1234",
                       "mobile": "+14155559876",
                       "fax": "+14155550000",
                       "website": "https://www.acme.com",
                       "linkedin": "john-doe"
                   }
               ]
           }',
           ARRAY['contact', 'business', 'professional', 'work', 'composite'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'emergencyContact',
           'Emergency contact information.',
           'contact',
           '{
               "type": "object",
               "description": "Emergency contact",
               "properties": {
                   "name": {
                       "type": "string",
                       "description": "Contact name",
                       "maxLength": 200
                   },
                   "relationship": {
                       "type": "string",
                       "description": "Relationship to person",
                       "enum": ["spouse", "partner", "parent", "child", "sibling", "relative", "friend", "colleague", "neighbor", "other"]
                   },
                   "phone": {
                       "type": "string",
                       "description": "Primary phone number",
                       "maxLength": 30
                   },
                   "alternatePhone": {
                       "type": ["string", "null"],
                       "description": "Alternate phone number",
                       "maxLength": 30
                   },
                   "email": {
                       "type": ["string", "null"],
                       "format": "email",
                       "description": "Email address"
                   },
                   "isPrimary": {
                       "type": "boolean",
                       "description": "Whether this is the primary emergency contact",
                       "default": false
                   },
                   "notes": {
                       "type": ["string", "null"],
                       "description": "Additional notes",
                       "maxLength": 500
                   }
               },
               "required": ["name", "relationship", "phone"],
               "examples": [
                   {
                       "name": "Jane Doe",
                       "relationship": "spouse",
                       "phone": "+14155551234",
                       "alternatePhone": "+14155559876",
                       "email": "jane.doe@example.com",
                       "isPrimary": true,
                       "notes": "Available 9am-6pm weekdays"
                   }
               ]
           }',
           ARRAY['contact', 'emergency', 'safety', 'composite'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'emergencyContacts',
           'Array of emergency contacts.',
           'contact',
           '{
               "type": "array",
               "description": "List of emergency contacts",
               "items": {
                   "type": "object",
                   "properties": {
                       "name": {"type": "string", "maxLength": 200},
                       "relationship": {"type": "string", "enum": ["spouse", "partner", "parent", "child", "sibling", "relative", "friend", "colleague", "neighbor", "other"]},
                       "phone": {"type": "string", "maxLength": 30},
                       "alternatePhone": {"type": ["string", "null"]},
                       "email": {"type": ["string", "null"], "format": "email"},
                       "isPrimary": {"type": "boolean", "default": false}
                   },
                   "required": ["name", "relationship", "phone"]
               },
               "examples": [
                   [
                       {"name": "Jane Doe", "relationship": "spouse", "phone": "+14155551234", "alternatePhone": null, "email": "jane@example.com", "isPrimary": true},
                       {"name": "John Doe Sr", "relationship": "parent", "phone": "+14155559999", "alternatePhone": null, "email": null, "isPrimary": false}
                   ]
               ]
           }',
           ARRAY['contact', 'emergency', 'array', 'safety'],
           true,
           true
       );

-- =============================================================================
-- CONTACT PREFERENCES
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'contactPreference',
           'Preferred method of contact.',
           'contact',
           '{
               "type": "string",
               "description": "Preferred contact method",
               "enum": ["email", "phone", "sms", "whatsapp", "mail", "any", "none"],
               "examples": ["email", "phone"],
               "default": "email"
           }',
           ARRAY['contact', 'preference', 'method', 'enum'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'contactPreferences',
           'Detailed contact preferences.',
           'contact',
           '{
               "type": "object",
               "description": "Contact preferences",
               "properties": {
                   "preferredMethod": {
                       "type": "string",
                       "description": "Preferred contact method",
                       "enum": ["email", "phone", "sms", "whatsapp", "mail", "any"],
                       "default": "email"
                   },
                   "preferredTime": {
                       "type": ["string", "null"],
                       "description": "Preferred time to contact",
                       "enum": ["morning", "afternoon", "evening", "anytime", null]
                   },
                   "preferredDays": {
                       "type": ["array", "null"],
                       "description": "Preferred days to contact",
                       "items": {
                           "type": "string",
                           "enum": ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
                       }
                   },
                   "doNotContact": {
                       "type": "boolean",
                       "description": "Do not contact flag",
                       "default": false
                   },
                   "marketingOptIn": {
                       "type": "boolean",
                       "description": "Opted in to marketing",
                       "default": false
                   },
                   "smsOptIn": {
                       "type": "boolean",
                       "description": "Opted in to SMS",
                       "default": false
                   },
                   "notes": {
                       "type": ["string", "null"],
                       "description": "Contact notes",
                       "maxLength": 500
                   }
               },
               "examples": [
                   {
                       "preferredMethod": "email",
                       "preferredTime": "morning",
                       "preferredDays": ["monday", "tuesday", "wednesday", "thursday", "friday"],
                       "doNotContact": false,
                       "marketingOptIn": true,
                       "smsOptIn": false,
                       "notes": null
                   }
               ]
           }',
           ARRAY['contact', 'preferences', 'settings', 'composite'],
           true,
           true
       );

-- =============================================================================
-- COUNTRY CALLING CODE FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'callingCode',
           'International calling code.',
           'contact',
           '{
               "type": "string",
               "description": "International calling code",
               "examples": ["+1", "+44", "+33", "+81", "+86"],
               "pattern": "^\\+[0-9]{1,4}$",
               "maxLength": 5
           }',
           ARRAY['calling', 'code', 'international', 'phone'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'countryCallingCode',
           'Country with its calling code.',
           'contact',
           '{
               "type": "object",
               "description": "Country calling code",
               "properties": {
                   "country": {
                       "type": "string",
                       "description": "Country name"
                   },
                   "countryCode": {
                       "type": "string",
                       "description": "ISO 3166-1 alpha-2 code",
                       "pattern": "^[A-Z]{2}$"
                   },
                   "callingCode": {
                       "type": "string",
                       "description": "Calling code with +",
                       "pattern": "^\\+[0-9]{1,4}$"
                   }
               },
               "required": ["countryCode", "callingCode"],
               "examples": [
                   {"country": "United States", "countryCode": "US", "callingCode": "+1"},
                   {"country": "United Kingdom", "countryCode": "GB", "callingCode": "+44"},
                   {"country": "Japan", "countryCode": "JP", "callingCode": "+81"}
               ]
           }',
           ARRAY['country', 'calling', 'code', 'composite'],
           true,
           true
       );

-- =============================================================================
-- PHONE EXTENSION FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'phoneExtension',
           'Phone extension number.',
           'contact',
           '{
               "type": ["string", "null"],
               "description": "Phone extension",
               "examples": ["1234", "5678", "x100", null],
               "pattern": "^[xX]?[0-9]{1,10}$",
               "maxLength": 11
           }',
           ARRAY['phone', 'extension', 'pbx'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'phoneWithExtension',
           'Phone number with extension.',
           'contact',
           '{
               "type": "object",
               "description": "Phone with extension",
               "properties": {
                   "number": {
                       "type": "string",
                       "description": "Phone number",
                       "maxLength": 30
                   },
                   "extension": {
                       "type": ["string", "null"],
                       "description": "Extension number",
                       "maxLength": 10
                   }
               },
               "required": ["number"],
               "examples": [
                   {"number": "+14155551234", "extension": "5678"},
                   {"number": "(415) 555-1234", "extension": null}
               ]
           }',
           ARRAY['phone', 'extension', 'composite'],
           true,
           true
       );