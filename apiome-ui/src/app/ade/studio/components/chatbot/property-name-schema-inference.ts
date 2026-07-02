/**
 * JSON Schema shape hints from common property names (#277, #278).
 * Used when chat refinement adds a property without an explicit type.
 */

export type InferredPropertySchema = Record<string, unknown>;

export interface InferredPropertyShape {
  /** Keywords merged into the property schema (type, format, minLength, …). */
  schema: InferredPropertySchema;
  /** When true, applyRefinementsToSpec adds the property to `required`. */
  suggestRequired?: boolean;
}

function normalizedPropertyKey(propertyName: string): string {
  return propertyName.trim().toLowerCase().replace(/_/g, '');
}

function schemaAndRequired(key: string): {
  schema: InferredPropertySchema;
  suggestRequired?: boolean;
} {
  switch (key) {
    case 'id':
      return {
        schema: { type: 'string', format: 'uuid' },
        suggestRequired: true,
      };
    case 'uuid':
    case 'guid':
      return { schema: { type: 'string', format: 'uuid' } };

    case 'email':
      return { schema: { type: 'string', format: 'email', maxLength: 254 } };

    case 'password':
    case 'passwd':
      return { schema: { type: 'string', minLength: 8, maxLength: 256 } };

    case 'username':
      return {
        schema: {
          type: 'string',
          minLength: 3,
          maxLength: 64,
          pattern: '^[a-zA-Z0-9._-]+$',
        },
      };

    case 'phone':
    case 'phonenumber':
    case 'mobilenumber':
    case 'telephone':
      return {
        schema: {
          type: 'string',
          pattern: '^\\+?[1-9]\\d{1,14}$',
          minLength: 8,
          maxLength: 16,
        },
      };

    case 'zip':
    case 'zipcode':
    case 'postalcode':
      return {
        schema: {
          type: 'string',
          pattern: '^[A-Za-z0-9][A-Za-z0-9\\-\\s]{2,11}$',
          maxLength: 12,
        },
      };

    case 'url':
    case 'website':
    case 'homepage':
    case 'uri':
      return { schema: { type: 'string', format: 'uri', maxLength: 2048 } };

    case 'createdat':
    case 'updatedat':
    case 'modifiedat':
    case 'deletedat':
      return { schema: { type: 'string', format: 'date-time' } };

    case 'birthdate':
    case 'dateofbirth':
      return { schema: { type: 'string', format: 'date' } };

    case 'age':
      return { schema: { type: 'integer', minimum: 0, maximum: 150 } };

    case 'price':
    case 'amount':
    case 'cost':
    case 'total':
      return { schema: { type: 'number', minimum: 0 } };

    case 'quantity':
    case 'qty':
    case 'stock':
    case 'count':
      return { schema: { type: 'integer', minimum: 0 } };

    case 'rating':
      return { schema: { type: 'number', minimum: 0, maximum: 5 } };

    case 'percentage':
    case 'percent':
      return { schema: { type: 'number', minimum: 0, maximum: 100 } };

    case 'latitude':
    case 'lat':
      return { schema: { type: 'number', minimum: -90, maximum: 90 } };

    case 'longitude':
    case 'lng':
    case 'lon':
      return { schema: { type: 'number', minimum: -180, maximum: 180 } };

    case 'year':
      return { schema: { type: 'integer', minimum: 1970, maximum: 2100 } };

    case 'month':
      return { schema: { type: 'integer', minimum: 1, maximum: 12 } };

    case 'day':
    case 'dayofmonth':
      return { schema: { type: 'integer', minimum: 1, maximum: 31 } };

    case 'isactive':
    case 'enabled':
    case 'disabled':
      return { schema: { type: 'boolean' } };

    case 'description':
    case 'bio':
    case 'notes':
    case 'comment':
    case 'comments':
      return { schema: { type: 'string', maxLength: 10000 } };

    case 'title':
    case 'subject':
      return { schema: { type: 'string', maxLength: 300 } };

    case 'firstname':
    case 'lastname':
    case 'middlename':
      return { schema: { type: 'string', maxLength: 100 } };

    case 'name':
      return { schema: { type: 'string', maxLength: 200 } };

    case 'countrycode':
      return {
        schema: {
          type: 'string',
          pattern: '^[A-Z]{2}$',
          minLength: 2,
          maxLength: 2,
        },
      };

    case 'currencycode':
      return {
        schema: {
          type: 'string',
          pattern: '^[A-Z]{3}$',
          minLength: 3,
          maxLength: 3,
        },
      };

    case 'sku':
      return {
        schema: {
          type: 'string',
          pattern: '^[A-Z0-9][A-Z0-9._-]{2,}$',
          minLength: 3,
          maxLength: 64,
        },
      };

    case 'slug':
      return {
        schema: {
          type: 'string',
          pattern: '^[a-z0-9]+(?:-[a-z0-9]+)*$',
          minLength: 1,
          maxLength: 128,
        },
      };

    default:
      return { schema: {} };
  }
}

/**
 * Schema keywords and optional required hint for a property identified by `propertyName`.
 * Matching is case-insensitive; underscores are ignored so `created_at` matches `createdAt`.
 */
export function inferPropertyShapeFromName(propertyName: string): InferredPropertyShape {
  const key = normalizedPropertyKey(propertyName);
  const { schema, suggestRequired } = schemaAndRequired(key);
  return suggestRequired ? { schema, suggestRequired: true } : { schema };
}

/**
 * Returns only JSON Schema keyword fragments (no required hint).
 * Prefer {@link inferPropertyShapeFromName} when integrating refinement ops.
 */
export function inferSchemaShapeFromPropertyName(propertyName: string): InferredPropertySchema {
  return inferPropertyShapeFromName(propertyName).schema;
}
