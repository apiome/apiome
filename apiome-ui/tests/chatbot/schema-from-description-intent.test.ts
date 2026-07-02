import { userPromptRequestsSchemaFromDescription } from '../../src/app/ade/studio/components/chatbot/schema-from-description-intent';

describe('userPromptRequestsSchemaFromDescription (#267)', () => {
  it('is true for plain-language domain descriptions without spec keywords', () => {
    expect(
      userPromptRequestsSchemaFromDescription(
        'I need a simple todo list with tasks that have titles, due dates, and completion flags',
      ),
    ).toBe(true);
    expect(
      userPromptRequestsSchemaFromDescription(
        'We want to model patients, appointments, and providers for a small clinic',
      ),
    ).toBe(true);
  });

  it('still treats explicit spec/schema vocabulary as a generation request', () => {
    expect(userPromptRequestsSchemaFromDescription('draft an openapi blob')).toBe(true);
    expect(userPromptRequestsSchemaFromDescription('show me the schema')).toBe(true);
  });

  it('is false for small talk and unrelated short prompts', () => {
    expect(userPromptRequestsSchemaFromDescription('tell me a joke')).toBe(false);
    expect(userPromptRequestsSchemaFromDescription('thanks for your help')).toBe(false);
    expect(userPromptRequestsSchemaFromDescription('hello')).toBe(false);
  });

  it('is false for vague "create" lines without modeling vocabulary', () => {
    expect(userPromptRequestsSchemaFromDescription('create something cool')).toBe(false);
  });

  it('is true for pasted-requirements phrasing', () => {
    expect(
      userPromptRequestsSchemaFromDescription(
        'Here are the requirements: users must authenticate with email and belong to organizations',
      ),
    ).toBe(true);
  });

  it('is true for polite prompts that lead into a modeling request', () => {
    // Greeting prefix should not suppress detection when the tail is a schema request.
    expect(
      userPromptRequestsSchemaFromDescription(
        'Hi, I need a blog platform with posts and comments',
      ),
    ).toBe(true);
    expect(
      userPromptRequestsSchemaFromDescription(
        'Hello, we want to model a library system with books and members',
      ),
    ).toBe(true);
  });

  it('is true for direct noun lists after "I need" / "we want" without an article', () => {
    // The entity-list pattern should catch these even without modeling vocabulary.
    expect(
      userPromptRequestsSchemaFromDescription('I need users, roles, and permissions'),
    ).toBe(true);
    expect(
      userPromptRequestsSchemaFromDescription('We want posts and comments'),
    ).toBe(true);
    expect(
      userPromptRequestsSchemaFromDescription('I need products, orders, and customers'),
    ).toBe(true);
  });

  it('is false when "I need/want" is followed by support or meta words', () => {
    // Common non-entity words after need/want should not trigger schema generation.
    expect(userPromptRequestsSchemaFromDescription('I need help and support')).toBe(false);
    expect(userPromptRequestsSchemaFromDescription('I need more information')).toBe(false);
  });
});
