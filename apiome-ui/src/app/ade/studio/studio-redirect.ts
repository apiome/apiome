import { STUDIO_APP_URL } from '../../lib/app-urls';

type SearchParams = Record<string, string | string[] | undefined>;

function studioRedirectUrl(path: string, searchParams: SearchParams): string {
  const target = new URL(path.replace(/^\//, ''), STUDIO_APP_URL);
  for (const [key, value] of Object.entries(searchParams)) {
    if (value === undefined) continue;
    target.searchParams.set(key, Array.isArray(value) ? value[0]! : value);
  }
  return target.toString();
}

export default function createStudioRedirectPage(path: string) {
  return async function StudioRedirectPage({
    searchParams,
  }: {
    searchParams: Promise<SearchParams>;
  }) {
    const { redirect } = await import('next/navigation');
    redirect(studioRedirectUrl(path, await searchParams));
  };
}
