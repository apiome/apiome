-- Property Templates: Geolocation Category
-- These templates define common geolocation patterns for storing location coordinates and spatial data
-- Property names are camelCase, alphanumeric only (a-zA-Z0-9)
-- Follows OpenAPI 3.1 / JSON Schema Draft 2020-12 standards

SET search_path TO odb, public;

-- =============================================================================
-- BASIC COORDINATE FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'latitude',
           'Latitude coordinate in decimal degrees. Ranges from -90 (south) to +90 (north).',
           'geolocation',
           '{
               "type": "number",
               "description": "Latitude in decimal degrees",
               "examples": [37.7749, 40.7128, -33.8688, 51.5074, 35.6762],
               "minimum": -90,
               "maximum": 90
           }',
           ARRAY['latitude', 'coordinate', 'decimal-degrees'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'longitude',
           'Longitude coordinate in decimal degrees. Ranges from -180 (west) to +180 (east).',
           'geolocation',
           '{
               "type": "number",
               "description": "Longitude in decimal degrees",
               "examples": [-122.4194, -74.0060, 151.2093, -0.1278, 139.6503],
               "minimum": -180,
               "maximum": 180
           }',
           ARRAY['longitude', 'coordinate', 'decimal-degrees'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'altitude',
           'Altitude or elevation in meters above sea level.',
           'geolocation',
           '{
               "type": ["number", "null"],
               "description": "Altitude in meters above sea level",
               "examples": [10.5, 1609, -400, 8848, null]
           }',
           ARRAY['altitude', 'elevation', 'meters', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'accuracy',
           'Location accuracy radius in meters.',
           'geolocation',
           '{
               "type": ["number", "null"],
               "description": "Location accuracy in meters",
               "examples": [5, 10, 50, 100, null],
               "minimum": 0
           }',
           ARRAY['accuracy', 'precision', 'meters', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'heading',
           'Direction of travel in degrees from true north (0-360).',
           'geolocation',
           '{
               "type": ["number", "null"],
               "description": "Heading in degrees from true north",
               "examples": [0, 90, 180, 270, 45.5, null],
               "minimum": 0,
               "maximum": 360
           }',
           ARRAY['heading', 'bearing', 'direction', 'degrees', 'nullable'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'speed',
           'Speed of movement in meters per second.',
           'geolocation',
           '{
               "type": ["number", "null"],
               "description": "Speed in meters per second",
               "examples": [0, 1.5, 10, 30, null],
               "minimum": 0
           }',
           ARRAY['speed', 'velocity', 'meters-per-second', 'nullable'],
           true,
           true
       );

-- =============================================================================
-- COMPOSITE COORDINATE OBJECTS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'coordinates',
           'Basic latitude and longitude coordinate pair.',
           'geolocation',
           '{
               "type": "object",
               "description": "Geographic coordinates",
               "properties": {
                   "latitude": {
                       "type": "number",
                       "description": "Latitude in decimal degrees",
                       "minimum": -90,
                       "maximum": 90
                   },
                   "longitude": {
                       "type": "number",
                       "description": "Longitude in decimal degrees",
                       "minimum": -180,
                       "maximum": 180
                   }
               },
               "required": ["latitude", "longitude"],
               "examples": [
                   {"latitude": 37.7749, "longitude": -122.4194},
                   {"latitude": 40.7128, "longitude": -74.0060},
                   {"latitude": 51.5074, "longitude": -0.1278}
               ]
           }',
           ARRAY['coordinates', 'point', 'location', 'composite'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'coordinates3d',
           'Three-dimensional coordinates with latitude, longitude, and altitude.',
           'geolocation',
           '{
               "type": "object",
               "description": "3D geographic coordinates",
               "properties": {
                   "latitude": {
                       "type": "number",
                       "description": "Latitude in decimal degrees",
                       "minimum": -90,
                       "maximum": 90
                   },
                   "longitude": {
                       "type": "number",
                       "description": "Longitude in decimal degrees",
                       "minimum": -180,
                       "maximum": 180
                   },
                   "altitude": {
                       "type": ["number", "null"],
                       "description": "Altitude in meters above sea level"
                   }
               },
               "required": ["latitude", "longitude"],
               "examples": [
                   {"latitude": 37.7749, "longitude": -122.4194, "altitude": 16},
                   {"latitude": 27.9881, "longitude": 86.9250, "altitude": 8848}
               ]
           }',
           ARRAY['coordinates', 'point', '3d', 'altitude', 'composite'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'location',
           'Complete location with coordinates and accuracy information.',
           'geolocation',
           '{
               "type": "object",
               "description": "Location with accuracy metadata",
               "properties": {
                   "latitude": {
                       "type": "number",
                       "description": "Latitude in decimal degrees",
                       "minimum": -90,
                       "maximum": 90
                   },
                   "longitude": {
                       "type": "number",
                       "description": "Longitude in decimal degrees",
                       "minimum": -180,
                       "maximum": 180
                   },
                   "altitude": {
                       "type": ["number", "null"],
                       "description": "Altitude in meters"
                   },
                   "accuracy": {
                       "type": ["number", "null"],
                       "description": "Horizontal accuracy in meters",
                       "minimum": 0
                   },
                   "altitudeAccuracy": {
                       "type": ["number", "null"],
                       "description": "Vertical accuracy in meters",
                       "minimum": 0
                   },
                   "timestamp": {
                       "type": ["string", "null"],
                       "format": "date-time",
                       "description": "When location was captured"
                   }
               },
               "required": ["latitude", "longitude"],
               "examples": [
                   {
                       "latitude": 37.7749,
                       "longitude": -122.4194,
                       "altitude": 16,
                       "accuracy": 10,
                       "altitudeAccuracy": 5,
                       "timestamp": "2024-01-15T12:30:00Z"
                   }
               ]
           }',
           ARRAY['location', 'coordinates', 'accuracy', 'composite'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'deviceLocation',
           'Device location with movement information from GPS or similar sensors.',
           'geolocation',
           '{
               "type": "object",
               "description": "Device location with movement data",
               "properties": {
                   "latitude": {
                       "type": "number",
                       "description": "Latitude in decimal degrees",
                       "minimum": -90,
                       "maximum": 90
                   },
                   "longitude": {
                       "type": "number",
                       "description": "Longitude in decimal degrees",
                       "minimum": -180,
                       "maximum": 180
                   },
                   "altitude": {
                       "type": ["number", "null"],
                       "description": "Altitude in meters"
                   },
                   "accuracy": {
                       "type": ["number", "null"],
                       "description": "Horizontal accuracy in meters",
                       "minimum": 0
                   },
                   "heading": {
                       "type": ["number", "null"],
                       "description": "Direction of travel in degrees",
                       "minimum": 0,
                       "maximum": 360
                   },
                   "speed": {
                       "type": ["number", "null"],
                       "description": "Speed in meters per second",
                       "minimum": 0
                   },
                   "timestamp": {
                       "type": "string",
                       "format": "date-time",
                       "description": "When location was captured"
                   },
                   "source": {
                       "type": ["string", "null"],
                       "description": "Location source",
                       "enum": ["gps", "network", "wifi", "cell", "ip", "manual", null]
                   }
               },
               "required": ["latitude", "longitude", "timestamp"],
               "examples": [
                   {
                       "latitude": 37.7749,
                       "longitude": -122.4194,
                       "altitude": 16,
                       "accuracy": 5,
                       "heading": 45.5,
                       "speed": 1.2,
                       "timestamp": "2024-01-15T12:30:00Z",
                       "source": "gps"
                   }
               ]
           }',
           ARRAY['location', 'device', 'gps', 'movement', 'composite'],
           true,
           true
       );

-- =============================================================================
-- GEOJSON FORMATS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'geoJsonPoint',
           'GeoJSON Point geometry for a single location.',
           'geolocation',
           '{
               "type": "object",
               "description": "GeoJSON Point geometry",
               "properties": {
                   "type": {
                       "type": "string",
                       "const": "Point",
                       "description": "GeoJSON geometry type"
                   },
                   "coordinates": {
                       "type": "array",
                       "description": "Coordinates as [longitude, latitude] or [longitude, latitude, altitude]",
                       "items": {
                           "type": "number"
                       },
                       "minItems": 2,
                       "maxItems": 3
                   }
               },
               "required": ["type", "coordinates"],
               "examples": [
                   {"type": "Point", "coordinates": [-122.4194, 37.7749]},
                   {"type": "Point", "coordinates": [-74.0060, 40.7128, 10]}
               ]
           }',
           ARRAY['geojson', 'point', 'geometry', 'standard'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'geoJsonLineString',
           'GeoJSON LineString geometry for a path or route.',
           'geolocation',
           '{
               "type": "object",
               "description": "GeoJSON LineString geometry",
               "properties": {
                   "type": {
                       "type": "string",
                       "const": "LineString",
                       "description": "GeoJSON geometry type"
                   },
                   "coordinates": {
                       "type": "array",
                       "description": "Array of coordinate positions",
                       "items": {
                           "type": "array",
                           "items": {"type": "number"},
                           "minItems": 2,
                           "maxItems": 3
                       },
                       "minItems": 2
                   }
               },
               "required": ["type", "coordinates"],
               "examples": [
                   {
                       "type": "LineString",
                       "coordinates": [
                           [-122.4194, 37.7749],
                           [-122.4089, 37.7855],
                           [-122.3984, 37.7916]
                       ]
                   }
               ]
           }',
           ARRAY['geojson', 'linestring', 'path', 'route', 'geometry'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'geoJsonPolygon',
           'GeoJSON Polygon geometry for an area or region.',
           'geolocation',
           '{
               "type": "object",
               "description": "GeoJSON Polygon geometry",
               "properties": {
                   "type": {
                       "type": "string",
                       "const": "Polygon",
                       "description": "GeoJSON geometry type"
                   },
                   "coordinates": {
                       "type": "array",
                       "description": "Array of linear rings (first is exterior, rest are holes)",
                       "items": {
                           "type": "array",
                           "description": "Linear ring of coordinates",
                           "items": {
                               "type": "array",
                               "items": {"type": "number"},
                               "minItems": 2,
                               "maxItems": 3
                           },
                           "minItems": 4
                       },
                       "minItems": 1
                   }
               },
               "required": ["type", "coordinates"],
               "examples": [
                   {
                       "type": "Polygon",
                       "coordinates": [[
                           [-122.4194, 37.7749],
                           [-122.4089, 37.7749],
                           [-122.4089, 37.7849],
                           [-122.4194, 37.7849],
                           [-122.4194, 37.7749]
                       ]]
                   }
               ]
           }',
           ARRAY['geojson', 'polygon', 'area', 'region', 'geometry'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'geoJsonMultiPoint',
           'GeoJSON MultiPoint geometry for multiple locations.',
           'geolocation',
           '{
               "type": "object",
               "description": "GeoJSON MultiPoint geometry",
               "properties": {
                   "type": {
                       "type": "string",
                       "const": "MultiPoint",
                       "description": "GeoJSON geometry type"
                   },
                   "coordinates": {
                       "type": "array",
                       "description": "Array of point coordinates",
                       "items": {
                           "type": "array",
                           "items": {"type": "number"},
                           "minItems": 2,
                           "maxItems": 3
                       }
                   }
               },
               "required": ["type", "coordinates"],
               "examples": [
                   {
                       "type": "MultiPoint",
                       "coordinates": [
                           [-122.4194, 37.7749],
                           [-74.0060, 40.7128],
                           [-0.1278, 51.5074]
                       ]
                   }
               ]
           }',
           ARRAY['geojson', 'multipoint', 'multiple', 'geometry'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'geoJsonFeature',
           'GeoJSON Feature with geometry and properties.',
           'geolocation',
           '{
               "type": "object",
               "description": "GeoJSON Feature",
               "properties": {
                   "type": {
                       "type": "string",
                       "const": "Feature",
                       "description": "GeoJSON object type"
                   },
                   "geometry": {
                       "type": ["object", "null"],
                       "description": "Geometry object"
                   },
                   "properties": {
                       "type": ["object", "null"],
                       "description": "Feature properties"
                   },
                   "id": {
                       "type": ["string", "number", "null"],
                       "description": "Feature identifier"
                   }
               },
               "required": ["type", "geometry", "properties"],
               "examples": [
                   {
                       "type": "Feature",
                       "geometry": {
                           "type": "Point",
                           "coordinates": [-122.4194, 37.7749]
                       },
                       "properties": {
                           "name": "San Francisco",
                           "population": 873965
                       },
                       "id": "sf-001"
                   }
               ]
           }',
           ARRAY['geojson', 'feature', 'properties', 'standard'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'geoJsonFeatureCollection',
           'GeoJSON FeatureCollection containing multiple features.',
           'geolocation',
           '{
               "type": "object",
               "description": "GeoJSON FeatureCollection",
               "properties": {
                   "type": {
                       "type": "string",
                       "const": "FeatureCollection",
                       "description": "GeoJSON object type"
                   },
                   "features": {
                       "type": "array",
                       "description": "Array of Feature objects",
                       "items": {
                           "type": "object"
                       }
                   }
               },
               "required": ["type", "features"],
               "examples": [
                   {
                       "type": "FeatureCollection",
                       "features": [
                           {
                               "type": "Feature",
                               "geometry": {"type": "Point", "coordinates": [-122.4194, 37.7749]},
                               "properties": {"name": "San Francisco"}
                           },
                           {
                               "type": "Feature",
                               "geometry": {"type": "Point", "coordinates": [-74.0060, 40.7128]},
                               "properties": {"name": "New York"}
                           }
                       ]
                   }
               ]
           }',
           ARRAY['geojson', 'featurecollection', 'collection', 'standard'],
           true,
           true
       );

-- =============================================================================
-- GEOHASH AND ENCODING FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'geohash',
           'Geohash string encoding of a location. Precision varies with length (4-12 characters typical).',
           'geolocation',
           '{
               "type": "string",
               "description": "Geohash encoded location",
               "examples": ["9q8yy", "9q8yyk8", "9q8yyk8yuv", "u4pruydqqvj"],
               "pattern": "^[0-9b-hjkmnp-z]+$",
               "minLength": 1,
               "maxLength": 12
           }',
           ARRAY['geohash', 'encoding', 'spatial-index'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'geohashWithPrecision',
           'Geohash with explicit precision level.',
           'geolocation',
           '{
               "type": "object",
               "description": "Geohash with precision information",
               "properties": {
                   "hash": {
                       "type": "string",
                       "description": "Geohash string",
                       "pattern": "^[0-9b-hjkmnp-z]+$",
                       "maxLength": 12
                   },
                   "precision": {
                       "type": "integer",
                       "description": "Geohash precision (character length)",
                       "minimum": 1,
                       "maximum": 12
                   },
                   "approximateAccuracy": {
                       "type": ["number", "null"],
                       "description": "Approximate accuracy in meters"
                   }
               },
               "required": ["hash", "precision"],
               "examples": [
                   {"hash": "9q8yyk8", "precision": 7, "approximateAccuracy": 76},
                   {"hash": "9q8yyk8yuv", "precision": 10, "approximateAccuracy": 0.6}
               ]
           }',
           ARRAY['geohash', 'encoding', 'precision', 'composite'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'h3Index',
           'H3 hexagonal hierarchical spatial index.',
           'geolocation',
           '{
               "type": "string",
               "description": "H3 index string",
               "examples": ["8928308280fffff", "8a2a1072b59ffff", "8f2830828052d25"],
               "pattern": "^[0-9a-f]{15}$",
               "minLength": 15,
               "maxLength": 15
           }',
           ARRAY['h3', 'index', 'hexagonal', 'uber'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'h3IndexWithResolution',
           'H3 index with resolution level.',
           'geolocation',
           '{
               "type": "object",
               "description": "H3 index with resolution",
               "properties": {
                   "index": {
                       "type": "string",
                       "description": "H3 index string",
                       "pattern": "^[0-9a-f]{15}$"
                   },
                   "resolution": {
                       "type": "integer",
                       "description": "H3 resolution (0-15)",
                       "minimum": 0,
                       "maximum": 15
                   }
               },
               "required": ["index", "resolution"],
               "examples": [
                   {"index": "8928308280fffff", "resolution": 9},
                   {"index": "8f2830828052d25", "resolution": 15}
               ]
           }',
           ARRAY['h3', 'index', 'resolution', 'composite'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           's2CellId',
           'S2 geometry cell identifier.',
           'geolocation',
           '{
               "type": "string",
               "description": "S2 cell ID",
               "examples": ["89c25a31", "89c25a3100000000"],
               "pattern": "^[0-9a-f]+$",
               "minLength": 1,
               "maxLength": 16
           }',
           ARRAY['s2', 'cell', 'index', 'google'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'plusCode',
           'Plus Code (Open Location Code) for location encoding.',
           'geolocation',
           '{
               "type": "string",
               "description": "Plus Code (Open Location Code)",
               "examples": ["849VCWC8+R9", "87G8Q2PQ+VX", "7FG8V6PW+QR"],
               "pattern": "^[23456789CFGHJMPQRVWX]{8}\\+[23456789CFGHJMPQRVWX]{2,}$"
           }',
           ARRAY['pluscode', 'olc', 'open-location-code', 'google'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'what3words',
           'what3words address (three word location).',
           'geolocation',
           '{
               "type": "string",
               "description": "what3words address",
               "examples": ["filled.count.soap", "index.home.raft", "daring.lion.race"],
               "pattern": "^[a-z]+\\.[a-z]+\\.[a-z]+$"
           }',
           ARRAY['what3words', 'w3w', 'three-words'],
           true,
           true
       );

-- =============================================================================
-- GEOCODING FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'geocodeResult',
           'Result from geocoding an address to coordinates.',
           'geolocation',
           '{
               "type": "object",
               "description": "Geocoding result",
               "properties": {
                   "latitude": {
                       "type": "number",
                       "description": "Latitude",
                       "minimum": -90,
                       "maximum": 90
                   },
                   "longitude": {
                       "type": "number",
                       "description": "Longitude",
                       "minimum": -180,
                       "maximum": 180
                   },
                   "formattedAddress": {
                       "type": ["string", "null"],
                       "description": "Formatted address from geocoder"
                   },
                   "accuracy": {
                       "type": "string",
                       "description": "Geocoding accuracy level",
                       "enum": ["rooftop", "rangeInterpolated", "geometricCenter", "approximate"]
                   },
                   "confidence": {
                       "type": ["number", "null"],
                       "description": "Confidence score (0-1)",
                       "minimum": 0,
                       "maximum": 1
                   },
                   "source": {
                       "type": ["string", "null"],
                       "description": "Geocoding service used"
                   }
               },
               "required": ["latitude", "longitude", "accuracy"],
               "examples": [
                   {
                       "latitude": 37.7749,
                       "longitude": -122.4194,
                       "formattedAddress": "San Francisco, CA, USA",
                       "accuracy": "rooftop",
                       "confidence": 0.95,
                       "source": "google"
                   }
               ]
           }',
           ARRAY['geocode', 'result', 'address', 'conversion'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'reverseGeocodeResult',
           'Result from reverse geocoding coordinates to an address.',
           'geolocation',
           '{
               "type": "object",
               "description": "Reverse geocoding result",
               "properties": {
                   "formattedAddress": {
                       "type": "string",
                       "description": "Full formatted address"
                   },
                   "streetNumber": {
                       "type": ["string", "null"],
                       "description": "Street number"
                   },
                   "street": {
                       "type": ["string", "null"],
                       "description": "Street name"
                   },
                   "neighborhood": {
                       "type": ["string", "null"],
                       "description": "Neighborhood"
                   },
                   "city": {
                       "type": ["string", "null"],
                       "description": "City"
                   },
                   "county": {
                       "type": ["string", "null"],
                       "description": "County"
                   },
                   "state": {
                       "type": ["string", "null"],
                       "description": "State or province"
                   },
                   "stateCode": {
                       "type": ["string", "null"],
                       "description": "State code"
                   },
                   "postalCode": {
                       "type": ["string", "null"],
                       "description": "Postal code"
                   },
                   "country": {
                       "type": ["string", "null"],
                       "description": "Country name"
                   },
                   "countryCode": {
                       "type": ["string", "null"],
                       "description": "ISO country code",
                       "pattern": "^[A-Z]{2}$"
                   }
               },
               "required": ["formattedAddress"],
               "examples": [
                   {
                       "formattedAddress": "1600 Amphitheatre Parkway, Mountain View, CA 94043, USA",
                       "streetNumber": "1600",
                       "street": "Amphitheatre Parkway",
                       "neighborhood": null,
                       "city": "Mountain View",
                       "county": "Santa Clara County",
                       "state": "California",
                       "stateCode": "CA",
                       "postalCode": "94043",
                       "country": "United States",
                       "countryCode": "US"
                   }
               ]
           }',
           ARRAY['geocode', 'reverse', 'address', 'result'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'geocodeAccuracy',
           'Accuracy level of geocoding result.',
           'geolocation',
           '{
               "type": "string",
               "description": "Geocoding accuracy level",
               "enum": ["rooftop", "parcel", "rangeInterpolated", "intersection", "geometricCenter", "approximate", "postalCode", "city", "state", "country"],
               "examples": ["rooftop", "geometricCenter", "approximate"]
           }',
           ARRAY['geocode', 'accuracy', 'enum'],
           true,
           true
       );

-- =============================================================================
-- BOUNDING BOX AND AREA FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'boundingBox',
           'Rectangular bounding box defined by corner coordinates.',
           'geolocation',
           '{
               "type": "object",
               "description": "Geographic bounding box",
               "properties": {
                   "north": {
                       "type": "number",
                       "description": "North latitude (top)",
                       "minimum": -90,
                       "maximum": 90
                   },
                   "south": {
                       "type": "number",
                       "description": "South latitude (bottom)",
                       "minimum": -90,
                       "maximum": 90
                   },
                   "east": {
                       "type": "number",
                       "description": "East longitude (right)",
                       "minimum": -180,
                       "maximum": 180
                   },
                   "west": {
                       "type": "number",
                       "description": "West longitude (left)",
                       "minimum": -180,
                       "maximum": 180
                   }
               },
               "required": ["north", "south", "east", "west"],
               "examples": [
                   {
                       "north": 37.8,
                       "south": 37.7,
                       "east": -122.35,
                       "west": -122.5
                   }
               ]
           }',
           ARRAY['bounding-box', 'bounds', 'rectangle', 'area'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'boundingBoxArray',
           'Bounding box as array [west, south, east, north] (GeoJSON bbox format).',
           'geolocation',
           '{
               "type": "array",
               "description": "Bounding box as [west, south, east, north]",
               "items": {
                   "type": "number"
               },
               "minItems": 4,
               "maxItems": 4,
               "examples": [
                   [-122.5, 37.7, -122.35, 37.8],
                   [-74.1, 40.6, -73.9, 40.9]
               ]
           }',
           ARRAY['bounding-box', 'bbox', 'array', 'geojson'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'viewport',
           'Map viewport with center, zoom, and bounds.',
           'geolocation',
           '{
               "type": "object",
               "description": "Map viewport configuration",
               "properties": {
                   "center": {
                       "type": "object",
                       "description": "Center point",
                       "properties": {
                           "latitude": {"type": "number", "minimum": -90, "maximum": 90},
                           "longitude": {"type": "number", "minimum": -180, "maximum": 180}
                       },
                       "required": ["latitude", "longitude"]
                   },
                   "zoom": {
                       "type": "number",
                       "description": "Zoom level",
                       "minimum": 0,
                       "maximum": 22
                   },
                   "bounds": {
                       "type": ["object", "null"],
                       "description": "Bounding box",
                       "properties": {
                           "north": {"type": "number"},
                           "south": {"type": "number"},
                           "east": {"type": "number"},
                           "west": {"type": "number"}
                       }
                   }
               },
               "required": ["center", "zoom"],
               "examples": [
                   {
                       "center": {"latitude": 37.7749, "longitude": -122.4194},
                       "zoom": 12,
                       "bounds": {"north": 37.8, "south": 37.7, "east": -122.35, "west": -122.5}
                   }
               ]
           }',
           ARRAY['viewport', 'map', 'zoom', 'center', 'bounds'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'circle',
           'Circular area defined by center point and radius.',
           'geolocation',
           '{
               "type": "object",
               "description": "Circular geographic area",
               "properties": {
                   "center": {
                       "type": "object",
                       "description": "Center point",
                       "properties": {
                           "latitude": {"type": "number", "minimum": -90, "maximum": 90},
                           "longitude": {"type": "number", "minimum": -180, "maximum": 180}
                       },
                       "required": ["latitude", "longitude"]
                   },
                   "radius": {
                       "type": "number",
                       "description": "Radius in meters",
                       "minimum": 0
                   }
               },
               "required": ["center", "radius"],
               "examples": [
                   {
                       "center": {"latitude": 37.7749, "longitude": -122.4194},
                       "radius": 1000
                   }
               ]
           }',
           ARRAY['circle', 'radius', 'area', 'geofence'],
           true,
           true
       );

-- =============================================================================
-- DISTANCE AND MEASUREMENT FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'distance',
           'Distance measurement with value and unit.',
           'geolocation',
           '{
               "type": "object",
               "description": "Distance measurement",
               "properties": {
                   "value": {
                       "type": "number",
                       "description": "Distance value",
                       "minimum": 0
                   },
                   "unit": {
                       "type": "string",
                       "description": "Distance unit",
                       "enum": ["meters", "kilometers", "feet", "miles", "nauticalMiles"],
                       "default": "meters"
                   }
               },
               "required": ["value", "unit"],
               "examples": [
                   {"value": 1500, "unit": "meters"},
                   {"value": 2.5, "unit": "kilometers"},
                   {"value": 10, "unit": "miles"}
               ]
           }',
           ARRAY['distance', 'measurement', 'unit'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'distanceMeters',
           'Distance in meters.',
           'geolocation',
           '{
               "type": "number",
               "description": "Distance in meters",
               "examples": [100, 1500, 10000],
               "minimum": 0
           }',
           ARRAY['distance', 'meters', 'metric'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'distanceKilometers',
           'Distance in kilometers.',
           'geolocation',
           '{
               "type": "number",
               "description": "Distance in kilometers",
               "examples": [0.5, 5, 100],
               "minimum": 0
           }',
           ARRAY['distance', 'kilometers', 'metric'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'distanceMiles',
           'Distance in miles.',
           'geolocation',
           '{
               "type": "number",
               "description": "Distance in miles",
               "examples": [0.5, 5, 100],
               "minimum": 0
           }',
           ARRAY['distance', 'miles', 'imperial'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'area',
           'Area measurement with value and unit.',
           'geolocation',
           '{
               "type": "object",
               "description": "Area measurement",
               "properties": {
                   "value": {
                       "type": "number",
                       "description": "Area value",
                       "minimum": 0
                   },
                   "unit": {
                       "type": "string",
                       "description": "Area unit",
                       "enum": ["squareMeters", "squareKilometers", "squareFeet", "squareMiles", "acres", "hectares"],
                       "default": "squareMeters"
                   }
               },
               "required": ["value", "unit"],
               "examples": [
                   {"value": 1000, "unit": "squareMeters"},
                   {"value": 2.5, "unit": "hectares"},
                   {"value": 10, "unit": "acres"}
               ]
           }',
           ARRAY['area', 'measurement', 'unit'],
           true,
           true
       );

-- =============================================================================
-- PLACE AND LOCATION REFERENCE FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'placeId',
           'Place identifier from a mapping service (e.g., Google Places).',
           'geolocation',
           '{
               "type": "string",
               "description": "Place identifier from mapping service",
               "examples": ["ChIJIQBpAG2ahYAR_6128GcTUEo", "ChIJOwg_06VPwokRYv534QaPC8g"],
               "minLength": 1,
               "maxLength": 255
           }',
           ARRAY['place', 'id', 'reference', 'google'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'placeInfo',
           'Place information with ID, name, and location.',
           'geolocation',
           '{
               "type": "object",
               "description": "Place information",
               "properties": {
                   "placeId": {
                       "type": ["string", "null"],
                       "description": "Place identifier"
                   },
                   "name": {
                       "type": "string",
                       "description": "Place name"
                   },
                   "address": {
                       "type": ["string", "null"],
                       "description": "Formatted address"
                   },
                   "latitude": {
                       "type": "number",
                       "description": "Latitude",
                       "minimum": -90,
                       "maximum": 90
                   },
                   "longitude": {
                       "type": "number",
                       "description": "Longitude",
                       "minimum": -180,
                       "maximum": 180
                   },
                   "types": {
                       "type": "array",
                       "description": "Place type categories",
                       "items": {"type": "string"}
                   }
               },
               "required": ["name", "latitude", "longitude"],
               "examples": [
                   {
                       "placeId": "ChIJIQBpAG2ahYAR_6128GcTUEo",
                       "name": "Googleplex",
                       "address": "1600 Amphitheatre Parkway, Mountain View, CA 94043",
                       "latitude": 37.4220656,
                       "longitude": -122.0840897,
                       "types": ["establishment", "point_of_interest"]
                   }
               ]
           }',
           ARRAY['place', 'info', 'poi', 'composite'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'timezone',
           'IANA timezone identifier for a location.',
           'geolocation',
           '{
               "type": "string",
               "description": "IANA timezone identifier",
               "examples": ["America/Los_Angeles", "Europe/London", "Asia/Tokyo", "UTC"],
               "minLength": 1,
               "maxLength": 50
           }',
           ARRAY['timezone', 'iana', 'time'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'timezoneInfo',
           'Timezone information with offset and DST status.',
           'geolocation',
           '{
               "type": "object",
               "description": "Timezone information",
               "properties": {
                   "id": {
                       "type": "string",
                       "description": "IANA timezone identifier"
                   },
                   "name": {
                       "type": "string",
                       "description": "Timezone display name"
                   },
                   "offsetMinutes": {
                       "type": "integer",
                       "description": "UTC offset in minutes"
                   },
                   "offsetString": {
                       "type": "string",
                       "description": "UTC offset string (e.g., -08:00)"
                   },
                   "isDst": {
                       "type": "boolean",
                       "description": "Whether DST is currently active"
                   },
                   "abbreviation": {
                       "type": ["string", "null"],
                       "description": "Timezone abbreviation (e.g., PST, EST)"
                   }
               },
               "required": ["id", "offsetMinutes"],
               "examples": [
                   {
                       "id": "America/Los_Angeles",
                       "name": "Pacific Time",
                       "offsetMinutes": -480,
                       "offsetString": "-08:00",
                       "isDst": false,
                       "abbreviation": "PST"
                   }
               ]
           }',
           ARRAY['timezone', 'offset', 'dst', 'composite'],
           true,
           true
       );

-- =============================================================================
-- ROUTE AND NAVIGATION FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'routeWaypoint',
           'Single waypoint in a route.',
           'geolocation',
           '{
               "type": "object",
               "description": "Route waypoint",
               "properties": {
                   "latitude": {
                       "type": "number",
                       "description": "Latitude",
                       "minimum": -90,
                       "maximum": 90
                   },
                   "longitude": {
                       "type": "number",
                       "description": "Longitude",
                       "minimum": -180,
                       "maximum": 180
                   },
                   "name": {
                       "type": ["string", "null"],
                       "description": "Waypoint name or label"
                   },
                   "stopover": {
                       "type": "boolean",
                       "description": "Whether this is a stop (vs pass-through)",
                       "default": true
                   },
                   "order": {
                       "type": ["integer", "null"],
                       "description": "Order in route sequence"
                   }
               },
               "required": ["latitude", "longitude"],
               "examples": [
                   {
                       "latitude": 37.7749,
                       "longitude": -122.4194,
                       "name": "Start",
                       "stopover": true,
                       "order": 0
                   }
               ]
           }',
           ARRAY['waypoint', 'route', 'navigation', 'stop'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'routeSummary',
           'Summary information for a route.',
           'geolocation',
           '{
               "type": "object",
               "description": "Route summary",
               "properties": {
                   "origin": {
                       "type": "object",
                       "description": "Starting point",
                       "properties": {
                           "latitude": {"type": "number", "minimum": -90, "maximum": 90},
                           "longitude": {"type": "number", "minimum": -180, "maximum": 180},
                           "name": {"type": ["string", "null"]}
                       },
                       "required": ["latitude", "longitude"]
                   },
                   "destination": {
                       "type": "object",
                       "description": "End point",
                       "properties": {
                           "latitude": {"type": "number", "minimum": -90, "maximum": 90},
                           "longitude": {"type": "number", "minimum": -180, "maximum": 180},
                           "name": {"type": ["string", "null"]}
                       },
                       "required": ["latitude", "longitude"]
                   },
                   "distanceMeters": {
                       "type": "number",
                       "description": "Total distance in meters",
                       "minimum": 0
                   },
                   "durationSeconds": {
                       "type": "number",
                       "description": "Estimated duration in seconds",
                       "minimum": 0
                   },
                   "waypointCount": {
                       "type": "integer",
                       "description": "Number of waypoints",
                       "minimum": 0
                   }
               },
               "required": ["origin", "destination", "distanceMeters", "durationSeconds"],
               "examples": [
                   {
                       "origin": {"latitude": 37.7749, "longitude": -122.4194, "name": "San Francisco"},
                       "destination": {"latitude": 34.0522, "longitude": -118.2437, "name": "Los Angeles"},
                       "distanceMeters": 616000,
                       "durationSeconds": 21600,
                       "waypointCount": 0
                   }
               ]
           }',
           ARRAY['route', 'summary', 'navigation', 'distance', 'duration'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'encodedPolyline',
           'Encoded polyline string representing a path (Google Polyline Algorithm).',
           'geolocation',
           '{
               "type": "string",
               "description": "Encoded polyline string",
               "examples": ["_p~iF~ps|U_ulLnnqC_mqNvxq`@", "mz}bHrxnhVjAaBdBmC"],
               "minLength": 1
           }',
           ARRAY['polyline', 'encoded', 'path', 'route'],
           true,
           true
       );

-- =============================================================================
-- GEOFENCE FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'geofence',
           'Geofence definition with shape and metadata.',
           'geolocation',
           '{
               "type": "object",
               "description": "Geofence definition",
               "properties": {
                   "id": {
                       "type": "string",
                       "description": "Geofence identifier"
                   },
                   "name": {
                       "type": "string",
                       "description": "Geofence name"
                   },
                   "type": {
                       "type": "string",
                       "description": "Geofence shape type",
                       "enum": ["circle", "polygon", "rectangle"]
                   },
                   "geometry": {
                       "type": "object",
                       "description": "Geofence geometry (varies by type)"
                   },
                   "isActive": {
                       "type": "boolean",
                       "description": "Whether geofence is active",
                       "default": true
                   },
                   "metadata": {
                       "type": ["object", "null"],
                       "description": "Additional metadata"
                   }
               },
               "required": ["id", "name", "type", "geometry"],
               "examples": [
                   {
                       "id": "gf-001",
                       "name": "Office Zone",
                       "type": "circle",
                       "geometry": {
                           "center": {"latitude": 37.7749, "longitude": -122.4194},
                           "radius": 100
                       },
                       "isActive": true,
                       "metadata": {"alertOnEnter": true, "alertOnExit": true}
                   }
               ]
           }',
           ARRAY['geofence', 'zone', 'boundary', 'trigger'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'geofenceEvent',
           'Geofence trigger event.',
           'geolocation',
           '{
               "type": "object",
               "description": "Geofence trigger event",
               "properties": {
                   "geofenceId": {
                       "type": "string",
                       "description": "Geofence identifier"
                   },
                   "eventType": {
                       "type": "string",
                       "description": "Event type",
                       "enum": ["enter", "exit", "dwell"]
                   },
                   "timestamp": {
                       "type": "string",
                       "format": "date-time",
                       "description": "When event occurred"
                   },
                   "location": {
                       "type": "object",
                       "description": "Location at time of event",
                       "properties": {
                           "latitude": {"type": "number", "minimum": -90, "maximum": 90},
                           "longitude": {"type": "number", "minimum": -180, "maximum": 180}
                       },
                       "required": ["latitude", "longitude"]
                   },
                   "dwellTimeSeconds": {
                       "type": ["integer", "null"],
                       "description": "Time spent in geofence (for dwell events)",
                       "minimum": 0
                   }
               },
               "required": ["geofenceId", "eventType", "timestamp", "location"],
               "examples": [
                   {
                       "geofenceId": "gf-001",
                       "eventType": "enter",
                       "timestamp": "2024-01-15T09:30:00Z",
                       "location": {"latitude": 37.7749, "longitude": -122.4194},
                       "dwellTimeSeconds": null
                   }
               ]
           }',
           ARRAY['geofence', 'event', 'trigger', 'enter', 'exit'],
           true,
           true
       );

-- =============================================================================
-- LOCATION HISTORY FIELDS
-- =============================================================================

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'locationHistory',
           'Array of timestamped location points.',
           'geolocation',
           '{
               "type": "array",
               "description": "Location history",
               "items": {
                   "type": "object",
                   "properties": {
                       "latitude": {"type": "number", "minimum": -90, "maximum": 90},
                       "longitude": {"type": "number", "minimum": -180, "maximum": 180},
                       "timestamp": {"type": "string", "format": "date-time"},
                       "accuracy": {"type": ["number", "null"], "minimum": 0}
                   },
                   "required": ["latitude", "longitude", "timestamp"]
               },
               "examples": [
                   [
                       {"latitude": 37.7749, "longitude": -122.4194, "timestamp": "2024-01-15T09:00:00Z", "accuracy": 10},
                       {"latitude": 37.7850, "longitude": -122.4094, "timestamp": "2024-01-15T09:30:00Z", "accuracy": 15},
                       {"latitude": 37.7950, "longitude": -122.3994, "timestamp": "2024-01-15T10:00:00Z", "accuracy": 8}
                   ]
               ]
           }',
           ARRAY['location', 'history', 'track', 'array'],
           true,
           true
       );

INSERT INTO property_templates (name, description, category, schema, tags, is_system, is_public)
VALUES (
           'locationTrack',
           'Location track with metadata and statistics.',
           'geolocation',
           '{
               "type": "object",
               "description": "Location track with metadata",
               "properties": {
                   "id": {
                       "type": "string",
                       "description": "Track identifier"
                   },
                   "name": {
                       "type": ["string", "null"],
                       "description": "Track name"
                   },
                   "startTime": {
                       "type": "string",
                       "format": "date-time",
                       "description": "Track start time"
                   },
                   "endTime": {
                       "type": ["string", "null"],
                       "format": "date-time",
                       "description": "Track end time"
                   },
                   "points": {
                       "type": "array",
                       "description": "Track points",
                       "items": {
                           "type": "object",
                           "properties": {
                               "latitude": {"type": "number"},
                               "longitude": {"type": "number"},
                               "timestamp": {"type": "string", "format": "date-time"},
                               "altitude": {"type": ["number", "null"]},
                               "speed": {"type": ["number", "null"]}
                           },
                           "required": ["latitude", "longitude", "timestamp"]
                       }
                   },
                   "totalDistanceMeters": {
                       "type": ["number", "null"],
                       "description": "Total distance traveled",
                       "minimum": 0
                   },
                   "durationSeconds": {
                       "type": ["number", "null"],
                       "description": "Total duration",
                       "minimum": 0
                   },
                   "bounds": {
                       "type": ["object", "null"],
                       "description": "Bounding box of track",
                       "properties": {
                           "north": {"type": "number"},
                           "south": {"type": "number"},
                           "east": {"type": "number"},
                           "west": {"type": "number"}
                       }
                   }
               },
               "required": ["id", "startTime", "points"],
               "examples": [
                   {
                       "id": "track-001",
                       "name": "Morning Run",
                       "startTime": "2024-01-15T07:00:00Z",
                       "endTime": "2024-01-15T07:45:00Z",
                       "points": [
                           {"latitude": 37.7749, "longitude": -122.4194, "timestamp": "2024-01-15T07:00:00Z", "altitude": 10, "speed": 0},
                           {"latitude": 37.7849, "longitude": -122.4094, "timestamp": "2024-01-15T07:15:00Z", "altitude": 15, "speed": 3.5}
                       ],
                       "totalDistanceMeters": 5000,
                       "durationSeconds": 2700,
                       "bounds": {"north": 37.79, "south": 37.77, "east": -122.40, "west": -122.42}
                   }
               ]
           }',
           ARRAY['location', 'track', 'gps', 'history', 'composite'],
           true,
           true
       );