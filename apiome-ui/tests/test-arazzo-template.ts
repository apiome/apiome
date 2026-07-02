/**
 * Test to verify Arazzo spec generation with Handlebars templates
 */

import { generateArazzoSpec } from '../src/app/utils/arazzo.ts';

const testClasses = [
  {
    id: '1',
    name: 'User',
    description: 'User model',
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
  },
  {
    id: '2',
    name: 'Product',
    description: 'Product model',
    properties: [
      {
        id: 'p3',
        name: 'title',
        data: { type: 'string' }
      },
      {
        id: 'p4',
        name: 'price',
        data: { type: 'number' }
      }
    ]
  }
];

console.log('🧪 Testing Arazzo Generation with Handlebars Templates\n');

async function test() {
  try {
    console.log('Test 1: Generate Arazzo spec WITHOUT metadata');
    const spec1 = await generateArazzoSpec(testClasses, {
      projectName: 'Test API',
      version: '1.0.0'
    });

    console.log('Result length:', spec1.length);
    console.log('\nGenerated spec:\n');
    console.log(spec1);

    // Parse to verify it's valid JSON
    const parsed1 = JSON.parse(spec1);

    console.log('\n📊 Validation:');
    console.log('- Arazzo version:', parsed1.arazzo);
    console.log('- Info title:', parsed1.info.title);
    console.log('- Number of workflows:', parsed1.workflows.length);
    console.log('- Number of source descriptions:', parsed1.sourceDescriptions.length);

    if (parsed1.workflows.length === 2) {
      console.log('✅ PASS: Correct number of workflows generated\n');
    } else {
      console.log('❌ FAIL: Expected 2 workflows, got', parsed1.workflows.length, '\n');
    }

    console.log('Test 2: Generate Arazzo spec WITH metadata');
    const spec2 = await generateArazzoSpec(testClasses, {
      projectName: 'Test API',
      version: '1.0.0',
      metadata: {
        summary: 'Test summary',
        contact: { email: 'test@example.com' }
      }
    });

    const parsed2 = JSON.parse(spec2);

    console.log('\n📊 Validation with metadata:');
    console.log('- Has x-metadata:', !!parsed2['x-metadata']);
    console.log('- Metadata summary:', parsed2['x-metadata']?.summary);

    if (parsed2['x-metadata'] && parsed2['x-metadata'].summary === 'Test summary') {
      console.log('✅ PASS: Metadata correctly included\n');
    } else {
      console.log('❌ FAIL: Metadata not properly included\n');
    }

    console.log('Test 3: Verify workflow structure');
    const workflow = parsed1.workflows[0];
    console.log('\n📊 First workflow structure:');
    console.log('- Workflow ID:', workflow.workflowId);
    console.log('- Summary:', workflow.summary);
    console.log('- Number of steps:', workflow.steps.length);
    console.log('- Step IDs:', workflow.steps.map((s: any) => s.stepId).join(', '));

    if (workflow.steps.length === 4) {
      console.log('✅ PASS: Workflow has all 4 CRUD steps\n');
    } else {
      console.log('❌ FAIL: Expected 4 steps, got', workflow.steps.length, '\n');
    }

    console.log('Test 4: Verify empty classes array');
    const spec3 = await generateArazzoSpec([], {
      projectName: 'Empty API',
      version: '1.0.0'
    });

    const parsed3 = JSON.parse(spec3);
    console.log('\n📊 Empty classes:');
    console.log('- Number of workflows:', parsed3.workflows.length);

    if (parsed3.workflows.length === 0) {
      console.log('✅ PASS: Empty array handled correctly\n');
    } else {
      console.log('❌ FAIL: Expected 0 workflows\n');
    }

    console.log('\n🎉 All tests completed successfully!');

  } catch (error) {
    console.error('\n❌ TEST FAILED:', error);
    if (error instanceof Error) {
      console.error('Error message:', error.message);
      console.error('Stack trace:', error.stack);
    }
    process.exit(1);
  }
}

test();

