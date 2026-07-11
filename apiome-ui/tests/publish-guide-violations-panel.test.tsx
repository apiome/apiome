import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PublishGuideViolationsPanel } from '@/app/components/ade/dashboard/PublishGuideViolationsPanel';
import * as versionLintReport from '@/app/utils/version-lint-report';

jest.mock('@/app/utils/version-lint-report', () => ({
  ...jest.requireActual('@/app/utils/version-lint-report'),
  fetchVersionLintReport: jest.fn(),
}));

const fetchVersionLintReport = versionLintReport.fetchVersionLintReport as jest.Mock;

describe('PublishGuideViolationsPanel', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('shows per-severity counts and expandable error violations', async () => {
    fetchVersionLintReport.mockResolvedValue({
      projectId: 'p1',
      versionRecordId: 'v1',
      versionId: '1.0.0',
      score: 72,
      grade: 'C',
      findings: [
        {
          id: 'e1',
          path: 'components.schemas.Pet',
          category: 'documentation',
          rule: 'schema-description',
          severity: 'error',
          message: 'Missing description',
        },
        {
          id: 'w1',
          path: 'components.schemas.Cat',
          category: 'naming',
          rule: 'schema-pascal-case',
          severity: 'warning',
          message: 'Use PascalCase',
        },
      ],
      ruleHits: {},
      severityCounts: { error: 1, warning: 1, info: 0 },
      reportFingerprint: 'abc',
      baseRevisionId: null,
      compatibilityOverall: null,
      guideName: 'Team Guide',
    });

    render(<PublishGuideViolationsPanel projectId="p1" versionId="v1" />);

    await waitFor(() => {
      expect(screen.getByTestId('publish-guide-violations-panel')).toBeInTheDocument();
    });

    expect(screen.getByText('Team Guide')).toBeInTheDocument();
    expect(screen.getByText('1 error')).toBeInTheDocument();
    expect(screen.getByText('1 warning')).toBeInTheDocument();
    expect(screen.getByText(/block publishing/i)).toBeInTheDocument();

    await userEvent.click(screen.getByTestId('publish-guide-errors-toggle'));
    expect(screen.getByText('schema-description')).toBeInTheDocument();
    expect(screen.getByText('components.schemas.Pet')).toBeInTheDocument();
  });

  it('allows publish messaging when only warnings remain', async () => {
    fetchVersionLintReport.mockResolvedValue({
      projectId: 'p1',
      versionRecordId: 'v1',
      versionId: '1.0.0',
      score: 90,
      grade: 'A',
      findings: [
        {
          id: 'w1',
          path: 'components.schemas.Pet',
          category: 'naming',
          rule: 'schema-pascal-case',
          severity: 'warning',
          message: 'Use PascalCase',
        },
      ],
      ruleHits: {},
      severityCounts: { error: 0, warning: 1, info: 0 },
      reportFingerprint: 'abc',
      baseRevisionId: null,
      compatibilityOverall: null,
      guideName: 'Apiome Recommended',
    });

    render(<PublishGuideViolationsPanel projectId="p1" versionId="v1" />);

    await waitFor(() => {
      expect(screen.getByText(/publishing is allowed/i)).toBeInTheDocument();
    });
  });
});
