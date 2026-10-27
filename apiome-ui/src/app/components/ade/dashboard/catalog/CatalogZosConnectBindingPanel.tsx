"use client";

/**
 * z/OS Connect binding panel for a catalog item (MFI-21.2, #3992).
 *
 * A z/OS Connect descriptor binds each REST operation to the COBOL structures a CICS / IMS program
 * passes. This panel lists every bound operation with its request and response structures, the
 * copybook items that declare each structure, and the OpenAPI items that define the operation.
 * Items linked to the descriptor (the Related artifacts panel beside it) are marked **Linked**;
 * an unlinked match says so and is linked from that panel's **Suggest links**.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Cable } from "lucide-react";
import { Card } from "@/app/components/ui/Card";
import { ErrorBanner } from "@/app/components/ui/ErrorState";
import {
  bindingItemHref,
  bindingKindLabel,
  bindingSummaryText,
  type ZosConnectBinding,
  type ZosConnectBindingItem,
  type ZosConnectBindingSide,
} from "@/app/utils/zosconnect-binding";

export interface CatalogZosConnectBindingPanelProps {
  /** The descriptor's catalog item id. */
  projectId: string;
  /** Changes whenever the item's links change, so the panel re-reads which matches are linked. */
  refreshKey?: string | number;
}

/** The items holding one side, or a quiet note when the catalog has none. */
function BindingItems({
  items,
  empty,
}: {
  items: ZosConnectBindingItem[];
  empty: string;
}) {
  if (items.length === 0) return <span className="zcb__missing">{empty}</span>;
  return (
    <ul className="zcb__items">
      {items.map((item) => (
        <li key={item.projectId} className="zcb__item">
          <Link href={bindingItemHref(item)} className="zcb__link">
            {item.name}
          </Link>
          <span
            className={
              item.linked ? "zcb__state zcb__state--linked" : "zcb__state"
            }
          >
            {item.linked ? "Linked" : "Not linked"}
          </span>
        </li>
      ))}
    </ul>
  );
}

function StructureCell({ side }: { side?: ZosConnectBindingSide | null }) {
  if (!side) return <span className="zcb__missing">None</span>;
  return (
    <>
      <code className="zcb__structure">{side.structure}</code>
      <BindingItems items={side.copybooks} empty="No copybook in the catalog" />
    </>
  );
}

export function CatalogZosConnectBindingPanel({
  projectId,
  refreshKey,
}: CatalogZosConnectBindingPanelProps) {
  const [binding, setBinding] = useState<ZosConnectBinding | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const res = await fetch(
        `/api/identity/projects/${encodeURIComponent(projectId)}/zosconnect-binding`,
      );
      const data = await res.json();
      if (!res.ok || !data.success)
        throw new Error(data.error || "The binding could not be read.");
      setBinding(data.binding as ZosConnectBinding);
    } catch (err) {
      setError(
        err instanceof Error && err.message
          ? err.message
          : "The binding could not be read.",
      );
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  return (
    <Card className="zcb" data-testid="catalog-detail-zosconnect-binding">
      <div className="zcb__header">
        <h2 className="zcb__title">
          <Cable aria-hidden />
          z/OS Connect binding
        </h2>
        {binding ? (
          <p className="zcb__summary" data-testid="zosconnect-binding-summary">
            {bindingKindLabel(binding.kind)}
            {binding.api.title ? ` for ${binding.api.title}` : ""} ·{" "}
            {bindingSummaryText(binding)}
          </p>
        ) : null}
      </div>
      {error ? (
        <ErrorBanner
          title="Couldn't load the z/OS Connect binding"
          description={error}
          onRetry={() => void load()}
          data-testid="zosconnect-binding-error"
        />
      ) : null}
      {binding && binding.operations.length > 0 ? (
        <table className="zcb__table">
          <thead>
            <tr>
              <th scope="col">Operation</th>
              <th scope="col">Request structure</th>
              <th scope="col">Response structure</th>
              <th scope="col">OpenAPI</th>
            </tr>
          </thead>
          <tbody>
            {binding.operations.map((operation) => (
              <tr
                key={operation.operation}
                data-testid="zosconnect-binding-row"
              >
                <td>
                  <code className="zcb__operation">{operation.operation}</code>
                  {operation.program ? (
                    <span className="zcb__program">
                      Program {operation.program}
                    </span>
                  ) : null}
                </td>
                <td>
                  <StructureCell side={operation.request} />
                </td>
                <td>
                  <StructureCell side={operation.response} />
                </td>
                <td>
                  <BindingItems
                    items={operation.openapi}
                    empty="No OpenAPI in the catalog"
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {binding && binding.operations.length === 0 ? (
        <p className="zcb__empty">This descriptor binds no operations.</p>
      ) : null}
    </Card>
  );
}

export default CatalogZosConnectBindingPanel;
