jest.mock('../../src/app/utils/template-loader', () => ({
  renderTemplate: jest.fn(),
  loadTemplate: jest.fn(),
}));

import { buildClassSchema } from '../../src/app/utils/openapi';

describe('property owner metadata (x-owner)', () => {
  it('includes x-owner from class property data in generated class schema', () => {
    const classData = {
      name: 'Order',
      schema: {},
      properties: [
        {
          id: 'cp1',
          name: 'status',
          data: {
            type: 'string',
            'x-owner': 'fulfillment-team',
          },
        },
      ],
    };

    const schema = buildClassSchema(classData as any);
    expect(schema.properties?.status).toMatchObject({
      type: 'string',
      'x-owner': 'fulfillment-team',
    });
  });
});
