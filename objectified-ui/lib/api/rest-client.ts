/**
 * REST API Client for objectified-rest services
 * 
 * This module provides functions to interact with the objectified-rest API
 * for class operations, replacing direct database helper calls.
 * 
 * All requests are proxied through Next.js API routes which handle authentication.
 */

/**
 * Delete a class via REST API (proxied through Next.js API route)
 */
export async function deleteClassWithSession(
  classId: string
): Promise<{ success: boolean; error?: string }> {
  try {
    const response = await fetch(`/api/classes/${classId}`, {
      method: 'DELETE',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Failed to delete class' }));
      return { success: false, error: errorData.error || `HTTP ${response.status}` };
    }

    const data = await response.json();
    return data.success ? { success: true } : { success: false, error: data.error };
  } catch (error: any) {
    console.error('Error deleting class via REST API:', error);
    return { success: false, error: error.message || 'Failed to delete class' };
  }
}

/**
 * Update class canvas metadata via REST API (proxied through Next.js API route)
 */
async function updateClassCanvasMetadata(
  classId: string,
  canvasMetadata: {
    position?: { x: number; y: number };
    dimensions?: { width?: number; height?: number };
    style?: {
      backgroundColor?: string;
      borderColor?: string;
      borderWidth?: number;
      borderStyle?: 'solid' | 'dashed' | 'dotted';
      headerGradient?: string;
      textColor?: string;
      headerTextColor?: string;
      icon?: string; // Custom icon from lucide-react
      collapsed?: boolean;
      zIndex?: number;
      labelFontSize?: number;
      labelFontFamily?: string;
      labelFontWeight?: 'normal' | 'bold';
      labelFontStyle?: 'normal' | 'italic';
      labelTextAlign?: 'left' | 'center' | 'right';
      labelMultiLine?: boolean;
    };
    group?: string | null;
  } | null
): Promise<{ success: boolean; error?: string; class?: any }> {
  try {
    const response = await fetch(`/api/classes/${classId}`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        canvas_metadata: canvasMetadata,
      }),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Failed to update class canvas metadata' }));
      return { success: false, error: errorData.error || `HTTP ${response.status}` };
    }

    const data = await response.json();
    return data.success ? { success: true, class: data.class } : { success: false, error: data.error };
  } catch (error: any) {
    console.error('Error updating class canvas metadata via REST API:', error);
    return { success: false, error: error.message || 'Failed to update class canvas metadata' };
  }
}

/**
 * Update class canvas metadata (convenience wrapper)
 */
export async function updateClassCanvasMetadataWithSession(
  classId: string,
  canvasMetadata: {
    position?: { x: number; y: number };
    dimensions?: { width?: number; height?: number };
    style?: {
      backgroundColor?: string;
      borderColor?: string;
      borderWidth?: number;
      borderStyle?: 'solid' | 'dashed' | 'dotted';
      headerGradient?: string;
      textColor?: string;
      headerTextColor?: string;
      icon?: string; // Custom icon from lucide-react
      collapsed?: boolean;
      zIndex?: number;
      labelFontSize?: number;
      labelFontFamily?: string;
      labelFontWeight?: 'normal' | 'bold';
      labelFontStyle?: 'normal' | 'italic';
      labelTextAlign?: 'left' | 'center' | 'right';
      labelMultiLine?: boolean;
    };
    group?: string | null;
  } | null
): Promise<{ success: boolean; error?: string; class?: any }> {
  return updateClassCanvasMetadata(classId, canvasMetadata);
}

/**
 * Get classes with properties and tags for a version via REST API
 */
async function getClassesWithPropertiesAndTags(versionId: string, signal?: AbortSignal): Promise<{ success: boolean; classes?: any[]; error?: string }> {
  try {
    const response = await fetch(`/api/classes/version/${versionId}/with-properties-tags`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
      signal,
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Failed to get classes' }));
      return { success: false, error: errorData.error || `HTTP ${response.status}` };
    }

    const data = await response.json();
    return data.success ? { success: true, classes: data.classes } : { success: false, error: data.error };
  } catch (error: any) {
    console.error('Error getting classes with properties and tags via REST API:', error);
    return { success: false, error: error.message || 'Failed to get classes' };
  }
}

/**
 * Get a single class with properties and tags via REST API
 */
async function getClassWithPropertiesAndTags(classId: string): Promise<{ success: boolean; class?: any; error?: string }> {
  try {
    const response = await fetch(`/api/classes/${classId}/with-properties-tags`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Failed to get class' }));
      return { success: false, error: errorData.error || `HTTP ${response.status}` };
    }

    const data = await response.json();
    return data.success ? { success: true, class: data.class } : { success: false, error: data.error };
  } catch (error: any) {
    console.error('Error getting class with properties and tags via REST API:', error);
    return { success: false, error: error.message || 'Failed to get class' };
  }
}

/**
 * Get classes with properties and tags for a version (convenience wrapper)
 */
export async function getClassesWithPropertiesAndTagsWithSession(
  versionId: string,
  signal?: AbortSignal
): Promise<{ success: boolean; classes?: any[]; error?: string }> {
  return getClassesWithPropertiesAndTags(versionId, signal);
}

/**
 * Get a single class with properties and tags (convenience wrapper)
 */
export async function getClassWithPropertiesAndTagsWithSession(
  classId: string
): Promise<{ success: boolean; class?: any; error?: string }> {
  return getClassWithPropertiesAndTags(classId);
}

/**
 * Create a new class via REST API (proxied through Next.js API route)
 */
async function createClass(
  versionId: string,
  name: string,
  description: string | null,
  schema: any
): Promise<{ success: boolean; class?: any; error?: string }> {
  try {
    const response = await fetch(`/api/classes`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        version_id: versionId,
        name: name.trim(),
        description: description,
        schema: schema,
        enabled: true,
      }),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Failed to create class' }));
      return { success: false, error: errorData.error || `HTTP ${response.status}` };
    }

    const data = await response.json();
    return data.success ? { success: true, class: data.class } : { success: false, error: data.error };
  } catch (error: any) {
    console.error('Error creating class via REST API:', error);
    return { success: false, error: error.message || 'Failed to create class' };
  }
}

/**
 * Update an existing class via REST API (proxied through Next.js API route)
 */
async function updateClass(
  classId: string,
  name: string,
  description: string | null,
  schema: any
): Promise<{ success: boolean; class?: any; error?: string }> {
  try {
    const response = await fetch(`/api/classes/${classId}`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        name: name.trim(),
        description: description,
        schema: schema,
      }),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ error: 'Failed to update class' }));
      return { success: false, error: errorData.error || `HTTP ${response.status}` };
    }

    const data = await response.json();
    return data.success ? { success: true, class: data.class } : { success: false, error: data.error };
  } catch (error: any) {
    console.error('Error updating class via REST API:', error);
    return { success: false, error: error.message || 'Failed to update class' };
  }
}

/**
 * Create a class (convenience wrapper)
 */
export async function createClassWithSession(
  versionId: string,
  name: string,
  description: string | null,
  schema: any
): Promise<{ success: boolean; class?: any; error?: string }> {
  return createClass(versionId, name, description, schema);
}

/**
 * Update a class (convenience wrapper)
 */
export async function updateClassWithSession(
  classId: string,
  name: string,
  description: string | null,
  schema: any
): Promise<{ success: boolean; class?: any; error?: string }> {
  return updateClass(classId, name, description, schema);
}
