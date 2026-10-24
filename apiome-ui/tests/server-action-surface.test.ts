/**
 * The server-action surface: every `'use server'` module and every function it exports.
 *
 * Each export of a `'use server'` module is a public POST endpoint — anyone holding its action id
 * can call it with any arguments — so the set is pinned here, with how each module checks its
 * caller. Data libraries (`lib/db/helper.ts`, `lib/db/admin-helper.ts`, `lib/db/import-helper.ts`
 * and the other `lib/db` helpers) must not be `'use server'`; client components reach them through
 * the guarded action modules listed below.
 *
 * **This test failing means a server action was added, removed or renamed.** Before updating the
 * ledger, make sure the new action checks its caller — use `lib/auth/action-guard.ts` — and say
 * how in `check`.
 */

import { describe, test, expect } from '@jest/globals';
import fs from 'fs';
import path from 'path';

const ROOT = path.resolve(__dirname, '..');

/** Every `'use server'` module, how it checks callers, and its exports. */
const LEDGER: Record<string, { check: string; exports: string[] }> = {
  'lib/auth/better-auth-one-time-code-actions.ts': {
    check: 'public: verifies a one-time sign-in code with Better Auth',
    exports: ['completeOneTimeCodeSignIn'],
  },
  'lib/auth/cli-login-actions.ts': {
    check: 'session: callCliLogin requires a signed-in user before calling REST',
    exports: ['getCliLoginRequest', 'approveCliLogin', 'denyCliLogin'],
  },
  'lib/auth/email-signup-actions.ts': {
    check: 'public by design: sign-up policy, rate limits and verification tokens (SGN-1.1/1.5)',
    exports: ['startEmailSignup', 'resendSignupVerification', 'verifyEmailSignup'],
  },
  'lib/auth/first-tenant-actions.ts': {
    check: 'session: provisions a workspace for the session user only',
    exports: ['provisionFirstTenant', 'provisionAdditionalTenant'],
  },
  'lib/auth/last-active-tenant-actions.ts': {
    check: "session: sets the session user's own active workspace after a membership check",
    exports: ['persistLastActiveTenant', 'setActiveTenant'],
  },
  'lib/auth/logout-actions.ts': {
    check: "public: only expires the caller's own cookies",
    exports: ['serverLogout'],
  },
  'lib/auth/oauth-signup-actions.ts': {
    check: 'public by design: completes a pending OAuth sign-up by its single-use, hour-lived pending id',
    exports: ['checkOauthSignupSlugAvailability', 'completeOAuthSignup'],
  },
  'lib/auth/onboarding-wizard-state-actions.ts': {
    check: "session: currentUser() — the session user's own wizard state",
    exports: ['loadOnboardingWizardState', 'saveOnboardingWizardStep', 'completeOnboardingWizard'],
  },
  'lib/auth/tenant-membership-context.ts': {
    check: "session: the session user's own memberships",
    exports: ['loadTenantMembershipContext'],
  },
  'lib/auth/tenant-slug-availability.ts': {
    check: 'session: signed-in slug probe',
    exports: ['checkTenantSlugAvailability'],
  },
  'lib/auth/two-factor-profile-actions.ts': {
    check: "session: the session user's own two-factor state (getEmailOtpAvailability reads config only)",
    exports: ['getBackupCodeStatus', 'getTrustedDeviceStatus', 'revokeThisTrustedDevice', 'getEmailOtpAvailability', 'getTwoFactorReauthStatus', 'getTwoFactorResetNotice', 'dismissTwoFactorResetNotice'],
  },
  'lib/auth/two-factor-requirement-actions.ts': {
    check: "session: the session user's own requirement",
    exports: ['getMyTwoFactorRequirement'],
  },
  'lib/db/admin-actions.ts': {
    check: 'requireSuperAdmin on every export',
    exports: ['getAllUsers', 'createUser', 'updateUser', 'deleteUser', 'getUserStats', 'getTenantStats', 'getTenantUsers', 'createTenant', 'updateTenant', 'deleteTenant', 'addUserToTenant', 'removeUserFromTenant', 'addTenantAdministrator', 'provisionSampleProject', 'removeTenantAdministrator', 'getUsersNotInTenant', 'getAllPropertyTemplates', 'getPropertyTemplateCategoriesAdmin', 'createPropertyTemplateAdmin', 'updatePropertyTemplateAdmin', 'deletePropertyTemplateAdmin', 'getAllLicenses', 'createLicense', 'updateLicense', 'deleteLicense', 'getAllFeatureFlags', 'createFeatureFlag', 'updateFeatureFlag', 'deleteFeatureFlag', 'getAllFeatureFlagGroups', 'createFeatureFlagGroup', 'updateFeatureFlagGroup', 'deleteFeatureFlagGroup', 'getAllUsersWithLicenses', 'getUserLicense', 'assignLicenseToUser', 'removeUserLicense', 'setUserFeatureFlag', 'removeUserFeatureFlag', 'togglePropertyTemplateStatus', 'getPropertyTemplateStats'],
  },
  'lib/db/commercial-access.ts': {
    check: "session: the session workspace's entitlements",
    exports: ['getCommercialAccessForSession'],
  },
  'lib/db/dashboard-home.ts': {
    check: "session: the session user's dashboard",
    exports: ['getDashboardHomeForSession'],
  },
  'lib/db/helper-actions.ts': {
    check: 'action-guard check per export (see the module table)',
    exports: ['getDashboardStats', 'getRecentActivity', 'getTenantsForUser', 'getTenantsAdministratedByUser', 'updateUserName', 'updateUserPassword', 'getCurrentUserLastLoginAt', 'getLinkedAccountsForUser', 'getUserHasPassword', 'unlinkExternalAccount', 'updatePersonalAccessToken', 'removePersonalAccessToken', 'getTenantUsers', 'updateTenant', 'addTenantAdministrator', 'addTenantUser', 'removeTenantAdministrator', 'removeTenantUser', 'createProject', 'updateProject', 'deleteProject', 'restoreProject', 'permanentDeleteProject', 'importProjectFromOpenAPI', 'getPublishedVersionsForTenant', 'updateVersionVisibility', 'deleteVersion', 'getClassesForVersion', 'getPropertiesForClass', 'getPropertiesForClassesBatch', 'buildOpenApiSpecJsonForVersion', 'getDefaultCanvasLayout', 'getEffectiveDefaultLayoutName', 'getNamedCanvasLayout', 'getApiKeysForTenant', 'createApiKey', 'deleteApiKey', 'toggleApiKeyStatus'],
  },
  'lib/db/import-actions.ts': {
    check: 'requireSelf + imports:create to start; job owner for the rest',
    exports: ['startImport', 'getImportStatus', 'cancelImport', 'commitImport', 'rollbackImport', 'rollbackCompletedImport', 'retryImport'],
  },
  'lib/db/project-pins.ts': {
    check: 'session: sessionReader() — the reader comes from the session',
    exports: ['listPinnedProjectsForSession', 'listPinnedProjectIdsForSession', 'pinProjectForSession', 'unpinProjectForSession'],
  },
  'lib/db/project-time.ts': {
    check: "session: the session user's own time",
    exports: ['recordProjectTimeForSession'],
  },
  'lib/db/project-views.ts': {
    check: "session: the session user's own views",
    exports: ['recordProjectViewForSession'],
  },
};

/** Source files under a directory, skipping dependencies and build output. */
function sources(dir: string): string[] {
  const out: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === 'node_modules' || entry.name.startsWith('.')) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...sources(full));
    else if (/\.(ts|tsx|js|jsx)$/.test(entry.name)) out.push(full);
  }
  return out;
}

/** Whether a file opens with the `'use server'` directive (after any comments). */
function isUseServer(text: string): boolean {
  const stripped = text.replace(/^(\s*(\/\/[^\n]*\n|\/\*[\s\S]*?\*\/))*\s*/, '');
  return /^['"]use server['"]/.test(stripped);
}

/** The functions a module exports (`export [async] function x` and `export const x`). */
function exportedNames(text: string): string[] {
  return [...text.matchAll(/^export (?:async )?function (\w+)|^export const (\w+)/gm)].map((m) => m[1] ?? m[2]);
}

const actual: Record<string, string[]> = {};
for (const file of [...sources(path.join(ROOT, 'lib')), ...sources(path.join(ROOT, 'src'))]) {
  const text = fs.readFileSync(file, 'utf8');
  if (isUseServer(text)) actual[path.relative(ROOT, file).split(path.sep).join('/')] = exportedNames(text);
}

describe('server-action surface', () => {
  test('the use-server modules are exactly the ledger’s', () => {
    expect(Object.keys(actual).sort()).toEqual(Object.keys(LEDGER).sort());
  });

  test.each(Object.keys(LEDGER))('%s exports exactly its ledger entry', (file) => {
    expect((actual[file] ?? []).slice().sort()).toEqual(LEDGER[file].exports.slice().sort());
  });

  test('data libraries are not server actions', () => {
    for (const file of ['lib/db/helper.ts', 'lib/db/admin-helper.ts', 'lib/db/import-helper.ts']) {
      expect(actual[file]).toBeUndefined();
    }
  });

  test('every module says how it checks its caller', () => {
    for (const [file, entry] of Object.entries(LEDGER)) expect([file, entry.check.trim()]).not.toEqual([file, '']);
  });
});
