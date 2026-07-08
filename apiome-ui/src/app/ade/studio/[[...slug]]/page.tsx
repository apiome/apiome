import { notFound } from 'next/navigation';

const isCommercial = process.env.APIOME_BUILD_PROFILE === 'commercial';

type StudioPageProps = {
  params: Promise<{ slug?: string[] }>;
};

export default async function StudioCatchAllPage({ params }: StudioPageProps) {
  if (!isCommercial) {
    notFound();
  }

  const { slug } = await params;

  try {
    const { resolveStudioPage } = await import('@suite/designer/routes');
    const Page = await resolveStudioPage(slug);
    return <Page />;
  } catch {
    notFound();
  }
}
