/**
 * Section 2.2.1 Color Representations
 * Method nodes (HTTP operations) are color-coded badges attached to path nodes.
 *
 * | Method   | Color  | Common Use Cases              |
 * |----------|--------|-------------------------------|
 * | GET      | Green  | Read, list, search operations |
 * | POST     | Blue   | Create, submit, trigger       |
 * | PUT      | Orange | Full resource replacement     |
 * | PATCH    | Purple | Partial updates               |
 * | DELETE   | Red    | Resource deletion             |
 * | HEAD     | Gray   | Metadata retrieval            |
 * | OPTIONS  | Gray   | CORS preflight                |
 */
export const OPERATION_COLORS: Record<string, string> = {
  GET: '#48BB78',
  POST: '#4299E1',
  PUT: '#ED8936',
  PATCH: '#9F7AEA',
  DELETE: '#F56565',
  HEAD: '#718096',
  OPTIONS: '#718096',
};

export const OPERATION_IDS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'] as const;

/** Label and color for sidebar and dropdowns (Section 2.2.1) */
export const AVAILABLE_OPERATIONS = OPERATION_IDS.map((id) => ({
  id,
  label: id,
  color: OPERATION_COLORS[id],
}));
