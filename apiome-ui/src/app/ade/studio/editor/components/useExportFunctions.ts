'use client';

import { useCallback } from 'react';
import { toPng, toSvg, toJpeg } from 'html-to-image';
import { jsPDF } from 'jspdf';
import { useReactFlow } from '@xyflow/react';
import type { Node, Edge } from '@xyflow/react';
import type { Project, Version } from './types';
import { getVersionRevisionNote } from '@/app/utils/version-display';

interface UseExportFunctionsProps {
  projects: Project[];
  versions: Version[];
  selectedProjectId: string;
  selectedVersionId: string;
  nodes: Node[];
  edges: Edge[];
  isDark: boolean;
  alertDialog: (options: { message: string; variant?: 'success' | 'warning' | 'error' | 'info' }) => Promise<void>;
  setLoadingMessage: (message: string) => void;
  setIsLoadingCanvas: (loading: boolean) => void;
  setExportDropdownOpen: (open: boolean) => void;
}

export function useExportFunctions({
  projects,
  versions,
  selectedProjectId,
  selectedVersionId,
  nodes,
  edges,
  isDark,
  alertDialog,
  setLoadingMessage,
  setIsLoadingCanvas,
  setExportDropdownOpen,
}: UseExportFunctionsProps) {
  const { fitView, getViewport, setViewport } = useReactFlow();

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

  const getFilenameBase = useCallback(() => {
    const selectedProject = projects.find(p => p.id === selectedProjectId);
    const selectedVersion = versions.find(v => v.version_id === selectedVersionId);
    return `${selectedProject?.name || 'canvas'}-v${selectedVersion?.version_id || '1'}`;
  }, [projects, versions, selectedProjectId, selectedVersionId]);

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

  // Handle PNG export
  const handleExportPng = useCallback(async () => {
    try {
      const viewportElement = getViewportElement();
      if (!viewportElement) {
        await alertDialog({ message: 'Canvas not found. Please try again.', variant: 'error' });
        return;
      }

      const filename = `${getFilenameBase()}.png`;
      setLoadingMessage('Exporting canvas as PNG...');
      setIsLoadingCanvas(true);

      const dataUrl = await withFullCanvasView(() =>
        toPng(viewportElement, {
          backgroundColor: isDark ? '#111827' : '#ffffff',
          quality: 1.0,
          pixelRatio: 2,
          filter: imageExportFilter,
        })
      );

      const link = document.createElement('a');
      link.download = filename;
      link.href = dataUrl;
      link.click();

      setIsLoadingCanvas(false);
      setLoadingMessage('');
      setExportDropdownOpen(false);

      await alertDialog({ message: `Canvas exported as ${filename}`, variant: 'success' });
    } catch (error) {
      console.error('Error exporting PNG:', error);
      setIsLoadingCanvas(false);
      setLoadingMessage('');
      await alertDialog({ message: 'Failed to export canvas as PNG. Please try again.', variant: 'error' });
    }
  }, [getFilenameBase, getViewportElement, isDark, alertDialog, setLoadingMessage, setIsLoadingCanvas, setExportDropdownOpen, imageExportFilter, withFullCanvasView]);

  // Handle SVG export
  const handleExportSvg = useCallback(async () => {
    try {
      const viewportElement = getViewportElement();
      if (!viewportElement) {
        await alertDialog({ message: 'Canvas not found. Please try again.', variant: 'error' });
        return;
      }

      const filename = `${getFilenameBase()}.svg`;
      setLoadingMessage('Exporting canvas as SVG...');
      setIsLoadingCanvas(true);

      const dataUrl = await withFullCanvasView(() =>
        toSvg(viewportElement, {
          backgroundColor: isDark ? '#111827' : '#ffffff',
          quality: 1.0,
          filter: imageExportFilter,
        })
      );

      const link = document.createElement('a');
      link.download = filename;
      link.href = dataUrl;
      link.click();

      setIsLoadingCanvas(false);
      setLoadingMessage('');
      setExportDropdownOpen(false);

      await alertDialog({ message: `Canvas exported as ${filename}`, variant: 'success' });
    } catch (error) {
      console.error('Error exporting SVG:', error);
      setIsLoadingCanvas(false);
      setLoadingMessage('');
      await alertDialog({ message: 'Failed to export canvas as SVG. Please try again.', variant: 'error' });
    }
  }, [getFilenameBase, getViewportElement, isDark, alertDialog, setLoadingMessage, setIsLoadingCanvas, setExportDropdownOpen, imageExportFilter, withFullCanvasView]);

  // Handle JPEG export
  const handleExportJpeg = useCallback(async () => {
    try {
      const viewportElement = getViewportElement();
      if (!viewportElement) {
        await alertDialog({ message: 'Canvas not found. Please try again.', variant: 'error' });
        return;
      }

      const filename = `${getFilenameBase()}.jpg`;
      setLoadingMessage('Exporting canvas as JPEG...');
      setIsLoadingCanvas(true);

      const dataUrl = await withFullCanvasView(() =>
        toJpeg(viewportElement, {
          backgroundColor: isDark ? '#111827' : '#ffffff',
          quality: 0.95,
          pixelRatio: 2,
          filter: imageExportFilter,
        })
      );

      const link = document.createElement('a');
      link.download = filename;
      link.href = dataUrl;
      link.click();

      setIsLoadingCanvas(false);
      setLoadingMessage('');
      setExportDropdownOpen(false);

      await alertDialog({ message: `Canvas exported as ${filename}`, variant: 'success' });
    } catch (error) {
      console.error('Error exporting JPEG:', error);
      setIsLoadingCanvas(false);
      setLoadingMessage('');
      await alertDialog({ message: 'Failed to export canvas as JPEG. Please try again.', variant: 'error' });
    }
  }, [getFilenameBase, getViewportElement, isDark, alertDialog, setLoadingMessage, setIsLoadingCanvas, setExportDropdownOpen, imageExportFilter, withFullCanvasView]);

  // Handle PDF export
  const handleExportPdf = useCallback(async () => {
    try {
      const viewportElement = getViewportElement();
      if (!viewportElement) {
        await alertDialog({ message: 'Canvas not found. Please try again.', variant: 'error' });
        return;
      }

      const selectedProject = projects.find(p => p.id === selectedProjectId);
      const selectedVersion = versions.find(v => v.version_id === selectedVersionId);
      const filename = `${getFilenameBase()}.pdf`;

      setLoadingMessage('Exporting canvas as PDF...');
      setIsLoadingCanvas(true);

      const imageDataUrl = await withFullCanvasView(() =>
        toPng(viewportElement, {
          backgroundColor: isDark ? '#111827' : '#ffffff',
          quality: 1.0,
          pixelRatio: 2,
          filter: imageExportFilter,
        })
      );

      const viewportRect = viewportElement.getBoundingClientRect();
      const imgWidth = viewportRect.width;
      const imgHeight = viewportRect.height;

      const pdfWidth = 297; // A4 landscape
      const pdfHeight = 210;

      const scaleX = pdfWidth / imgWidth;
      const scaleY = pdfHeight / imgHeight;
      const scale = Math.min(scaleX, scaleY);

      const scaledWidth = imgWidth * scale;
      const scaledHeight = imgHeight * scale;

      const xOffset = (pdfWidth - scaledWidth) / 2;
      const yOffset = (pdfHeight - scaledHeight) / 2;

      const pdf = new jsPDF({
        orientation: 'landscape',
        unit: 'mm',
        format: 'a4',
      });

      pdf.setProperties({
        title: `${selectedProject?.name || 'Canvas'} - Version ${selectedVersion?.version_id || '1'}`,
        subject: 'API Schema Canvas Export',
        author: 'Apiome',
        keywords: 'api, schema, openapi, canvas',
        creator: 'Apiome Studio',
      });

      pdf.setFontSize(16);
      pdf.setTextColor(isDark ? 200 : 40);
      pdf.text(`${selectedProject?.name || 'Canvas'} - v${selectedVersion?.version_id || '1'}`, 10, 15);

      pdf.setFontSize(10);
      pdf.setTextColor(isDark ? 150 : 100);
      pdf.text(`Exported: ${new Date().toLocaleString()}`, 10, 22);

      pdf.addImage(imageDataUrl, 'PNG', xOffset, yOffset + 15, scaledWidth, scaledHeight - 15);

      pdf.setFontSize(8);
      pdf.setTextColor(isDark ? 150 : 100);
      pdf.text('Generated by Apiome Studio', pdfWidth - 60, pdfHeight - 5);

      pdf.save(filename);

      setIsLoadingCanvas(false);
      setLoadingMessage('');
      setExportDropdownOpen(false);

      await alertDialog({ message: `Canvas exported as ${filename}`, variant: 'success' });
    } catch (error) {
      console.error('Error exporting PDF:', error);
      setIsLoadingCanvas(false);
      setLoadingMessage('');
      await alertDialog({ message: 'Failed to export canvas as PDF. Please try again.', variant: 'error' });
    }
  }, [projects, versions, selectedProjectId, selectedVersionId, getFilenameBase, getViewportElement, isDark, alertDialog, setLoadingMessage, setIsLoadingCanvas, setExportDropdownOpen, imageExportFilter, withFullCanvasView]);

  // Handle Mermaid export
  const handleExportMermaid = useCallback(async () => {
    try {
      const selectedProject = projects.find(p => p.id === selectedProjectId);
      const selectedVersion = versions.find(v => v.version_id === selectedVersionId);
      const filename = `${getFilenameBase()}.mmd`;

      setLoadingMessage('Exporting canvas as Mermaid...');
      setIsLoadingCanvas(true);

      let mermaidContent = 'classDiagram\n';
      mermaidContent += `  %% ${selectedProject?.name || 'Canvas'} - Version ${selectedVersion?.version_id || '1'}\n`;
      mermaidContent += `  %% Generated by Apiome Studio on ${new Date().toLocaleDateString()}\n\n`;

      nodes.forEach(node => {
        if (node.data && node.type !== 'groupNode') {
          const className = String(node.data.name || 'UnnamedClass').replace(/[^a-zA-Z0-9_]/g, '_');
          mermaidContent += `  class ${className} {\n`;

          if (node.data.properties && Array.isArray(node.data.properties)) {
            node.data.properties.forEach((prop: any) => {
              const propName = String(prop.name || 'unnamed').replace(/[^a-zA-Z0-9_]/g, '_');
              const propType = String(prop.type || 'string').replace(/[^a-zA-Z0-9_]/g, '_');
              const visibility = prop.required ? '+' : '-';
              const arrayMarker = prop.is_array ? '[]' : '';
              mermaidContent += `    ${visibility}${propType}${arrayMarker} ${propName}\n`;
            });
          }

          mermaidContent += '  }\n\n';
        }
      });

      const nodeNames = new Map<string, string>();
      nodes.forEach(node => {
        if (node.data && node.type !== 'groupNode') {
          nodeNames.set(node.id, String(node.data.name || 'UnnamedClass').replace(/[^a-zA-Z0-9_]/g, '_'));
        }
      });

      edges.forEach(edge => {
        const sourceName = nodeNames.get(edge.source);
        const targetName = nodeNames.get(edge.target);

        if (sourceName && targetName) {
          let relationship = '-->';
          let label = '';

          if (edge.data) {
            if (edge.data.type === 'allOf' || edge.data.type === 'inheritance') {
              relationship = '--|>';
              label = edge.label ? ` : ${edge.label}` : ' : extends';
            } else if (edge.data.type === 'anyOf') {
              relationship = '..>';
              label = ' : anyOf';
            } else if (edge.data.type === 'oneOf') {
              relationship = '..>';
              label = ' : oneOf';
            } else if (edge.label) {
              label = ` : ${edge.label}`;
            }
          } else if (edge.label) {
            label = ` : ${edge.label}`;
          }

          mermaidContent += `  ${sourceName} ${relationship} ${targetName}${label}\n`;
        }
      });

      const blob = new Blob([mermaidContent], { type: 'text/plain;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.download = filename;
      link.href = url;
      link.click();
      URL.revokeObjectURL(url);

      setIsLoadingCanvas(false);
      setLoadingMessage('');
      setExportDropdownOpen(false);

      await alertDialog({
        message: `Canvas exported as ${filename}. You can view this diagram at https://mermaid.live/`,
        variant: 'success',
      });
    } catch (error) {
      console.error('Error exporting Mermaid:', error);
      setIsLoadingCanvas(false);
      setLoadingMessage('');
      await alertDialog({ message: 'Failed to export canvas as Mermaid. Please try again.', variant: 'error' });
    }
  }, [projects, versions, selectedProjectId, selectedVersionId, nodes, edges, getFilenameBase, alertDialog, setLoadingMessage, setIsLoadingCanvas, setExportDropdownOpen]);

  // Handle PlantUML export
  const handleExportPlantUml = useCallback(async () => {
    try {
      const selectedProject = projects.find(p => p.id === selectedProjectId);
      const selectedVersion = versions.find(v => v.version_id === selectedVersionId);
      const filename = `${getFilenameBase()}.puml`;

      setLoadingMessage('Exporting canvas as PlantUML...');
      setIsLoadingCanvas(true);

      let plantUmlContent = '@startuml\n';
      plantUmlContent += `' ${selectedProject?.name || 'Canvas'} - Version ${selectedVersion?.version_id || '1'}\n`;
      plantUmlContent += `' Generated by Apiome Studio on ${new Date().toLocaleDateString()}\n\n`;
      plantUmlContent += 'skinparam classAttributeIconSize 0\n';
      plantUmlContent += 'skinparam shadowing false\n';
      plantUmlContent += 'skinparam class {\n';
      plantUmlContent += '  BackgroundColor White\n';
      plantUmlContent += '  BorderColor #4F46E5\n';
      plantUmlContent += '  ArrowColor #4F46E5\n';
      plantUmlContent += '}\n\n';

      nodes.forEach(node => {
        if (node.data && node.type !== 'groupNode') {
          const className = String(node.data.name || 'UnnamedClass').replace(/[^a-zA-Z0-9_]/g, '_');
          plantUmlContent += `class ${className} {\n`;

          if (node.data.properties && Array.isArray(node.data.properties)) {
            node.data.properties.forEach((prop: any) => {
              const propName = String(prop.name || 'unnamed');
              const propType = String(prop.type || 'string');
              const visibility = prop.required ? '+' : '-';
              const arrayMarker = prop.is_array ? '[]' : '';
              plantUmlContent += `  ${visibility}${propName} : ${propType}${arrayMarker}\n`;
            });
          }

          plantUmlContent += '}\n\n';
        }
      });

      const nodeNames = new Map<string, string>();
      nodes.forEach(node => {
        if (node.data && node.type !== 'groupNode') {
          nodeNames.set(node.id, String(node.data.name || 'UnnamedClass').replace(/[^a-zA-Z0-9_]/g, '_'));
        }
      });

      edges.forEach(edge => {
        const sourceName = nodeNames.get(edge.source);
        const targetName = nodeNames.get(edge.target);

        if (sourceName && targetName) {
          let arrow = '-->';
          let label = '';

          if (edge.data) {
            if (edge.data.type === 'allOf' || edge.data.type === 'inheritance') {
              arrow = '--|>';
              label = edge.label ? ` : ${edge.label}` : ' : extends';
            } else if (edge.data.type === 'anyOf') {
              arrow = '..>';
              label = ' : anyOf';
            } else if (edge.data.type === 'oneOf') {
              arrow = '..>';
              label = ' : oneOf';
            } else if (edge.label) {
              label = ` : ${edge.label}`;
            }
          } else if (edge.label) {
            label = ` : ${edge.label}`;
          }

          plantUmlContent += `${sourceName} ${arrow} ${targetName}${label}\n`;
        }
      });

      plantUmlContent += '\n@enduml\n';

      const blob = new Blob([plantUmlContent], { type: 'text/plain;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.download = filename;
      link.href = url;
      link.click();
      URL.revokeObjectURL(url);

      setIsLoadingCanvas(false);
      setLoadingMessage('');
      setExportDropdownOpen(false);

      await alertDialog({
        message: `Canvas exported as ${filename}. You can render this at https://www.plantuml.com/plantuml/`,
        variant: 'success',
      });
    } catch (error) {
      console.error('Error exporting PlantUML:', error);
      setIsLoadingCanvas(false);
      setLoadingMessage('');
      await alertDialog({ message: 'Failed to export canvas as PlantUML. Please try again.', variant: 'error' });
    }
  }, [projects, versions, selectedProjectId, selectedVersionId, nodes, edges, getFilenameBase, alertDialog, setLoadingMessage, setIsLoadingCanvas, setExportDropdownOpen]);

  // Handle DOT (GraphViz) export
  const handleExportDot = useCallback(async () => {
    try {
      const selectedProject = projects.find(p => p.id === selectedProjectId);
      const selectedVersion = versions.find(v => v.version_id === selectedVersionId);
      const filename = `${getFilenameBase()}.dot`;

      setLoadingMessage('Exporting canvas as DOT...');
      setIsLoadingCanvas(true);

      let dotContent = 'digraph {\n';
      dotContent += `  // ${selectedProject?.name || 'Canvas'} - Version ${selectedVersion?.version_id || '1'}\n`;
      dotContent += `  // Generated by Apiome Studio on ${new Date().toLocaleDateString()}\n\n`;
      dotContent += '  graph [rankdir=TB, nodesep=0.5, ranksep=0.8, bgcolor=transparent];\n';
      dotContent += '  node [shape=record, style=filled, fillcolor="#f8f9fa", fontname="Arial", fontsize=10];\n';
      dotContent += '  edge [color="#4F46E5", fontname="Arial", fontsize=9];\n\n';

      const nodeMap = new Map<string, string>();
      nodes.forEach(node => {
        if (node.data && node.type !== 'groupNode') {
          const nodeId = node.id.replace(/[^a-zA-Z0-9_]/g, '_');
          nodeMap.set(node.id, nodeId);

          const className = String(node.data.name || 'UnnamedClass').replace(/"/g, '\\"');
          let label = `{${className}|`;

          if (node.data.properties && Array.isArray(node.data.properties)) {
            const propLines = node.data.properties.map((prop: any) => {
              const propName = String(prop.name || 'unnamed').replace(/"/g, '\\"');
              const propType = String(prop.type || 'string').replace(/"/g, '\\"');
              const isRequired = prop.required ? '+' : '-';
              const isArray = prop.is_array ? '[]' : '';
              return `${isRequired} ${propName}: ${propType}${isArray}`;
            });

            if (propLines.length > 0) {
              label += propLines.join('\\l') + '\\l';
            }
          }

          label += '}';
          dotContent += `  ${nodeId} [label="${label}"];\n`;
        }
      });

      dotContent += '\n  // Relationships\n';

      edges.forEach(edge => {
        const sourceId = nodeMap.get(edge.source);
        const targetId = nodeMap.get(edge.target);

        if (sourceId && targetId) {
          const edgeAttrs: string[] = [];

          if (edge.data) {
            const edgeType = edge.data.type;

            if (edgeType === 'allOf' || edgeType === 'inheritance') {
              edgeAttrs.push('arrowhead=empty', 'style=solid');
              edgeAttrs.push(edge.label ? `label="${String(edge.label).replace(/"/g, '\\"')}"` : 'label="extends"');
            } else if (edgeType === 'anyOf') {
              edgeAttrs.push('arrowhead=vee', 'style=dashed', 'label="anyOf"');
            } else if (edgeType === 'oneOf') {
              edgeAttrs.push('arrowhead=vee', 'style=dashed', 'label="oneOf"');
            } else {
              edgeAttrs.push('arrowhead=vee');
              if (edge.label) edgeAttrs.push(`label="${String(edge.label).replace(/"/g, '\\"')}"`);
            }

            if (edge.data.cardinality) {
              const card = String(edge.data.cardinality).replace(/"/g, '\\"');
              if (!edge.label) edgeAttrs.push(`label="${card}"`);
              else edgeAttrs.push(`headlabel="${card}"`);
            }
          } else if (edge.label) {
            edgeAttrs.push(`label="${String(edge.label).replace(/"/g, '\\"')}"`);
          }

          const attrs = edgeAttrs.length > 0 ? ` [${edgeAttrs.join(', ')}]` : '';
          dotContent += `  ${sourceId} -> ${targetId}${attrs};\n`;
        }
      });

      dotContent += '}\n';

      const blob = new Blob([dotContent], { type: 'text/plain;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.download = filename;
      link.href = url;
      link.click();
      URL.revokeObjectURL(url);

      setIsLoadingCanvas(false);
      setLoadingMessage('');
      setExportDropdownOpen(false);

      await alertDialog({
        message: `Canvas exported as ${filename}. Visualize at https://dreampuf.github.io/GraphvizOnline/`,
        variant: 'success',
      });
    } catch (error) {
      console.error('Error exporting DOT:', error);
      setIsLoadingCanvas(false);
      setLoadingMessage('');
      await alertDialog({ message: 'Failed to export canvas as DOT. Please try again.', variant: 'error' });
    }
  }, [projects, versions, selectedProjectId, selectedVersionId, nodes, edges, getFilenameBase, alertDialog, setLoadingMessage, setIsLoadingCanvas, setExportDropdownOpen]);

  // Handle GraphML export
  const handleExportGraphMl = useCallback(async () => {
    try {
      const selectedProject = projects.find(p => p.id === selectedProjectId);
      const selectedVersion = versions.find(v => v.version_id === selectedVersionId);
      const filename = `${getFilenameBase()}.graphml`;

      setLoadingMessage('Exporting canvas as GraphML...');
      setIsLoadingCanvas(true);

      const escapeXml = (str: string) => {
        return str
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;')
          .replace(/"/g, '&quot;')
          .replace(/'/g, '&apos;');
      };

      let graphMlContent = '<?xml version="1.0" encoding="UTF-8"?>\n';
      graphMlContent += '<graphml xmlns="http://graphml.graphdrawing.org/xmlns"\n';
      graphMlContent += '    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"\n';
      graphMlContent += '    xsi:schemaLocation="http://graphml.graphdrawing.org/xmlns\n';
      graphMlContent += '    http://graphml.graphdrawing.org/xmlns/1.0/graphml.xsd">\n\n';
      graphMlContent += '  <!-- Node attributes -->\n';
      graphMlContent += '  <key id="d0" for="node" attr.name="name" attr.type="string"/>\n';
      graphMlContent += '  <key id="d1" for="node" attr.name="description" attr.type="string"/>\n';
      graphMlContent += '  <key id="d2" for="node" attr.name="properties" attr.type="string"/>\n';
      graphMlContent += '  <key id="d3" for="node" attr.name="x" attr.type="double"/>\n';
      graphMlContent += '  <key id="d4" for="node" attr.name="y" attr.type="double"/>\n';
      graphMlContent += '  <key id="d5" for="node" attr.name="nodeType" attr.type="string"/>\n\n';
      graphMlContent += '  <!-- Edge attributes -->\n';
      graphMlContent += '  <key id="e0" for="edge" attr.name="label" attr.type="string"/>\n';
      graphMlContent += '  <key id="e1" for="edge" attr.name="type" attr.type="string"/>\n';
      graphMlContent += '  <key id="e2" for="edge" attr.name="cardinality" attr.type="string"/>\n\n';

      graphMlContent += `  <graph id="${escapeXml(selectedProject?.name || 'canvas')}" edgedefault="directed">\n`;
      graphMlContent += `    <!-- ${selectedProject?.name || 'Canvas'} - Version ${selectedVersion?.version_id || '1'} -->\n`;
      graphMlContent += `    <!-- Generated by Apiome Studio on ${new Date().toLocaleDateString()} -->\n\n`;

      nodes.forEach(node => {
        if (node.data && node.type !== 'groupNode') {
          graphMlContent += `    <node id="${escapeXml(node.id)}">\n`;
          graphMlContent += `      <data key="d0">${escapeXml(String(node.data.name))}</data>\n`;

          if (node.data.description) {
            graphMlContent += `      <data key="d1">${escapeXml(String(node.data.description))}</data>\n`;
          }

          if (node.data.properties && Array.isArray(node.data.properties)) {
            const propsJson = escapeXml(JSON.stringify(node.data.properties.map((p: any) => ({
              name: p.name,
              type: p.type || 'string',
              required: !!p.required,
              is_array: !!p.is_array
            }))));
            graphMlContent += `      <data key="d2">${propsJson}</data>\n`;
          }

          if (node.position) {
            graphMlContent += `      <data key="d3">${node.position.x}</data>\n`;
            graphMlContent += `      <data key="d4">${node.position.y}</data>\n`;
          }

          graphMlContent += `      <data key="d5">class</data>\n`;
          graphMlContent += '    </node>\n';
        }
      });

      graphMlContent += '\n';

      edges.forEach((edge, index) => {
        graphMlContent += `    <edge id="e${index}" source="${escapeXml(edge.source)}" target="${escapeXml(edge.target)}">\n`;

        if (edge.label) {
          graphMlContent += `      <data key="e0">${escapeXml(String(edge.label))}</data>\n`;
        }

        if (edge.data) {
          const edgeType = edge.data.type || 'reference';
          graphMlContent += `      <data key="e1">${escapeXml(String(edgeType))}</data>\n`;

          if (edge.data.cardinality) {
            graphMlContent += `      <data key="e2">${escapeXml(String(edge.data.cardinality))}</data>\n`;
          }
        }

        graphMlContent += '    </edge>\n';
      });

      graphMlContent += '  </graph>\n';
      graphMlContent += '</graphml>\n';

      const blob = new Blob([graphMlContent], { type: 'application/xml;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.download = filename;
      link.href = url;
      link.click();
      URL.revokeObjectURL(url);

      setIsLoadingCanvas(false);
      setLoadingMessage('');
      setExportDropdownOpen(false);

      await alertDialog({
        message: `Canvas exported as ${filename}. Open with yEd, Gephi, or Cytoscape.`,
        variant: 'success',
      });
    } catch (error) {
      console.error('Error exporting GraphML:', error);
      setIsLoadingCanvas(false);
      setLoadingMessage('');
      await alertDialog({ message: 'Failed to export canvas as GraphML. Please try again.', variant: 'error' });
    }
  }, [projects, versions, selectedProjectId, selectedVersionId, nodes, edges, getFilenameBase, alertDialog, setLoadingMessage, setIsLoadingCanvas, setExportDropdownOpen]);

  // Handle JSON export
  const handleExportJson = useCallback(async () => {
    try {
      const selectedProject = projects.find(p => p.id === selectedProjectId);
      const selectedVersion = versions.find(v => v.version_id === selectedVersionId);
      const filename = `${getFilenameBase()}-canvas.json`;

      setLoadingMessage('Exporting canvas as JSON...');
      setIsLoadingCanvas(true);

      const canvasData = {
        metadata: {
          projectName: selectedProject?.name || 'Unknown',
          projectSlug: selectedProject?.slug || '',
          versionId: selectedVersion?.version_id || '',
          versionDescription: selectedVersion ? getVersionRevisionNote(selectedVersion) : '',
          exportedAt: new Date().toISOString(),
          exportedBy: 'Apiome Studio',
        },
        nodes: nodes.filter(n => n.type !== 'groupNode').map(node => ({
          id: node.id,
          name: node.data?.name,
          description: node.data?.description,
          position: node.position,
          properties: node.data?.properties || [],
          schema: node.data?.schema,
          tags: node.data?.tags || [],
        })),
        edges: edges.map(edge => ({
          id: edge.id,
          source: edge.source,
          target: edge.target,
          label: edge.label,
          type: edge.data?.type,
          cardinality: edge.data?.cardinality,
        })),
      };

      const jsonContent = JSON.stringify(canvasData, null, 2);

      const blob = new Blob([jsonContent], { type: 'application/json;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.download = filename;
      link.href = url;
      link.click();
      URL.revokeObjectURL(url);

      setIsLoadingCanvas(false);
      setLoadingMessage('');
      setExportDropdownOpen(false);

      await alertDialog({ message: `Canvas exported as ${filename}`, variant: 'success' });
    } catch (error) {
      console.error('Error exporting JSON:', error);
      setIsLoadingCanvas(false);
      setLoadingMessage('');
      await alertDialog({ message: 'Failed to export canvas as JSON. Please try again.', variant: 'error' });
    }
  }, [projects, versions, selectedProjectId, selectedVersionId, nodes, edges, getFilenameBase, alertDialog, setLoadingMessage, setIsLoadingCanvas, setExportDropdownOpen]);

  return {
    handleExportPng,
    handleExportSvg,
    handleExportJpeg,
    handleExportPdf,
    handleExportMermaid,
    handleExportPlantUml,
    handleExportDot,
    handleExportGraphMl,
    handleExportJson,
  };
}

