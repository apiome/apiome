import ProductEditorClient from './ProductEditorClient';

/**
 * Ship → Products → one product — `/ade/dashboard/products/[slug]` (APX-1.1, #6098).
 *
 * @param props - The route's params.
 * @returns The product editor.
 */
export default async function ProductPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return <ProductEditorClient slug={decodeURIComponent(slug)} />;
}
