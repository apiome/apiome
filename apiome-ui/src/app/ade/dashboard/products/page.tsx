import ProductsClient from './ProductsClient';

/**
 * Ship → Products — `/ade/dashboard/products` (APX-1.1, #6098).
 *
 * Thin server component: all state lives in the client component, matching the other dashboard
 * screens.
 */
export default function ProductsPage() {
  return <ProductsClient />;
}
