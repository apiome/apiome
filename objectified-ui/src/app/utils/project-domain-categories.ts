/**
 * Optional domain labels for projects (#243, #242). Stored in project metadata as `domainCategory` (id string).
 */

export const PROJECT_DOMAIN_CATEGORY_NONE = 'none';

export interface ProjectDomainCategory {
  id: string;
  label: string;
  /** Short hint for pickers */
  hint: string;
}

export const PROJECT_DOMAIN_CATEGORIES: readonly ProjectDomainCategory[] = [
  {
    id: 'iot',
    label: 'IoT device schemas',
    hint: 'Sensors, devices, telemetry, and connected hardware models.',
  },
  {
    id: 'social',
    label: 'Social media entities',
    hint: 'Users, posts, feeds, reactions, and social graphs.',
  },
  {
    id: 'gaming',
    label: 'Gaming (Player, Match, Leaderboard)',
    hint: 'Players, sessions, matches, rankings, and live ops data.',
  },
  {
    id: 'travel',
    label: 'Travel & hospitality',
    hint: 'Bookings, guests, itineraries, properties, and reservations.',
  },
  {
    id: 'media',
    label: 'Media & entertainment',
    hint: 'Content catalogs, rights, playback, and editorial metadata.',
  },
  {
    id: 'ecommerce',
    label: 'E-commerce (Product, Cart, Order, Payment, Shipping)',
    hint: 'Catalogs, carts, checkout, payments, and fulfillment models.',
  },
  {
    id: 'healthcare',
    label: 'Healthcare (Patient, Appointment, Medication, Insurance)',
    hint: 'Clinical and administrative records, scheduling, prescriptions, and coverage.',
  },
  {
    id: 'finance',
    label: 'Finance (Account, Transaction, Investment, Loan)',
    hint: 'Accounts, money movement, portfolios, and lending products.',
  },
  {
    id: 'saas',
    label: 'SaaS (Tenant, User, Subscription, Usage)',
    hint: 'Multi-tenant identity, billing, metering, and subscription lifecycle.',
  },
  {
    id: 'education',
    label: 'Education (Course, Student, Assignment, Grade)',
    hint: 'Curriculum, enrollment, coursework, and outcomes.',
  },
  {
    id: 'realestate',
    label: 'Real Estate (Property, Listing, Agent, Transaction)',
    hint: 'Listings, brokerage, offers, and deal flow.',
  },
  {
    id: 'logistics',
    label: 'Logistics (Shipment, Route, Warehouse, Delivery)',
    hint: 'Movements, routing, facilities, and last-mile delivery.',
  },
];

const byId = new Map(PROJECT_DOMAIN_CATEGORIES.map((c) => [c.id, c]));

export function getProjectDomainCategory(id: string | undefined | null): ProjectDomainCategory | undefined {
  if (!id || id === PROJECT_DOMAIN_CATEGORY_NONE) return undefined;
  return byId.get(id);
}

export function getProjectDomainCategoryLabel(id: string | undefined | null): string | undefined {
  return getProjectDomainCategory(id)?.label;
}
