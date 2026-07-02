-- Property Templates: Address Category
-- These templates define common address patterns for storing location and postal information
-- Property names are camelCase, alphanumeric only (a-zA-Z0-9)
-- Follows OpenAPI 3.1 / JSON Schema Draft 2020-12 standards

SET search_path TO apiome, public;

-- =============================================================================
-- STREET ADDRESS FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'streetAddress',
    'Primary street address including house number and street name.',
    'address',
    '{
        "type": "string",
        "description": "Street address line",
        "examples": ["123 Main Street", "456 Oak Avenue, Suite 100", "1600 Pennsylvania Avenue NW"],
        "minLength": 1,
        "maxLength": 255
    }',
    ARRAY['street', 'address', 'line1', 'primary'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'streetAddress2',
    'Secondary street address line for apartment, suite, unit, or building information.',
    'address',
    '{
        "type": ["string", "null"],
        "description": "Secondary address line (apt, suite, unit, etc.)",
        "examples": ["Apt 4B", "Suite 500", "Building C", "Floor 12", null],
        "maxLength": 255
    }',
    ARRAY['street', 'address', 'line2', 'secondary', 'nullable'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'streetAddress3',
    'Tertiary street address line for additional location details.',
    'address',
    '{
        "type": ["string", "null"],
        "description": "Tertiary address line for additional details",
        "examples": ["c/o John Smith", "Attention: Billing Dept", null],
        "maxLength": 255
    }',
    ARRAY['street', 'address', 'line3', 'tertiary', 'nullable'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'houseNumber',
    'House or building number portion of a street address.',
    'address',
    '{
        "type": "string",
        "description": "House or building number",
        "examples": ["123", "456A", "12-14", "1600"],
        "minLength": 1,
        "maxLength": 20
    }',
    ARRAY['house', 'number', 'building', 'address'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'streetName',
    'Street name without the house number.',
    'address',
    '{
        "type": "string",
        "description": "Street name",
        "examples": ["Main Street", "Oak Avenue", "Pennsylvania Avenue NW", "Boulevard Saint-Germain"],
        "minLength": 1,
        "maxLength": 255
    }',
    ARRAY['street', 'name', 'address'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'apartmentNumber',
    'Apartment, suite, or unit number.',
    'address',
    '{
        "type": ["string", "null"],
        "description": "Apartment, suite, or unit number",
        "examples": ["4B", "Suite 500", "Unit 12", "#301", null],
        "maxLength": 50
    }',
    ARRAY['apartment', 'suite', 'unit', 'address', 'nullable'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'floor',
    'Floor or level number within a building.',
    'address',
    '{
        "type": ["string", "null"],
        "description": "Floor or level number",
        "examples": ["1", "12", "Ground", "Basement", "Penthouse", null],
        "maxLength": 20
    }',
    ARRAY['floor', 'level', 'building', 'address', 'nullable'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'building',
    'Building name or identifier.',
    'address',
    '{
        "type": ["string", "null"],
        "description": "Building name or identifier",
        "examples": ["Tower A", "Empire State Building", "Riverside Plaza", null],
        "maxLength": 100
    }',
    ARRAY['building', 'name', 'address', 'nullable'],
    true,
    true
);

-- =============================================================================
-- CITY AND LOCALITY FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'city',
    'City or locality name.',
    'address',
    '{
        "type": "string",
        "description": "City or locality name",
        "examples": ["New York", "Los Angeles", "London", "Tokyo", "Sao Paulo"],
        "minLength": 1,
        "maxLength": 100
    }',
    ARRAY['city', 'locality', 'address'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'locality',
    'Locality name (generic term for city, town, village, etc.).',
    'address',
    '{
        "type": "string",
        "description": "Locality name (city, town, village)",
        "examples": ["San Francisco", "Greenwich", "Shibuya", "Montmartre"],
        "minLength": 1,
        "maxLength": 100
    }',
    ARRAY['locality', 'city', 'town', 'address'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'sublocality',
    'Sublocality such as neighborhood, district, or borough.',
    'address',
    '{
        "type": ["string", "null"],
        "description": "Sublocality (neighborhood, district, borough)",
        "examples": ["Manhattan", "Brooklyn", "Shibuya", "Westminster", null],
        "maxLength": 100
    }',
    ARRAY['sublocality', 'neighborhood', 'district', 'borough', 'nullable'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'neighborhood',
    'Neighborhood or local area name.',
    'address',
    '{
        "type": ["string", "null"],
        "description": "Neighborhood or local area",
        "examples": ["SoHo", "Haight-Ashbury", "Notting Hill", "Le Marais", null],
        "maxLength": 100
    }',
    ARRAY['neighborhood', 'area', 'address', 'nullable'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'district',
    'Administrative district or area.',
    'address',
    '{
        "type": ["string", "null"],
        "description": "Administrative district",
        "examples": ["Central District", "Financial District", "District 1", null],
        "maxLength": 100
    }',
    ARRAY['district', 'administrative', 'address', 'nullable'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'borough',
    'Borough or county subdivision (used in some cities like NYC or London).',
    'address',
    '{
        "type": ["string", "null"],
        "description": "Borough or county subdivision",
        "examples": ["Manhattan", "Queens", "Camden", "Southwark", null],
        "maxLength": 100
    }',
    ARRAY['borough', 'subdivision', 'address', 'nullable'],
    true,
    true
);

-- =============================================================================
-- STATE AND PROVINCE FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'state',
    'State or region name (full name).',
    'address',
    '{
        "type": "string",
        "description": "State or region name",
        "examples": ["California", "New York", "Texas", "Florida"],
        "minLength": 1,
        "maxLength": 100
    }',
    ARRAY['state', 'region', 'address'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'stateCode',
    'State or region code (abbreviated form).',
    'address',
    '{
        "type": "string",
        "description": "State or region code",
        "examples": ["CA", "NY", "TX", "FL"],
        "pattern": "^[A-Z]{2,3}$",
        "minLength": 2,
        "maxLength": 3
    }',
    ARRAY['state', 'code', 'abbreviation', 'address'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'province',
    'Province name (used in Canada, China, and other countries).',
    'address',
    '{
        "type": "string",
        "description": "Province name",
        "examples": ["Ontario", "British Columbia", "Quebec", "Guangdong"],
        "minLength": 1,
        "maxLength": 100
    }',
    ARRAY['province', 'region', 'address'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'provinceCode',
    'Province code (abbreviated form).',
    'address',
    '{
        "type": "string",
        "description": "Province code",
        "examples": ["ON", "BC", "QC", "AB"],
        "pattern": "^[A-Z]{2,3}$",
        "minLength": 2,
        "maxLength": 3
    }',
    ARRAY['province', 'code', 'abbreviation', 'address'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'region',
    'Generic region, state, or province name.',
    'address',
    '{
        "type": ["string", "null"],
        "description": "Region, state, or province name",
        "examples": ["California", "Ontario", "Bavaria", "Ile-de-France", null],
        "maxLength": 100
    }',
    ARRAY['region', 'state', 'province', 'address', 'nullable'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'regionCode',
    'Generic region, state, or province code.',
    'address',
    '{
        "type": ["string", "null"],
        "description": "Region, state, or province code",
        "examples": ["CA", "ON", "BY", "IDF", null],
        "maxLength": 10
    }',
    ARRAY['region', 'code', 'abbreviation', 'address', 'nullable'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'county',
    'County name (administrative division below state/province).',
    'address',
    '{
        "type": ["string", "null"],
        "description": "County name",
        "examples": ["Los Angeles County", "Cook County", "Greater London", null],
        "maxLength": 100
    }',
    ARRAY['county', 'administrative', 'address', 'nullable'],
    true,
    true
);

-- =============================================================================
-- POSTAL CODE FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'postalCode',
    'Postal code or ZIP code (generic international format).',
    'address',
    '{
        "type": "string",
        "description": "Postal code or ZIP code",
        "examples": ["10001", "90210", "SW1A 1AA", "M5V 3L9", "100-0001"],
        "minLength": 1,
        "maxLength": 20
    }',
    ARRAY['postal', 'code', 'zip', 'address'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'zipCode',
    'US ZIP code (5 digits).',
    'address',
    '{
        "type": "string",
        "description": "US ZIP code (5 digits)",
        "examples": ["10001", "90210", "33139", "60601"],
        "pattern": "^[0-9]{5}$",
        "minLength": 5,
        "maxLength": 5
    }',
    ARRAY['zip', 'code', 'us', 'address'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'zipCodeExtended',
    'US ZIP+4 code (9 digits with hyphen).',
    'address',
    '{
        "type": "string",
        "description": "US ZIP+4 code",
        "examples": ["10001-1234", "90210-5678", "33139-0001"],
        "pattern": "^[0-9]{5}-[0-9]{4}$",
        "minLength": 10,
        "maxLength": 10
    }',
    ARRAY['zip', 'code', 'extended', 'us', 'address'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'zipCodeFlexible',
    'US ZIP code accepting both 5-digit and ZIP+4 formats.',
    'address',
    '{
        "type": "string",
        "description": "US ZIP code (5-digit or ZIP+4)",
        "examples": ["10001", "90210-5678", "33139", "60601-1234"],
        "pattern": "^[0-9]{5}(-[0-9]{4})?$",
        "minLength": 5,
        "maxLength": 10
    }',
    ARRAY['zip', 'code', 'flexible', 'us', 'address'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'postalCodeCA',
    'Canadian postal code.',
    'address',
    '{
        "type": "string",
        "description": "Canadian postal code",
        "examples": ["M5V 3L9", "K1A 0B1", "V6B 4Y8", "H3Z 2Y7"],
        "pattern": "^[A-Za-z][0-9][A-Za-z] ?[0-9][A-Za-z][0-9]$",
        "minLength": 6,
        "maxLength": 7
    }',
    ARRAY['postal', 'code', 'canada', 'address'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'postalCodeUK',
    'UK postcode.',
    'address',
    '{
        "type": "string",
        "description": "UK postcode",
        "examples": ["SW1A 1AA", "EC1A 1BB", "W1A 0AX", "M1 1AE"],
        "pattern": "^[A-Za-z]{1,2}[0-9][0-9A-Za-z]? ?[0-9][A-Za-z]{2}$",
        "minLength": 5,
        "maxLength": 8
    }',
    ARRAY['postal', 'code', 'uk', 'postcode', 'address'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'postalCodeDE',
    'German postal code (PLZ).',
    'address',
    '{
        "type": "string",
        "description": "German postal code (PLZ)",
        "examples": ["10115", "80331", "20095", "50667"],
        "pattern": "^[0-9]{5}$",
        "minLength": 5,
        "maxLength": 5
    }',
    ARRAY['postal', 'code', 'germany', 'plz', 'address'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'postalCodeFR',
    'French postal code.',
    'address',
    '{
        "type": "string",
        "description": "French postal code",
        "examples": ["75001", "69001", "13001", "33000"],
        "pattern": "^[0-9]{5}$",
        "minLength": 5,
        "maxLength": 5
    }',
    ARRAY['postal', 'code', 'france', 'address'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'postalCodeJP',
    'Japanese postal code.',
    'address',
    '{
        "type": "string",
        "description": "Japanese postal code",
        "examples": ["100-0001", "150-0001", "530-0001", "600-8216"],
        "pattern": "^[0-9]{3}-[0-9]{4}$",
        "minLength": 8,
        "maxLength": 8
    }',
    ARRAY['postal', 'code', 'japan', 'address'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'postalCodeAU',
    'Australian postal code.',
    'address',
    '{
        "type": "string",
        "description": "Australian postal code",
        "examples": ["2000", "3000", "4000", "5000"],
        "pattern": "^[0-9]{4}$",
        "minLength": 4,
        "maxLength": 4
    }',
    ARRAY['postal', 'code', 'australia', 'address'],
    true,
    true
);

-- =============================================================================
-- COUNTRY FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'country',
    'Country name (full name).',
    'address',
    '{
        "type": "string",
        "description": "Country name",
        "examples": ["United States", "United Kingdom", "Canada", "Germany", "Japan"],
        "minLength": 1,
        "maxLength": 100
    }',
    ARRAY['country', 'name', 'address'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'countryCode',
    'ISO 3166-1 alpha-2 country code (2 letters).',
    'address',
    '{
        "type": "string",
        "description": "ISO 3166-1 alpha-2 country code",
        "examples": ["US", "GB", "CA", "DE", "JP", "FR", "AU"],
        "pattern": "^[A-Z]{2}$",
        "minLength": 2,
        "maxLength": 2
    }',
    ARRAY['country', 'code', 'iso3166', 'alpha2', 'address'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'countryCode3',
    'ISO 3166-1 alpha-3 country code (3 letters).',
    'address',
    '{
        "type": "string",
        "description": "ISO 3166-1 alpha-3 country code",
        "examples": ["USA", "GBR", "CAN", "DEU", "JPN", "FRA", "AUS"],
        "pattern": "^[A-Z]{3}$",
        "minLength": 3,
        "maxLength": 3
    }',
    ARRAY['country', 'code', 'iso3166', 'alpha3', 'address'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'countryCodeNumeric',
    'ISO 3166-1 numeric country code.',
    'address',
    '{
        "type": "string",
        "description": "ISO 3166-1 numeric country code",
        "examples": ["840", "826", "124", "276", "392"],
        "pattern": "^[0-9]{3}$",
        "minLength": 3,
        "maxLength": 3
    }',
    ARRAY['country', 'code', 'iso3166', 'numeric', 'address'],
    true,
    true
);

-- =============================================================================
-- COMPOSITE ADDRESS OBJECTS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'simpleAddress',
    'Basic address with street, city, state, postal code, and country.',
    'address',
    '{
        "type": "object",
        "description": "Basic address structure",
        "properties": {
            "streetAddress": {
                "type": "string",
                "description": "Street address",
                "maxLength": 255
            },
            "city": {
                "type": "string",
                "description": "City name",
                "maxLength": 100
            },
            "state": {
                "type": ["string", "null"],
                "description": "State or province",
                "maxLength": 100
            },
            "postalCode": {
                "type": "string",
                "description": "Postal or ZIP code",
                "maxLength": 20
            },
            "country": {
                "type": "string",
                "description": "Country name or code",
                "maxLength": 100
            }
        },
        "required": ["streetAddress", "city", "postalCode", "country"],
        "examples": [
            {
                "streetAddress": "123 Main Street",
                "city": "New York",
                "state": "NY",
                "postalCode": "10001",
                "country": "US"
            }
        ]
    }',
    ARRAY['address', 'composite', 'basic', 'simple'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'fullAddress',
    'Complete address with multiple street lines and full geographic hierarchy.',
    'address',
    '{
        "type": "object",
        "description": "Complete address structure",
        "properties": {
            "streetAddress": {
                "type": "string",
                "description": "Primary street address",
                "maxLength": 255
            },
            "streetAddress2": {
                "type": ["string", "null"],
                "description": "Secondary address line",
                "maxLength": 255
            },
            "streetAddress3": {
                "type": ["string", "null"],
                "description": "Tertiary address line",
                "maxLength": 255
            },
            "city": {
                "type": "string",
                "description": "City name",
                "maxLength": 100
            },
            "district": {
                "type": ["string", "null"],
                "description": "District or neighborhood",
                "maxLength": 100
            },
            "state": {
                "type": ["string", "null"],
                "description": "State or province name",
                "maxLength": 100
            },
            "stateCode": {
                "type": ["string", "null"],
                "description": "State or province code",
                "maxLength": 10
            },
            "postalCode": {
                "type": "string",
                "description": "Postal or ZIP code",
                "maxLength": 20
            },
            "country": {
                "type": "string",
                "description": "Country name",
                "maxLength": 100
            },
            "countryCode": {
                "type": "string",
                "description": "ISO 3166-1 alpha-2 country code",
                "pattern": "^[A-Z]{2}$"
            }
        },
        "required": ["streetAddress", "city", "postalCode", "country", "countryCode"],
        "examples": [
            {
                "streetAddress": "123 Main Street",
                "streetAddress2": "Suite 400",
                "streetAddress3": null,
                "city": "San Francisco",
                "district": "Financial District",
                "state": "California",
                "stateCode": "CA",
                "postalCode": "94105",
                "country": "United States",
                "countryCode": "US"
            }
        ]
    }',
    ARRAY['address', 'composite', 'full', 'complete'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'internationalAddress',
    'Flexible international address supporting various global formats.',
    'address',
    '{
        "type": "object",
        "description": "Flexible international address format",
        "properties": {
            "addressLines": {
                "type": "array",
                "description": "Address lines in local format",
                "items": {
                    "type": "string",
                    "maxLength": 255
                },
                "minItems": 1,
                "maxItems": 5
            },
            "locality": {
                "type": "string",
                "description": "City, town, or locality",
                "maxLength": 100
            },
            "administrativeArea": {
                "type": ["string", "null"],
                "description": "State, province, region, or prefecture",
                "maxLength": 100
            },
            "postalCode": {
                "type": ["string", "null"],
                "description": "Postal code in local format",
                "maxLength": 20
            },
            "country": {
                "type": "string",
                "description": "Country name",
                "maxLength": 100
            },
            "countryCode": {
                "type": "string",
                "description": "ISO 3166-1 alpha-2 country code",
                "pattern": "^[A-Z]{2}$"
            },
            "sortingCode": {
                "type": ["string", "null"],
                "description": "Sorting code (used in some countries)",
                "maxLength": 20
            }
        },
        "required": ["addressLines", "locality", "country", "countryCode"],
        "examples": [
            {
                "addressLines": ["123 Main Street", "Suite 400"],
                "locality": "San Francisco",
                "administrativeArea": "CA",
                "postalCode": "94105",
                "country": "United States",
                "countryCode": "US",
                "sortingCode": null
            }
        ]
    }',
    ARRAY['address', 'composite', 'international', 'flexible'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'usAddress',
    'United States address format.',
    'address',
    '{
        "type": "object",
        "description": "US address format",
        "properties": {
            "streetAddress": {
                "type": "string",
                "description": "Street address",
                "maxLength": 255
            },
            "streetAddress2": {
                "type": ["string", "null"],
                "description": "Apt, suite, unit, etc.",
                "maxLength": 255
            },
            "city": {
                "type": "string",
                "description": "City name",
                "maxLength": 100
            },
            "state": {
                "type": "string",
                "description": "State code",
                "pattern": "^[A-Z]{2}$"
            },
            "zipCode": {
                "type": "string",
                "description": "ZIP code (5-digit or ZIP+4)",
                "pattern": "^[0-9]{5}(-[0-9]{4})?$"
            }
        },
        "required": ["streetAddress", "city", "state", "zipCode"],
        "examples": [
            {
                "streetAddress": "123 Main Street",
                "streetAddress2": "Apt 4B",
                "city": "New York",
                "state": "NY",
                "zipCode": "10001"
            },
            {
                "streetAddress": "1600 Pennsylvania Avenue NW",
                "streetAddress2": null,
                "city": "Washington",
                "state": "DC",
                "zipCode": "20500-0003"
            }
        ]
    }',
    ARRAY['address', 'composite', 'us', 'united-states'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'canadianAddress',
    'Canadian address format.',
    'address',
    '{
        "type": "object",
        "description": "Canadian address format",
        "properties": {
            "streetAddress": {
                "type": "string",
                "description": "Street address",
                "maxLength": 255
            },
            "streetAddress2": {
                "type": ["string", "null"],
                "description": "Unit, suite, etc.",
                "maxLength": 255
            },
            "city": {
                "type": "string",
                "description": "City name",
                "maxLength": 100
            },
            "province": {
                "type": "string",
                "description": "Province code",
                "pattern": "^[A-Z]{2}$"
            },
            "postalCode": {
                "type": "string",
                "description": "Canadian postal code",
                "pattern": "^[A-Za-z][0-9][A-Za-z] ?[0-9][A-Za-z][0-9]$"
            }
        },
        "required": ["streetAddress", "city", "province", "postalCode"],
        "examples": [
            {
                "streetAddress": "350 Fifth Avenue",
                "streetAddress2": "Suite 3400",
                "city": "Toronto",
                "province": "ON",
                "postalCode": "M5V 3L9"
            }
        ]
    }',
    ARRAY['address', 'composite', 'canada', 'canadian'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'ukAddress',
    'United Kingdom address format.',
    'address',
    '{
        "type": "object",
        "description": "UK address format",
        "properties": {
            "addressLine1": {
                "type": "string",
                "description": "Building/house number and street",
                "maxLength": 255
            },
            "addressLine2": {
                "type": ["string", "null"],
                "description": "Secondary address line",
                "maxLength": 255
            },
            "city": {
                "type": "string",
                "description": "Town or city",
                "maxLength": 100
            },
            "county": {
                "type": ["string", "null"],
                "description": "County (optional)",
                "maxLength": 100
            },
            "postcode": {
                "type": "string",
                "description": "UK postcode",
                "pattern": "^[A-Za-z]{1,2}[0-9][0-9A-Za-z]? ?[0-9][A-Za-z]{2}$"
            }
        },
        "required": ["addressLine1", "city", "postcode"],
        "examples": [
            {
                "addressLine1": "10 Downing Street",
                "addressLine2": null,
                "city": "London",
                "county": "Greater London",
                "postcode": "SW1A 2AA"
            }
        ]
    }',
    ARRAY['address', 'composite', 'uk', 'united-kingdom'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'europeanAddress',
    'Generic European address format.',
    'address',
    '{
        "type": "object",
        "description": "Generic European address format",
        "properties": {
            "streetAddress": {
                "type": "string",
                "description": "Street name and number",
                "maxLength": 255
            },
            "streetAddress2": {
                "type": ["string", "null"],
                "description": "Additional address details",
                "maxLength": 255
            },
            "postalCode": {
                "type": "string",
                "description": "Postal code",
                "maxLength": 20
            },
            "city": {
                "type": "string",
                "description": "City name",
                "maxLength": 100
            },
            "region": {
                "type": ["string", "null"],
                "description": "Region, province, or state",
                "maxLength": 100
            },
            "countryCode": {
                "type": "string",
                "description": "ISO 3166-1 alpha-2 country code",
                "pattern": "^[A-Z]{2}$"
            }
        },
        "required": ["streetAddress", "postalCode", "city", "countryCode"],
        "examples": [
            {
                "streetAddress": "Unter den Linden 77",
                "streetAddress2": null,
                "postalCode": "10117",
                "city": "Berlin",
                "region": null,
                "countryCode": "DE"
            },
            {
                "streetAddress": "55 Rue du Faubourg Saint-Honore",
                "streetAddress2": null,
                "postalCode": "75008",
                "city": "Paris",
                "region": "Ile-de-France",
                "countryCode": "FR"
            }
        ]
    }',
    ARRAY['address', 'composite', 'europe', 'european'],
    true,
    true
);

-- =============================================================================
-- ADDRESS WITH GEOLOCATION
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'geoAddress',
    'Address with latitude and longitude coordinates.',
    'address',
    '{
        "type": "object",
        "description": "Address with geolocation coordinates",
        "properties": {
            "streetAddress": {
                "type": "string",
                "description": "Street address",
                "maxLength": 255
            },
            "streetAddress2": {
                "type": ["string", "null"],
                "description": "Secondary address line",
                "maxLength": 255
            },
            "city": {
                "type": "string",
                "description": "City name",
                "maxLength": 100
            },
            "state": {
                "type": ["string", "null"],
                "description": "State or province",
                "maxLength": 100
            },
            "postalCode": {
                "type": "string",
                "description": "Postal code",
                "maxLength": 20
            },
            "country": {
                "type": "string",
                "description": "Country name",
                "maxLength": 100
            },
            "countryCode": {
                "type": "string",
                "description": "ISO 3166-1 alpha-2 country code",
                "pattern": "^[A-Z]{2}$"
            },
            "latitude": {
                "type": ["number", "null"],
                "description": "Latitude coordinate",
                "minimum": -90,
                "maximum": 90
            },
            "longitude": {
                "type": ["number", "null"],
                "description": "Longitude coordinate",
                "minimum": -180,
                "maximum": 180
            },
            "accuracy": {
                "type": ["string", "null"],
                "description": "Geocoding accuracy level",
                "enum": ["rooftop", "rangeInterpolated", "geometric", "approximate", null]
            }
        },
        "required": ["streetAddress", "city", "postalCode", "country", "countryCode"],
        "examples": [
            {
                "streetAddress": "1600 Amphitheatre Parkway",
                "streetAddress2": null,
                "city": "Mountain View",
                "state": "CA",
                "postalCode": "94043",
                "country": "United States",
                "countryCode": "US",
                "latitude": 37.4220656,
                "longitude": -122.0840897,
                "accuracy": "rooftop"
            }
        ]
    }',
    ARRAY['address', 'composite', 'geolocation', 'coordinates'],
    true,
    true
);

-- =============================================================================
-- ADDRESS TYPE AND LABEL FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'addressType',
    'Type classification for an address.',
    'address',
    '{
        "type": "string",
        "description": "Type of address",
        "enum": ["home", "work", "billing", "shipping", "mailing", "headquarters", "branch", "warehouse", "other"],
        "examples": ["home", "work", "billing"],
        "default": "home"
    }',
    ARRAY['address', 'type', 'enum', 'classification'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'addressLabel',
    'Custom label for an address.',
    'address',
    '{
        "type": ["string", "null"],
        "description": "Custom label for the address",
        "examples": ["Main Office", "Summer House", "Parents Home", null],
        "maxLength": 100
    }',
    ARRAY['address', 'label', 'custom', 'nullable'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'labeledAddress',
    'Address with type and custom label.',
    'address',
    '{
        "type": "object",
        "description": "Address with type classification and label",
        "properties": {
            "type": {
                "type": "string",
                "description": "Address type",
                "enum": ["home", "work", "billing", "shipping", "mailing", "headquarters", "branch", "warehouse", "other"],
                "default": "home"
            },
            "label": {
                "type": ["string", "null"],
                "description": "Custom label",
                "maxLength": 100
            },
            "isPrimary": {
                "type": "boolean",
                "description": "Whether this is the primary address",
                "default": false
            },
            "streetAddress": {
                "type": "string",
                "description": "Street address",
                "maxLength": 255
            },
            "streetAddress2": {
                "type": ["string", "null"],
                "description": "Secondary address line",
                "maxLength": 255
            },
            "city": {
                "type": "string",
                "description": "City name",
                "maxLength": 100
            },
            "state": {
                "type": ["string", "null"],
                "description": "State or province",
                "maxLength": 100
            },
            "postalCode": {
                "type": "string",
                "description": "Postal code",
                "maxLength": 20
            },
            "country": {
                "type": "string",
                "description": "Country name or code",
                "maxLength": 100
            }
        },
        "required": ["type", "streetAddress", "city", "postalCode", "country"],
        "examples": [
            {
                "type": "work",
                "label": "Main Office",
                "isPrimary": true,
                "streetAddress": "123 Business Ave",
                "streetAddress2": "Floor 10",
                "city": "San Francisco",
                "state": "CA",
                "postalCode": "94105",
                "country": "US"
            }
        ]
    }',
    ARRAY['address', 'composite', 'labeled', 'typed'],
    true,
    true
);

-- =============================================================================
-- ADDRESS VALIDATION STATUS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'addressValidationStatus',
    'Validation status for an address.',
    'address',
    '{
        "type": "string",
        "description": "Address validation status",
        "enum": ["unvalidated", "valid", "invalid", "corrected", "partial", "unknown"],
        "examples": ["unvalidated", "valid", "corrected"],
        "default": "unvalidated"
    }',
    ARRAY['address', 'validation', 'status', 'enum'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'validatedAddress',
    'Address with validation status and metadata.',
    'address',
    '{
        "type": "object",
        "description": "Address with validation information",
        "properties": {
            "original": {
                "type": "object",
                "description": "Original address as entered",
                "properties": {
                    "streetAddress": {"type": "string"},
                    "city": {"type": "string"},
                    "state": {"type": ["string", "null"]},
                    "postalCode": {"type": "string"},
                    "country": {"type": "string"}
                }
            },
            "standardized": {
                "type": ["object", "null"],
                "description": "Standardized/corrected address",
                "properties": {
                    "streetAddress": {"type": "string"},
                    "city": {"type": "string"},
                    "state": {"type": ["string", "null"]},
                    "postalCode": {"type": "string"},
                    "country": {"type": "string"}
                }
            },
            "validationStatus": {
                "type": "string",
                "description": "Validation result",
                "enum": ["unvalidated", "valid", "invalid", "corrected", "partial", "unknown"]
            },
            "validatedAt": {
                "type": ["string", "null"],
                "format": "date-time",
                "description": "When validation was performed"
            },
            "validationSource": {
                "type": ["string", "null"],
                "description": "Service used for validation"
            }
        },
        "required": ["original", "validationStatus"],
        "examples": [
            {
                "original": {
                    "streetAddress": "123 Main St",
                    "city": "New York",
                    "state": "NY",
                    "postalCode": "10001",
                    "country": "US"
                },
                "standardized": {
                    "streetAddress": "123 Main Street",
                    "city": "New York",
                    "state": "NY",
                    "postalCode": "10001-1234",
                    "country": "United States"
                },
                "validationStatus": "corrected",
                "validatedAt": "2024-01-15T09:30:00Z",
                "validationSource": "USPS"
            }
        ]
    }',
    ARRAY['address', 'composite', 'validation', 'standardized'],
    true,
    true
);

-- =============================================================================
-- FORMATTED ADDRESS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'formattedAddress',
    'Single-line formatted address string.',
    'address',
    '{
        "type": "string",
        "description": "Single-line formatted address",
        "examples": [
            "123 Main Street, New York, NY 10001, USA",
            "10 Downing Street, London SW1A 2AA, United Kingdom",
            "1600 Pennsylvania Avenue NW, Washington, DC 20500"
        ],
        "maxLength": 500
    }',
    ARRAY['address', 'formatted', 'string', 'display'],
    true,
    true
);

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
    'multilineAddress',
    'Multi-line formatted address for display or printing.',
    'address',
    '{
        "type": "array",
        "description": "Multi-line formatted address",
        "items": {
            "type": "string",
            "maxLength": 255
        },
        "minItems": 1,
        "maxItems": 6,
        "examples": [
            [
                "John Smith",
                "123 Main Street",
                "Apt 4B",
                "New York, NY 10001",
                "United States"
            ]
        ]
    }',
    ARRAY['address', 'formatted', 'multiline', 'display'],
    true,
    true
);
