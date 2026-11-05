'use client';

/**
 * ExportErdView — a database export drawn as an entity-relationship diagram (MFX-45.3, #4376).
 *
 * SQL DDL, DBML and Prisma outputs are judged as diagrams, not as text. On the Review step the artifact
 * viewer toggles between the written text and this view, which draws the export's relational projection
 * (the manifest's `relational`, from the emitter — `./exportErd.ts` holds the model):
 *
 *  - a table node per table: its name, a **junction** / **child table** badge and **✚ SYNTH** when the
 *    export made the table up, and its columns with their type, **PK** / **FK** / **UQ** markers,
 *    **NOT NULL**, and **✚** on every column the export made up;
 *  - a foreign-key edge per reference, dashed when the export made it up;
 *  - selection shared with the step: clicking a table or a column selects the canonical construct it came
 *    from (the tree and the code viewer follow), and the step's selection highlights here and is brought
 *    into view.
 *
 * Every node's content is a real button with an accessible name that says in words what the row shows, so
 * the diagram is operable without a pointer and readable without colour.
 */

import { memo, useEffect, useMemo } from 'react';
import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { Database } from 'lucide-react';
import { cn } from '@lib/utils';
import { MOTION_MS, motionDuration } from '@lib/motion';
import {
  columnAriaLabel,
  columnKeyMarkers,
  erdCounts,
  erdEdges,
  erdFocusTable,
  erdLayout,
  erdSelection,
  ERD_GEOMETRY,
  tableAriaLabel,
  tableKindLabel,
  type RelationalSchema,
  type RelationalTable,
} from './exportErd';

/** The data one table node carries. */
interface ErdTableData extends Record<string, unknown> {
  table: RelationalTable;
  /** The table's own construct is selected. */
  selected: boolean;
  /** Names of this table's columns whose construct is selected. */
  selectedColumns: string[];
  /** Select a canonical construct. */
  onSelect: (entityKey: string) => void;
}

type ErdTableNodeType = Node<ErdTableData, 'erdTable'>;

/** One table: header + column rows, each a button that selects its construct. */
export const ErdTableNode = memo(function ErdTableNode({ data }: NodeProps<ErdTableNodeType>) {
  const { table, selected, selectedColumns, onSelect } = data;
  const kind = tableKindLabel(table.kind);
  return (
    <div
      className="xstd-erd__table"
      data-selected={selected}
      data-synthesized={table.synthesized}
      data-testid={`erd-table-${table.name}`}
    >
      {/* Edges leave a referencing table on its left and arrive on a referenced table's right. */}
      <Handle type="source" position={Position.Left} className="xstd-erd__handle" isConnectable={false} />
      <Handle type="target" position={Position.Right} className="xstd-erd__handle" isConnectable={false} />
      <button
        type="button"
        className="xstd-erd__head nodrag"
        aria-pressed={selected}
        aria-label={tableAriaLabel(table)}
        data-testid={`erd-table-select-${table.name}`}
        onClick={() => onSelect(table.entity_key)}
      >
        <span className="xstd-erd__name">{table.name}</span>
        {kind && <span className="xstd-erd__kind">{kind}</span>}
        {table.synthesized && (
          <span className="xstd-erd__synth" data-testid={`erd-table-synth-${table.name}`}>
            <span aria-hidden>✚</span> SYNTH
          </span>
        )}
      </button>
      <ul className="xstd-erd__columns">
        {table.columns.map((column) => {
          const isSelected = selectedColumns.includes(column.name);
          const markers = columnKeyMarkers(column);
          return (
            <li key={column.name}>
              <button
                type="button"
                className="xstd-erd__column nodrag"
                aria-pressed={isSelected}
                aria-label={columnAriaLabel(table.name, column)}
                data-selected={isSelected}
                data-synthesized={column.synthesized}
                data-testid={`erd-column-${table.name}.${column.name}`}
                disabled={!column.entity_key}
                title={column.entity_key ? undefined : 'This column has no source construct to select'}
                onClick={() => column.entity_key && onSelect(column.entity_key)}
              >
                <span className="xstd-erd__markers" aria-hidden>
                  {markers.map((marker) => (
                    <span key={marker} className="xstd-erd__marker" data-marker={marker}>
                      {marker}
                    </span>
                  ))}
                </span>
                <span className="xstd-erd__colname" aria-hidden>
                  {column.synthesized && <span className="xstd-erd__synth-glyph">✚ </span>}
                  {column.name}
                </span>
                <span className="xstd-erd__type" aria-hidden>
                  {column.type}
                  {column.not_null && <span className="xstd-erd__nn"> NOT NULL</span>}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
});

const NODE_TYPES = { erdTable: ErdTableNode };

export interface ExportErdViewProps {
  /** The export's relational projection (the manifest's `relational`). */
  schema: RelationalSchema;
  /** The step's selected canonical construct. */
  selectedEntityKey: string | null;
  /** Select a canonical construct (a table's record or list field, a column's field). */
  onSelectEntityKey: (entityKey: string) => void;
  className?: string;
}

/** The diagram: summary, legend, and the flow canvas. */
export function ExportErdView(props: ExportErdViewProps) {
  return (
    <ReactFlowProvider>
      <ErdCanvas {...props} />
    </ReactFlowProvider>
  );
}

function ErdCanvas({ schema, selectedEntityKey, onSelectEntityKey, className }: ExportErdViewProps) {
  const counts = useMemo(() => erdCounts(schema), [schema]);
  const placed = useMemo(() => erdLayout(schema), [schema]);
  const fks = useMemo(() => erdEdges(schema), [schema]);
  const selection = useMemo(() => erdSelection(schema, selectedEntityKey), [schema, selectedEntityKey]);
  const focusTable = useMemo(() => erdFocusTable(schema, selectedEntityKey), [schema, selectedEntityKey]);

  const nodes = useMemo<ErdTableNodeType[]>(
    () =>
      placed.map(({ table, x, y, height }) => ({
        id: table.name,
        type: 'erdTable',
        position: { x, y },
        width: ERD_GEOMETRY.tableWidth,
        height,
        // The node's size and handles are known up front, so the diagram (edges included) draws on the
        // first paint instead of after React Flow measures every node.
        handles: [
          { type: 'source', position: Position.Left, x: 0, y: height / 2, width: 1, height: 1 },
          { type: 'target', position: Position.Right, x: ERD_GEOMETRY.tableWidth, y: height / 2, width: 1, height: 1 },
        ],
        draggable: false,
        selectable: false,
        data: {
          table,
          selected: selection.tables.has(table.name),
          selectedColumns: table.columns
            .filter((column) => selection.columns.has(`${table.name}.${column.name}`))
            .map((column) => column.name),
          onSelect: onSelectEntityKey,
        },
      })),
    [placed, selection, onSelectEntityKey],
  );

  const edges = useMemo<Edge[]>(
    () =>
      fks.map((fk) => {
        const touchesFocus = focusTable != null && (fk.source === focusTable || fk.target === focusTable);
        return {
          id: fk.id,
          source: fk.source,
          target: fk.target,
          type: 'smoothstep',
          // The label is drawn for the focused table's keys only, so a busy diagram stays legible; every
          // edge keeps it as its accessible name.
          label: touchesFocus ? fk.label : undefined,
          ariaLabel: `Foreign key ${fk.label}${fk.synthesized ? ', made up by the export' : ''}`,
          className: cn('xstd-erd__edge', fk.synthesized && 'xstd-erd__edge--synth'),
          selectable: false,
          focusable: false,
        };
      }),
    [fks, focusTable],
  );

  return (
    <div className={cn('xstd-erd', className)} data-testid="export-erd">
      <div className="xstd-erd__bar">
        <span className="xstd-caps">
          <Database aria-hidden />
          Entity-relationship diagram
        </span>
        <span className="xstd-note" data-testid="export-erd-summary">
          {counts.tables} table{counts.tables === 1 ? '' : 's'} · {counts.foreignKeys} foreign key
          {counts.foreignKeys === 1 ? '' : 's'}
          {counts.madeUpTables + counts.madeUpColumns > 0 &&
            ` · made up by the export: ${counts.madeUpTables} table${counts.madeUpTables === 1 ? '' : 's'}, ${
              counts.madeUpColumns
            } column${counts.madeUpColumns === 1 ? '' : 's'}`}
        </span>
      </div>
      <p className="xstd-erd__legend" data-testid="export-erd-legend">
        <span className="xstd-erd__marker" data-marker="PK">PK</span> primary key
        <span className="xstd-erd__marker" data-marker="FK">FK</span> foreign key
        <span className="xstd-erd__marker" data-marker="UQ">UQ</span> unique
        <span className="xstd-erd__synth">
          <span aria-hidden>✚</span> SYNTH
        </span>{' '}
        made up by the export (dashed when it is a foreign key)
      </p>
      <div className="xstd-erd__canvas" role="group" aria-label={`Tables of the ${schema.dialect} export`}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={NODE_TYPES}
          fitView
          minZoom={0.2}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          proOptions={{ hideAttribution: true }}
        >
          <Background />
          <Controls showInteractive={false} />
          <FocusSelected table={focusTable} />
        </ReactFlow>
      </div>
    </div>
  );
}

/** Bring the selected table into view whenever the selection moves to another table. */
function FocusSelected({ table }: { table: string | null }) {
  const flow = useReactFlow();
  useEffect(() => {
    if (!table) return;
    void flow.fitView({ nodes: [{ id: table }], maxZoom: 1, padding: 0.6, duration: motionDuration(MOTION_MS.slow) });
  }, [flow, table]);
  return null;
}

export default ExportErdView;
