'use client';

import { useSession } from 'next-auth/react';
import { getTenantsForUser, getAdminsForTenant } from '../../../../../lib/db/helper';
import { useEffect, useState } from 'react';

interface Tenant {
  id: string;
  name: string;
  description: string;
  slug: string;
  enabled: boolean;
  deleted_at: string | null;
  created_at: string;
  updated_at: string;
}

const Tenants = () => {
  const { data: session, update } = useSession();
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const currentTenantId = (session?.user as any)?.current_tenant_id;

  useEffect(() => {
    if (session) {
      const userId: string = (session.user as any)?.user_id;

      getTenantsForUser(userId)
        .then(x => {
          setTenants(JSON.parse(x));
        });
    }
  }, [session]);

  const handleSelectTenant = async (tenant: Tenant) => {
    const tenantId = tenant.id;

    await update({
      current_tenant_id: tenantId,
    });
  };

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold mb-4">Tenants</h1>
      {tenants.length === 0 ? (
        <p>No tenants available.</p>
      ) : (
        <ul className="space-y-4">
          {tenants.map(tenant => (
            <li
              key={tenant.id}
              className="border rounded-lg p-4 flex justify-between items-center"
            >
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="text-xl font-semibold">{tenant.name} ({tenant.slug})</h3>
                  {tenant.id === currentTenantId && (
                    <span className="bg-blue-500 text-white text-xs font-semibold px-2 py-1 rounded">
                      current
                    </span>
                  )}
                </div>
                <p className="text-gray-600">{tenant.description}</p>
              </div>
              <button
                onClick={() => handleSelectTenant(tenant)}
                className="bg-blue-500 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded cursor-pointer"
              >
                Select
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

export default Tenants;