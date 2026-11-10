/**
 * @jest-environment node
 *
 * ESLint's flat-config layer calls `structuredClone`, which `jest-environment-jsdom` does
 * not expose. Nothing here touches the DOM — the rule reads an AST.
 */

/**
 * `hive/no-raw-form-control` — the form-control backstop.
 *
 * Two halves. The first proves the rule fires on a raw `<input>`, `<select>` or `<textarea>`
 * and stays quiet on the primitives and on the input types that have none. The second is the
 * ratchet: it runs the rule over the app and holds the result against
 * `eslint-rules/raw-form-control-baseline.json`, the list of files that predate the rule. A
 * file outside the list may not contain a raw control, and a file on the list must still
 * contain one — so a migrated file has to be struck off, and the list only gets shorter.
 */

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';
import { Linter, RuleTester } from 'eslint';
import * as tsParser from '@typescript-eslint/parser';
import hive from '../eslint-rules/hive.js';
import baseline from '../eslint-rules/raw-form-control-baseline.json';

const rule = hive.rules['no-raw-form-control'];

const ruleTester = new RuleTester({
  languageOptions: {
    ecmaVersion: 2022,
    sourceType: 'module',
    parserOptions: { ecmaFeatures: { jsx: true } },
  },
});

describe('hive/no-raw-form-control', () => {
  // `RuleTester` declares a `describe`/`it` of its own per case, so it runs in the suite
  // body rather than inside a test — Jest refuses a nested `it`.
  ruleTester.run('no-raw-form-control', rule, {
    valid: [
      // The primitives are components, not intrinsic elements.
      { code: 'const a = <Input id="name" />;' },
      { code: 'const a = <Select><SelectTrigger /></Select>;' },
      { code: 'const a = <Textarea rows={3} />;' },
      { code: 'const a = <Checkbox checked />;' },
      // Input types with no primitive: the browser's control is the right one, or nothing is drawn.
      { code: 'const a = <input type="hidden" name="csrf" value={token} />;' },
      { code: 'const a = <input type="file" accept=".json" onChange={onPick} />;' },
      { code: 'const a = <input type="range" min={0} max={10} />;' },
      { code: 'const a = <input type="color" />;' },
      { code: 'const a = <input type={"file"} />;' },
      // Other intrinsic elements are none of this rule's business.
      { code: 'const a = <button type="button">Save</button>;' },
      { code: 'const a = <option value="a">A</option>;' },
      // A member expression is somebody's component, whatever it is called.
      { code: 'const a = <Form.input />;' },
    ],
    invalid: [
      {
        code: 'const a = <input className="h-9 rounded-md border" />;',
        errors: [{ messageId: 'rawControl', data: { element: 'input', primitive: '<Input>' } }],
      },
      {
        code: 'const a = <input type="text" />;',
        errors: [{ messageId: 'rawControl', data: { element: 'input', primitive: '<Input>' } }],
      },
      {
        code: 'const a = <input type="password" autoComplete="current-password" />;',
        errors: [{ messageId: 'rawControl', data: { element: 'input', primitive: '<Input>' } }],
      },
      // A computed type could be anything, so it is held to the common case.
      {
        code: 'const a = <input type={kind} />;',
        errors: [{ messageId: 'rawControl', data: { element: 'input', primitive: '<Input>' } }],
      },
      {
        code: 'const a = <input type="checkbox" checked={on} onChange={toggle} />;',
        errors: [{ messageId: 'rawControl', data: { element: 'input', primitive: '<Checkbox> or <Switch>' } }],
      },
      {
        code: 'const a = <input type="radio" name="mode" />;',
        errors: [{ messageId: 'rawControl', data: { element: 'input', primitive: '<RadioGroup>' } }],
      },
      {
        code: 'const a = <select value={v}><option>A</option></select>;',
        errors: [{ messageId: 'rawControl', data: { element: 'select', primitive: '<Select>' } }],
      },
      {
        code: 'const a = <textarea rows={4} />;',
        errors: [{ messageId: 'rawControl', data: { element: 'textarea', primitive: '<Textarea>' } }],
      },
    ],
  });
});

describe('the raw-form-control baseline', () => {
  const PROJECT_ROOT = resolve(__dirname, '..');
  const APP_ROOT = join(PROJECT_ROOT, 'src', 'app');
  /** The primitives are the one place a raw control is drawn. */
  const PRIMITIVES = join(APP_ROOT, 'components', 'ui');

  /** Every `.tsx` under `src/app`, outside the primitives. */
  function sourceFiles(): string[] {
    const found: string[] = [];
    const walk = (absolute: string) => {
      for (const entry of readdirSync(absolute)) {
        const child = join(absolute, entry);
        if (child === PRIMITIVES) continue;
        if (statSync(child).isDirectory()) walk(child);
        else if (child.endsWith('.tsx')) found.push(child);
      }
    };
    walk(APP_ROOT);
    return found;
  }

  /** Project-relative paths of the files the rule reports in, read off the tree as it is now. */
  const offenders = (() => {
    const linter = new Linter({ configType: 'flat' });
    const config = [
      {
        files: ['**/*.tsx'],
        languageOptions: { parser: tsParser, parserOptions: { ecmaFeatures: { jsx: true } } },
        plugins: { hive },
        rules: { 'hive/no-raw-form-control': 'error' as const },
      },
    ];
    return sourceFiles()
      .filter((file) => {
        const source = readFileSync(file, 'utf8');
        // Cheap pre-filter: a file with none of the three tags cannot be reported.
        if (!/<(?:input|select|textarea)\b/.test(source)) return false;
        const messages = linter.verify(source, config, { filename: 'file.tsx' });
        // A file the parser could not read would otherwise pass as "no raw controls".
        const fatal = messages.find((message) => message.fatal);
        if (fatal) throw new Error(`${relative(PROJECT_ROOT, file)}: ${fatal.message}`);
        return messages.some((message) => message.ruleId === 'hive/no-raw-form-control');
      })
      .map((file) => relative(PROJECT_ROOT, file).split('\\').join('/'))
      .sort();
  })();

  it('lets no file outside the baseline draw a raw control', () => {
    const listed = new Set(baseline as string[]);
    expect(offenders.filter((file) => !listed.has(file))).toEqual([]);
  });

  it('only gets shorter: a file with no raw control left has been struck off', () => {
    const current = new Set(offenders);
    expect((baseline as string[]).filter((file) => !current.has(file))).toEqual([]);
  });

  it('is sorted, so two branches that each strike a line merge cleanly', () => {
    expect(baseline).toEqual([...(baseline as string[])].sort());
  });
});
