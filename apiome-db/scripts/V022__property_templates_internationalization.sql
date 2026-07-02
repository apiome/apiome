-- Property Templates: Internationalization (i18n) Category
-- These templates define common patterns for localization, language, and regional settings
-- Property names are camelCase, alphanumeric only (a-zA-Z0-9)
-- Follows OpenAPI 3.1 / JSON Schema Draft 2020-12 standards

SET search_path TO apiome, public;

-- =============================================================================
-- LANGUAGE FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'language',
           'ISO 639-1 two-letter language code.',
           'i18n',
           '{
               "type": "string",
               "description": "ISO 639-1 language code",
               "examples": ["en", "es", "fr", "de", "ja", "zh", "ar", "pt"],
               "pattern": "^[a-z]{2}$",
               "minLength": 2,
               "maxLength": 2
           }',
           ARRAY['language', 'iso639', 'code'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'language3',
           'ISO 639-2/T three-letter language code.',
           'i18n',
           '{
               "type": "string",
               "description": "ISO 639-2/T language code",
               "examples": ["eng", "spa", "fra", "deu", "jpn", "zho", "ara", "por"],
               "pattern": "^[a-z]{3}$",
               "minLength": 3,
               "maxLength": 3
           }',
           ARRAY['language', 'iso639', 'code', 'alpha3'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'languageTag',
           'IETF BCP 47 language tag with optional region and script.',
           'i18n',
           '{
               "type": "string",
               "description": "IETF BCP 47 language tag",
               "examples": ["en", "en-US", "en-GB", "zh-Hans", "zh-Hant-TW", "pt-BR", "sr-Latn"],
               "pattern": "^[a-zA-Z]{2,3}(-[a-zA-Z]{4})?(-[a-zA-Z]{2}|[0-9]{3})?(-[a-zA-Z0-9]{5,8})*$",
               "minLength": 2,
               "maxLength": 35
           }',
           ARRAY['language', 'bcp47', 'ietf', 'tag'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'languageName',
           'Human-readable language name.',
           'i18n',
           '{
               "type": "string",
               "description": "Language name",
               "examples": ["English", "Spanish", "French", "German", "Japanese", "Chinese", "Arabic"],
               "minLength": 1,
               "maxLength": 100
           }',
           ARRAY['language', 'name', 'display'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'languageNativeName',
           'Language name in its native form.',
           'i18n',
           '{
               "type": "string",
               "description": "Language name in native script",
               "examples": ["English", "Español", "Français", "Deutsch", "日本語", "中文", "العربية"],
               "minLength": 1,
               "maxLength": 100
           }',
           ARRAY['language', 'name', 'native', 'display'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'languageInfo',
           'Complete language information with code, name, and metadata.',
           'i18n',
           '{
               "type": "object",
               "description": "Complete language information",
               "properties": {
                   "code": {
                       "type": "string",
                       "description": "ISO 639-1 code",
                       "pattern": "^[a-z]{2}$"
                   },
                   "code3": {
                       "type": ["string", "null"],
                       "description": "ISO 639-2/T code",
                       "pattern": "^[a-z]{3}$"
                   },
                   "name": {
                       "type": "string",
                       "description": "Language name in English"
                   },
                   "nativeName": {
                       "type": "string",
                       "description": "Language name in native script"
                   },
                   "direction": {
                       "type": "string",
                       "description": "Text direction",
                       "enum": ["ltr", "rtl"],
                       "default": "ltr"
                   },
                   "script": {
                       "type": ["string", "null"],
                       "description": "Primary script used"
                   }
               },
               "required": ["code", "name", "nativeName"],
               "examples": [
                   {
                       "code": "en",
                       "code3": "eng",
                       "name": "English",
                       "nativeName": "English",
                       "direction": "ltr",
                       "script": "Latin"
                   },
                   {
                       "code": "ar",
                       "code3": "ara",
                       "name": "Arabic",
                       "nativeName": "العربية",
                       "direction": "rtl",
                       "script": "Arabic"
                   },
                   {
                       "code": "ja",
                       "code3": "jpn",
                       "name": "Japanese",
                       "nativeName": "日本語",
                       "direction": "ltr",
                       "script": "Japanese"
                   }
               ]
           }',
           ARRAY['language', 'info', 'composite', 'complete'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'languageList',
           'Array of supported language codes.',
           'i18n',
           '{
               "type": "array",
               "description": "List of supported language codes",
               "items": {
                   "type": "string",
                   "pattern": "^[a-z]{2}(-[A-Z]{2})?$"
               },
               "uniqueItems": true,
               "examples": [
                   ["en", "es", "fr", "de"],
                   ["en-US", "en-GB", "es-ES", "es-MX"]
               ]
           }',
           ARRAY['language', 'list', 'array', 'supported'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'primaryLanguage',
           'Primary/default language with optional fallbacks.',
           'i18n',
           '{
               "type": "object",
               "description": "Primary language with fallback chain",
               "properties": {
                   "primary": {
                       "type": "string",
                       "description": "Primary language code",
                       "pattern": "^[a-z]{2}(-[A-Z]{2})?$"
                   },
                   "fallbacks": {
                       "type": "array",
                       "description": "Fallback language codes in priority order",
                       "items": {
                           "type": "string",
                           "pattern": "^[a-z]{2}(-[A-Z]{2})?$"
                       }
                   }
               },
               "required": ["primary"],
               "examples": [
                   {"primary": "fr-CA", "fallbacks": ["fr", "en"]},
                   {"primary": "zh-TW", "fallbacks": ["zh-CN", "en"]}
               ]
           }',
           ARRAY['language', 'primary', 'fallback', 'default'],
           true,
           true
       );

-- =============================================================================
-- LOCALE FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'locale',
           'Locale identifier combining language and region.',
           'i18n',
           '{
               "type": "string",
               "description": "Locale identifier (language-REGION)",
               "examples": ["en-US", "en-GB", "es-ES", "es-MX", "fr-FR", "fr-CA", "zh-CN", "zh-TW", "pt-BR"],
               "pattern": "^[a-z]{2}(-[A-Z]{2})?$",
               "minLength": 2,
               "maxLength": 5
           }',
           ARRAY['locale', 'language', 'region'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'localeExtended',
           'Extended locale with script and variant support.',
           'i18n',
           '{
               "type": "string",
               "description": "Extended locale identifier",
               "examples": ["en-US", "zh-Hans-CN", "zh-Hant-TW", "sr-Latn-RS", "pt-BR"],
               "pattern": "^[a-z]{2,3}(-[A-Za-z]{4})?(-[A-Z]{2}|[0-9]{3})?(-[a-zA-Z0-9]+)*$",
               "minLength": 2,
               "maxLength": 50
           }',
           ARRAY['locale', 'extended', 'script', 'variant'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'localeInfo',
           'Complete locale information with language, region, and formatting preferences.',
           'i18n',
           '{
               "type": "object",
               "description": "Complete locale information",
               "properties": {
                   "code": {
                       "type": "string",
                       "description": "Locale code",
                       "pattern": "^[a-z]{2}(-[A-Z]{2})?$"
                   },
                   "language": {
                       "type": "string",
                       "description": "Language code",
                       "pattern": "^[a-z]{2}$"
                   },
                   "region": {
                       "type": ["string", "null"],
                       "description": "Region/country code",
                       "pattern": "^[A-Z]{2}$"
                   },
                   "script": {
                       "type": ["string", "null"],
                       "description": "Script code",
                       "pattern": "^[A-Z][a-z]{3}$"
                   },
                   "name": {
                       "type": "string",
                       "description": "Locale display name"
                   },
                   "nativeName": {
                       "type": "string",
                       "description": "Locale name in native language"
                   },
                   "direction": {
                       "type": "string",
                       "description": "Text direction",
                       "enum": ["ltr", "rtl"]
                   }
               },
               "required": ["code", "language", "name", "direction"],
               "examples": [
                   {
                       "code": "en-US",
                       "language": "en",
                       "region": "US",
                       "script": null,
                       "name": "English (United States)",
                       "nativeName": "English (United States)",
                       "direction": "ltr"
                   },
                   {
                       "code": "ar-SA",
                       "language": "ar",
                       "region": "SA",
                       "script": null,
                       "name": "Arabic (Saudi Arabia)",
                       "nativeName": "العربية (المملكة العربية السعودية)",
                       "direction": "rtl"
                   }
               ]
           }',
           ARRAY['locale', 'info', 'composite', 'complete'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'localeList',
           'Array of supported locales.',
           'i18n',
           '{
               "type": "array",
               "description": "List of supported locales",
               "items": {
                   "type": "string",
                   "pattern": "^[a-z]{2}(-[A-Z]{2})?$"
               },
               "uniqueItems": true,
               "examples": [
                   ["en-US", "en-GB", "es-ES", "fr-FR"],
                   ["en-US", "es-MX", "pt-BR", "fr-CA"]
               ]
           }',
           ARRAY['locale', 'list', 'array', 'supported'],
           true,
           true
       );

-- =============================================================================
-- TIMEZONE FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'timezone',
           'IANA timezone identifier.',
           'i18n',
           '{
               "type": "string",
               "description": "IANA timezone identifier",
               "examples": ["America/New_York", "Europe/London", "Asia/Tokyo", "Pacific/Auckland", "UTC"],
               "minLength": 1,
               "maxLength": 64
           }',
           ARRAY['timezone', 'iana', 'tz'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'timezoneOffset',
           'Timezone UTC offset in minutes.',
           'i18n',
           '{
               "type": "integer",
               "description": "UTC offset in minutes",
               "examples": [-480, -300, 0, 60, 330, 540],
               "minimum": -720,
               "maximum": 840
           }',
           ARRAY['timezone', 'offset', 'utc', 'minutes'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'timezoneOffsetString',
           'Timezone UTC offset as string.',
           'i18n',
           '{
               "type": "string",
               "description": "UTC offset string",
               "examples": ["-08:00", "-05:00", "+00:00", "+01:00", "+05:30", "+09:00"],
               "pattern": "^[+-][0-9]{2}:[0-9]{2}$"
           }',
           ARRAY['timezone', 'offset', 'utc', 'string'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'timezoneAbbreviation',
           'Timezone abbreviation.',
           'i18n',
           '{
               "type": "string",
               "description": "Timezone abbreviation",
               "examples": ["PST", "EST", "UTC", "GMT", "JST", "IST", "CET"],
               "pattern": "^[A-Z]{2,5}$",
               "minLength": 2,
               "maxLength": 5
           }',
           ARRAY['timezone', 'abbreviation', 'short'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'timezoneInfo',
           'Complete timezone information.',
           'i18n',
           '{
               "type": "object",
               "description": "Complete timezone information",
               "properties": {
                   "id": {
                       "type": "string",
                       "description": "IANA timezone identifier"
                   },
                   "name": {
                       "type": "string",
                       "description": "Display name"
                   },
                   "abbreviation": {
                       "type": "string",
                       "description": "Current abbreviation"
                   },
                   "offsetMinutes": {
                       "type": "integer",
                       "description": "Current UTC offset in minutes"
                   },
                   "offsetString": {
                       "type": "string",
                       "description": "Current UTC offset string"
                   },
                   "isDst": {
                       "type": "boolean",
                       "description": "Whether DST is currently active"
                   },
                   "dstOffset": {
                       "type": ["integer", "null"],
                       "description": "DST offset in minutes when active"
                   }
               },
               "required": ["id", "name", "offsetMinutes", "isDst"],
               "examples": [
                   {
                       "id": "America/New_York",
                       "name": "Eastern Time",
                       "abbreviation": "EST",
                       "offsetMinutes": -300,
                       "offsetString": "-05:00",
                       "isDst": false,
                       "dstOffset": 60
                   },
                   {
                       "id": "Europe/London",
                       "name": "Greenwich Mean Time",
                       "abbreviation": "GMT",
                       "offsetMinutes": 0,
                       "offsetString": "+00:00",
                       "isDst": false,
                       "dstOffset": 60
                   }
               ]
           }',
           ARRAY['timezone', 'info', 'composite', 'complete'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'timezoneList',
           'Array of timezone identifiers.',
           'i18n',
           '{
               "type": "array",
               "description": "List of timezone identifiers",
               "items": {
                   "type": "string"
               },
               "uniqueItems": true,
               "examples": [
                   ["America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles"],
                   ["Europe/London", "Europe/Paris", "Europe/Berlin", "Europe/Moscow"]
               ]
           }',
           ARRAY['timezone', 'list', 'array'],
           true,
           true
       );

-- =============================================================================
-- REGION AND COUNTRY FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'region',
           'ISO 3166-1 alpha-2 region/country code.',
           'i18n',
           '{
               "type": "string",
               "description": "ISO 3166-1 alpha-2 country code",
               "examples": ["US", "GB", "CA", "AU", "DE", "FR", "JP", "CN"],
               "pattern": "^[A-Z]{2}$",
               "minLength": 2,
               "maxLength": 2
           }',
           ARRAY['region', 'country', 'iso3166', 'code'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'region3',
           'ISO 3166-1 alpha-3 region/country code.',
           'i18n',
           '{
               "type": "string",
               "description": "ISO 3166-1 alpha-3 country code",
               "examples": ["USA", "GBR", "CAN", "AUS", "DEU", "FRA", "JPN", "CHN"],
               "pattern": "^[A-Z]{3}$",
               "minLength": 3,
               "maxLength": 3
           }',
           ARRAY['region', 'country', 'iso3166', 'alpha3'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'regionNumeric',
           'ISO 3166-1 numeric region/country code.',
           'i18n',
           '{
               "type": "string",
               "description": "ISO 3166-1 numeric country code",
               "examples": ["840", "826", "124", "036", "276", "250", "392", "156"],
               "pattern": "^[0-9]{3}$",
               "minLength": 3,
               "maxLength": 3
           }',
           ARRAY['region', 'country', 'iso3166', 'numeric'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'regionName',
           'Human-readable region/country name.',
           'i18n',
           '{
               "type": "string",
               "description": "Country/region name",
               "examples": ["United States", "United Kingdom", "Canada", "Germany", "Japan", "France"],
               "minLength": 1,
               "maxLength": 100
           }',
           ARRAY['region', 'country', 'name', 'display'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'regionInfo',
           'Complete region/country information.',
           'i18n',
           '{
               "type": "object",
               "description": "Complete country/region information",
               "properties": {
                   "code": {
                       "type": "string",
                       "description": "ISO 3166-1 alpha-2 code",
                       "pattern": "^[A-Z]{2}$"
                   },
                   "code3": {
                       "type": "string",
                       "description": "ISO 3166-1 alpha-3 code",
                       "pattern": "^[A-Z]{3}$"
                   },
                   "numericCode": {
                       "type": "string",
                       "description": "ISO 3166-1 numeric code",
                       "pattern": "^[0-9]{3}$"
                   },
                   "name": {
                       "type": "string",
                       "description": "Country name in English"
                   },
                   "nativeName": {
                       "type": "string",
                       "description": "Country name in native language"
                   },
                   "continent": {
                       "type": ["string", "null"],
                       "description": "Continent code"
                   },
                   "capital": {
                       "type": ["string", "null"],
                       "description": "Capital city"
                   },
                   "currencies": {
                       "type": "array",
                       "description": "Official currency codes",
                       "items": {"type": "string", "pattern": "^[A-Z]{3}$"}
                   },
                   "languages": {
                       "type": "array",
                       "description": "Official language codes",
                       "items": {"type": "string", "pattern": "^[a-z]{2}$"}
                   },
                   "callingCode": {
                       "type": ["string", "null"],
                       "description": "International calling code"
                   }
               },
               "required": ["code", "code3", "name"],
               "examples": [
                   {
                       "code": "US",
                       "code3": "USA",
                       "numericCode": "840",
                       "name": "United States",
                       "nativeName": "United States",
                       "continent": "NA",
                       "capital": "Washington, D.C.",
                       "currencies": ["USD"],
                       "languages": ["en"],
                       "callingCode": "+1"
                   },
                   {
                       "code": "JP",
                       "code3": "JPN",
                       "numericCode": "392",
                       "name": "Japan",
                       "nativeName": "日本",
                       "continent": "AS",
                       "capital": "Tokyo",
                       "currencies": ["JPY"],
                       "languages": ["ja"],
                       "callingCode": "+81"
                   }
               ]
           }',
           ARRAY['region', 'country', 'info', 'composite', 'complete'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'regionList',
           'Array of region/country codes.',
           'i18n',
           '{
               "type": "array",
               "description": "List of country/region codes",
               "items": {
                   "type": "string",
                   "pattern": "^[A-Z]{2}$"
               },
               "uniqueItems": true,
               "examples": [
                   ["US", "CA", "MX"],
                   ["DE", "FR", "GB", "IT", "ES"]
               ]
           }',
           ARRAY['region', 'country', 'list', 'array'],
           true,
           true
       );

-- =============================================================================
-- SCRIPT AND WRITING SYSTEM FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'script',
           'ISO 15924 script code.',
           'i18n',
           '{
               "type": "string",
               "description": "ISO 15924 script code",
               "examples": ["Latn", "Cyrl", "Arab", "Hans", "Hant", "Jpan", "Kore", "Deva"],
               "pattern": "^[A-Z][a-z]{3}$",
               "minLength": 4,
               "maxLength": 4
           }',
           ARRAY['script', 'iso15924', 'writing-system'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'scriptInfo',
           'Complete script/writing system information.',
           'i18n',
           '{
               "type": "object",
               "description": "Script/writing system information",
               "properties": {
                   "code": {
                       "type": "string",
                       "description": "ISO 15924 code",
                       "pattern": "^[A-Z][a-z]{3}$"
                   },
                   "name": {
                       "type": "string",
                       "description": "Script name"
                   },
                   "direction": {
                       "type": "string",
                       "description": "Writing direction",
                       "enum": ["ltr", "rtl", "ttb"]
                   },
                   "unicodeRange": {
                       "type": ["string", "null"],
                       "description": "Primary Unicode range"
                   }
               },
               "required": ["code", "name", "direction"],
               "examples": [
                   {
                       "code": "Latn",
                       "name": "Latin",
                       "direction": "ltr",
                       "unicodeRange": "U+0000-007F"
                   },
                   {
                       "code": "Arab",
                       "name": "Arabic",
                       "direction": "rtl",
                       "unicodeRange": "U+0600-06FF"
                   }
               ]
           }',
           ARRAY['script', 'info', 'writing-system', 'composite'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'textDirection',
           'Text direction for layout.',
           'i18n',
           '{
               "type": "string",
               "description": "Text direction",
               "enum": ["ltr", "rtl", "auto"],
               "examples": ["ltr", "rtl"],
               "default": "ltr"
           }',
           ARRAY['direction', 'text', 'layout', 'rtl', 'ltr'],
           true,
           true
       );

-- =============================================================================
-- NUMBER AND CURRENCY FORMATTING FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'numberFormat',
           'Number formatting preferences.',
           'i18n',
           '{
               "type": "object",
               "description": "Number formatting configuration",
               "properties": {
                   "decimalSeparator": {
                       "type": "string",
                       "description": "Decimal separator character",
                       "enum": [".", ","],
                       "default": "."
                   },
                   "thousandsSeparator": {
                       "type": "string",
                       "description": "Thousands grouping separator",
                       "enum": [",", ".", " ", ""],
                       "default": ","
                   },
                   "groupingSize": {
                       "type": "integer",
                       "description": "Digits per group",
                       "minimum": 0,
                       "maximum": 4,
                       "default": 3
                   },
                   "negativeFormat": {
                       "type": "string",
                       "description": "Negative number format",
                       "enum": ["-n", "(n)", "n-"],
                       "default": "-n"
                   }
               },
               "examples": [
                   {
                       "decimalSeparator": ".",
                       "thousandsSeparator": ",",
                       "groupingSize": 3,
                       "negativeFormat": "-n"
                   },
                   {
                       "decimalSeparator": ",",
                       "thousandsSeparator": ".",
                       "groupingSize": 3,
                       "negativeFormat": "-n"
                   }
               ]
           }',
           ARRAY['number', 'format', 'decimal', 'thousands'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'currencyFormat',
           'Currency formatting preferences.',
           'i18n',
           '{
               "type": "object",
               "description": "Currency formatting configuration",
               "properties": {
                   "currencyCode": {
                       "type": "string",
                       "description": "Default currency code",
                       "pattern": "^[A-Z]{3}$"
                   },
                   "symbolPosition": {
                       "type": "string",
                       "description": "Currency symbol position",
                       "enum": ["before", "after"],
                       "default": "before"
                   },
                   "symbolSpacing": {
                       "type": "boolean",
                       "description": "Space between symbol and amount",
                       "default": false
                   },
                   "decimalPlaces": {
                       "type": "integer",
                       "description": "Number of decimal places",
                       "minimum": 0,
                       "maximum": 4,
                       "default": 2
                   },
                   "decimalSeparator": {
                       "type": "string",
                       "description": "Decimal separator",
                       "enum": [".", ","],
                       "default": "."
                   },
                   "thousandsSeparator": {
                       "type": "string",
                       "description": "Thousands separator",
                       "enum": [",", ".", " ", ""],
                       "default": ","
                   }
               },
               "required": ["currencyCode"],
               "examples": [
                   {
                       "currencyCode": "USD",
                       "symbolPosition": "before",
                       "symbolSpacing": false,
                       "decimalPlaces": 2,
                       "decimalSeparator": ".",
                       "thousandsSeparator": ","
                   },
                   {
                       "currencyCode": "EUR",
                       "symbolPosition": "after",
                       "symbolSpacing": true,
                       "decimalPlaces": 2,
                       "decimalSeparator": ",",
                       "thousandsSeparator": "."
                   }
               ]
           }',
           ARRAY['currency', 'format', 'money', 'symbol'],
           true,
           true
       );

-- =============================================================================
-- DATE AND TIME FORMATTING FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'dateFormat',
           'Date format pattern.',
           'i18n',
           '{
               "type": "string",
               "description": "Date format pattern",
               "examples": ["MM/DD/YYYY", "DD/MM/YYYY", "YYYY-MM-DD", "DD.MM.YYYY"],
               "minLength": 1,
               "maxLength": 50
           }',
           ARRAY['date', 'format', 'pattern'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'timeFormat',
           'Time format pattern.',
           'i18n',
           '{
               "type": "string",
               "description": "Time format pattern",
               "examples": ["HH:mm:ss", "hh:mm:ss a", "HH:mm", "h:mm a"],
               "minLength": 1,
               "maxLength": 50
           }',
           ARRAY['time', 'format', 'pattern'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'dateTimeFormat',
           'Combined date and time format pattern.',
           'i18n',
           '{
               "type": "string",
               "description": "DateTime format pattern",
               "examples": ["MM/DD/YYYY HH:mm:ss", "DD/MM/YYYY HH:mm", "YYYY-MM-DD HH:mm:ss"],
               "minLength": 1,
               "maxLength": 100
           }',
           ARRAY['datetime', 'format', 'pattern'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'dateTimeFormatInfo',
           'Complete date/time formatting preferences.',
           'i18n',
           '{
               "type": "object",
               "description": "Date/time formatting configuration",
               "properties": {
                   "dateFormat": {
                       "type": "string",
                       "description": "Date format pattern"
                   },
                   "timeFormat": {
                       "type": "string",
                       "description": "Time format pattern"
                   },
                   "dateTimeFormat": {
                       "type": "string",
                       "description": "Combined format pattern"
                   },
                   "use24Hour": {
                       "type": "boolean",
                       "description": "Use 24-hour time",
                       "default": true
                   },
                   "firstDayOfWeek": {
                       "type": "integer",
                       "description": "First day of week (0=Sunday, 1=Monday)",
                       "minimum": 0,
                       "maximum": 6,
                       "default": 0
                   },
                   "weekendDays": {
                       "type": "array",
                       "description": "Weekend days (0=Sunday)",
                       "items": {"type": "integer", "minimum": 0, "maximum": 6},
                       "default": [0, 6]
                   }
               },
               "required": ["dateFormat", "timeFormat"],
               "examples": [
                   {
                       "dateFormat": "MM/DD/YYYY",
                       "timeFormat": "h:mm a",
                       "dateTimeFormat": "MM/DD/YYYY h:mm a",
                       "use24Hour": false,
                       "firstDayOfWeek": 0,
                       "weekendDays": [0, 6]
                   },
                   {
                       "dateFormat": "DD.MM.YYYY",
                       "timeFormat": "HH:mm",
                       "dateTimeFormat": "DD.MM.YYYY HH:mm",
                       "use24Hour": true,
                       "firstDayOfWeek": 1,
                       "weekendDays": [0, 6]
                   }
               ]
           }',
           ARRAY['datetime', 'format', 'composite', 'week'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'calendarSystem',
           'Calendar system identifier.',
           'i18n',
           '{
               "type": "string",
               "description": "Calendar system",
               "enum": ["gregorian", "islamic", "hebrew", "chinese", "japanese", "buddhist", "persian", "indian"],
               "examples": ["gregorian", "islamic", "hebrew"],
               "default": "gregorian"
           }',
           ARRAY['calendar', 'system', 'type'],
           true,
           true
       );

-- =============================================================================
-- MEASUREMENT AND UNIT FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'measurementSystem',
           'Measurement system preference.',
           'i18n',
           '{
               "type": "string",
               "description": "Measurement system",
               "enum": ["metric", "imperial", "us"],
               "examples": ["metric", "imperial", "us"],
               "default": "metric"
           }',
           ARRAY['measurement', 'system', 'units'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'temperatureUnit',
           'Temperature unit preference.',
           'i18n',
           '{
               "type": "string",
               "description": "Temperature unit",
               "enum": ["celsius", "fahrenheit", "kelvin"],
               "examples": ["celsius", "fahrenheit"],
               "default": "celsius"
           }',
           ARRAY['temperature', 'unit', 'preference'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'distanceUnit',
           'Distance unit preference.',
           'i18n',
           '{
               "type": "string",
               "description": "Distance unit",
               "enum": ["kilometers", "miles"],
               "examples": ["kilometers", "miles"],
               "default": "kilometers"
           }',
           ARRAY['distance', 'unit', 'preference'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'unitPreferences',
           'Complete unit preference settings.',
           'i18n',
           '{
               "type": "object",
               "description": "Unit preferences",
               "properties": {
                   "measurementSystem": {
                       "type": "string",
                       "description": "Measurement system",
                       "enum": ["metric", "imperial", "us"]
                   },
                   "temperature": {
                       "type": "string",
                       "description": "Temperature unit",
                       "enum": ["celsius", "fahrenheit", "kelvin"]
                   },
                   "distance": {
                       "type": "string",
                       "description": "Distance unit",
                       "enum": ["kilometers", "miles"]
                   },
                   "weight": {
                       "type": "string",
                       "description": "Weight unit",
                       "enum": ["kilograms", "pounds"]
                   },
                   "volume": {
                       "type": "string",
                       "description": "Volume unit",
                       "enum": ["liters", "gallons"]
                   },
                   "speed": {
                       "type": "string",
                       "description": "Speed unit",
                       "enum": ["kmh", "mph"]
                   }
               },
               "examples": [
                   {
                       "measurementSystem": "metric",
                       "temperature": "celsius",
                       "distance": "kilometers",
                       "weight": "kilograms",
                       "volume": "liters",
                       "speed": "kmh"
                   },
                   {
                       "measurementSystem": "imperial",
                       "temperature": "fahrenheit",
                       "distance": "miles",
                       "weight": "pounds",
                       "volume": "gallons",
                       "speed": "mph"
                   }
               ]
           }',
           ARRAY['units', 'preferences', 'measurement', 'composite'],
           true,
           true
       );

-- =============================================================================
-- LOCALIZED CONTENT FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'localizedString',
           'String with translations for multiple locales.',
           'i18n',
           '{
               "type": "object",
               "description": "Localized string with translations",
               "additionalProperties": {
                   "type": "string"
               },
               "examples": [
                   {
                       "en": "Hello",
                       "es": "Hola",
                       "fr": "Bonjour",
                       "de": "Hallo",
                       "ja": "こんにちは"
                   },
                   {
                       "en-US": "Color",
                       "en-GB": "Colour",
                       "es": "Color",
                       "fr": "Couleur"
                   }
               ]
           }',
           ARRAY['localized', 'string', 'translation', 'multilingual'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'localizedText',
           'Longer text content with translations.',
           'i18n',
           '{
               "type": "object",
               "description": "Localized text content",
               "additionalProperties": {
                   "type": "string"
               },
               "examples": [
                   {
                       "en": "Welcome to our application. We hope you enjoy using it.",
                       "es": "Bienvenido a nuestra aplicación. Esperamos que disfrute usándola.",
                       "fr": "Bienvenue dans notre application. Nous espérons que vous apprécierez son utilisation."
                   }
               ]
           }',
           ARRAY['localized', 'text', 'translation', 'multilingual', 'content'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'localizedContent',
           'Structured localized content with title and body.',
           'i18n',
           '{
               "type": "object",
               "description": "Structured localized content",
               "additionalProperties": {
                   "type": "object",
                   "properties": {
                       "title": {"type": "string"},
                       "body": {"type": "string"},
                       "summary": {"type": ["string", "null"]}
                   },
                   "required": ["title", "body"]
               },
               "examples": [
                   {
                       "en": {
                           "title": "Welcome",
                           "body": "Welcome to our platform.",
                           "summary": "A warm welcome message"
                       },
                       "es": {
                           "title": "Bienvenido",
                           "body": "Bienvenido a nuestra plataforma.",
                           "summary": "Un mensaje de bienvenida"
                       }
                   }
               ]
           }',
           ARRAY['localized', 'content', 'structured', 'multilingual'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'translationStatus',
           'Status of content translation.',
           'i18n',
           '{
               "type": "string",
               "description": "Translation status",
               "enum": ["notTranslated", "machineTranslated", "humanTranslated", "reviewed", "approved"],
               "examples": ["notTranslated", "machineTranslated", "approved"],
               "default": "notTranslated"
           }',
           ARRAY['translation', 'status', 'enum', 'workflow'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'translationInfo',
           'Translation metadata for a piece of content.',
           'i18n',
           '{
               "type": "object",
               "description": "Translation information",
               "properties": {
                   "sourceLocale": {
                       "type": "string",
                       "description": "Original content locale"
                   },
                   "translations": {
                       "type": "object",
                       "description": "Translation status by locale",
                       "additionalProperties": {
                           "type": "object",
                           "properties": {
                               "status": {
                                   "type": "string",
                                   "enum": ["notTranslated", "machineTranslated", "humanTranslated", "reviewed", "approved"]
                               },
                               "translatedAt": {
                                   "type": ["string", "null"],
                                   "format": "date-time"
                               },
                               "translatedBy": {
                                   "type": ["string", "null"]
                               },
                               "reviewedAt": {
                                   "type": ["string", "null"],
                                   "format": "date-time"
                               },
                               "reviewedBy": {
                                   "type": ["string", "null"]
                               }
                           },
                           "required": ["status"]
                       }
                   },
                   "completionPercentage": {
                       "type": "number",
                       "description": "Overall translation completion",
                       "minimum": 0,
                       "maximum": 100
                   }
               },
               "required": ["sourceLocale", "translations"],
               "examples": [
                   {
                       "sourceLocale": "en-US",
                       "translations": {
                           "es": {"status": "approved", "translatedAt": "2024-01-15T10:00:00Z", "translatedBy": "user123", "reviewedAt": "2024-01-16T14:00:00Z", "reviewedBy": "reviewer456"},
                           "fr": {"status": "machineTranslated", "translatedAt": "2024-01-15T10:00:00Z", "translatedBy": null, "reviewedAt": null, "reviewedBy": null},
                           "de": {"status": "notTranslated", "translatedAt": null, "translatedBy": null, "reviewedAt": null, "reviewedBy": null}
                       },
                       "completionPercentage": 66.7
                   }
               ]
           }',
           ARRAY['translation', 'info', 'metadata', 'workflow', 'composite'],
           true,
           true
       );

-- =============================================================================
-- COMPOSITE I18N SETTINGS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'i18nSettings',
           'Complete internationalization settings for a user or system.',
           'i18n',
           '{
               "type": "object",
               "description": "Complete i18n settings",
               "properties": {
                   "locale": {
                       "type": "string",
                       "description": "Primary locale",
                       "pattern": "^[a-z]{2}(-[A-Z]{2})?$"
                   },
                   "language": {
                       "type": "string",
                       "description": "Language code",
                       "pattern": "^[a-z]{2}$"
                   },
                   "region": {
                       "type": ["string", "null"],
                       "description": "Region code",
                       "pattern": "^[A-Z]{2}$"
                   },
                   "timezone": {
                       "type": "string",
                       "description": "IANA timezone"
                   },
                   "currency": {
                       "type": "string",
                       "description": "Default currency",
                       "pattern": "^[A-Z]{3}$"
                   },
                   "measurementSystem": {
                       "type": "string",
                       "description": "Measurement system",
                       "enum": ["metric", "imperial", "us"]
                   },
                   "dateFormat": {
                       "type": "string",
                       "description": "Date format pattern"
                   },
                   "timeFormat": {
                       "type": "string",
                       "description": "Time format pattern"
                   },
                   "use24Hour": {
                       "type": "boolean",
                       "description": "Use 24-hour time"
                   },
                   "firstDayOfWeek": {
                       "type": "integer",
                       "description": "First day of week",
                       "minimum": 0,
                       "maximum": 6
                   },
                   "numberFormat": {
                       "type": "object",
                       "description": "Number formatting preferences",
                       "properties": {
                           "decimalSeparator": {"type": "string"},
                           "thousandsSeparator": {"type": "string"}
                       }
                   }
               },
               "required": ["locale", "language", "timezone"],
               "examples": [
                   {
                       "locale": "en-US",
                       "language": "en",
                       "region": "US",
                       "timezone": "America/New_York",
                       "currency": "USD",
                       "measurementSystem": "imperial",
                       "dateFormat": "MM/DD/YYYY",
                       "timeFormat": "h:mm a",
                       "use24Hour": false,
                       "firstDayOfWeek": 0,
                       "numberFormat": {
                           "decimalSeparator": ".",
                           "thousandsSeparator": ","
                       }
                   },
                   {
                       "locale": "de-DE",
                       "language": "de",
                       "region": "DE",
                       "timezone": "Europe/Berlin",
                       "currency": "EUR",
                       "measurementSystem": "metric",
                       "dateFormat": "DD.MM.YYYY",
                       "timeFormat": "HH:mm",
                       "use24Hour": true,
                       "firstDayOfWeek": 1,
                       "numberFormat": {
                           "decimalSeparator": ",",
                           "thousandsSeparator": "."
                       }
                   }
               ]
           }',
           ARRAY['i18n', 'settings', 'composite', 'complete', 'preferences'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'supportedLocales',
           'Configuration for supported locales in an application.',
           'i18n',
           '{
               "type": "object",
               "description": "Supported locales configuration",
               "properties": {
                   "defaultLocale": {
                       "type": "string",
                       "description": "Default/fallback locale",
                       "pattern": "^[a-z]{2}(-[A-Z]{2})?$"
                   },
                   "availableLocales": {
                       "type": "array",
                       "description": "All available locales",
                       "items": {
                           "type": "string",
                           "pattern": "^[a-z]{2}(-[A-Z]{2})?$"
                       },
                       "uniqueItems": true
                   },
                   "fallbackChain": {
                       "type": "object",
                       "description": "Locale fallback mapping",
                       "additionalProperties": {
                           "type": "string"
                       }
                   },
                   "autoDetect": {
                       "type": "boolean",
                       "description": "Auto-detect user locale",
                       "default": true
                   }
               },
               "required": ["defaultLocale", "availableLocales"],
               "examples": [
                   {
                       "defaultLocale": "en-US",
                       "availableLocales": ["en-US", "en-GB", "es-ES", "es-MX", "fr-FR", "de-DE", "ja-JP"],
                       "fallbackChain": {
                           "en-GB": "en-US",
                           "es-MX": "es-ES",
                           "fr-CA": "fr-FR"
                       },
                       "autoDetect": true
                   }
               ]
           }',
           ARRAY['locales', 'supported', 'configuration', 'fallback'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'contentLocalization',
           'Localization metadata for content items.',
           'i18n',
           '{
               "type": "object",
               "description": "Content localization metadata",
               "properties": {
                   "originalLocale": {
                       "type": "string",
                       "description": "Original content locale",
                       "pattern": "^[a-z]{2}(-[A-Z]{2})?$"
                   },
                   "currentLocale": {
                       "type": "string",
                       "description": "Current viewing locale",
                       "pattern": "^[a-z]{2}(-[A-Z]{2})?$"
                   },
                   "availableIn": {
                       "type": "array",
                       "description": "Locales where content is available",
                       "items": {
                           "type": "string",
                           "pattern": "^[a-z]{2}(-[A-Z]{2})?$"
                       }
                   },
                   "isTranslated": {
                       "type": "boolean",
                       "description": "Whether current view is translated"
                   },
                   "lastTranslatedAt": {
                       "type": ["string", "null"],
                       "format": "date-time",
                       "description": "When last translated"
                   }
               },
               "required": ["originalLocale", "currentLocale", "availableIn"],
               "examples": [
                   {
                       "originalLocale": "en-US",
                       "currentLocale": "es-ES",
                       "availableIn": ["en-US", "es-ES", "fr-FR", "de-DE"],
                       "isTranslated": true,
                       "lastTranslatedAt": "2024-01-15T10:00:00Z"
                   }
               ]
           }',
           ARRAY['content', 'localization', 'metadata', 'translation'],
           true,
           true
       );