/**
 * E2E helpers for commercial-only suite surfaces (Designer, Paths, etc.).
 */
export const isCommercialSuiteBuild = process.env.APIOME_BUILD_PROFILE === 'commercial';

export function commercialSuiteOnly(): boolean {
  return isCommercialSuiteBuild;
}
