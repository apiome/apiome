/**
 * The Catalog list screen (HIVE-7.1, #5318).
 *
 * `docs/mockups/sources/catalog.html` — the card, the table, the stat strip and the format
 * facet — plus the two shared marks and `catalogModel`, the rules all of them share. The quiet
 * pass (HIVE-11.6, #5602, `docs/mockups/proposals/catalog-quiet.html`) replaced the standing
 * non-publishable note and the supported-formats gallery with the first-visit explainer
 * callout and the "How the catalog works" dialog.
 *
 * The dialogs the screen opens are deliberately *not* here: the lint report, the quality
 * history, the conversion preview and the import wizard all live under
 * `components/ade/dashboard/catalog` and `components/ade/import`, because the item **detail**
 * screen (HIVE-7.2) opens the same ones.
 */

export * from './catalogModel';

export { default as CatalogCard, CatalogRowMenu } from './CatalogCard';
export type { CatalogCardProps, CatalogItemHandlers, CatalogRowMenuProps } from './CatalogCard';

export { default as CatalogTable, catalogTableStamp } from './CatalogTable';
export type { CatalogTableProps } from './CatalogTable';

export { CatalogFormatRow, ConvertedBadge } from './CatalogBadges';
export type { CatalogFormatRowProps, ConvertedBadgeProps } from './CatalogBadges';

export { CatalogStatsRow } from './CatalogStatsRow';
export type { CatalogStatsRowProps } from './CatalogStatsRow';

export { CatalogFormatFacet } from './CatalogFormatFacet';
export type { CatalogFormatFacetProps } from './CatalogFormatFacet';

export {
  CatalogAboutDialog,
  CATALOG_ABOUT_PILL_LIMIT,
  SUPPORTED_FORMATS_GUIDE_HREF,
  catalogFormatCountsLine,
} from './CatalogAboutDialog';
export type { CatalogAboutDialogProps, CatalogFormatCounts } from './CatalogAboutDialog';

export { CatalogExplainerCallout, CATALOG_EXPLAINER_ID } from './CatalogExplainerCallout';
export type { CatalogExplainerCalloutProps } from './CatalogExplainerCallout';
