/**
 * Shared shapes for the project creation wizard. Lives outside the dialog
 * itself so individual step components can import the types without a
 * circular dependency.
 */

import { BLANK_TEMPLATE_ID, type ProjectOpenApiMetadata } from '../../../../utils/project-templates';
import { PROJECT_DOMAIN_CATEGORY_NONE } from '../../../../utils/project-domain-categories';

export type WizardPath = 'manual' | 'ai' | 'import';

export type WizardStepId = 'path' | 'basics' | 'template' | 'review';

export const WIZARD_STEPS: WizardStepId[] = ['path', 'basics', 'template', 'review'];

export interface WizardBasics {
  name: string;
  slug: string;
  /** Whether the user manually edited the slug — disables auto-derive. */
  slugTouched: boolean;
  description: string;
  domainCategory: string;
}

export interface WizardTemplate {
  templateId: string;
  metadata: ProjectOpenApiMetadata;
}

export interface WizardState {
  path: WizardPath;
  basics: WizardBasics;
  template: WizardTemplate;
}

export function createInitialWizardState(): WizardState {
  return {
    path: 'manual',
    basics: {
      name: '',
      slug: '',
      slugTouched: false,
      description: '',
      domainCategory: PROJECT_DOMAIN_CATEGORY_NONE,
    },
    template: {
      templateId: BLANK_TEMPLATE_ID,
      metadata: {},
    },
  };
}
