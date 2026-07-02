/**
 * SPDX License Identifiers
 * Common open source licenses for dropdown selection
 * Based on SPDX License List: https://spdx.org/licenses/
 */

export interface SPDXLicense {
  identifier: string;
  name: string;
  osiApproved?: boolean;
}

export const SPDX_LICENSES: SPDXLicense[] = [
  // Permissive licenses
  { identifier: 'MIT', name: 'MIT License', osiApproved: true },
  { identifier: 'Apache-2.0', name: 'Apache License 2.0', osiApproved: true },
  { identifier: 'BSD-2-Clause', name: 'BSD 2-Clause "Simplified" License', osiApproved: true },
  { identifier: 'BSD-3-Clause', name: 'BSD 3-Clause "New" or "Revised" License', osiApproved: true },
  { identifier: 'ISC', name: 'ISC License', osiApproved: true },
  { identifier: '0BSD', name: 'BSD Zero Clause License', osiApproved: true },

  // Copyleft licenses
  { identifier: 'GPL-2.0-only', name: 'GNU General Public License v2.0 only', osiApproved: true },
  { identifier: 'GPL-2.0-or-later', name: 'GNU General Public License v2.0 or later', osiApproved: true },
  { identifier: 'GPL-3.0-only', name: 'GNU General Public License v3.0 only', osiApproved: true },
  { identifier: 'GPL-3.0-or-later', name: 'GNU General Public License v3.0 or later', osiApproved: true },
  { identifier: 'LGPL-2.1-only', name: 'GNU Lesser General Public License v2.1 only', osiApproved: true },
  { identifier: 'LGPL-2.1-or-later', name: 'GNU Lesser General Public License v2.1 or later', osiApproved: true },
  { identifier: 'LGPL-3.0-only', name: 'GNU Lesser General Public License v3.0 only', osiApproved: true },
  { identifier: 'LGPL-3.0-or-later', name: 'GNU Lesser General Public License v3.0 or later', osiApproved: true },
  { identifier: 'AGPL-3.0-only', name: 'GNU Affero General Public License v3.0 only', osiApproved: true },
  { identifier: 'AGPL-3.0-or-later', name: 'GNU Affero General Public License v3.0 or later', osiApproved: true },

  // Mozilla Public License
  { identifier: 'MPL-2.0', name: 'Mozilla Public License 2.0', osiApproved: true },

  // Eclipse Public License
  { identifier: 'EPL-1.0', name: 'Eclipse Public License 1.0', osiApproved: true },
  { identifier: 'EPL-2.0', name: 'Eclipse Public License 2.0', osiApproved: true },

  // Creative Commons
  { identifier: 'CC0-1.0', name: 'Creative Commons Zero v1.0 Universal' },
  { identifier: 'CC-BY-4.0', name: 'Creative Commons Attribution 4.0 International' },
  { identifier: 'CC-BY-SA-4.0', name: 'Creative Commons Attribution Share Alike 4.0 International' },

  // Other popular licenses
  { identifier: 'Unlicense', name: 'The Unlicense', osiApproved: true },
  { identifier: 'Artistic-2.0', name: 'Artistic License 2.0', osiApproved: true },
  { identifier: 'BSL-1.0', name: 'Boost Software License 1.0', osiApproved: true },

  // Proprietary/Commercial
  { identifier: 'UNLICENSED', name: 'Proprietary/Unlicensed' },
].sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }));

/**
 * Get license URL from SPDX identifier
 */
export function getLicenseUrl(identifier: string): string | undefined {
  if (!identifier) return undefined;

  // Special cases
  if (identifier === 'UNLICENSED') return undefined;

  // Standard SPDX URL pattern
  return `https://spdx.org/licenses/${identifier}.html`;
}

/**
 * Get license name from identifier
 */
export function getLicenseName(identifier: string): string | undefined {
  const license = SPDX_LICENSES.find(l => l.identifier === identifier);
  return license?.name;
}

