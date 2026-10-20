'use client';

/**
 * The **Compass export** source of the **Import to catalog** wizard — CDG-5.5 (#5983).
 *
 * Choose the JSON file Atlassian Compass exported (components, owners, links and relationships;
 * at most 5 MB) and **Import export**. The file is staged as an import report: its components and
 * owners become suggestions, and every field with no Apiome equivalent is listed. Nothing is created
 * until a suggestion is accepted, so the wizard shows the report next ({@link MigrationReport}).
 */

import * as React from 'react';
import { FileJson, Upload } from 'lucide-react';

import { Alert, Button, Spinner } from '@/app/components/ui';
import { compassFileProblem, type MigrationRun } from '@lib/catalog-migrations';
import { uploadCompassExport } from './catalogMigrationsApi';

/** A file's text (`Blob.text()`, or a `FileReader` where it is missing). */
function readText(file: File): Promise<string> {
  if (typeof file.text === 'function') return file.text();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ''));
    reader.onerror = () => reject(new Error('Could not read the file'));
    reader.readAsText(file);
  });
}

/** Props for {@link CompassImportIntake}. */
export interface CompassImportIntakeProps {
  /** Called with the staged report once the upload succeeded. */
  onImported: (run: MigrationRun) => void;
}

/**
 * The file picker and the upload.
 *
 * @param props - See {@link CompassImportIntakeProps}.
 * @returns The intake.
 */
export function CompassImportIntake({ onImported }: CompassImportIntakeProps) {
  const [file, setFile] = React.useState<File | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const inputId = React.useId();

  const choose = (chosen: File | null) => {
    setError(chosen ? compassFileProblem(chosen) : null);
    setFile(chosen);
  };

  const upload = async () => {
    if (!file) return;
    const problem = compassFileProblem(file);
    if (problem) {
      setError(problem);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      onImported(await uploadCompassExport(file.name, await readText(file)));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not import the Compass export');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mig-intake" data-testid="compass-intake">
      <p className="agt-muted">
        Export your components from Atlassian Compass as JSON — <span className="mono">{'{components, teams}'}</span> or a{' '}
        <span className="mono">searchComponents</span> response. Components, owners, links and{' '}
        <span className="mono">DEPENDS_ON</span> relationships come across as suggestions you accept one by one; every
        other field is listed in the report.
      </p>
      <label htmlFor={inputId} className="imp-drop mig-intake__drop">
        <span className="tnt-icon-tile imp-drop__glyph" data-tone="accent" aria-hidden>
          <FileJson />
        </span>
        <span className="mig-intake__name">{file ? file.name : 'Choose the Compass export (.json)'}</span>
        <input
          id={inputId}
          type="file"
          accept=".json,application/json"
          className="sr-only"
          onChange={(event) => choose(event.target.files?.[0] ?? null)}
          data-testid="compass-intake-file"
        />
      </label>
      {error ? <Alert variant="danger">{error}</Alert> : null}
      <div>
        <Button onClick={() => void upload()} disabled={!file || busy || Boolean(error)} data-testid="compass-intake-import">
          {busy ? <Spinner aria-hidden /> : <Upload aria-hidden />}
          Import export
        </Button>
      </div>
    </div>
  );
}
