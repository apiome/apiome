'use client';

/**
 * The "Used by properties" table of the primitive-detail page (#3477).
 *
 * The other half of the impact list. {@link DependentsCard} answers "which *types* reference this
 * one" through `$ref` edges; this answers "which *properties* are bound to it" through the
 * Designer's property→type binding (`class_properties.primitive_id`, #3475). The REST reverse
 * index is scope-aware, so the rows are always the viewer's own projects — a shared system type
 * never lists another tenant's model.
 *
 * Each row names the class and property, the project and version it lives in, and links into the
 * Designer at that version when the suite is configured; without it the label stands alone.
 */

import * as React from 'react';
import Link from 'next/link';
import { ListTree } from 'lucide-react';

import {
  DataTable,
  DataTableFoot,
  DataTableToolbar,
  type DataTableColumn,
} from '@/app/components/ui/DataTable';
import { EmptyState } from '@/app/components/ui/EmptyState';
import type { PropertyDependentRef } from '@/app/ade/dashboard/primitives/primitiveDetailModel';
import { buildDesignerEditorHref } from '../../../../../../lib/external-links';

import {
  EMPTY_VALUE,
  NO_PROPERTY_DEPENDENTS_DESCRIPTION,
  NO_PROPERTY_DEPENDENTS_TITLE,
  propertyDependentLabel,
  propertyDependentLocation,
  propertyDependentsFootLabel,
} from './primitiveDetailView';

export interface PropertyDependentsCardProps {
  /** The viewer's class properties bound to this type, one row per property. */
  dependents: readonly PropertyDependentRef[];
  /** How this type is addressed, for the table's sub-line. */
  identity: string;
}

/** One bound property, keyed for the table. */
interface PropertyDependentRow {
  key: string;
  dep: PropertyDependentRef;
  index: number;
  /** The Designer deep link to the property's version, or `null` when there is no Designer. */
  href: string | null;
}

/**
 * Render the card. See {@link PropertyDependentsCardProps}.
 *
 * @returns The table of bound properties, or the empty sentence in its place.
 */
export default function PropertyDependentsCard({
  dependents,
  identity,
}: PropertyDependentsCardProps) {
  const rows = React.useMemo<PropertyDependentRow[]>(
    () =>
      dependents.map((dep, index) => ({
        key: `${dep.class_property_id}-${index}`,
        dep,
        index,
        href: buildDesignerEditorHref(dep.project_id, dep.version_id),
      })),
    [dependents]
  );

  const columns: DataTableColumn<PropertyDependentRow>[] = [
    {
      id: 'property',
      header: 'Property',
      skeletonWidth: '12rem',
      cell: ({ dep, index, href }) => {
        const label = propertyDependentLabel(dep);
        if (!href) return <span className="mono">{label}</span>;
        return (
          <Link
            href={href}
            data-testid={`property-dependent-link-${index}`}
            title={`Open ${label} in the Designer`}
            aria-label={`Open ${label} in the Designer`}
            className="prm-ref-link mono"
          >
            {label}
          </Link>
        );
      },
    },
    {
      id: 'location',
      header: 'Project · Version',
      skeletonWidth: '9rem',
      cell: ({ dep }) => <span>{propertyDependentLocation(dep)}</span>,
    },
    {
      id: 'ref',
      header: 'Bound as',
      align: 'end',
      skeletonWidth: '8rem',
      cell: ({ dep }) =>
        dep.primitive_ref ? (
          <span className="mono">{dep.primitive_ref}</span>
        ) : (
          <span className="prm-faint">{EMPTY_VALUE}</span>
        ),
    },
  ];

  return (
    <DataTable<PropertyDependentRow>
      caption="Used by properties"
      dense
      scrollX
      columns={columns}
      rows={rows}
      getRowId={(row) => row.key}
      getRowLabel={(row) => propertyDependentLabel(row.dep)}
      data-testid="primitive-detail-property-dependents"
      empty={
        <EmptyState
          icon={<ListTree aria-hidden />}
          title={NO_PROPERTY_DEPENDENTS_TITLE}
          description={NO_PROPERTY_DEPENDENTS_DESCRIPTION}
          variant="compact"
        />
      }
      toolbar={
        <DataTableToolbar>
          <span className="prm-panel-head">
            <ListTree aria-hidden />
            <span className="prm-panel-head__text">
              <h2 className="prm-panel-head__title">Used by properties</h2>
              <span className="prm-panel-head__sub">
                Properties bound to <span className="mono">{identity}</span>
              </span>
            </span>
          </span>
        </DataTableToolbar>
      }
      footer={
        rows.length > 0 ? (
          <DataTableFoot data-testid="primitive-detail-property-dependents-foot">
            <span>{propertyDependentsFootLabel(rows.length)}</span>
          </DataTableFoot>
        ) : undefined
      }
    />
  );
}
