import ImportReportClient from './ImportReportClient';

/**
 * Bring in → Catalog → one import report — `/ade/dashboard/catalog/imports/[id]` (CDG-5.5, #5983).
 *
 * @param props - The route's params.
 * @returns The page.
 */
export default async function ImportReportPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ImportReportClient id={id} />;
}
