'use server';

/**
 * The admin console's server actions.
 *
 * `lib/db/admin-helper.ts` used to be a `'use server'` module, so every user, tenant, licence and
 * feature-flag operation in it was a public endpoint that nobody had to sign in to call. It is now a
 * plain server library (the sign-up flows also call it, with no admin session), and the admin
 * console's client components call these wrappers instead. Each one first requires the super-admin
 * session the console signs in with (the `admin_session` cookie, `requireSuperAdmin`) and returns
 * `{ success: false, error: "Unauthorized" }` without it.
 *
 * Adding an export here is a security decision: `tests/server-action-surface.test.ts` lists every
 * action and fails on a new one.
 */

import { requireSuperAdmin } from '../auth/action-guard';
import * as admin from './admin-helper';

/**
 * Run `action` for a signed-in super admin; otherwise return the refusal.
 *
 * @param action The admin-helper call to make.
 * @returns Its result, or `{"success":false,"error":"Unauthorized"}`.
 */
async function asSuperAdmin<T>(action: () => Promise<T>): Promise<T | string> {
  const refusal = await requireSuperAdmin();
  return refusal ? JSON.stringify({ success: false, error: refusal }) : action();
}

export async function getAllUsers(...args: Parameters<typeof admin.getAllUsers>) {
  return asSuperAdmin(() => admin.getAllUsers(...args));
}

export async function createUser(...args: Parameters<typeof admin.createUser>) {
  return asSuperAdmin(() => admin.createUser(...args));
}

export async function updateUser(...args: Parameters<typeof admin.updateUser>) {
  return asSuperAdmin(() => admin.updateUser(...args));
}

export async function deleteUser(...args: Parameters<typeof admin.deleteUser>) {
  return asSuperAdmin(() => admin.deleteUser(...args));
}

export async function getUserStats(...args: Parameters<typeof admin.getUserStats>) {
  return asSuperAdmin(() => admin.getUserStats(...args));
}

export async function getTenantStats(...args: Parameters<typeof admin.getTenantStats>) {
  return asSuperAdmin(() => admin.getTenantStats(...args));
}

export async function getTenantUsers(...args: Parameters<typeof admin.getTenantUsers>) {
  return asSuperAdmin(() => admin.getTenantUsers(...args));
}

export async function createTenant(...args: Parameters<typeof admin.createTenant>) {
  return asSuperAdmin(() => admin.createTenant(...args));
}

export async function updateTenant(...args: Parameters<typeof admin.updateTenant>) {
  return asSuperAdmin(() => admin.updateTenant(...args));
}

export async function deleteTenant(...args: Parameters<typeof admin.deleteTenant>) {
  return asSuperAdmin(() => admin.deleteTenant(...args));
}

export async function addUserToTenant(...args: Parameters<typeof admin.addUserToTenant>) {
  return asSuperAdmin(() => admin.addUserToTenant(...args));
}

export async function removeUserFromTenant(...args: Parameters<typeof admin.removeUserFromTenant>) {
  return asSuperAdmin(() => admin.removeUserFromTenant(...args));
}

export async function addTenantAdministrator(...args: Parameters<typeof admin.addTenantAdministrator>) {
  return asSuperAdmin(() => admin.addTenantAdministrator(...args));
}

export async function provisionSampleProject(...args: Parameters<typeof admin.provisionSampleProject>) {
  return asSuperAdmin(() => admin.provisionSampleProject(...args));
}

export async function removeTenantAdministrator(...args: Parameters<typeof admin.removeTenantAdministrator>) {
  return asSuperAdmin(() => admin.removeTenantAdministrator(...args));
}

export async function getUsersNotInTenant(...args: Parameters<typeof admin.getUsersNotInTenant>) {
  return asSuperAdmin(() => admin.getUsersNotInTenant(...args));
}

export async function getAllPropertyTemplates(...args: Parameters<typeof admin.getAllPropertyTemplates>) {
  return asSuperAdmin(() => admin.getAllPropertyTemplates(...args));
}

export async function getPropertyTemplateCategoriesAdmin(...args: Parameters<typeof admin.getPropertyTemplateCategoriesAdmin>) {
  return asSuperAdmin(() => admin.getPropertyTemplateCategoriesAdmin(...args));
}

export async function createPropertyTemplateAdmin(...args: Parameters<typeof admin.createPropertyTemplateAdmin>) {
  return asSuperAdmin(() => admin.createPropertyTemplateAdmin(...args));
}

export async function updatePropertyTemplateAdmin(...args: Parameters<typeof admin.updatePropertyTemplateAdmin>) {
  return asSuperAdmin(() => admin.updatePropertyTemplateAdmin(...args));
}

export async function deletePropertyTemplateAdmin(...args: Parameters<typeof admin.deletePropertyTemplateAdmin>) {
  return asSuperAdmin(() => admin.deletePropertyTemplateAdmin(...args));
}

export async function getAllLicenses(...args: Parameters<typeof admin.getAllLicenses>) {
  return asSuperAdmin(() => admin.getAllLicenses(...args));
}

export async function createLicense(...args: Parameters<typeof admin.createLicense>) {
  return asSuperAdmin(() => admin.createLicense(...args));
}

export async function updateLicense(...args: Parameters<typeof admin.updateLicense>) {
  return asSuperAdmin(() => admin.updateLicense(...args));
}

export async function deleteLicense(...args: Parameters<typeof admin.deleteLicense>) {
  return asSuperAdmin(() => admin.deleteLicense(...args));
}

export async function getAllFeatureFlags(...args: Parameters<typeof admin.getAllFeatureFlags>) {
  return asSuperAdmin(() => admin.getAllFeatureFlags(...args));
}

export async function createFeatureFlag(...args: Parameters<typeof admin.createFeatureFlag>) {
  return asSuperAdmin(() => admin.createFeatureFlag(...args));
}

export async function updateFeatureFlag(...args: Parameters<typeof admin.updateFeatureFlag>) {
  return asSuperAdmin(() => admin.updateFeatureFlag(...args));
}

export async function deleteFeatureFlag(...args: Parameters<typeof admin.deleteFeatureFlag>) {
  return asSuperAdmin(() => admin.deleteFeatureFlag(...args));
}

export async function getAllFeatureFlagGroups(...args: Parameters<typeof admin.getAllFeatureFlagGroups>) {
  return asSuperAdmin(() => admin.getAllFeatureFlagGroups(...args));
}

export async function createFeatureFlagGroup(...args: Parameters<typeof admin.createFeatureFlagGroup>) {
  return asSuperAdmin(() => admin.createFeatureFlagGroup(...args));
}

export async function updateFeatureFlagGroup(...args: Parameters<typeof admin.updateFeatureFlagGroup>) {
  return asSuperAdmin(() => admin.updateFeatureFlagGroup(...args));
}

export async function deleteFeatureFlagGroup(...args: Parameters<typeof admin.deleteFeatureFlagGroup>) {
  return asSuperAdmin(() => admin.deleteFeatureFlagGroup(...args));
}

export async function getAllUsersWithLicenses(...args: Parameters<typeof admin.getAllUsersWithLicenses>) {
  return asSuperAdmin(() => admin.getAllUsersWithLicenses(...args));
}

export async function getUserLicense(...args: Parameters<typeof admin.getUserLicense>) {
  return asSuperAdmin(() => admin.getUserLicense(...args));
}

export async function assignLicenseToUser(...args: Parameters<typeof admin.assignLicenseToUser>) {
  return asSuperAdmin(() => admin.assignLicenseToUser(...args));
}

export async function removeUserLicense(...args: Parameters<typeof admin.removeUserLicense>) {
  return asSuperAdmin(() => admin.removeUserLicense(...args));
}

export async function setUserFeatureFlag(...args: Parameters<typeof admin.setUserFeatureFlag>) {
  return asSuperAdmin(() => admin.setUserFeatureFlag(...args));
}

export async function removeUserFeatureFlag(...args: Parameters<typeof admin.removeUserFeatureFlag>) {
  return asSuperAdmin(() => admin.removeUserFeatureFlag(...args));
}

export async function togglePropertyTemplateStatus(...args: Parameters<typeof admin.togglePropertyTemplateStatus>) {
  return asSuperAdmin(() => admin.togglePropertyTemplateStatus(...args));
}

export async function getPropertyTemplateStats(...args: Parameters<typeof admin.getPropertyTemplateStats>) {
  return asSuperAdmin(() => admin.getPropertyTemplateStats(...args));
}
