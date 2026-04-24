import fs from 'fs';
import path from 'path';
import YAML from 'yaml';
import { parseOpenAPISpec } from '../../src/app/utils/openapi-import';
import { convertSwaggerToOpenAPI } from '../../src/app/utils/swagger-converter';
import { importOpenApiFromRepository, RepositoryOpenApiFormat } from '../../lib/repositories/importers/openapi';

function deriveOpenApiFormat(content: string): RepositoryOpenApiFormat {
  const swaggerMatch = content.match(/^\s*swagger\s*:\s*["']?(\d+\.\d+)/m);
  if (swaggerMatch?.[1]?.startsWith('2.0')) return 'swagger_2_0';
  const match = content.match(/^\s*openapi\s*:\s*["']?(\d+\.\d+)/m);
  if (match?.[1]?.startsWith('3.0')) return 'openapi_3_0';
  return 'openapi_3_1';
}

describe('repository OpenAPI importer hook', () => {
  it('matches one-shot OpenAPI dialog parsing across the OpenAPI fixture set', async () => {
    const fixturesDir = path.join(__dirname, '../../examples/openapi');
    const fixtures = fs
      .readdirSync(fixturesDir)
      .filter((name) => name.endsWith('.yaml') || name.endsWith('.yml') || name.endsWith('.json'))
      .sort();

    expect(fixtures.length).toBeGreaterThan(0);

    for (const fixture of fixtures) {
      const content = fs.readFileSync(path.join(fixturesDir, fixture), 'utf-8');
      const oneShotResult = parseOpenAPISpec(content);
      const repositoryResult = await importOpenApiFromRepository({
        source: `repository://${fixture}`,
        format: deriveOpenApiFormat(content),
        content,
        refs: [],
      });

      expect(repositoryResult.success).toBe(oneShotResult.success);
      if (oneShotResult.success) {
        expect(repositoryResult.parseResult).toEqual(oneShotResult);
      } else {
        expect(repositoryResult.parseResult).toBeUndefined();
      }
      expect(repositoryResult.warnings).toEqual(oneShotResult.warnings);
      expect(repositoryResult.error).toBe(oneShotResult.error);
    }
  });

  it('delegates cross-file refs to the REPO-3.8 resolver when refs are present', async () => {
    const resolved = `
openapi: 3.1.0
info:
  title: Resolved
  version: 1.0.0
components:
  schemas:
    User:
      type: object
      properties:
        id:
          type: string
`;

    const resolveRefs = jest.fn().mockResolvedValue(resolved);

    const result = await importOpenApiFromRepository(
      {
        source: 'repository://services/openapi.yaml',
        format: 'openapi_3_1',
        content: 'openapi: 3.1.0',
        refs: [{ path: './schemas/user.yaml', content: 'type: object' }],
      },
      { resolveRefs }
    );

    expect(resolveRefs).toHaveBeenCalledTimes(1);
    expect(resolveRefs).toHaveBeenCalledWith({
      source: 'repository://services/openapi.yaml',
      format: 'openapi_3_1',
      content: 'openapi: 3.1.0',
      refs: [{ path: './schemas/user.yaml', content: 'type: object' }],
    });
    expect(result.success).toBe(true);
    expect(result.parseResult?.success).toBe(true);
    expect(result.parseResult?.classes.some((cls) => cls.name === 'User')).toBe(true);
  });

  it('returns success: false when refs are present but no resolver is configured', async () => {
    const result = await importOpenApiFromRepository({
      source: 'repository://services/openapi.yaml',
      format: 'openapi_3_1',
      content: 'openapi: 3.1.0',
      refs: [{ path: './schemas/user.yaml', content: 'type: object' }],
    });

    expect(result.success).toBe(false);
    expect(result.error).toMatch(/REPO-3\.8/);
  });

  it('maps Swagger 2.0 repository fixtures to the same internal entities as the 3.x parse pipeline', async () => {
    const swaggerPath = path.join(__dirname, '../../examples/swagger/01-swagger-2-petstore.yaml');
    const swaggerContent = fs.readFileSync(swaggerPath, 'utf-8');

    const swaggerImportResult = await importOpenApiFromRepository({
      source: 'repository://swagger/01-swagger-2-petstore.yaml',
      format: 'swagger_2_0',
      content: swaggerContent,
      refs: [],
    });

    expect(swaggerImportResult.success).toBe(true);
    expect(swaggerImportResult.parseResult?.success).toBe(true);

    const convertedSwagger = convertSwaggerToOpenAPI(YAML.parse(swaggerContent));
    expect(convertedSwagger.success).toBe(true);
    const openApiEquivalentContent = YAML.stringify(convertedSwagger.document);

    const openApiEquivalentResult = await importOpenApiFromRepository({
      source: 'repository://openapi/swagger-equivalent.yaml',
      format: 'openapi_3_1',
      content: openApiEquivalentContent,
      refs: [],
    });

    expect(openApiEquivalentResult.success).toBe(true);

    const swaggerParsed = swaggerImportResult.parseResult;
    const openApiParsed = openApiEquivalentResult.parseResult;
    expect(openApiParsed?.classes).toEqual(swaggerParsed?.classes);
    expect(openApiParsed?.paths).toEqual(swaggerParsed?.paths);
    expect(openApiParsed?.securitySchemes).toEqual(swaggerParsed?.securitySchemes);
    expect(openApiParsed?.title).toBe(swaggerParsed?.title);
    expect(openApiParsed?.version).toBe(swaggerParsed?.version);
    expect(openApiParsed?.description).toBe(swaggerParsed?.description);
    expect(openApiParsed?.info).toEqual(swaggerParsed?.info);
    expect(openApiParsed?.servers).toEqual(swaggerParsed?.servers);
    expect(openApiParsed?.tags).toEqual(swaggerParsed?.tags);

    const parsed = swaggerParsed;
    expect(parsed?.classes.some((cls) => cls.name === 'Pet')).toBe(true);
    expect(parsed?.paths?.some((entry) => entry.path === '/pets')).toBe(true);

    const listPets = parsed?.paths
      ?.find((entry) => entry.path === '/pets')
      ?.operations.find((operation) => operation.operationId === 'listPets');
    expect(listPets?.parameters.some((parameter) => parameter.name === 'status' && parameter.in === 'query')).toBe(
      true
    );

    const schemeNames = (parsed?.securitySchemes ?? []).map((scheme) => scheme.scheme_name);
    expect(schemeNames).toEqual(expect.arrayContaining(['api_key', 'basic_auth', 'oauth2']));
  });
});
