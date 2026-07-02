'use client';

import React, { useState, useCallback, useEffect, useRef } from 'react';
import dynamic from 'next/dynamic';
import * as Dialog from '@radix-ui/react-dialog';
import {
  X,
  Image,
  FileCode,
  FileText,
  BarChart3,
  Layout,
  LayoutDashboard,
  Network,
  Zap,
  Download,
  Check,
  Settings,
  Eye,
  Crop,
  Maximize2,
  Layers,
  Grid3X3,
  Clock,
} from 'lucide-react';
import { toPng, toSvg, toJpeg } from 'html-to-image';
import { jsPDF } from 'jspdf';
import { useReactFlow } from '@xyflow/react';
import type { Node, Edge } from '@xyflow/react';
import { useStudio } from '../../../ade/studio/StudioContext';

const MonacoEditor = dynamic(() => import('@monaco-editor/react'), { ssr: false });

// Export format types
type ExportFormat =
  | 'png'
  | 'jpeg'
  | 'svg'
  | 'pdf'
  | 'json'
  | 'mermaid'
  | 'plantuml'
  | 'graphml'
  | 'dot';

/** Monaco editor language for text export formats (syntax highlighting). */
function getMonacoLanguageForFormat(format: ExportFormat): string {
  switch (format) {
    case 'json':
      return 'json';
    case 'graphml':
      return 'xml';
    case 'mermaid':
    case 'plantuml':
    case 'dot':
    default:
      return 'plaintext';
  }
}

interface ExportCategory {
  id: string;
  name: string;
  formats: {
    id: ExportFormat;
    name: string;
    description: string;
    icon: React.ElementType;
  }[];
}

const exportCategories: ExportCategory[] = [
  {
    id: 'images',
    name: 'Images',
    formats: [
      { id: 'png', name: 'PNG Image', description: 'Raster image with transparency support', icon: Image },
      { id: 'jpeg', name: 'JPEG Image', description: 'Compressed photo-quality image', icon: Image },
      { id: 'svg', name: 'SVG Image', description: 'Scalable vector graphics', icon: FileCode },
    ],
  },
  {
    id: 'documents',
    name: 'Documents',
    formats: [
      { id: 'pdf', name: 'PDF Document', description: 'Portable document format', icon: FileText },
      { id: 'json', name: 'JSON Data', description: 'Raw canvas data in JSON format', icon: FileCode },
    ],
  },
  {
    id: 'diagrams',
    name: 'Diagram Code',
    formats: [
      { id: 'mermaid', name: 'Mermaid', description: 'Mermaid diagram syntax', icon: BarChart3 },
      { id: 'plantuml', name: 'PlantUML', description: 'PlantUML class diagram syntax', icon: Layout },
      { id: 'graphml', name: 'GraphML', description: 'XML-based graph format for yEd, Gephi', icon: Network },
      { id: 'dot', name: 'DOT (GraphViz)', description: 'GraphViz DOT language format', icon: Zap },
    ],
  },
];

export type ExportRange = 'full' | 'viewport' | 'groups';

/** Minimal group shape for export (id, name, nodeIds). */
export interface ExportGroup {
  id: string;
  name: string;
  nodeIds: string[];
}

interface ExportOptions {
  // Export range (#403 full/viewport, #404 groups)
  exportRange: ExportRange;
  // #404: when exportRange === 'groups', which group IDs to include
  selectedGroupIds: string[];
  // Image options
  quality: number; // 0.1 - 1.0
  scale: number; // 1, 2, 4
  includeBackground: boolean;
  backgroundColor: string;
  // PDF options
  pageSize: 'a4' | 'letter' | 'auto';
  orientation: 'portrait' | 'landscape';
  // General options (#406: include/exclude UI elements)
  includeUiElements: boolean;
  includeGrid: boolean;
  includeWatermark: boolean;
  watermarkText: string;
  // #409: include timestamp and metadata on image/PDF exports
  includeTimestampAndMetadata: boolean;
}

const defaultOptions: ExportOptions = {
  exportRange: 'full',
  selectedGroupIds: [],
  quality: 1.0,
  scale: 2,
  includeBackground: true,
  backgroundColor: '#ffffff',
  pageSize: 'auto',
  orientation: 'landscape',
  includeUiElements: false,
  includeGrid: false,
  includeWatermark: false,
  watermarkText: '',
  includeTimestampAndMetadata: false,
};

/** #409: Build timestamp and metadata lines for export overlay. */
function getTimestampAndMetadataLines(projectName: string, versionId: string): string[] {
  const now = new Date();
  const dateStr = now.toISOString().replace('T', ' ').slice(0, 19) + 'Z';
  return [
    `${projectName || 'canvas'} · v${versionId || '1'}`,
    `Exported ${dateStr}`,
  ];
}

/** #409: Draw timestamp and metadata on a raster image (data URL), return new data URL. */
function drawTimestampAndMetadataOnImage(
  dataUrl: string,
  projectName: string,
  versionId: string,
  pixelRatio: number = 1,
  outputFormat: { mime: 'image/png' } | { mime: 'image/jpeg'; quality: number } = { mime: 'image/png' }
): Promise<string> {
  return new Promise((resolve, reject) => {
    const img = new window.Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => {
      const w = img.width;
      const h = img.height;
      const canvas = document.createElement('canvas');
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext('2d');
      if (!ctx) {
        reject(new Error('Canvas 2d context not available'));
        return;
      }
      ctx.drawImage(img, 0, 0);
      const lines = getTimestampAndMetadataLines(projectName, versionId);
      const fontSize = Math.max(10, 12 * pixelRatio);
      const padding = 12 * pixelRatio;
      const lineHeight = fontSize * 1.2;
      ctx.font = `${fontSize}px system-ui, sans-serif`;
      ctx.textAlign = 'right';
      ctx.fillStyle = 'rgba(0,0,0,0.5)';
      ctx.strokeStyle = 'rgba(255,255,255,0.8)';
      ctx.lineWidth = 2;
      const x = w - padding;
      const yStart = h - padding - lineHeight * lines.length;
      lines.forEach((line, i) => {
        const y = yStart + (i + 1) * lineHeight;
        ctx.strokeText(line, x, y);
        ctx.fillText(line, x, y);
      });
      const outUrl =
        outputFormat.mime === 'image/jpeg'
          ? canvas.toDataURL('image/jpeg', outputFormat.quality)
          : canvas.toDataURL('image/png');
      resolve(outUrl);
    };
    img.onerror = () => reject(new Error('Failed to load image for overlay'));
    img.src = dataUrl;
  });
}

interface ExportWizardProps {
  open: boolean;
  onClose: () => void;
  nodes: Node[];
  edges: Edge[];
  groups?: ExportGroup[];
  isDark: boolean;
  projectName: string;
  versionId: string;
  alertDialog: (options: { message: string; variant?: 'success' | 'warning' | 'error' | 'info' }) => Promise<void>;
}

export default function ExportWizard({
  open,
  onClose,
  nodes,
  edges,
  groups = [],
  isDark,
  projectName,
  versionId,
  alertDialog,
}: ExportWizardProps) {
  const [selectedFormat, setSelectedFormat] = useState<ExportFormat>('png');
  const [options, setOptions] = useState<ExportOptions>(defaultOptions);
  const [isExporting, setIsExporting] = useState(false);
  const [isGeneratingPreview, setIsGeneratingPreview] = useState(false);
  const [previewDataUrl, setPreviewDataUrl] = useState<string | null>(null);
  const [previewText, setPreviewText] = useState<string | null>(null);
  const [isPreviewStale, setIsPreviewStale] = useState(true);
  const previewRequestIdRef = useRef(0);

  const { fitView, fitBounds, getViewport, setViewport } = useReactFlow();
  const { setExportGridOverride } = useStudio();

  /** Fit view to entire canvas, run fn (capture), then restore previous viewport. */
  const withFullCanvasView = useCallback(
    async <T,>(fn: () => Promise<T>): Promise<T> => {
      const previous = getViewport();
      fitView({ padding: 0.2, duration: 0 });
      await new Promise((r) => requestAnimationFrame(r));
      await new Promise((r) => setTimeout(r, 50));
      try {
        return await fn();
      } finally {
        setViewport(previous, { duration: 0 });
      }
    },
    [fitView, getViewport, setViewport]
  );

  /** Node IDs that belong to the given groups (group node ids + their class node ids). */
  const getNodeIdsForGroups = useCallback(
    (groupIds: string[]) => {
      const set = new Set<string>();
      for (const g of groups) {
        if (!groupIds.includes(g.id)) continue;
        set.add(g.id); // group node itself
        g.nodeIds.forEach((id) => set.add(id));
      }
      return set;
    },
    [groups]
  );

  /** Compute bounding box of nodes by id. Returns null if no nodes or invalid. */
  const getBoundsForNodeIds = useCallback(
    (nodeIds: Set<string>): { x: number; y: number; width: number; height: number } | null => {
      const toInclude = nodes.filter((n) => nodeIds.has(n.id));
      if (toInclude.length === 0) return null;
      let minX = Infinity,
        minY = Infinity,
        maxX = -Infinity,
        maxY = -Infinity;
      for (const node of toInclude) {
        const w = (node.measured?.width ?? node.style?.width ?? 0) as number;
        const h = (node.measured?.height ?? node.style?.height ?? 0) as number;
        minX = Math.min(minX, node.position.x);
        minY = Math.min(minY, node.position.y);
        maxX = Math.max(maxX, node.position.x + (w || 200));
        maxY = Math.max(maxY, node.position.y + (h || 120));
      }
      const width = Math.max(1, maxX - minX);
      const height = Math.max(1, maxY - minY);
      return { x: minX, y: minY, width, height };
    },
    [nodes]
  );

  /** Fit view to selected groups' bounds, run fn (capture), then restore. (#404) */
  const withGroupsView = useCallback(
    async <T,>(groupIds: string[], fn: () => Promise<T>): Promise<T> => {
      const nodeIds = getNodeIdsForGroups(groupIds);
      const bounds = getBoundsForNodeIds(nodeIds);
      if (!bounds) return fn(); // fallback: no change
      const previous = getViewport();
      fitBounds(bounds, { padding: 0.2, duration: 0 });
      await new Promise((r) => requestAnimationFrame(r));
      await new Promise((r) => setTimeout(r, 50));
      try {
        return await fn();
      } finally {
        setViewport(previous, { duration: 0 });
      }
    },
    [getNodeIdsForGroups, getBoundsForNodeIds, fitBounds, getViewport, setViewport]
  );

  const getFilenameBase = useCallback(() => {
    return `${projectName || 'canvas'}-v${versionId || '1'}`;
  }, [projectName, versionId]);

  const getViewportElement = useCallback(() => {
    return document.querySelector('.react-flow__viewport') as HTMLElement | null;
  }, []);

  /** Element that shows the current visible viewport (for "export current viewport"). */
  const getPaneElement = useCallback(() => {
    return document.querySelector('.react-flow__renderer') as HTMLElement | null;
  }, []);

  /** (#407) Apply grid include/exclude for export: set override, wait for paint, run fn, then clear. */
  const withGridOverride = useCallback(
    async <T,>(includeGrid: boolean, fn: () => Promise<T>): Promise<T> => {
      setExportGridOverride(includeGrid);
      await new Promise((r) => requestAnimationFrame(r));
      await new Promise((r) => setTimeout(r, 80));
      try {
        return await fn();
      } finally {
        setExportGridOverride(null);
      }
    },
    [setExportGridOverride]
  );

  const imageExportFilter = useCallback((node: Element) => {
    if (node.classList) {
      return !node.classList.contains('react-flow__controls') &&
             !node.classList.contains('react-flow__minimap') &&
             !node.classList.contains('react-flow__attribution') &&
             !node.classList.contains('react-flow__panel');
    }
    return true;
  }, []);

  const generateTextExport = useCallback(
    (format: ExportFormat, limitToNodeIds?: Set<string>): string => {
      let classNodes = nodes.filter((n) => n.type !== 'groupNode');
      let edgesFiltered = edges;
      if (limitToNodeIds?.size) {
        classNodes = classNodes.filter((n) => limitToNodeIds.has(n.id));
        edgesFiltered = edges.filter(
          (e) => limitToNodeIds.has(e.source) && limitToNodeIds.has(e.target)
        );
      }

      switch (format) {
        case 'json':
          return JSON.stringify({ nodes: classNodes, edges: edgesFiltered }, null, 2);

        case 'mermaid':
          return generateMermaid(classNodes, edgesFiltered);

        case 'plantuml':
          return generatePlantUml(classNodes, edgesFiltered);

        case 'graphml':
          return generateGraphMl(classNodes, edgesFiltered);

        case 'dot':
          return generateDot(classNodes, edgesFiltered);

        default:
          return '';
      }
    },
    [nodes, edges]
  );

  useEffect(() => {
    // Cancel in-flight image preview work.
    previewRequestIdRef.current += 1;
    setIsGeneratingPreview(false);

    if (!open) {
      setPreviewDataUrl(null);
      setPreviewText(null);
      setIsPreviewStale(true);
      return;
    }

    const isImageExportFormat = ['png', 'jpeg', 'svg', 'pdf'].includes(selectedFormat);

    if (isImageExportFormat) {
      // Raster/vector/PDF: preview only after "Generate preview" (heavy canvas capture).
      setPreviewDataUrl(null);
      setPreviewText(null);
      setIsPreviewStale(true);
    } else {
      // JSON, Mermaid, PlantUML, GraphML, DOT: instant text preview (no button).
      setPreviewDataUrl(null);
      const nodeIdSet =
        options.exportRange === 'groups' && options.selectedGroupIds.length > 0
          ? getNodeIdsForGroups(options.selectedGroupIds)
          : undefined;
      setPreviewText(generateTextExport(selectedFormat, nodeIdSet));
      setIsPreviewStale(false);
    }
  }, [open, selectedFormat, options, generateTextExport, getNodeIdsForGroups]);

  const generatePreview = useCallback(async (requestId: number) => {
    const isCurrent = () => open && previewRequestIdRef.current === requestId;
    const viewportElement = getViewportElement();
    const paneElement = getPaneElement();

    const isViewport = options.exportRange === 'viewport';
    const isGroups =
      options.exportRange === 'groups' && options.selectedGroupIds.length > 0;
    const captureElement = isViewport ? paneElement : viewportElement;
    if (!captureElement) {
      if (isCurrent()) setPreviewDataUrl(null);
      return;
    }

    try {
      const dataUrl = await withGridOverride(options.includeGrid, async () => {
        const capture = async () => {
          const bg = options.includeBackground
            ? (isDark ? '#111827' : options.backgroundColor)
            : 'transparent';
          return toPng(captureElement, {
            backgroundColor: bg,
            quality: 0.5, // Lower quality for preview
            pixelRatio: 1,
            filter: options.includeUiElements ? undefined : imageExportFilter,
          });
        };
        if (isViewport) {
          return capture();
        }
        if (isGroups) {
          return withGroupsView(options.selectedGroupIds, capture);
        }
        return withFullCanvasView(capture);
      });
      if (!isCurrent()) return;
      let finalDataUrl = dataUrl;
      if (options.includeTimestampAndMetadata) {
        try {
          finalDataUrl = await drawTimestampAndMetadataOnImage(
            dataUrl,
            projectName,
            versionId,
            1,
            { mime: 'image/png' }
          );
        } catch {
          // keep original preview on error
        }
      }
      if (!isCurrent()) return;
      setPreviewDataUrl(finalDataUrl);
      setPreviewText(null);
    } catch (error) {
      console.error('Error generating preview:', error);
      if (isCurrent()) setPreviewDataUrl(null);
    }
  }, [open, selectedFormat, options, isDark, projectName, versionId, getViewportElement, getPaneElement, imageExportFilter, withFullCanvasView, withGroupsView, withGridOverride]);

  const handleGeneratePreview = useCallback(async () => {
    if (!open) return;
    if (!['png', 'jpeg', 'svg', 'pdf'].includes(selectedFormat)) return;
    const requestId = (previewRequestIdRef.current += 1);
    setIsPreviewStale(false);
    setIsGeneratingPreview(true);
    setPreviewDataUrl(null);
    setPreviewText(null);

    // Ensure the spinner renders before heavy preview work begins.
    await new Promise((r) => setTimeout(r, 0));

    try {
      await generatePreview(requestId);
    } finally {
      if (open && previewRequestIdRef.current === requestId) {
        setIsGeneratingPreview(false);
      }
    }
  }, [open, selectedFormat, generatePreview]);

  type ClassProperty = { name: string; data?: { type?: string } };
  type ClassNodeData = { name?: string; properties?: ClassProperty[] };

  const getClassNodeData = (node: Node): ClassNodeData =>
    (node.data ?? {}) as ClassNodeData;

  // Generate Mermaid diagram
  const generateMermaid = (classNodes: Node[], edges: Edge[]): string => {
    let mermaid = 'classDiagram\n';

    classNodes.forEach(node => {
      const data = getClassNodeData(node);
      const className = data.name || node.id;
      mermaid += `  class ${className} {\n`;

      const properties = data.properties ?? [];
      properties.forEach((prop) => {
        const propType = prop.data?.type ?? 'any';
        mermaid += `    +${propType} ${prop.name}\n`;
      });

      mermaid += '  }\n';
    });

    edges.forEach(edge => {
      const sourceNode = classNodes.find(n => n.id === edge.source);
      const targetNode = classNodes.find(n => n.id === edge.target);
      if (sourceNode && targetNode) {
        const sourceName = getClassNodeData(sourceNode).name || sourceNode.id;
        const targetName = getClassNodeData(targetNode).name || targetNode.id;
        mermaid += `  ${sourceName} --> ${targetName}\n`;
      }
    });

    return mermaid;
  };

  // Generate PlantUML diagram
  const generatePlantUml = (classNodes: Node[], edges: Edge[]): string => {
    let uml = '@startuml\n\n';

    classNodes.forEach(node => {
      const data = getClassNodeData(node);
      const className = data.name || node.id;
      uml += `class ${className} {\n`;

      const properties = data.properties ?? [];
      properties.forEach((prop) => {
        const propType = prop.data?.type ?? 'any';
        uml += `  +${prop.name}: ${propType}\n`;
      });

      uml += '}\n\n';
    });

    edges.forEach(edge => {
      const sourceNode = classNodes.find(n => n.id === edge.source);
      const targetNode = classNodes.find(n => n.id === edge.target);
      if (sourceNode && targetNode) {
        const sourceName = getClassNodeData(sourceNode).name || sourceNode.id;
        const targetName = getClassNodeData(targetNode).name || targetNode.id;
        uml += `${sourceName} --> ${targetName}\n`;
      }
    });

    uml += '\n@enduml';
    return uml;
  };

  // Generate GraphML
  const generateGraphMl = (classNodes: Node[], edges: Edge[]): string => {
    let xml = '<?xml version="1.0" encoding="UTF-8"?>\n';
    xml += '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">\n';
    xml += '  <graph id="G" edgedefault="directed">\n';

    classNodes.forEach(node => {
      const data = getClassNodeData(node);
      xml += `    <node id="${node.id}">\n`;
      xml += `      <data key="label">${data.name || node.id}</data>\n`;
      xml += '    </node>\n';
    });

    edges.forEach((edge, index) => {
      xml += `    <edge id="e${index}" source="${edge.source}" target="${edge.target}"/>\n`;
    });

    xml += '  </graph>\n';
    xml += '</graphml>';
    return xml;
  };

  // Generate DOT
  const generateDot = (classNodes: Node[], edges: Edge[]): string => {
    let dot = 'digraph G {\n';
    dot += '  rankdir=TB;\n';
    dot += '  node [shape=record];\n\n';

    classNodes.forEach(node => {
      const data = getClassNodeData(node);
      const className = data.name || node.id;
      const properties = data.properties ?? [];
      const propStr = properties
        .map((p) => `${p.name}: ${p.data?.type ?? 'any'}`)
        .join('\\l');
      dot += `  "${node.id}" [label="{${className}|${propStr}\\l}"];\n`;
    });

    dot += '\n';

    edges.forEach(edge => {
      dot += `  "${edge.source}" -> "${edge.target}";\n`;
    });

    dot += '}';
    return dot;
  };

  /** Capture image for export: full canvas, current viewport, or selected groups. */
  const captureExportImage = useCallback(
    async (toImage: (el: HTMLElement) => Promise<string>) => {
      const isViewport = options.exportRange === 'viewport';
      const isGroups =
        options.exportRange === 'groups' && options.selectedGroupIds.length > 0;
      const viewportElement = getViewportElement();
      const paneElement = getPaneElement();
      if (isViewport) {
        if (!paneElement) throw new Error('Canvas not found');
        return toImage(paneElement);
      }
      if (isGroups) {
        if (!viewportElement) throw new Error('Canvas not found');
        return withGroupsView(options.selectedGroupIds, () =>
          toImage(viewportElement)
        );
      }
      if (!viewportElement) throw new Error('Canvas not found');
      return withFullCanvasView(() => toImage(viewportElement));
    },
    [options.exportRange, options.selectedGroupIds, getViewportElement, getPaneElement, withFullCanvasView, withGroupsView]
  );

  const canExportGroups =
    options.exportRange !== 'groups' || options.selectedGroupIds.length > 0;

  // Handle export
  const handleExport = useCallback(async () => {
    if (!canExportGroups) {
      await alertDialog({
        message: 'Select at least one group to export, or choose a different export range.',
        variant: 'warning',
      });
      return;
    }
    setIsExporting(true);

    const isImageFormat = ['png', 'jpeg', 'svg', 'pdf'].includes(selectedFormat);
    if (isImageFormat) {
      setExportGridOverride(options.includeGrid);
      await new Promise((r) => requestAnimationFrame(r));
      await new Promise((r) => setTimeout(r, 80));
    }

    try {
      const filename = getFilenameBase();
      const bgPng = options.includeBackground
        ? (isDark ? '#111827' : options.backgroundColor)
        : 'transparent';
      const bgJpeg = isDark ? '#111827' : options.backgroundColor;
      const suffix =
        options.exportRange === 'viewport'
          ? '-viewport'
          : options.exportRange === 'groups' && options.selectedGroupIds.length > 0
            ? '-groups'
            : '';

      switch (selectedFormat) {
        case 'png': {
          let dataUrl = await captureExportImage((el) =>
            toPng(el, {
              backgroundColor: bgPng,
              quality: options.quality,
              pixelRatio: options.scale,
              filter: options.includeUiElements ? undefined : imageExportFilter,
            })
          );
          if (options.includeTimestampAndMetadata) {
            dataUrl = await drawTimestampAndMetadataOnImage(
              dataUrl,
              projectName,
              versionId,
              options.scale,
              { mime: 'image/png' }
            );
          }
          downloadDataUrl(dataUrl, `${filename}${suffix}.png`);
          break;
        }

        case 'jpeg': {
          let dataUrl = await captureExportImage((el) =>
            toJpeg(el, {
              backgroundColor: bgJpeg,
              quality: options.quality,
              pixelRatio: options.scale,
              filter: options.includeUiElements ? undefined : imageExportFilter,
            })
          );
          if (options.includeTimestampAndMetadata) {
            dataUrl = await drawTimestampAndMetadataOnImage(
              dataUrl,
              projectName,
              versionId,
              options.scale,
              { mime: 'image/jpeg', quality: options.quality }
            );
          }
          downloadDataUrl(dataUrl, `${filename}${suffix}.jpg`);
          break;
        }

        case 'svg': {
          const dataUrl = await captureExportImage((el) =>
            toSvg(el, {
              backgroundColor: bgPng,
              filter: options.includeUiElements ? undefined : imageExportFilter,
            })
          );
          downloadDataUrl(dataUrl, `${filename}${suffix}.svg`);
          break;
        }

        case 'pdf': {
          const dataUrl = await captureExportImage((el) =>
            toPng(el, {
              backgroundColor: bgPng,
              quality: 1.0,
              pixelRatio: options.scale,
              filter: options.includeUiElements ? undefined : imageExportFilter,
            })
          );

          const img = new window.Image();
          img.src = dataUrl;
          await new Promise(resolve => { img.onload = resolve; });

          const pdf = new jsPDF({
            orientation: options.orientation,
            unit: 'px',
            format: options.pageSize === 'auto' ? [img.width, img.height] : options.pageSize,
          });

          const pageWidth = pdf.internal.pageSize.getWidth();
          const pageHeight = pdf.internal.pageSize.getHeight();
          const scale = Math.min(pageWidth / img.width, pageHeight / img.height);
          const scaledWidth = img.width * scale;
          const scaledHeight = img.height * scale;
          const x = (pageWidth - scaledWidth) / 2;
          const y = (pageHeight - scaledHeight) / 2;

          pdf.addImage(dataUrl, 'PNG', x, y, scaledWidth, scaledHeight);

          if (options.includeTimestampAndMetadata) {
            const lines = getTimestampAndMetadataLines(projectName, versionId);
            const padding = 12;
            pdf.setFontSize(8);
            pdf.setTextColor(100, 100, 100);
            lines.forEach((line, i) => {
              pdf.text(line, pageWidth - padding, pageHeight - padding - i * 10, { align: 'right' });
            });
          }

          pdf.save(`${filename}${suffix}.pdf`);
          break;
        }

        case 'json':
        case 'mermaid':
        case 'plantuml':
        case 'graphml':
        case 'dot': {
          const nodeIdSet =
            options.exportRange === 'groups' && options.selectedGroupIds.length > 0
              ? getNodeIdsForGroups(options.selectedGroupIds)
              : undefined;
          const text = generateTextExport(selectedFormat, nodeIdSet);
          const extension = selectedFormat === 'json' ? 'json'
            : selectedFormat === 'mermaid' ? 'mmd'
            : selectedFormat === 'plantuml' ? 'puml'
            : selectedFormat === 'graphml' ? 'graphml'
            : 'dot';
          const textSuffix = nodeIdSet ? '-groups' : '';
          downloadText(text, `${filename}${textSuffix}.${extension}`);
          break;
        }
      }

      await alertDialog({ message: `Canvas exported successfully!`, variant: 'success' });
      onClose();
    } catch (error) {
      console.error('Export error:', error);
      await alertDialog({ message: 'Failed to export. Please try again.', variant: 'error' });
    } finally {
      setExportGridOverride(null);
      setIsExporting(false);
    }
  }, [canExportGroups, selectedFormat, options, isDark, projectName, versionId, getFilenameBase, imageExportFilter, generateTextExport, getNodeIdsForGroups, alertDialog, onClose, captureExportImage, setExportGridOverride]);

  const downloadDataUrl = (dataUrl: string, filename: string) => {
    const link = document.createElement('a');
    link.download = filename;
    link.href = dataUrl;
    link.click();
  };

  const downloadText = (text: string, filename: string) => {
    const blob = new Blob([text], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.download = filename;
    link.href = url;
    link.click();
    URL.revokeObjectURL(url);
  };

  const selectedFormatInfo = exportCategories
    .flatMap(c => c.formats)
    .find(f => f.id === selectedFormat);

  const isImageFormat = ['png', 'jpeg', 'svg', 'pdf'].includes(selectedFormat);

  return (
    <Dialog.Root open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/50 backdrop-blur-sm z-[9998]" />
        <Dialog.Content
          aria-describedby={undefined}
          className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[900px] max-w-[95vw] h-[90vh] bg-white dark:bg-gray-900 rounded-2xl shadow-2xl z-[9999] flex flex-col overflow-hidden"
        >
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-xl">
                <Download className="w-5 h-5 text-white" />
              </div>
              <div>
                <Dialog.Title className="text-lg font-semibold text-gray-900 dark:text-gray-100">
                  Export Canvas
                </Dialog.Title>
                <Dialog.Description className="text-sm text-gray-500 dark:text-gray-400">
                  Choose a format and configure export options
                </Dialog.Description>
              </div>
            </div>
            <Dialog.Close asChild>
              <button className="p-2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-colors">
                <X className="w-5 h-5" />
              </button>
            </Dialog.Close>
          </div>

          {/* Content */}
          <div className="flex-1 flex overflow-hidden">
            {/* Left Sidebar - Format Selection */}
            <div className="w-56 border-r border-gray-200 dark:border-gray-700 overflow-y-auto bg-gray-50 dark:bg-gray-800/50">
              <div className="p-4 space-y-6">
                {exportCategories.map(category => (
                  <div key={category.id}>
                    <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2 px-2">
                      {category.name}
                    </h3>
                    <div className="space-y-1">
                      {category.formats.map(format => {
                        const Icon = format.icon;
                        const isSelected = selectedFormat === format.id;
                        return (
                          <button
                            key={format.id}
                            onClick={() => setSelectedFormat(format.id)}
                            className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left transition-all ${
                              isSelected
                                ? 'bg-indigo-100 dark:bg-indigo-900/50 text-indigo-700 dark:text-indigo-300 border border-indigo-200 dark:border-indigo-700'
                                : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700/50'
                            }`}
                          >
                            <Icon className={`w-4 h-4 ${isSelected ? 'text-indigo-600 dark:text-indigo-400' : 'text-gray-400'}`} />
                            <span className="text-sm font-medium">{format.name}</span>
                            {isSelected && <Check className="w-4 h-4 ml-auto text-indigo-600 dark:text-indigo-400" />}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Right Content - Preview and Options */}
            <div className="flex-1 flex flex-col overflow-hidden">
              {/* Preview */}
              <div className="flex-1 p-4 overflow-hidden">
                <div className="h-full rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-100 dark:bg-gray-800 overflow-hidden flex items-center justify-center">
                  {isGeneratingPreview ? (
                    <div className="text-gray-400 dark:text-gray-500 flex flex-col items-center gap-2">
                      <div className="w-8 h-8 border-2 border-gray-300/60 dark:border-gray-600/60 border-t-gray-600 dark:border-t-gray-200 rounded-full animate-spin" />
                      <span className="text-sm">Generating preview...</span>
                    </div>
                  ) : previewDataUrl ? (
                    <img
                      src={previewDataUrl}
                      alt="Export preview"
                      className="max-w-full max-h-full object-contain"
                    />
                  ) : previewText ? (
                    <div className="w-full h-full min-h-[200px] rounded-lg overflow-hidden">
                      <MonacoEditor
                        height="100%"
                        language={getMonacoLanguageForFormat(selectedFormat)}
                        value={previewText}
                        theme={isDark ? 'vs-dark' : 'light'}
                        options={{
                          readOnly: true,
                          minimap: { enabled: false },
                          scrollBeyondLastLine: false,
                          fontSize: 12,
                          wordWrap: 'on',
                          lineNumbers: 'on',
                          folding: true,
                          padding: { top: 8, bottom: 8 },
                        }}
                      />
                    </div>
                  ) : (
                    <div className="text-gray-400 dark:text-gray-500 flex flex-col items-center gap-2">
                      <Eye className="w-8 h-8" />
                      <span className="text-sm">
                        {isImageFormat && isPreviewStale
                          ? 'Click “Generate preview” to create a preview.'
                          : 'No preview available.'}
                      </span>
                    </div>
                  )}
                </div>
              </div>

              {/* Options Panel */}
              <div className="border-t border-gray-200 dark:border-gray-700 p-4 bg-gray-50 dark:bg-gray-800/50">
                <div className="flex items-center gap-2 mb-3">
                  <Settings className="w-4 h-4 text-gray-400" />
                  <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
                    {selectedFormatInfo?.name} Options
                  </h4>
                </div>

                <div className="grid grid-cols-3 gap-4">
                  {isImageFormat && (
                    <>
                      {/* Export range: full, viewport, or selected groups (#403, #404) */}
                      <div className="col-span-3">
                        <label className="text-xs font-medium text-gray-500 dark:text-gray-400 block mb-2">
                          Export range
                        </label>
                        <div className="flex gap-2 flex-wrap">
                          <button
                            type="button"
                            onClick={() => setOptions(prev => ({ ...prev, exportRange: 'full' }))}
                            className={`flex-1 min-w-0 flex items-center justify-center gap-2 px-3 py-2 rounded-lg border text-sm font-medium transition-all ${
                              options.exportRange === 'full'
                                ? 'bg-indigo-100 dark:bg-indigo-900/50 text-indigo-700 dark:text-indigo-300 border-indigo-200 dark:border-indigo-700'
                                : 'border-gray-200 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700/50'
                            }`}
                          >
                            <Maximize2 className="w-4 h-4 shrink-0" />
                            Full canvas
                          </button>
                          <button
                            type="button"
                            onClick={() => setOptions(prev => ({ ...prev, exportRange: 'viewport' }))}
                            className={`flex-1 min-w-0 flex items-center justify-center gap-2 px-3 py-2 rounded-lg border text-sm font-medium transition-all ${
                              options.exportRange === 'viewport'
                                ? 'bg-indigo-100 dark:bg-indigo-900/50 text-indigo-700 dark:text-indigo-300 border-indigo-200 dark:border-indigo-700'
                                : 'border-gray-200 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700/50'
                            }`}
                          >
                            <Crop className="w-4 h-4 shrink-0" />
                            Viewport
                          </button>
                          <button
                            type="button"
                            onClick={() =>
                              setOptions(prev => ({
                                ...prev,
                                exportRange: 'groups',
                                selectedGroupIds:
                                  prev.exportRange === 'groups' ? prev.selectedGroupIds : [],
                              }))
                            }
                            className={`flex-1 min-w-0 flex items-center justify-center gap-2 px-3 py-2 rounded-lg border text-sm font-medium transition-all ${
                              options.exportRange === 'groups'
                                ? 'bg-indigo-100 dark:bg-indigo-900/50 text-indigo-700 dark:text-indigo-300 border-indigo-200 dark:border-indigo-700'
                                : 'border-gray-200 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700/50'
                            }`}
                          >
                            <Layers className="w-4 h-4 shrink-0" />
                            Selected groups
                          </button>
                        </div>
                        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1.5">
                          {options.exportRange === 'viewport'
                            ? 'Export only what is visible on screen (current pan and zoom).'
                            : options.exportRange === 'groups'
                              ? 'Export only the groups you select below.'
                              : 'Fit and export the entire canvas.'}
                        </p>
                        {/* Group selector when export range is "groups" (#404) */}
                        {options.exportRange === 'groups' && (
                          <div className="mt-3 p-3 rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 max-h-40 overflow-y-auto">
                            <span className="text-xs font-medium text-gray-500 dark:text-gray-400 block mb-2">
                              Select groups to export
                            </span>
                            {groups.length === 0 ? (
                              <p className="text-sm text-gray-500 dark:text-gray-400">
                                No groups on the canvas. Create groups first, then export them.
                              </p>
                            ) : (
                              <div className="space-y-1.5">
                                {groups.map((g) => (
                                  <label
                                    key={g.id}
                                    className="flex items-center gap-2 cursor-pointer text-sm text-gray-700 dark:text-gray-300"
                                  >
                                    <input
                                      type="checkbox"
                                      checked={options.selectedGroupIds.includes(g.id)}
                                      onChange={(e) =>
                                        setOptions((prev) => ({
                                          ...prev,
                                          selectedGroupIds: e.target.checked
                                            ? [...prev.selectedGroupIds, g.id]
                                            : prev.selectedGroupIds.filter((id) => id !== g.id),
                                        }))
                                      }
                                      className="rounded border-gray-300 dark:border-gray-600"
                                    />
                                    <span className="truncate">{g.name}</span>
                                    <span className="text-xs text-gray-400 dark:text-gray-500">
                                      ({g.nodeIds.length} node{g.nodeIds.length !== 1 ? 's' : ''})
                                    </span>
                                  </label>
                                ))}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                      {/* Scale */}
                      <div>
                        <label className="text-xs font-medium text-gray-500 dark:text-gray-400 block mb-1">
                          Resolution
                        </label>
                        <select
                          value={options.scale}
                          onChange={(e) => setOptions(prev => ({ ...prev, scale: Number(e.target.value) }))}
                          className="w-full px-3 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100"
                        >
                          <option value={1}>1x (Standard)</option>
                          <option value={2}>2x (High DPI)</option>
                          <option value={4}>4x (Ultra HD)</option>
                        </select>
                      </div>

                      {/* Quality (for PNG/JPEG) */}
                      {['png', 'jpeg'].includes(selectedFormat) && (
                        <div>
                          <label className="text-xs font-medium text-gray-500 dark:text-gray-400 block mb-1">
                            Quality
                          </label>
                          <select
                            value={options.quality}
                            onChange={(e) => setOptions(prev => ({ ...prev, quality: Number(e.target.value) }))}
                            className="w-full px-3 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100"
                          >
                            <option value={0.7}>Good (70%)</option>
                            <option value={0.85}>High (85%)</option>
                            <option value={1.0}>Maximum (100%)</option>
                          </select>
                        </div>
                      )}

                      {/* Background */}
                      <div>
                        <label className="text-xs font-medium text-gray-500 dark:text-gray-400 block mb-1">
                          Background
                        </label>
                        <div className="flex items-center gap-2">
                          <input
                            type="checkbox"
                            checked={options.includeBackground}
                            onChange={(e) => setOptions(prev => ({ ...prev, includeBackground: e.target.checked }))}
                            className="rounded border-gray-300 dark:border-gray-600"
                          />
                          <span className="text-sm text-gray-700 dark:text-gray-300">Include</span>
                        </div>
                      </div>

                      {/* Include UI elements (#406) */}
                      <div className="col-span-3">
                        <label className="text-xs font-medium text-gray-500 dark:text-gray-400 block mb-1">
                          UI elements
                        </label>
                        <div className="flex items-center gap-2">
                          <input
                            type="checkbox"
                            id="export-include-ui"
                            checked={options.includeUiElements}
                            onChange={(e) => setOptions(prev => ({ ...prev, includeUiElements: e.target.checked }))}
                            className="rounded border-gray-300 dark:border-gray-600"
                          />
                          <label htmlFor="export-include-ui" className="text-sm text-gray-700 dark:text-gray-300 cursor-pointer">
                            Include UI elements
                          </label>
                          <LayoutDashboard className="w-4 h-4 text-gray-400" aria-hidden />
                        </div>
                        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                          Include zoom controls, minimap, attribution, and other canvas overlays in the export.
                        </p>
                      </div>

                      {/* Include grid (#407) */}
                      <div className="col-span-3">
                        <label className="text-xs font-medium text-gray-500 dark:text-gray-400 block mb-1">
                          Grid
                        </label>
                        <div className="flex items-center gap-2">
                          <input
                            type="checkbox"
                            id="export-include-grid"
                            checked={options.includeGrid}
                            onChange={(e) => setOptions(prev => ({ ...prev, includeGrid: e.target.checked }))}
                            className="rounded border-gray-300 dark:border-gray-600"
                          />
                          <label htmlFor="export-include-grid" className="text-sm text-gray-700 dark:text-gray-300 cursor-pointer">
                            Include grid
                          </label>
                          <Grid3X3 className="w-4 h-4 text-gray-400" aria-hidden />
                        </div>
                        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                          Include the canvas dot/line grid in the exported image.
                        </p>
                      </div>

                      {/* #409: Timestamp and metadata */}
                      <div className="col-span-3">
                        <label className="text-xs font-medium text-gray-500 dark:text-gray-400 block mb-1">
                          Timestamp & metadata
                        </label>
                        <div className="flex items-center gap-2">
                          <input
                            type="checkbox"
                            id="export-include-timestamp-metadata"
                            checked={options.includeTimestampAndMetadata}
                            onChange={(e) =>
                              setOptions((prev) => ({ ...prev, includeTimestampAndMetadata: e.target.checked }))
                            }
                            className="rounded border-gray-300 dark:border-gray-600"
                          />
                          <label
                            htmlFor="export-include-timestamp-metadata"
                            className="text-sm text-gray-700 dark:text-gray-300 cursor-pointer flex items-center gap-1.5"
                          >
                            <Clock className="w-4 h-4 text-gray-400" aria-hidden />
                            Include timestamp and metadata
                          </label>
                        </div>
                        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                          Show project name, version, and export date in the bottom-right corner of the export.
                        </p>
                      </div>
                    </>
                  )}

                  {selectedFormat === 'pdf' && (
                    <>
                      {/* Page Size */}
                      <div>
                        <label className="text-xs font-medium text-gray-500 dark:text-gray-400 block mb-1">
                          Page Size
                        </label>
                        <select
                          value={options.pageSize}
                          onChange={(e) =>
                            setOptions((prev) => ({
                              ...prev,
                              pageSize: e.target.value as ExportOptions['pageSize'],
                            }))
                          }
                          className="w-full px-3 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100"
                        >
                          <option value="auto">Auto (fit content)</option>
                          <option value="a4">A4</option>
                          <option value="letter">Letter</option>
                        </select>
                      </div>

                      {/* Orientation */}
                      <div>
                        <label className="text-xs font-medium text-gray-500 dark:text-gray-400 block mb-1">
                          Orientation
                        </label>
                        <select
                          value={options.orientation}
                          onChange={(e) =>
                            setOptions((prev) => ({
                              ...prev,
                              orientation: e.target.value as ExportOptions['orientation'],
                            }))
                          }
                          className="w-full px-3 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100"
                        >
                          <option value="landscape">Landscape</option>
                          <option value="portrait">Portrait</option>
                        </select>
                      </div>
                    </>
                  )}

                  {!isImageFormat && (
                    <div className="col-span-3 text-sm text-gray-500 dark:text-gray-400">
                      No additional options for {selectedFormatInfo?.name} export.
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* Footer */}
          <div className="flex items-center justify-between px-6 py-4 border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50">
            <p className="text-sm text-gray-500 dark:text-gray-400">
              {selectedFormatInfo?.description}
            </p>
            <div className="flex items-center gap-3">
              <button
                onClick={onClose}
                className="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-600 transition-colors"
              >
                Close
              </button>
              {isImageFormat && (
                <button
                  type="button"
                  onClick={handleGeneratePreview}
                  disabled={!open || isGeneratingPreview || isExporting}
                  className="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                >
                  {isGeneratingPreview ? (
                    <>
                      <div className="w-4 h-4 border-2 border-gray-400/50 dark:border-gray-300/50 border-t-gray-700 dark:border-t-white rounded-full animate-spin" />
                      <span>Generating…</span>
                    </>
                  ) : (
                    <>
                      <Eye className="w-4 h-4" />
                      <span>Generate preview</span>
                    </>
                  )}
                </button>
              )}
              <button
                onClick={handleExport}
                disabled={isExporting || !canExportGroups}
                className="px-4 py-2 text-sm font-medium text-white bg-gradient-to-r from-indigo-500 to-purple-600 rounded-lg hover:from-indigo-600 hover:to-purple-700 transition-all shadow-lg shadow-indigo-500/25 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
              >
                {isExporting ? (
                  <>
                    <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    <span>Exporting...</span>
                  </>
                ) : (
                  <>
                    <Download className="w-4 h-4" />
                    <span>Export</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
