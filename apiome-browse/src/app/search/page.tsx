import { searchPublishedPublicCatalog } from "../../../lib/db/helper";
import { SearchClient } from "./SearchClient";
import { sanitizeSearchInput } from "../utils/searchValidation";

export default async function SearchPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string }>;
}) {
  const { q } = await searchParams;
  const query = sanitizeSearchInput(q || "");
  const results = query ? await searchPublishedPublicCatalog(query) : [];

  return <SearchClient initialQuery={query} initialResults={results} />;
}
