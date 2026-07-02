'use client';

import { useEffect, useRef, useState, useImperativeHandle, forwardRef } from 'react';
import mermaid from 'mermaid';
import { AlertCircle, ZoomIn, ZoomOut, Maximize2 } from 'lucide-react';

interface MermaidPreviewProps {
  code: string;
  projectSlug?: string;
  versionSlug?: string;
  onSvgReady?: (hasSvg: boolean) => void;
}

export interface MermaidPreviewRef {
  exportSVG: () => void;
  exportPNG: () => void;
  hasSvg: () => boolean;
}

const MermaidPreview = forwardRef<MermaidPreviewRef, MermaidPreviewProps>(
  ({ code, projectSlug = 'diagram', versionSlug = '1-0-0', onSvgReady }, ref) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [svg, setSvg] = useState<string>('');
  const [zoom, setZoom] = useState<number>(100);

  useEffect(() => {
    // Initialize mermaid
    mermaid.initialize({
      startOnLoad: false,
      theme: 'default',
      securityLevel: 'loose',
      fontFamily: 'var(--font-inter), -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    });
  }, []);

  useEffect(() => {
    if (!code || !containerRef.current) return;

    const renderDiagram = async () => {
      try {
        setError(null);
        const id = `mermaid-${Date.now()}`;
        const { svg: renderedSvg } = await mermaid.render(id, code);
        setSvg(renderedSvg);
        onSvgReady?.(true);
      } catch (err: any) {
        console.error('Mermaid rendering error:', err);
        setError(err.message || 'Failed to render diagram');
        setSvg('');
        onSvgReady?.(false);
      }
    };

    renderDiagram();
  }, [code, onSvgReady]);

  // Expose export functions to parent component
  useImperativeHandle(ref, () => ({
    exportSVG: handleExportSVG,
    exportPNG: handleExportPNG,
    hasSvg: () => !!svg,
  }));

  const handleExportSVG = () => {
    if (!svg) return;

    const blob = new Blob([svg], { type: 'image/svg+xml' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${projectSlug}-${versionSlug}-diagram.svg`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const handleExportPNG = async () => {
    if (!svg) return;

    try {
      // Create an image from the SVG using data URL to avoid CORS issues
      const img = new Image();

      // Ensure SVG has proper namespace and dimensions
      const parser = new DOMParser();
      const svgDoc = parser.parseFromString(svg, 'image/svg+xml');
      const svgElement = svgDoc.documentElement;

      // Get SVG dimensions
      const viewBox = svgElement.getAttribute('viewBox');
      let width = parseFloat(svgElement.getAttribute('width') || '800');
      let height = parseFloat(svgElement.getAttribute('height') || '600');

      // If viewBox exists but no width/height, extract from viewBox
      if (viewBox && (!svgElement.getAttribute('width') || !svgElement.getAttribute('height'))) {
        const [, , vbWidth, vbHeight] = viewBox.split(' ').map(Number);
        width = vbWidth || width;
        height = vbHeight || height;
        svgElement.setAttribute('width', width.toString());
        svgElement.setAttribute('height', height.toString());
      }

      // Serialize the SVG back to string
      const serializer = new XMLSerializer();
      const svgString = serializer.serializeToString(svgElement);

      // Convert SVG to data URL
      const svgDataUrl = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svgString);

      img.onload = () => {
        try {
          // Create a canvas and draw the image
          const canvas = document.createElement('canvas');
          const ctx = canvas.getContext('2d');

          // Set canvas size with some padding
          const padding = 40;
          canvas.width = width + padding;
          canvas.height = height + padding;

          if (ctx) {
            // Fill with white background
            ctx.fillStyle = 'white';
            ctx.fillRect(0, 0, canvas.width, canvas.height);

            // Draw the image centered with padding
            ctx.drawImage(img, padding / 2, padding / 2, width, height);

            // Convert to PNG and download
            canvas.toBlob((blob) => {
              if (blob) {
                const pngUrl = URL.createObjectURL(blob);
                const link = document.createElement('a');
                link.href = pngUrl;
                link.download = `${projectSlug}-${versionSlug}-diagram.png`;
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
                URL.revokeObjectURL(pngUrl);
              } else {
                console.error('Failed to create blob from canvas');
                alert('Failed to export PNG. Please try again or use SVG export.');
              }
            }, 'image/png');
          }
        } catch (err) {
          console.error('Canvas drawing error:', err);
          alert('Failed to export PNG. Please try SVG export instead.');
        }
      };

      img.onerror = (err) => {
        console.error('Image loading error:', err);
        alert('Failed to load diagram for PNG export. Please try SVG export instead.');
      };

      // Set cross-origin to anonymous (though not needed for data URLs)
      img.crossOrigin = 'anonymous';
      img.src = svgDataUrl;
    } catch (err) {
      console.error('PNG export error:', err);
      alert('Failed to export PNG. Please try SVG export instead.');
    }
  };

  if (error) {
    return (
      <div className="h-full flex items-center justify-center bg-gray-50 dark:bg-gray-900">
        <div className="text-center p-6 max-w-md">
          <AlertCircle className="h-12 w-12 text-red-500 mx-auto mb-4" />
          <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-2">
            Diagram Rendering Error
          </h3>
          <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
            {error}
          </p>
          <p className="text-xs text-gray-500 dark:text-gray-500">
            Please check your Mermaid syntax and try again
          </p>
        </div>
      </div>
    );
  }

  const handleZoomIn = () => {
    setZoom((prev) => Math.min(prev + 25, 400));
  };

  const handleZoomOut = () => {
    setZoom((prev) => Math.max(prev - 25, 25));
  };

  const handleResetZoom = () => {
    setZoom(100);
  };

  return (
    <div className="h-full flex flex-col bg-white dark:bg-gray-900 relative">
      {/* Zoom Controls */}
      <div className="absolute top-4 right-4 z-10 flex flex-col gap-2 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg shadow-lg p-2">
        <button
          onClick={handleZoomIn}
          disabled={zoom >= 400}
          className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center"
          title="Zoom In"
        >
          <ZoomIn size={16} className="text-gray-700 dark:text-gray-300" />
        </button>
        <div className="text-xs font-medium text-center text-gray-700 dark:text-gray-300 px-1">
          {zoom}%
        </div>
        <button
          onClick={handleZoomOut}
          disabled={zoom <= 25}
          className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center"
          title="Zoom Out"
        >
          <ZoomOut size={16} className="text-gray-700 dark:text-gray-300" />
        </button>
        <div className="border-t border-gray-300 dark:border-gray-600 my-1"></div>
        <button
          onClick={handleResetZoom}
          className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded transition-colors flex items-center justify-center"
          title="Reset Zoom (100%)"
        >
          <Maximize2 size={16} className="text-gray-700 dark:text-gray-300" />
        </button>
      </div>

      {/* Scrollable Diagram Container */}
      <div className="flex-1 overflow-auto">
        <div className="min-w-full min-h-full p-8 flex items-start justify-center">
          <div
            ref={containerRef}
            style={{
              transform: `scale(${zoom / 100})`,
              transformOrigin: 'top center',
              transition: 'transform 0.2s ease-out',
            }}
            dangerouslySetInnerHTML={{ __html: svg }}
          />
        </div>
      </div>
    </div>
  );
});

MermaidPreview.displayName = 'MermaidPreview';

export default MermaidPreview;

