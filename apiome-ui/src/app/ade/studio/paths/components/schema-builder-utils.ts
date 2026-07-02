export function buildArraySchemaFromCurrent(value: any): Record<string, unknown> {
  if (value && typeof value === 'object') {
    if (value.$ref) {
      return { type: 'array', items: { $ref: value.$ref } };
    }

    if (value.type === 'object') {
      return {
        type: 'array',
        items: {
          ...value,
        },
      };
    }

    if (value.type === 'array' && value.items && typeof value.items === 'object') {
      return {
        type: 'array',
        items: {
          ...value.items,
        },
      };
    }

    if (typeof value.type === 'string' && value.type.length > 0) {
      return { type: 'array', items: { type: value.type } };
    }
  }

  return { type: 'array', items: { type: 'string' } };
}
