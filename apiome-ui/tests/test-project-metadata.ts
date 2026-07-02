/**
 * Test for Project Metadata Feature
 * Verifies that metadata is correctly included in OpenAPI spec generation
 */

import { generateOpenApiSpec } from '../src/app/utils/openapi.ts';

console.log('🧪 Testing Project Metadata Feature\n');
console.log('━'.repeat(60));

// Test data
const testClasses = [
  {
    id: '1',
    name: 'User',
    description: 'User account',
    properties: [
      {
        id: 'p1',
        name: 'email',
        data: { type: 'string', format: 'email' }
      },
      {
        id: 'p2',
        name: 'name',
        data: { type: 'string' }
      }
    ]
  }
];

const testMetadata = {
  summary: 'User Management API',
  termsOfService: 'https://example.com/terms',
  contact: {
    name: 'API Support Team',
    url: 'https://example.com/support',
    email: 'support@example.com'
  },
  license: {
    name: 'Apache License 2.0',
    identifier: 'Apache-2.0',
    url: 'https://www.apache.org/licenses/LICENSE-2.0.html'
  }
};

async function runTests() {
  try {
    // Test 1: Generate spec WITHOUT metadata
    console.log('\n📝 Test 1: Generate OpenAPI spec WITHOUT metadata');
    const specWithoutMetadata = await generateOpenApiSpec(testClasses, {
      projectName: 'Test API',
      version: '1.0.0'
    });

    const parsedWithout = JSON.parse(specWithoutMetadata);

    console.log('   Info object:', JSON.stringify(parsedWithout.info, null, 2));

    if (!parsedWithout.info.summary && !parsedWithout.info.contact && !parsedWithout.info.license) {
      console.log('   ✅ PASS: No metadata fields present (as expected)\n');
    } else {
      console.log('   ❌ FAIL: Unexpected metadata fields present\n');
    }

    // Test 2: Generate spec WITH metadata
    console.log('📝 Test 2: Generate OpenAPI spec WITH metadata');
    const specWithMetadata = await generateOpenApiSpec(testClasses, {
      projectName: 'Test API',
      version: '1.0.0',
      metadata: testMetadata
    });

    const parsedWith = JSON.parse(specWithMetadata);

    console.log('   Info object:', JSON.stringify(parsedWith.info, null, 2));

    let allTestsPassed = true;

    // Validate summary
    if (parsedWith.info.summary === testMetadata.summary) {
      console.log('   ✅ Summary: Correct');
    } else {
      console.log('   ❌ Summary: Missing or incorrect');
      allTestsPassed = false;
    }

    // Validate termsOfService
    if (parsedWith.info.termsOfService === testMetadata.termsOfService) {
      console.log('   ✅ Terms of Service: Correct');
    } else {
      console.log('   ❌ Terms of Service: Missing or incorrect');
      allTestsPassed = false;
    }

    // Validate contact
    if (parsedWith.info.contact &&
        parsedWith.info.contact.name === testMetadata.contact.name &&
        parsedWith.info.contact.url === testMetadata.contact.url &&
        parsedWith.info.contact.email === testMetadata.contact.email) {
      console.log('   ✅ Contact: All fields correct');
    } else {
      console.log('   ❌ Contact: Missing or incorrect');
      allTestsPassed = false;
    }

    // Validate license
    if (parsedWith.info.license &&
        parsedWith.info.license.name === testMetadata.license.name &&
        parsedWith.info.license.identifier === testMetadata.license.identifier &&
        parsedWith.info.license.url === testMetadata.license.url) {
      console.log('   ✅ License: All fields correct');
    } else {
      console.log('   ❌ License: Missing or incorrect');
      allTestsPassed = false;
    }

    // Test 3: Partial metadata
    console.log('\n📝 Test 3: Generate OpenAPI spec with PARTIAL metadata');
    const partialMetadata = {
      summary: 'Simple API',
      license: {
        name: 'MIT License',
        identifier: 'MIT'
      }
    };

    const specWithPartial = await generateOpenApiSpec(testClasses, {
      projectName: 'Test API',
      version: '1.0.0',
      metadata: partialMetadata
    });

    const parsedPartial = JSON.parse(specWithPartial);

    if (parsedPartial.info.summary === 'Simple API' &&
        parsedPartial.info.license &&
        parsedPartial.info.license.name === 'MIT License' &&
        !parsedPartial.info.contact &&
        !parsedPartial.info.termsOfService) {
      console.log('   ✅ PASS: Partial metadata handled correctly');
    } else {
      console.log('   ❌ FAIL: Partial metadata not handled correctly');
      allTestsPassed = false;
    }

    console.log('\n' + '━'.repeat(60));

    if (allTestsPassed) {
      console.log('\n🎉 All tests PASSED!');
      console.log('✅ Project metadata feature is working correctly');
      process.exit(0);
    } else {
      console.log('\n⚠️  Some tests FAILED');
      console.log('❌ Please review the implementation');
      process.exit(1);
    }

  } catch (error) {
    console.error('\n❌ Error during testing:', error);
    console.error('Error message:', error instanceof Error ? error.message : String(error));
    process.exit(1);
  }
}

runTests();

