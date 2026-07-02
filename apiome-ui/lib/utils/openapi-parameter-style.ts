import type { ParameterInLocation } from './openapi-parameter-name';

/** Serialization `style` values allowed by OpenAPI 3.x per `in` (see Parameter Object). */
export type QueryParamStyle = 'form' | 'spaceDelimited' | 'pipeDelimited' | 'deepObject';
export type PathParamStyle = 'simple' | 'label' | 'matrix';
export type HeaderParamStyle = 'simple';
export type CookieParamStyle = 'form';

export type ParamSerializationStyle =
  | QueryParamStyle
  | PathParamStyle
  | HeaderParamStyle
  | CookieParamStyle;

export const PARAM_STYLE_OPTIONS: Record<
  ParameterInLocation,
  readonly { value: ParamSerializationStyle; label: string }[]
> = {
  path: [
    { value: 'simple', label: 'simple' },
    { value: 'label', label: 'label' },
    { value: 'matrix', label: 'matrix' },
  ],
  query: [
    { value: 'form', label: 'form' },
    { value: 'spaceDelimited', label: 'spaceDelimited' },
    { value: 'pipeDelimited', label: 'pipeDelimited' },
    { value: 'deepObject', label: 'deepObject' },
  ],
  header: [{ value: 'simple', label: 'simple' }],
  cookie: [{ value: 'form', label: 'form' }],
};

export function defaultStyleForIn(inLocation: ParameterInLocation): ParamSerializationStyle {
  switch (inLocation) {
    case 'path':
      return 'simple';
    case 'query':
      return 'form';
    case 'header':
      return 'simple';
    case 'cookie':
      return 'form';
  }
}

/** Coerce stored `style` to a value valid for the current `in` location. */
export function normalizeStyleForLocation(
  inLocation: ParameterInLocation,
  style: string | undefined
): ParamSerializationStyle {
  const allowed = PARAM_STYLE_OPTIONS[inLocation].map((o) => o.value);
  if (style && (allowed as string[]).includes(style)) {
    return style as ParamSerializationStyle;
  }
  return defaultStyleForIn(inLocation);
}
