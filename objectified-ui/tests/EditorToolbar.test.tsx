/**
 * Component tests for the class-designer (Studio) editor toolbar (RC1-3.1, #3616).
 *
 * EditorToolbar is the primary chrome of the class designer: it owns project/version selection, the
 * canvas/code view switch, tag management, and the canvas export menu. It was previously uncovered.
 * These tests render it with React Testing Library and assert the props-driven behaviour the editor
 * depends on, without a database or the heavy canvas runtime.
 */

import React from 'react';
import { render as rtlRender, screen, fireEvent } from '@testing-library/react';
import * as Tooltip from '@radix-ui/react-tooltip';
import { EditorToolbar } from '../src/app/ade/studio/editor/components/EditorToolbar';

type ToolbarProps = React.ComponentProps<typeof EditorToolbar>;

/** The toolbar's Export control uses a Radix Tooltip, which requires a Tooltip.Provider ancestor
 *  (supplied by the app shell in production). Wrap renders so the component mounts as it does live. */
function render(ui: React.ReactElement) {
  return rtlRender(<Tooltip.Provider>{ui}</Tooltip.Provider>);
}

/** Build a fully-populated props object; individual tests override the handful of fields they assert. */
function makeProps(overrides: Partial<ToolbarProps> = {}): ToolbarProps {
  const noop = () => {};
  const asyncNoop = async () => {};
  return {
    // Data
    projects: [{ id: 'p1', name: 'Acme API' } as any],
    versions: [{ id: 'v1', published: false } as any],
    selectedProjectId: 'p1',
    selectedVersionId: 'v1',
    viewMode: 'canvas',
    isReadOnly: false,
    isDark: false,
    isLoadingProjects: false,
    isLoadingVersions: false,
    currentTenantId: 't1',
    clickToFocusEnabled: false,
    lodEnabled: false,
    layoutSaved: false,
    // Setters
    setSelectedProjectId: jest.fn(),
    setContextProjectId: jest.fn(),
    setSelectedVersionId: jest.fn(),
    setContextVersionId: jest.fn(),
    setIsReadOnly: jest.fn(),
    setViewMode: jest.fn(),
    setTagManagerOpen: jest.fn(),
    setProjectTags: jest.fn(),
    // Handlers
    loadProjectTags: jest.fn(asyncNoop),
    toggleTheme: jest.fn(),
    toggleClickToFocus: jest.fn(),
    toggleLod: jest.fn(),
    handleSaveLayout: jest.fn(asyncNoop),
    handleLoadLayout: jest.fn(asyncNoop),
    // Export handlers
    handleExportPng: jest.fn(asyncNoop),
    handleExportSvg: jest.fn(asyncNoop),
    handleExportJpeg: jest.fn(asyncNoop),
    handleExportPdf: jest.fn(asyncNoop),
    handleExportMermaid: jest.fn(asyncNoop),
    handleExportPlantUml: jest.fn(asyncNoop),
    handleExportDot: jest.fn(asyncNoop),
    handleExportGraphMl: jest.fn(asyncNoop),
    handleExportJson: jest.fn(asyncNoop),
    // Dropdown state
    exportDropdownOpen: false,
    setExportDropdownOpen: jest.fn(),
    layoutDropdownOpen: false,
    setLayoutDropdownOpen: jest.fn(),
    exportDropdownRef: { current: null } as any,
    layoutDropdownRef: { current: null } as any,
    ...overrides,
  };
}

describe('EditorToolbar (class designer)', () => {
  it('shows editor actions once a project and version are selected', () => {
    render(<EditorToolbar {...makeProps()} />);
    expect(screen.getByText('Tags')).toBeInTheDocument();
    expect(screen.getByText('Canvas')).toBeInTheDocument();
    expect(screen.getByText('Code')).toBeInTheDocument();
    expect(screen.getByText('Export')).toBeInTheDocument();
  });

  it('hides editor actions until both a project and a version are selected', () => {
    render(<EditorToolbar {...makeProps({ selectedVersionId: '' })} />);
    expect(screen.queryByText('Tags')).not.toBeInTheDocument();
    expect(screen.queryByText('Export')).not.toBeInTheDocument();
  });

  it('opens the tag manager when Tags is clicked', () => {
    const setTagManagerOpen = jest.fn();
    render(<EditorToolbar {...makeProps({ setTagManagerOpen })} />);
    fireEvent.click(screen.getByText('Tags'));
    expect(setTagManagerOpen).toHaveBeenCalledWith(true);
  });

  it('switches to the code view from the view toggle', () => {
    const setViewMode = jest.fn();
    render(<EditorToolbar {...makeProps({ setViewMode })} />);
    fireEvent.click(screen.getByText('Code'));
    expect(setViewMode).toHaveBeenCalledWith('code');
  });

  it('toggles the export menu open when Export is clicked', () => {
    const setExportDropdownOpen = jest.fn();
    render(<EditorToolbar {...makeProps({ exportDropdownOpen: false, setExportDropdownOpen })} />);
    fireEvent.click(screen.getByText('Export'));
    expect(setExportDropdownOpen).toHaveBeenCalledWith(true);
  });

  it('invokes the matching export handler from the open export menu', () => {
    const handleExportPng = jest.fn();
    const handleExportJson = jest.fn();
    render(
      <EditorToolbar
        {...makeProps({ exportDropdownOpen: true, handleExportPng, handleExportJson })}
      />,
    );
    fireEvent.click(screen.getByText('PNG Image'));
    expect(handleExportPng).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByText('Canvas JSON'));
    expect(handleExportJson).toHaveBeenCalledTimes(1);
  });

  it('does not render the export menu while in code view', () => {
    render(<EditorToolbar {...makeProps({ viewMode: 'code', exportDropdownOpen: true })} />);
    expect(screen.queryByText('PNG Image')).not.toBeInTheDocument();
  });
});
