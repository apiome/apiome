/**
 * Preset OpenAPI-oriented metadata for new projects. Lets users start from a template
 * instead of filling API metadata from scratch (#52).
 */

export interface ProjectOpenApiMetadata {
  summary?: string;
  termsOfService?: string;
  contact?: { name?: string; url?: string; email?: string };
  license?: { name?: string; identifier?: string; url?: string };
  /** Domain category id; see `project-domain-categories.ts` (#243) */
  domainCategory?: string;
}

export interface ProjectStartTemplate {
  id: string;
  label: string;
  /** Shown under the template picker */
  hint: string;
  suggestedDescription: string;
  metadata: ProjectOpenApiMetadata;
}

export const BLANK_TEMPLATE_ID = 'blank';

export const PROJECT_START_TEMPLATES: readonly ProjectStartTemplate[] = [
  {
    id: 'blank',
    label: 'Blank',
    hint: 'No preset metadata. Use this when you will fill everything in yourself.',
    suggestedDescription: '',
    metadata: {},
  },
  {
    id: 'public-rest',
    label: 'Public REST API',
    hint: 'External developers: permissive license, support contact, and a clear API summary.',
    suggestedDescription: 'Public HTTP API for third-party integrators and client applications.',
    metadata: {
      summary: 'Public REST API for external consumers.',
      contact: {
        name: 'API Support',
        url: 'https://example.com/support',
        email: 'api-support@example.com',
      },
      license: {
        name: 'MIT License',
        identifier: 'MIT',
        url: 'https://spdx.org/licenses/MIT.html',
      },
    },
  },
  {
    id: 'internal',
    label: 'Internal / private API',
    hint: 'Service-to-service or private network APIs; proprietary license and minimal public contact.',
    suggestedDescription: 'Internal API for trusted services within the organization.',
    metadata: {
      summary: 'Internal API for service-to-service communication (not for public use).',
      contact: {
        name: 'Platform Team',
        url: 'https://example.com/internal',
        email: 'platform@example.com',
      },
      license: {
        name: 'Proprietary/Unlicensed',
        identifier: 'UNLICENSED',
      },
    },
  },
  {
    id: 'partner-b2b',
    label: 'Partner / B2B integration',
    hint: 'Approved partners: terms of service, dedicated contact, and a controlled license.',
    suggestedDescription: 'B2B integration API for contractually approved partners.',
    metadata: {
      summary: 'Partner integration API; access is governed by agreement.',
      termsOfService: 'https://example.com/partner-terms',
      contact: {
        name: 'Partner Integrations',
        url: 'https://example.com/partners',
        email: 'partners@example.com',
      },
      license: {
        name: 'Proprietary — partner use only',
        identifier: 'UNLICENSED',
      },
    },
  },
  {
    id: 'microservice',
    label: 'Microservice boundary',
    hint: 'Small, focused surface area with Apache 2.0 — common for shared platform services.',
    suggestedDescription: 'Boundary API for a single domain capability behind a stable contract.',
    metadata: {
      summary: 'Microservice API exposing one bounded context.',
      contact: {
        name: 'Service Owners',
        url: 'https://example.com/docs',
        email: 'team@example.com',
      },
      license: {
        name: 'Apache License 2.0',
        identifier: 'Apache-2.0',
        url: 'https://spdx.org/licenses/Apache-2.0.html',
      },
    },
  },
  {
    id: 'openapi-design',
    label: 'OpenAPI design starter',
    hint: 'Emphasizes documentation and standards-friendly licensing for design-first workflows.',
    suggestedDescription: 'Design-first API: iterate on the OpenAPI model before implementation.',
    metadata: {
      summary: 'API under active OpenAPI design; contract may change during review.',
      termsOfService: 'https://example.com/api-terms',
      contact: {
        name: 'API Design',
        url: 'https://example.com/api',
        email: 'api-design@example.com',
      },
      license: {
        name: 'Apache License 2.0',
        identifier: 'Apache-2.0',
        url: 'https://spdx.org/licenses/Apache-2.0.html',
      },
    },
  },
];

export function getProjectStartTemplate(id: string): ProjectStartTemplate | undefined {
  return PROJECT_START_TEMPLATES.find((t) => t.id === id);
}

export function applyProjectStartTemplate(id: string): {
  suggestedDescription: string;
  metadata: ProjectOpenApiMetadata;
} {
  const t = getProjectStartTemplate(id) ?? getProjectStartTemplate(BLANK_TEMPLATE_ID)!;
  return {
    suggestedDescription: t.suggestedDescription,
    metadata: JSON.parse(JSON.stringify(t.metadata)) as ProjectOpenApiMetadata,
  };
}
