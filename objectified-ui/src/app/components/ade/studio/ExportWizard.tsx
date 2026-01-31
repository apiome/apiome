'use client';

import React, { useState, useCallback, useEffect, useRef } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import {
  X,
  Image,
  FileCode,
  FileText,
  BarChart3,
  Layout,
  Network,
  Zap,
  Download,
  Check,
  Settings,
  Eye
} from 'lucide-react';
import { toPng, toSvg, toJpeg } from 'html-to-image';
import { jsPDF } from 'jspdf';
import type { Node, Edge } from '@xyflow/react';

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

interface ExportOptions {
  // Image options
  quality: number; // 0.1 - 1.0
  scale: number; // 1, 2, 4
  includeBackground: boolean;
  backgroundColor: string;
  // PDF options
  pageSize: 'a4' | 'letter' | 'auto';
  orientation: 'portrait' | 'landscape';
  // General options
  includeGrid: boolean;
  includeWatermark: boolean;
  watermarkText: string;
}

const defaultOptions: ExportOptions = {
  quality: 1.0,
  scale: 2,
  includeBackground: true,
  backgroundColor: '#ffffff',
  pageSize: 'auto',
  orientation: 'landscape',
  includeGrid: false,
  includeWatermark: false,
  watermarkText: '',
};

interface ExportWizardProps {
  open: boolean;
  onClose: () => void;
  nodes: Node[];
  edges: Edge[];
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
  isDark,
  projectName,
  versionId,
  alertDialog,
}: ExportWizardProps) {
  const [selectedFormat, setSelectedFormat] = useState<ExportFormat>('png');
  const [options, setOptions] = useState<ExportOptions>(defaultOptions);
  const [isExporting, setIsExporting] = useState(false);
  const [previewDataUrl, setPreviewDataUrl] = useState<string | null>(null);
  const [previewText, setPreviewText] = useState<string | null>(null);
  const previewTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  const getFilenameBase = useCallback(() => {
    return `${projectName || 'canvas'}-v${versionId || '1'}`;
  }, [projectName, versionId]);

  const getViewportElement = useCallback(() => {
    return document.querySelector('.react-flow__viewport') as HTMLElement | null;
  }, []);

  const imageExportFilter = useCallback((node: Element) => {
    if (node.classList) {
      return !node.classList.contains('react-flow__controls') &&
             !node.classList.contains('react-flow__minimap') &&
             !node.classList.contains('react-flow__attribution') &&
             !node.classList.contains('react-flow__panel');
    }
    return true;
  }, []);

  // Generate preview when format or options change
  useEffect(() => {
    if (!open) return;

    // Clear previous timeout
    if (previewTimeoutRef.current) {
      clearTimeout(previewTimeoutRef.current);
    }

    // Debounce preview generation
    previewTimeoutRef.current = setTimeout(() => {
      generatePreview();
    }, 300);

    return () => {
      if (previewTimeoutRef.current) {
        clearTimeout(previewTimeoutRef.current);
      }
    };
  }, [open, selectedFormat, options]);

  const generatePreview = useCallback(async () => {
    const viewportElement = getViewportElement();

    // For image formats, generate a preview image
    if (['png', 'jpeg', 'svg', 'pdf'].includes(selectedFormat)) {
      if (!viewportElement) {
        setPreviewDataUrl(null);
        return;
      }

      try {
        const dataUrl = await toPng(viewportElement, {
          backgroundColor: options.includeBackground
            ? (isDark ? '#111827' : options.backgroundColor)
            : 'transparent',
          quality: 0.5, // Lower quality for preview
          pixelRatio: 1,
          filter: imageExportFilter,
        });
        setPreviewDataUrl(dataUrl);
        setPreviewText(null);
      } catch (error) {
        console.error('Error generating preview:', error);
        setPreviewDataUrl(null);
      }
    } else {
      // For text-based formats, generate preview text
      setPreviewDataUrl(null);
      const text = generateTextExport(selectedFormat);
      setPreviewText(text.substring(0, 2000) + (text.length > 2000 ? '\n...' : ''));
    }
  }, [selectedFormat, options, isDark, getViewportElement, imageExportFilter, nodes, edges]);

  const generateTextExport = useCallback((format: ExportFormat): string => {
    const classNodes = nodes.filter(n => n.type !== 'groupNode');

    switch (format) {
      case 'json':
        return JSON.stringify({ nodes: classNodes, edges }, null, 2);

      case 'mermaid':
        return generateMermaid(classNodes, edges);

      case 'plantuml':
        return generatePlantUml(classNodes, edges);

      case 'graphml':
        return generateGraphMl(classNodes, edges);

      case 'dot':
        return generateDot(classNodes, edges);

      default:
        return '';
    }
  }, [nodes, edges]);

  // Generate Mermaid diagram
  const generateMermaid = (classNodes: Node[], edges: Edge[]): string => {
    let mermaid = 'classDiagram\n';

    classNodes.forEach(node => {
      const data = node.data as any;
      const className = data.name || node.id;
      mermaid += `  class ${className} {\n`;

      const properties = data.properties || [];
      properties.forEach((prop: any) => {
        const propType = prop.data?.type || 'any';
        mermaid += `    +${propType} ${prop.name}\n`;
      });

      mermaid += '  }\n';
    });

    edges.forEach(edge => {
      const sourceNode = classNodes.find(n => n.id === edge.source);
      const targetNode = classNodes.find(n => n.id === edge.target);
      if (sourceNode && targetNode) {
        const sourceName = (sourceNode.data as any).name || sourceNode.id;
        const targetName = (targetNode.data as any).name || targetNode.id;
        mermaid += `  ${sourceName} --> ${targetName}\n`;
      }
    });

    return mermaid;
  };

  // Generate PlantUML diagram
  const generatePlantUml = (classNodes: Node[], edges: Edge[]): string => {
    let uml = '@startuml\n\n';

    classNodes.forEach(node => {
      const data = node.data as any;
      const className = data.name || node.id;
      uml += `class ${className} {\n`;

      const properties = data.properties || [];
      properties.forEach((prop: any) => {
        const propType = prop.data?.type || 'any';
        uml += `  +${prop.name}: ${propType}\n`;
      });

      uml += '}\n\n';
    });

    edges.forEach(edge => {
      const sourceNode = classNodes.find(n => n.id === edge.source);
      const targetNode = classNodes.find(n => n.id === edge.target);
      if (sourceNode && targetNode) {
        const sourceName = (sourceNode.data as any).name || sourceNode.id;
        const targetName = (targetNode.data as any).name || targetNode.id;
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
      const data = node.data as any;
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
      const data = node.data as any;
      const className = data.name || node.id;
      const properties = data.properties || [];
      const propStr = properties.map((p: any) => `${p.name}: ${p.data?.type || 'any'}`).join('\\l');
      dot += `  "${node.id}" [label="{${className}|${propStr}\\l}"];\n`;
    });

    dot += '\n';

    edges.forEach(edge => {
      dot += `  "${edge.source}" -> "${edge.target}";\n`;
    });

    dot += '}';
    return dot;
  };

  // Handle export
  const handleExport = useCallback(async () => {
    setIsExporting(true);

    try {
      const viewportElement = getViewportElement();
      const filename = getFilenameBase();

      switch (selectedFormat) {
        case 'png': {
          if (!viewportElement) throw new Error('Canvas not found');
          const dataUrl = await toPng(viewportElement, {
            backgroundColor: options.includeBackground
              ? (isDark ? '#111827' : options.backgroundColor)
              : 'transparent',
            quality: options.quality,
            pixelRatio: options.scale,
            filter: imageExportFilter,
          });
          downloadDataUrl(dataUrl, `${filename}.png`);
          break;
        }

        case 'jpeg': {
          if (!viewportElement) throw new Error('Canvas not found');
          const dataUrl = await toJpeg(viewportElement, {
            backgroundColor: isDark ? '#111827' : options.backgroundColor,
            quality: options.quality,
            pixelRatio: options.scale,
            filter: imageExportFilter,
          });
          downloadDataUrl(dataUrl, `${filename}.jpg`);
          break;
        }

        case 'svg': {
          if (!viewportElement) throw new Error('Canvas not found');
          const dataUrl = await toSvg(viewportElement, {
            backgroundColor: options.includeBackground
              ? (isDark ? '#111827' : options.backgroundColor)
              : 'transparent',
            filter: imageExportFilter,
          });
          downloadDataUrl(dataUrl, `${filename}.svg`);
          break;
        }

        case 'pdf': {
          if (!viewportElement) throw new Error('Canvas not found');
          const dataUrl = await toPng(viewportElement, {
            backgroundColor: isDark ? '#111827' : options.backgroundColor,
            quality: 1.0,
            pixelRatio: options.scale,
            filter: imageExportFilter,
          });

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
          pdf.save(`${filename}.pdf`);
          break;
        }

        case 'json':
        case 'mermaid':
        case 'plantuml':
        case 'graphml':
        case 'dot': {
          const text = generateTextExport(selectedFormat);
          const extension = selectedFormat === 'json' ? 'json'
            : selectedFormat === 'mermaid' ? 'mmd'
            : selectedFormat === 'plantuml' ? 'puml'
            : selectedFormat === 'graphml' ? 'graphml'
            : 'dot';
          downloadText(text, `${filename}.${extension}`);
          break;
        }
      }

      await alertDialog({ message: `Canvas exported successfully!`, variant: 'success' });
      onClose();
    } catch (error) {
      console.error('Export error:', error);
      await alertDialog({ message: 'Failed to export. Please try again.', variant: 'error' });
    } finally {
      setIsExporting(false);
    }
  }, [selectedFormat, options, isDark, getViewportElement, getFilenameBase, imageExportFilter, generateTextExport, alertDialog, onClose]);

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
        <Dialog.Content className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[900px] max-w-[95vw] h-[90vh] bg-white dark:bg-gray-900 rounded-2xl shadow-2xl z-[9999] flex flex-col overflow-hidden">
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
                  {previewDataUrl ? (
                    <img
                      src={previewDataUrl}
                      alt="Export preview"
                      className="max-w-full max-h-full object-contain"
                    />
                  ) : previewText ? (
                    <pre className="w-full h-full p-4 text-xs font-mono text-gray-700 dark:text-gray-300 overflow-auto bg-gray-50 dark:bg-gray-900">
                      {previewText}
                    </pre>
                  ) : (
                    <div className="text-gray-400 dark:text-gray-500 flex flex-col items-center gap-2">
                      <Eye className="w-8 h-8" />
                      <span className="text-sm">Generating preview...</span>
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
                          onChange={(e) => setOptions(prev => ({ ...prev, pageSize: e.target.value as any }))}
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
                          onChange={(e) => setOptions(prev => ({ ...prev, orientation: e.target.value as any }))}
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
              <button
                onClick={handleExport}
                disabled={isExporting}
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
