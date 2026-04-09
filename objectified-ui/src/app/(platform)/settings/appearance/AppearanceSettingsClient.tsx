'use client';

import * as React from 'react';
import * as Popover from '@radix-ui/react-popover';
import { useTheme } from '@/app/providers/ThemeProvider';
import type { ThemePaletteOverrides } from '@lib/theme/types';
import { RadioGroup, RadioGroupItem } from '@/app/components/ui/RadioGroup';
import { Button } from '@/app/components/ui/Button';
import { Input } from '@/app/components/ui/Input';
import { Label } from '@/app/components/ui/Label';
import { tryParseCssColor } from '@lib/theme/color-validation';

const PALETTE_KEYS: { key: keyof ThemePaletteOverrides; label: string }[] = [
  { key: 'primary', label: 'Primary' },
  { key: 'secondary', label: 'Secondary' },
  { key: 'accent', label: 'Accent' },
  { key: 'background', label: 'Background' },
  { key: 'surface', label: 'Surface' },
  { key: 'text', label: 'Text' },
];

type FormatTab = 'hex' | 'hsl' | 'rgb';

function rgbToHex(r: number, g: number, b: number): string {
  const h = (n: number) => n.toString(16).padStart(2, '0');
  return `#${h(r)}${h(g)}${h(b)}`;
}

function parseRgbFromComputed(computed: string): { r: number; g: number; b: number } | null {
  const m = computed.match(/^rgba?\(([^)]+)\)/);
  if (!m) return null;
  const parts = m[1].split(',').map((p) => parseFloat(p.trim()));
  if (parts.length < 3) return null;
  return { r: parts[0], g: parts[1], b: parts[2] };
}

function ColorTokenPopover({
  label,
  value,
  fallbackColor,
  onChange,
}: {
  label: string;
  value: string | undefined;
  fallbackColor: string;
  onChange: (v: string | undefined) => void;
}) {
  const [open, setOpen] = React.useState(false);
  const [tab, setTab] = React.useState<FormatTab>('hex');
  const [hex, setHex] = React.useState('#000000');
  const [hsl, setHsl] = React.useState('0, 0%, 50%');
  const [rgb, setRgb] = React.useState('128, 128, 128');
  const [err, setErr] = React.useState('');

  const syncFromColor = (color: string) => {
    const ok = tryParseCssColor(color);
    if (!ok) return;
    if (typeof document !== 'undefined') {
      const el = document.createElement('div');
      el.style.color = ok;
      document.body.appendChild(el);
      const computed = getComputedStyle(el).color;
      document.body.removeChild(el);
      const rgbObj = parseRgbFromComputed(computed);
      if (rgbObj) {
        setRgb(`${rgbObj.r}, ${rgbObj.g}, ${rgbObj.b}`);
        setHex(rgbToHex(Math.round(rgbObj.r), Math.round(rgbObj.g), Math.round(rgbObj.b)));
      }
    }
  };

  React.useEffect(() => {
    if (open) {
      const base = value || '#6366f1';
      setHex(base.startsWith('#') ? base : '#6366f1');
      syncFromColor(base);
      setErr('');
    }
  }, [open, value]);

  const apply = () => {
    let raw = '';
    if (tab === 'hex') raw = hex;
    else if (tab === 'hsl') raw = `hsl(${hsl})`;
    else raw = `rgb(${rgb})`;
    const parsed = tryParseCssColor(raw);
    if (!parsed) {
      setErr('Invalid color');
      return;
    }
    onChange(parsed);
    setErr('');
    setOpen(false);
  };

  const clear = () => {
    onChange(undefined);
    setOpen(false);
  };

  return (
    <div className="flex flex-col gap-1">
      <Label className="text-xs font-medium text-slate-600 dark:text-slate-400">{label}</Label>
      <Popover.Root open={open} onOpenChange={setOpen}>
        <Popover.Trigger asChild>
          <button
            type="button"
            className="flex h-9 w-full max-w-xs items-center gap-2 rounded-md border border-slate-300 bg-white px-2 text-left text-sm dark:border-slate-600 dark:bg-slate-900"
          >
            <span
              className="h-6 w-6 shrink-0 rounded border border-slate-200 dark:border-slate-600"
              style={{ backgroundColor: value ?? fallbackColor }}
            />
            <span className="truncate text-slate-700 dark:text-slate-200">{value || 'Default'}</span>
          </button>
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content
            className="z-[3000] w-72 rounded-md border border-slate-200 bg-white p-3 shadow-lg dark:border-slate-600 dark:bg-slate-900"
            sideOffset={4}
          >
            <div className="mb-2 flex gap-1">
              {(['hex', 'hsl', 'rgb'] as const).map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => setTab(t)}
                  className={
                    tab === t
                      ? 'rounded bg-indigo-100 px-2 py-1 text-xs font-medium text-indigo-800 dark:bg-indigo-900/50 dark:text-indigo-200'
                      : 'rounded px-2 py-1 text-xs text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800'
                  }
                >
                  {t.toUpperCase()}
                </button>
              ))}
            </div>
            {tab === 'hex' && (
              <div className="space-y-2">
                <input
                  type="color"
                  value={hex.startsWith('#') ? hex.slice(0, 7) : '#000000'}
                  onChange={(e) => {
                    setHex(e.target.value);
                    syncFromColor(e.target.value);
                  }}
                  className="h-10 w-full cursor-pointer"
                  aria-label="Pick color"
                />
                <Input value={hex} onChange={(e) => setHex(e.target.value)} placeholder="#RRGGBB" />
              </div>
            )}
            {tab === 'hsl' && (
              <Input
                value={hsl}
                onChange={(e) => setHsl(e.target.value)}
                placeholder="e.g. 250 80% 60%"
              />
            )}
            {tab === 'rgb' && (
              <Input value={rgb} onChange={(e) => setRgb(e.target.value)} placeholder="e.g. 99, 102, 241" />
            )}
            {err && <p className="text-xs text-red-600">{err}</p>}
            <div className="mt-3 flex justify-end gap-2">
              <Button type="button" variant="outline" size="sm" onClick={clear}>
                Clear
              </Button>
              <Button type="button" size="sm" onClick={apply}>
                Apply
              </Button>
            </div>
            <Popover.Arrow className="fill-white dark:fill-slate-900" />
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
    </div>
  );
}

export function AppearanceSettingsClient() {
  const {
    currentTheme,
    setTheme,
    paletteOverrides,
    setPaletteOverrides,
    resetPaletteToThemeDefaults,
    persistThemePreference,
  } = useTheme();

  const [mode, setMode] = React.useState<'light' | 'dark' | 'system'>('system');

  React.useEffect(() => {
    const id = currentTheme.id;
    if (id === 'light' || id === 'dark' || id === 'system') {
      setMode(id);
    }
  }, [currentTheme.id]);

  const [saving, setSaving] = React.useState(false);
  const [message, setMessage] = React.useState('');

  const onModeChange = (v: string) => {
    if (v !== 'light' && v !== 'dark' && v !== 'system') return;
    setMode(v);
    setTheme(v);
  };

  const onSave = async () => {
    setSaving(true);
    setMessage('');
    try {
      await persistThemePreference();
      setMessage('Saved.');
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mt-6 space-y-8">
      <section aria-labelledby="theme-mode-heading">
        <h2 id="theme-mode-heading" className="text-lg font-medium text-slate-900 dark:text-slate-100">
          Theme mode
        </h2>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
          Light, Dark, or System (follows your OS). Changes apply immediately without reloading.
        </p>
        <RadioGroup value={mode} onValueChange={onModeChange} className="mt-4 grid gap-3 sm:grid-cols-3">
          <div className="flex flex-col gap-2 rounded-lg border border-slate-200 p-3 dark:border-slate-700">
            <RadioGroupItem value="light" label="Light" />
            <div className="h-14 rounded-md border border-slate-200 bg-white shadow-sm dark:border-slate-600" />
          </div>
          <div className="flex flex-col gap-2 rounded-lg border border-slate-200 p-3 dark:border-slate-700">
            <RadioGroupItem value="dark" label="Dark" />
            <div className="h-14 rounded-md border border-slate-600 bg-slate-900 shadow-sm" />
          </div>
          <div className="flex flex-col gap-2 rounded-lg border border-slate-200 p-3 dark:border-slate-700">
            <RadioGroupItem value="system" label="System" />
            <div className="flex h-14 overflow-hidden rounded-md border border-slate-300 dark:border-slate-600">
              <div className="w-1/2 bg-white" />
              <div className="w-1/2 bg-slate-900" />
            </div>
          </div>
        </RadioGroup>
      </section>

      <section aria-labelledby="custom-palette-heading">
        <h2 id="custom-palette-heading" className="text-lg font-medium text-slate-900 dark:text-slate-100">
          Custom palette
        </h2>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
          Optional overrides for key colors. Use hex, HSL, or RGB in the popover.
        </p>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          {PALETTE_KEYS.map(({ key, label }) => (
            <ColorTokenPopover
              key={key}
              label={label}
              fallbackColor={
                key === 'primary'
                  ? currentTheme.colors.primary
                  : key === 'secondary'
                    ? currentTheme.colors.secondary
                    : key === 'accent'
                      ? currentTheme.colors.accent
                      : key === 'background'
                        ? currentTheme.colors.background
                        : key === 'surface'
                          ? currentTheme.colors.card
                          : currentTheme.colors.foreground
              }
              value={paletteOverrides[key]}
              onChange={(v) =>
                setPaletteOverrides((prev) => {
                  const next = { ...prev };
                  if (v === undefined) delete next[key];
                  else next[key] = v;
                  return next;
                })
              }
            />
          ))}
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button type="button" variant="outline" onClick={resetPaletteToThemeDefaults}>
            Reset to theme defaults
          </Button>
          <Button type="button" onClick={onSave} disabled={saving}>
            {saving ? 'Saving…' : 'Save preferences'}
          </Button>
          {message && <span className="text-sm text-slate-600 dark:text-slate-400">{message}</span>}
        </div>
      </section>
    </div>
  );
}
