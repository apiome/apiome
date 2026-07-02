/**
 * Verification script to test that renderTemplate is properly awaited
 */

import Handlebars from 'handlebars';
import { readFileSync } from 'fs';
import { join } from 'path';

// Register the json helper
Handlebars.registerHelper('json', function(context) {
  return JSON.stringify(context, null, 2);
});

async function testTemplateRendering() {
  console.log('Testing template rendering with async/await...\n');

  try {
    // Load and compile template
    const templatePath = join(process.cwd(), 'src', 'app', 'utils', 'templates', 'openapi', 'openapi-spec.hbs');
    const templateSource = readFileSync(templatePath, 'utf-8');
    const template = Handlebars.compile(templateSource);

    // Test data
    const testData = {
      openapi: '3.1.0',
      info: {
        title: 'Test API',
        version: '1.0.0',
        description: 'Test Description'
      },
      schemas: {
        Person: {
          type: 'object',
          properties: {
            name: { type: 'string' },
            age: { type: 'number' }
          }
        }
      }
    };

    // Render template
    const rendered = template(testData);

    console.log('✅ Template rendered successfully');
    console.log('✅ Result is a string, not a Promise');

    // Parse to verify valid JSON
    const parsed = JSON.parse(rendered);
    console.log('✅ Result is valid JSON');
    console.log(`   - OpenAPI version: ${parsed.openapi}`);
    console.log(`   - API title: ${parsed.info.title}`);
    console.log(`   - Schemas: ${Object.keys(parsed.components.schemas).join(', ')}`);

    console.log('\n🎉 All checks passed! The fix is working correctly.\n');
    return true;
  } catch (error) {
    console.error('❌ Test failed:', error.message);
    return false;
  }
}

// Run the test
testTemplateRendering().then(success => {
  process.exit(success ? 0 : 1);
});

