import { AppearanceSettingsClient } from './AppearanceSettingsClient';

export const metadata = {
  title: 'Appearance · Objectified',
};

export default function AppearanceSettingsPage() {
  return (
    <div className="mx-auto max-w-3xl px-4 py-8">
      <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-slate-100">Appearance</h1>
      <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
        Choose a built-in theme, tune colors, and save your preferences for this account.
      </p>
      <AppearanceSettingsClient />
    </div>
  );
}
