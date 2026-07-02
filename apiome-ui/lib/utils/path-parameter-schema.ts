/**
 * Map a Designer class property `data` object to a JSON Schema fragment suitable for
 * OpenAPI ParameterObject.schema (path parameters are limited to primitive/array shapes).
 */
export function propertyDataToParameterSchema(
  propertyData: Record<string, unknown> | undefined
): Record<string, unknown> {
  const data = propertyData || { type: 'string' };
  const type = (data.type as string) || 'string';
  const pathParamTypes = ['string', 'integer', 'number', 'boolean', 'array'];
  const paramType = pathParamTypes.includes(type) ? type : 'string';
  const schema: Record<string, unknown> = { type: paramType, required: true };
  if (data.format != null) schema.format = data.format;
  if (Array.isArray(data.enum)) schema.enum = data.enum;
  if (data.minimum != null) schema.minimum = data.minimum;
  if (data.maximum != null) schema.maximum = data.maximum;
  if (data.minLength != null) schema.minLength = data.minLength;
  if (data.maxLength != null) schema.maxLength = data.maxLength;
  if (data.pattern != null) schema.pattern = data.pattern;
  if (paramType === 'array' && data.items != null) schema.items = data.items;
  return schema;
}
