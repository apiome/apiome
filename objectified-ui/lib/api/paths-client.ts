/**
 * REST API Client for Path operations
 * 
 * This module provides functions to interact with the paths REST API
 * for path, operation, parameter, request body, and response CRUD operations.
 * 
 * All requests are proxied through Next.js API routes which handle authentication.
 */

// ==================== Types ====================

export interface PathData {
  id: string;
  version_id: string;
  pathname: string;
  metadata?: Record<string, any>;
  summary?: string;
  description?: string;
  created_at?: string;
  updated_at?: string;
}

export interface OperationData {
  id: string;
  version_path_id: string;
  operation: string;
  metadata?: Record<string, any>;
  created_at?: string;
  updated_at?: string;
}

export interface SharedParameterData {
  id: string;
  version_path_id: string;
  name: string;
  in_location: 'path' | 'query' | 'header' | 'cookie';
  summary?: string;
  description?: string;
  data?: Record<string, any>;
}

export interface SharedRequestBodyData {
  id: string;
  version_path_id: string;
  name: string;
  description?: string;
  required: boolean;
}

export interface SharedResponseData {
  id: string;
  version_path_id: string;
  status_code: string;
  description?: string;
  data?: Record<string, any>;
  class_id?: string | null;
  inline_schema?: Record<string, any> | null;
}

export interface ContentTypeData {
  id: string;
  media_type: string;
  class_id?: string | null;
  class_name?: string | null;
  inline_schema?: Record<string, any> | null;
  encoding?: Record<string, any> | null;
  examples?: any[] | null;
}

export interface ApiResponse<T = any> {
  success: boolean;
  data?: T;
  error?: string;
}

export interface PathsCanvasBlob {
  nodes: Record<string, unknown>[];
  edges: Record<string, unknown>[];
  viewport: { x: number; y: number; zoom: number };
  updated_at?: string | null;
}

// ==================== Path CRUD ====================

/**
 * List all paths for a version
 */
export async function getPathsForVersion(
  versionId: string
): Promise<ApiResponse<PathData[]>> {
  try {
    const response = await fetch(`/api/paths/${versionId}`, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Failed to get paths' }));
      return { success: false, error: errorData.error || `HTTP ${response.status}` };
    }

    const data = await response.json();
    return { success: true, data: data.paths || data };
  } catch (error: any) {
    console.error('Error getting paths:', error);
    return { success: false, error: error.message || 'Failed to get paths' };
  }
}

/**
 * Get a single path with operations
 */
export async function getPath(
  versionId: string,
  pathId: string
): Promise<ApiResponse<PathData & { operations: OperationData[] }>> {
  try {
    const response = await fetch(`/api/paths/${versionId}/${pathId}`, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Failed to get path' }));
      return { success: false, error: errorData.error || `HTTP ${response.status}` };
    }

    const data = await response.json();
    return { success: true, data: data.path || data };
  } catch (error: any) {
    console.error('Error getting path:', error);
    return { success: false, error: error.message || 'Failed to get path' };
  }
}

/**
 * Get a path with full operation details (parameters, request bodies, responses)
 */
export async function getPathFull(
  versionId: string,
  pathId: string
): Promise<ApiResponse<any>> {
  try {
    const response = await fetch(`/api/paths/${versionId}/${pathId}/full`, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Failed to get path' }));
      return { success: false, error: errorData.error || `HTTP ${response.status}` };
    }

    const data = await response.json();
    return { success: true, data: data.path || data };
  } catch (error: any) {
    console.error('Error getting full path:', error);
    return { success: false, error: error.message || 'Failed to get path' };
  }
}

/**
 * Create a new path
 */
export async function createPath(
  versionId: string,
  pathname: string,
  metadata?: Record<string, any>
): Promise<ApiResponse<PathData>> {
  try {
    const response = await fetch(`/api/paths/${versionId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pathname, metadata }),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Failed to create path' }));
      return { success: false, error: errorData.error || `HTTP ${response.status}` };
    }

    const data = await response.json();
    return { success: true, data: data.path || data };
  } catch (error: any) {
    console.error('Error creating path:', error);
    return { success: false, error: error.message || 'Failed to create path' };
  }
}

/**
 * Update an existing path
 */
export async function updatePath(
  versionId: string,
  pathId: string,
  updates: { pathname?: string; metadata?: Record<string, any> }
): Promise<ApiResponse<PathData>> {
  try {
    const response = await fetch(`/api/paths/${versionId}/${pathId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Failed to update path' }));
      return { success: false, error: errorData.error || `HTTP ${response.status}` };
    }

    const data = await response.json();
    return { success: true, data: data.path || data };
  } catch (error: any) {
    console.error('Error updating path:', error);
    return { success: false, error: error.message || 'Failed to update path' };
  }
}

/**
 * Load persisted Paths React Flow canvas for a version_path (#2642).
 */
export async function getPathCanvas(
  versionId: string,
  pathId: string
): Promise<ApiResponse<PathsCanvasBlob>> {
  try {
    const response = await fetch(`/api/paths/${versionId}/${pathId}/canvas`, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Failed to load canvas' }));
      return { success: false, error: errorData.error || `HTTP ${response.status}` };
    }

    const data = await response.json();
    const canvas = data.canvas ?? data;
    return { success: true, data: canvas };
  } catch (error: any) {
    console.error('Error loading path canvas:', error);
    return { success: false, error: error.message || 'Failed to load canvas' };
  }
}

/**
 * Save Paths React Flow canvas (last-write-wins, #2642).
 */
export async function putPathCanvas(
  versionId: string,
  pathId: string,
  body: Omit<PathsCanvasBlob, 'updated_at'>
): Promise<ApiResponse<PathsCanvasBlob>> {
  try {
    const response = await fetch(`/api/paths/${versionId}/${pathId}/canvas`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        nodes: body.nodes,
        edges: body.edges,
        viewport: body.viewport,
      }),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Failed to save canvas' }));
      return { success: false, error: errorData.error || `HTTP ${response.status}` };
    }

    const data = await response.json();
    const canvas = data.canvas ?? data;
    return { success: true, data: canvas };
  } catch (error: any) {
    console.error('Error saving path canvas:', error);
    return { success: false, error: error.message || 'Failed to save canvas' };
  }
}

/**
 * Delete a path
 */
export async function deletePath(
  versionId: string,
  pathId: string
): Promise<ApiResponse<void>> {
  try {
    const response = await fetch(`/api/paths/${versionId}/${pathId}`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Failed to delete path' }));
      return { success: false, error: errorData.error || `HTTP ${response.status}` };
    }

    return { success: true };
  } catch (error: any) {
    console.error('Error deleting path:', error);
    return { success: false, error: error.message || 'Failed to delete path' };
  }
}

// ==================== Operation CRUD ====================

/**
 * List operations for a path
 */
export async function getOperationsForPath(
  versionId: string,
  pathId: string
): Promise<ApiResponse<OperationData[]>> {
  try {
    const response = await fetch(`/api/paths/${versionId}/${pathId}/operations`, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Failed to get operations' }));
      return { success: false, error: errorData.error || `HTTP ${response.status}` };
    }

    const data = await response.json();
    return { success: true, data: data.operations || data };
  } catch (error: any) {
    console.error('Error getting operations:', error);
    return { success: false, error: error.message || 'Failed to get operations' };
  }
}

/**
 * Create an operation
 */
export async function createOperation(
  versionId: string,
  pathId: string,
  operation: string,
  metadata?: Record<string, any>
): Promise<ApiResponse<OperationData>> {
  try {
    const response = await fetch(`/api/paths/${versionId}/${pathId}/operations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ operation, metadata }),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Failed to create operation' }));
      return { success: false, error: errorData.error || `HTTP ${response.status}` };
    }

    const data = await response.json();
    return { success: true, data: data.operation || data };
  } catch (error: any) {
    console.error('Error creating operation:', error);
    return { success: false, error: error.message || 'Failed to create operation' };
  }
}

/**
 * Update an operation
 */
export async function updateOperation(
  versionId: string,
  pathId: string,
  operationId: string,
  updates: { operation?: string; metadata?: Record<string, any> }
): Promise<ApiResponse<OperationData>> {
  try {
    const response = await fetch(`/api/paths/${versionId}/${pathId}/operations/${operationId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Failed to update operation' }));
      return { success: false, error: errorData.error || `HTTP ${response.status}` };
    }

    const data = await response.json();
    return { success: true, data: data.operation || data };
  } catch (error: any) {
    console.error('Error updating operation:', error);
    return { success: false, error: error.message || 'Failed to update operation' };
  }
}

/**
 * Delete an operation
 */
export async function deleteOperation(
  versionId: string,
  pathId: string,
  operationId: string
): Promise<ApiResponse<void>> {
  try {
    const response = await fetch(`/api/paths/${versionId}/${pathId}/operations/${operationId}`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Failed to delete operation' }));
      return { success: false, error: errorData.error || `HTTP ${response.status}` };
    }

    return { success: true };
  } catch (error: any) {
    console.error('Error deleting operation:', error);
    return { success: false, error: error.message || 'Failed to delete operation' };
  }
}

/**
 * Update operation description (summary, description, operationId, tags)
 */
export async function updateOperationDescription(
  versionId: string,
  pathId: string,
  operationId: string,
  description: {
    summary?: string;
    description?: string;
    operation_id?: string;
    metadata?: Record<string, any>; // tags, deprecated, externalDocs
  }
): Promise<ApiResponse<any>> {
  try {
    const response = await fetch(`/api/paths/${versionId}/${pathId}/operations/${operationId}/description`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(description),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Failed to update description' }));
      return { success: false, error: errorData.error || `HTTP ${response.status}` };
    }

    const data = await response.json();
    return { success: true, data };
  } catch (error: any) {
    console.error('Error updating operation description:', error);
    return { success: false, error: error.message || 'Failed to update description' };
  }
}

// ==================== Shared Parameters ====================

/**
 * List shared parameters for a path
 */
export async function getSharedParameters(
  versionId: string,
  pathId: string
): Promise<ApiResponse<SharedParameterData[]>> {
  try {
    const response = await fetch(`/api/paths/${versionId}/${pathId}/parameters`, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Failed to get parameters' }));
      return { success: false, error: errorData.error || `HTTP ${response.status}` };
    }

    const data = await response.json();
    return { success: true, data: data.parameters || data };
  } catch (error: any) {
    console.error('Error getting parameters:', error);
    return { success: false, error: error.message || 'Failed to get parameters' };
  }
}

/**
 * Create a shared parameter
 */
export async function createSharedParameter(
  versionId: string,
  pathId: string,
  param: {
    name: string;
    in_location: 'path' | 'query' | 'header' | 'cookie';
    summary?: string;
    description?: string;
    data?: Record<string, any>;
  }
): Promise<ApiResponse<SharedParameterData>> {
  try {
    const response = await fetch(`/api/paths/${versionId}/${pathId}/parameters`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(param),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Failed to create parameter' }));
      return { success: false, error: errorData.error || `HTTP ${response.status}` };
    }

    const data = await response.json();
    return { success: true, data: data.parameter || data };
  } catch (error: any) {
    console.error('Error creating parameter:', error);
    return { success: false, error: error.message || 'Failed to create parameter' };
  }
}

/**
 * Link a parameter to an operation
 */
export async function linkParameterToOperation(
  versionId: string,
  pathId: string,
  operationId: string,
  parameterId: string
): Promise<ApiResponse<any>> {
  try {
    const response = await fetch(
      `/api/paths/${versionId}/${pathId}/operations/${operationId}/parameters/${parameterId}/link`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      }
    );

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Failed to link parameter' }));
      return { success: false, error: errorData.error || `HTTP ${response.status}` };
    }

    const data = await response.json();
    return { success: true, data };
  } catch (error: any) {
    console.error('Error linking parameter:', error);
    return { success: false, error: error.message || 'Failed to link parameter' };
  }
}

/**
 * Unlink a parameter from an operation
 */
export async function unlinkParameterFromOperation(
  versionId: string,
  pathId: string,
  operationId: string,
  parameterId: string
): Promise<ApiResponse<void>> {
  try {
    const response = await fetch(
      `/api/paths/${versionId}/${pathId}/operations/${operationId}/parameters/${parameterId}/link`,
      {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
      }
    );

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Failed to unlink parameter' }));
      return { success: false, error: errorData.error || `HTTP ${response.status}` };
    }

    return { success: true };
  } catch (error: any) {
    console.error('Error unlinking parameter:', error);
    return { success: false, error: error.message || 'Failed to unlink parameter' };
  }
}

// ==================== Shared Request Bodies ====================

/**
 * List shared request bodies for a path
 */
export async function getSharedRequestBodies(
  versionId: string,
  pathId: string
): Promise<ApiResponse<SharedRequestBodyData[]>> {
  try {
    const response = await fetch(`/api/paths/${versionId}/${pathId}/request-bodies`, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Failed to get request bodies' }));
      return { success: false, error: errorData.error || `HTTP ${response.status}` };
    }

    const data = await response.json();
    return { success: true, data: data.request_bodies || data };
  } catch (error: any) {
    console.error('Error getting request bodies:', error);
    return { success: false, error: error.message || 'Failed to get request bodies' };
  }
}

/**
 * Create a shared request body
 */
export async function createSharedRequestBody(
  versionId: string,
  pathId: string,
  requestBody: {
    name: string;
    description?: string;
    required?: boolean;
  }
): Promise<ApiResponse<SharedRequestBodyData>> {
  try {
    const response = await fetch(`/api/paths/${versionId}/${pathId}/request-bodies`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(requestBody),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Failed to create request body' }));
      return { success: false, error: errorData.error || `HTTP ${response.status}` };
    }

    const data = await response.json();
    return { success: true, data: data.request_body || data };
  } catch (error: any) {
    console.error('Error creating request body:', error);
    return { success: false, error: error.message || 'Failed to create request body' };
  }
}

/**
 * Add a content type to a request body (with class reference)
 */
export async function addRequestBodyContentType(
  versionId: string,
  pathId: string,
  requestBodyId: string,
  contentType: {
    media_type: string;
    class_id?: string;
    inline_schema?: Record<string, any>;
    encoding?: Record<string, any>;
    examples?: any[];
  }
): Promise<ApiResponse<ContentTypeData>> {
  try {
    const response = await fetch(`/api/paths/${versionId}/${pathId}/request-bodies/${requestBodyId}/content-types`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(contentType),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Failed to add content type' }));
      return { success: false, error: errorData.error || `HTTP ${response.status}` };
    }

    const data = await response.json();
    return { success: true, data };
  } catch (error: any) {
    console.error('Error adding content type:', error);
    return { success: false, error: error.message || 'Failed to add content type' };
  }
}

/**
 * Copy class properties to request body inline schema
 */
export async function copyClassToRequestBodyInlineSchema(
  versionId: string,
  pathId: string,
  requestBodyId: string,
  mediaType: string,
  classId: string
): Promise<ApiResponse<ContentTypeData>> {
  try {
    // URL-encode the media type (replace / with _)
    const safeMediaType = mediaType.replace('/', '_');
    const response = await fetch(
      `/api/paths/${versionId}/${pathId}/request-bodies/${requestBodyId}/content-types/${safeMediaType}/copy-from-class`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ class_id: classId }),
      }
    );

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Failed to copy class' }));
      return { success: false, error: errorData.error || `HTTP ${response.status}` };
    }

    const data = await response.json();
    return { success: true, data };
  } catch (error: any) {
    console.error('Error copying class to inline schema:', error);
    return { success: false, error: error.message || 'Failed to copy class' };
  }
}

/**
 * Link request body to operation
 */
export async function linkRequestBodyToOperation(
  versionId: string,
  pathId: string,
  operationId: string,
  requestBodyId: string,
  metadata?: Record<string, any>
): Promise<ApiResponse<any>> {
  try {
    const response = await fetch(
      `/api/paths/${versionId}/${pathId}/operations/${operationId}/request-body/${requestBodyId}/link`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ metadata }),
      }
    );

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Failed to link request body' }));
      return { success: false, error: errorData.error || `HTTP ${response.status}` };
    }

    const data = await response.json();
    return { success: true, data };
  } catch (error: any) {
    console.error('Error linking request body:', error);
    return { success: false, error: error.message || 'Failed to link request body' };
  }
}

/**
 * Unlink request body from operation
 */
export async function unlinkRequestBodyFromOperation(
  versionId: string,
  pathId: string,
  operationId: string
): Promise<ApiResponse<void>> {
  try {
    const response = await fetch(
      `/api/paths/${versionId}/${pathId}/operations/${operationId}/request-body/link`,
      {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
      }
    );

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Failed to unlink request body' }));
      return { success: false, error: errorData.error || `HTTP ${response.status}` };
    }

    return { success: true };
  } catch (error: any) {
    console.error('Error unlinking request body:', error);
    return { success: false, error: error.message || 'Failed to unlink request body' };
  }
}

// ==================== Shared Responses ====================

/**
 * List shared responses for a path
 */
export async function getSharedResponses(
  versionId: string,
  pathId: string
): Promise<ApiResponse<SharedResponseData[]>> {
  try {
    const response = await fetch(`/api/paths/${versionId}/${pathId}/responses`, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Failed to get responses' }));
      return { success: false, error: errorData.error || `HTTP ${response.status}` };
    }

    const data = await response.json();
    return { success: true, data: data.responses || data };
  } catch (error: any) {
    console.error('Error getting responses:', error);
    return { success: false, error: error.message || 'Failed to get responses' };
  }
}

/**
 * Create a shared response
 */
export async function createSharedResponse(
  versionId: string,
  pathId: string,
  responseData: {
    status_code: string;
    description?: string;
    data?: Record<string, any>;
    class_id?: string;
    inline_schema?: Record<string, any>;
  }
): Promise<ApiResponse<SharedResponseData>> {
  try {
    const response = await fetch(`/api/paths/${versionId}/${pathId}/responses`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(responseData),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Failed to create response' }));
      return { success: false, error: errorData.error || `HTTP ${response.status}` };
    }

    const data = await response.json();
    return { success: true, data: data.response || data };
  } catch (error: any) {
    console.error('Error creating response:', error);
    return { success: false, error: error.message || 'Failed to create response' };
  }
}

/**
 * Add a content type to a response
 */
export async function addResponseContentType(
  versionId: string,
  pathId: string,
  responseId: string,
  contentType: {
    media_type: string;
    class_id?: string;
    inline_schema?: Record<string, any>;
    examples?: any[];
  }
): Promise<ApiResponse<ContentTypeData>> {
  try {
    const response = await fetch(`/api/paths/${versionId}/${pathId}/responses/${responseId}/content-types`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(contentType),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Failed to add content type' }));
      return { success: false, error: errorData.error || `HTTP ${response.status}` };
    }

    const data = await response.json();
    return { success: true, data };
  } catch (error: any) {
    console.error('Error adding response content type:', error);
    return { success: false, error: error.message || 'Failed to add content type' };
  }
}

/**
 * Copy class properties to response inline schema
 */
export async function copyClassToResponseInlineSchema(
  versionId: string,
  pathId: string,
  responseId: string,
  mediaType: string,
  classId: string
): Promise<ApiResponse<ContentTypeData>> {
  try {
    const safeMediaType = mediaType.replace('/', '_');
    const response = await fetch(
      `/api/paths/${versionId}/${pathId}/responses/${responseId}/content-types/${safeMediaType}/copy-from-class`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ class_id: classId }),
      }
    );

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Failed to copy class' }));
      return { success: false, error: errorData.error || `HTTP ${response.status}` };
    }

    const data = await response.json();
    return { success: true, data };
  } catch (error: any) {
    console.error('Error copying class to response inline schema:', error);
    return { success: false, error: error.message || 'Failed to copy class' };
  }
}

/**
 * Link response to operation
 */
export async function linkResponseToOperation(
  versionId: string,
  pathId: string,
  operationId: string,
  responseId: string,
  metadata?: Record<string, any>
): Promise<ApiResponse<any>> {
  try {
    const response = await fetch(
      `/api/paths/${versionId}/${pathId}/operations/${operationId}/responses/${responseId}/link`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ metadata }),
      }
    );

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Failed to link response' }));
      return { success: false, error: errorData.error || `HTTP ${response.status}` };
    }

    const data = await response.json();
    return { success: true, data };
  } catch (error: any) {
    console.error('Error linking response:', error);
    return { success: false, error: error.message || 'Failed to link response' };
  }
}

/**
 * Unlink response from operation
 */
export async function unlinkResponseFromOperation(
  versionId: string,
  pathId: string,
  operationId: string,
  responseId: string
): Promise<ApiResponse<void>> {
  try {
    const response = await fetch(
      `/api/paths/${versionId}/${pathId}/operations/${operationId}/responses/${responseId}/link`,
      {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
      }
    );

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Failed to unlink response' }));
      return { success: false, error: errorData.error || `HTTP ${response.status}` };
    }

    return { success: true };
  } catch (error: any) {
    console.error('Error unlinking response:', error);
    return { success: false, error: error.message || 'Failed to unlink response' };
  }
}

/**
 * Delete a shared response
 */
export async function deleteSharedResponse(
  versionId: string,
  pathId: string,
  responseId: string
): Promise<ApiResponse<void>> {
  try {
    const response = await fetch(`/api/paths/${versionId}/${pathId}/responses/${responseId}`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Failed to delete response' }));
      return { success: false, error: errorData.error || `HTTP ${response.status}` };
    }

    return { success: true };
  } catch (error: any) {
    console.error('Error deleting response:', error);
    return { success: false, error: error.message || 'Failed to delete response' };
  }
}

/**
 * Delete a shared request body
 */
export async function deleteSharedRequestBody(
  versionId: string,
  pathId: string,
  requestBodyId: string
): Promise<ApiResponse<void>> {
  try {
    const response = await fetch(`/api/paths/${versionId}/${pathId}/request-bodies/${requestBodyId}`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Failed to delete request body' }));
      return { success: false, error: errorData.error || `HTTP ${response.status}` };
    }

    return { success: true };
  } catch (error: any) {
    console.error('Error deleting request body:', error);
    return { success: false, error: error.message || 'Failed to delete request body' };
  }
}

/**
 * Delete a shared parameter
 */
export async function deleteSharedParameter(
  versionId: string,
  pathId: string,
  parameterId: string
): Promise<ApiResponse<void>> {
  try {
    const response = await fetch(`/api/paths/${versionId}/${pathId}/parameters/${parameterId}`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Failed to delete parameter' }));
      return { success: false, error: errorData.error || `HTTP ${response.status}` };
    }

    return { success: true };
  } catch (error: any) {
    console.error('Error deleting parameter:', error);
    return { success: false, error: error.message || 'Failed to delete parameter' };
  }
}
