'use server';

/**
 * Handlebars Template Loader and Helpers
 *
 * Manages loading and compiling Handlebars templates for OpenAPI generation.
 */

import Handlebars from 'handlebars';
import { readFileSync } from 'fs';
import { join } from 'path';

/**
 * Cache for compiled templates
 */
const templateCache = new Map<string, HandlebarsTemplateDelegate>();

/**
 * Register custom Handlebars helpers
 */
function registerHelpers(): void {
  // Helper to convert objects to JSON strings
  Handlebars.registerHelper('json', function(context) {
    return JSON.stringify(context, null, 2);
  });

  // Helper for conditional JSON formatting
  Handlebars.registerHelper('jsonInline', function(context) {
    return JSON.stringify(context);
  });

  // Helper to check if value exists and is not empty
  Handlebars.registerHelper('hasValue', function(value) {
    return value !== undefined && value !== null && value !== '';
  });

  // Helper to check if object has keys
  Handlebars.registerHelper('hasKeys', function(obj) {
    return obj && typeof obj === 'object' && Object.keys(obj).length > 0;
  });
}

registerHelpers();

/**
 * Load and compile a Handlebars template
 * @param templateName - Name of the template file (without path)
 * @returns Compiled Handlebars template
 */
export async function loadTemplate(templateName: string): Promise<HandlebarsTemplateDelegate> {
  // Check cache first
  if (templateCache.has(templateName)) {
    return templateCache.get(templateName)!;
  }

  try {
    // Read template file from templates directory
    const templatePath = join(process.cwd(), 'src', 'app', 'utils', 'templates', templateName);
    const templateSource = readFileSync(templatePath, 'utf-8');

    // Compile template
    const template = Handlebars.compile(templateSource);

    // Cache compiled template
    templateCache.set(templateName, template);

    return template;
  } catch (error) {
    throw new Error(`Failed to load template "${templateName}": ${error instanceof Error ? error.message : String(error)}`);
  }
}

/**
 * Clear the template cache (useful for development/testing)
 */
export async function clearTemplateCache(): Promise<void> {
  templateCache.clear();
}

/**
 * Preload commonly used templates
 */
export async function preloadTemplates(templateNames: string[]): Promise<void> {
  await Promise.all(templateNames.map(async (name) => {
    try {
      await loadTemplate(name);
    } catch (error) {
      console.error(`Failed to preload template "${name}":`, error);
    }
  }));
}

/**
 * Render a template with the given data
 * @param templateName - Name of the template file
 * @param data - Data to pass to the template
 * @returns Rendered template string
 */
export async function renderTemplate(templateName: string, data: any): Promise<string> {
  const template = await loadTemplate(templateName);
  return template(data);
}

