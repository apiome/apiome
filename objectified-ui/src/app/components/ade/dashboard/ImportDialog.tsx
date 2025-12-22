'use client';

import { useState } from 'react';
import { Upload, Link2, FileText, Github, Cloud, Package, X, FileCode } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '../../../components/ui/Dialog';
import { Button } from '../../../components/ui/Button';

interface ImportDialogProps {
  open: boolean;
  onClose: () => void;
  tenantId: string;
  userId: string;
}

interface RecentImport {
  filename: string;
  date: string;
}

const ImportDialog: React.FC<ImportDialogProps> = ({
  open,
  onClose,
  tenantId, // Will be used in future steps for project creation
  userId    // Will be used in future steps for tracking import activity
}) => {
  const [selectedSource, setSelectedSource] = useState<string | null>(null);
  const [recentImports] = useState<RecentImport[]>([
    { filename: 'petstore.yaml', date: '3 days ago' },
    { filename: 'user-service.json', date: '1 week ago' },
    { filename: 'payment-api.yaml', date: '2 weeks ago' },
  ]);

  const handleSourceClick = (source: string) => {
    setSelectedSource(source);
    // TODO: Navigate to next step based on source
    console.log('Selected source:', source);
  };

  const handleReImport = (filename: string) => {
    console.log('Re-importing:', filename);
    // TODO: Implement re-import functionality
  };

  const handleClose = () => {
    setSelectedSource(null);
    onClose();
  };

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="max-w-4xl max-h-[90vh] overflow-hidden flex flex-col">
        <DialogHeader className="border-b border-gray-200 dark:border-gray-700 pb-4">
          <div className="flex items-center justify-between">
            <DialogTitle className="text-2xl font-bold text-gray-900 dark:text-white">
              Import Specification
            </DialogTitle>
            <button
              onClick={handleClose}
              className="rounded-lg p-2 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
            >
              <X className="h-5 w-5 text-gray-500 dark:text-gray-400" />
            </button>
          </div>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto py-6 px-6">
          {/* Step Indicator */}
          <div className="mb-8">
            <div className="flex items-center justify-center gap-2 text-sm">
              <div className="flex items-center">
                <div className="flex items-center justify-center w-8 h-8 rounded-full bg-indigo-600 text-white font-semibold">
                  1
                </div>
                <span className="ml-2 font-medium text-gray-900 dark:text-white">Source</span>
              </div>
              <div className="w-16 h-0.5 bg-gray-300 dark:bg-gray-600"></div>
              <div className="flex items-center">
                <div className="flex items-center justify-center w-8 h-8 rounded-full bg-gray-200 dark:bg-gray-700 text-gray-500 dark:text-gray-400 font-semibold">
                  2
                </div>
                <span className="ml-2 text-gray-500 dark:text-gray-400">Analyze</span>
              </div>
              <div className="w-16 h-0.5 bg-gray-300 dark:bg-gray-600"></div>
              <div className="flex items-center">
                <div className="flex items-center justify-center w-8 h-8 rounded-full bg-gray-200 dark:bg-gray-700 text-gray-500 dark:text-gray-400 font-semibold">
                  3
                </div>
                <span className="ml-2 text-gray-500 dark:text-gray-400">Preview</span>
              </div>
              <div className="w-16 h-0.5 bg-gray-300 dark:bg-gray-600"></div>
              <div className="flex items-center">
                <div className="flex items-center justify-center w-8 h-8 rounded-full bg-gray-200 dark:bg-gray-700 text-gray-500 dark:text-gray-400 font-semibold">
                  4
                </div>
                <span className="ml-2 text-gray-500 dark:text-gray-400">Import</span>
              </div>
              <div className="w-16 h-0.5 bg-gray-300 dark:bg-gray-600"></div>
              <div className="flex items-center">
                <div className="flex items-center justify-center w-8 h-8 rounded-full bg-gray-200 dark:bg-gray-700 text-gray-500 dark:text-gray-400 font-semibold">
                  5
                </div>
                <span className="ml-2 text-gray-500 dark:text-gray-400">Done</span>
              </div>
            </div>
          </div>

          {/* Choose Import Source */}
          <div className="mb-8">
            <div className="bg-gradient-to-r from-indigo-50 to-purple-50 dark:from-indigo-950/30 dark:to-purple-950/30 rounded-xl border-2 border-indigo-200 dark:border-indigo-800 p-6">
              <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-6 text-center">
                Choose Import Source
              </h2>

              {/* Source Options Grid */}
              <div className="grid grid-cols-3 gap-4 mb-4">
                {/* File Upload */}
                <button
                  onClick={() => handleSourceClick('file')}
                  className={`group relative p-6 rounded-lg border-2 transition-all duration-200 ${
                    selectedSource === 'file'
                      ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/30 shadow-lg'
                      : 'border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 hover:border-indigo-300 dark:hover:border-indigo-700 hover:shadow-md'
                  }`}
                >
                  <div className="flex flex-col items-center text-center">
                    <div className={`w-12 h-12 rounded-xl flex items-center justify-center mb-3 transition-colors ${
                      selectedSource === 'file'
                        ? 'bg-indigo-500 text-white'
                        : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 group-hover:bg-indigo-100 dark:group-hover:bg-indigo-900/50 group-hover:text-indigo-600 dark:group-hover:text-indigo-400'
                    }`}>
                      <Upload className="h-6 w-6" />
                    </div>
                    <div className={`font-semibold mb-1 ${
                      selectedSource === 'file' ? 'text-indigo-700 dark:text-indigo-300' : 'text-gray-900 dark:text-white'
                    }`}>
                      File Upload
                    </div>
                    <div className="text-xs text-gray-600 dark:text-gray-400">
                      Drop files or click to browse
                    </div>
                  </div>
                </button>

                {/* URL Import */}
                <button
                  onClick={() => handleSourceClick('url')}
                  className={`group relative p-6 rounded-lg border-2 transition-all duration-200 ${
                    selectedSource === 'url'
                      ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/30 shadow-lg'
                      : 'border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 hover:border-indigo-300 dark:hover:border-indigo-700 hover:shadow-md'
                  }`}
                >
                  <div className="flex flex-col items-center text-center">
                    <div className={`w-12 h-12 rounded-xl flex items-center justify-center mb-3 transition-colors ${
                      selectedSource === 'url'
                        ? 'bg-indigo-500 text-white'
                        : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 group-hover:bg-indigo-100 dark:group-hover:bg-indigo-900/50 group-hover:text-indigo-600 dark:group-hover:text-indigo-400'
                    }`}>
                      <Link2 className="h-6 w-6" />
                    </div>
                    <div className={`font-semibold mb-1 ${
                      selectedSource === 'url' ? 'text-indigo-700 dark:text-indigo-300' : 'text-gray-900 dark:text-white'
                    }`}>
                      URL Import
                    </div>
                    <div className="text-xs text-gray-600 dark:text-gray-400">
                      Fetch from URL or repository
                    </div>
                  </div>
                </button>

                {/* Clipboard */}
                <button
                  onClick={() => handleSourceClick('clipboard')}
                  className={`group relative p-6 rounded-lg border-2 transition-all duration-200 ${
                    selectedSource === 'clipboard'
                      ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/30 shadow-lg'
                      : 'border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 hover:border-indigo-300 dark:hover:border-indigo-700 hover:shadow-md'
                  }`}
                >
                  <div className="flex flex-col items-center text-center">
                    <div className={`w-12 h-12 rounded-xl flex items-center justify-center mb-3 transition-colors ${
                      selectedSource === 'clipboard'
                        ? 'bg-indigo-500 text-white'
                        : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 group-hover:bg-indigo-100 dark:group-hover:bg-indigo-900/50 group-hover:text-indigo-600 dark:group-hover:text-indigo-400'
                    }`}>
                      <FileText className="h-6 w-6" />
                    </div>
                    <div className={`font-semibold mb-1 ${
                      selectedSource === 'clipboard' ? 'text-indigo-700 dark:text-indigo-300' : 'text-gray-900 dark:text-white'
                    }`}>
                      Clipboard Paste
                    </div>
                    <div className="text-xs text-gray-600 dark:text-gray-400">
                      Paste JSON or YAML content
                    </div>
                  </div>
                </button>

                {/* Git Repository */}
                <button
                  onClick={() => handleSourceClick('git')}
                  className={`group relative p-6 rounded-lg border-2 transition-all duration-200 ${
                    selectedSource === 'git'
                      ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/30 shadow-lg'
                      : 'border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 hover:border-indigo-300 dark:hover:border-indigo-700 hover:shadow-md'
                  }`}
                >
                  <div className="flex flex-col items-center text-center">
                    <div className={`w-12 h-12 rounded-xl flex items-center justify-center mb-3 transition-colors ${
                      selectedSource === 'git'
                        ? 'bg-indigo-500 text-white'
                        : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 group-hover:bg-indigo-100 dark:group-hover:bg-indigo-900/50 group-hover:text-indigo-600 dark:group-hover:text-indigo-400'
                    }`}>
                      <Github className="h-6 w-6" />
                    </div>
                    <div className={`font-semibold mb-1 ${
                      selectedSource === 'git' ? 'text-indigo-700 dark:text-indigo-300' : 'text-gray-900 dark:text-white'
                    }`}>
                      Git Repository
                    </div>
                    <div className="text-xs text-gray-600 dark:text-gray-400">
                      Clone from GitHub/GitLab
                    </div>
                  </div>
                </button>

                {/* SwaggerHub */}
                <button
                  onClick={() => handleSourceClick('swaggerhub')}
                  className={`group relative p-6 rounded-lg border-2 transition-all duration-200 ${
                    selectedSource === 'swaggerhub'
                      ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/30 shadow-lg'
                      : 'border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 hover:border-indigo-300 dark:hover:border-indigo-700 hover:shadow-md'
                  }`}
                >
                  <div className="flex flex-col items-center text-center">
                    <div className={`w-12 h-12 rounded-xl flex items-center justify-center mb-3 transition-colors ${
                      selectedSource === 'swaggerhub'
                        ? 'bg-indigo-500 text-white'
                        : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 group-hover:bg-indigo-100 dark:group-hover:bg-indigo-900/50 group-hover:text-indigo-600 dark:group-hover:text-indigo-400'
                    }`}>
                      <Cloud className="h-6 w-6" />
                    </div>
                    <div className={`font-semibold mb-1 ${
                      selectedSource === 'swaggerhub' ? 'text-indigo-700 dark:text-indigo-300' : 'text-gray-900 dark:text-white'
                    }`}>
                      SwaggerHub Integration
                    </div>
                    <div className="text-xs text-gray-600 dark:text-gray-400">
                      Import from SwaggerHub
                    </div>
                  </div>
                </button>

                {/* Registry Import */}
                <button
                  onClick={() => handleSourceClick('registry')}
                  className={`group relative p-6 rounded-lg border-2 transition-all duration-200 ${
                    selectedSource === 'registry'
                      ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/30 shadow-lg'
                      : 'border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 hover:border-indigo-300 dark:hover:border-indigo-700 hover:shadow-md'
                  }`}
                >
                  <div className="flex flex-col items-center text-center">
                    <div className={`w-12 h-12 rounded-xl flex items-center justify-center mb-3 transition-colors ${
                      selectedSource === 'registry'
                        ? 'bg-indigo-500 text-white'
                        : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 group-hover:bg-indigo-100 dark:group-hover:bg-indigo-900/50 group-hover:text-indigo-600 dark:group-hover:text-indigo-400'
                    }`}>
                      <Package className="h-6 w-6" />
                    </div>
                    <div className={`font-semibold mb-1 ${
                      selectedSource === 'registry' ? 'text-indigo-700 dark:text-indigo-300' : 'text-gray-900 dark:text-white'
                    }`}>
                      Registry Import
                    </div>
                    <div className="text-xs text-gray-600 dark:text-gray-400">
                      Import from schema registry
                    </div>
                  </div>
                </button>
              </div>
            </div>
          </div>

          {/* Recent Imports */}
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
              Recent Imports
            </h3>
            <div className="space-y-2">
              {recentImports.map((item, index) => (
                <div
                  key={index}
                  className="flex items-center justify-between p-3 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors"
                >
                  <div className="flex items-center gap-3">
                    <FileCode className="h-5 w-5 text-gray-400" />
                    <div>
                      <div className="text-sm font-medium text-gray-900 dark:text-white">
                        {item.filename}
                      </div>
                      <div className="text-xs text-gray-500 dark:text-gray-400">
                        {item.date}
                      </div>
                    </div>
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => handleReImport(item.filename)}
                  >
                    Re-import
                  </Button>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="border-t border-gray-200 dark:border-gray-700 px-6 py-4 flex items-center justify-between bg-gray-50 dark:bg-gray-800/50">
          <Button variant="outline" onClick={handleClose}>
            Cancel
          </Button>
          <Button
            onClick={() => {
              if (selectedSource) {
                // TODO: Navigate to next step
                console.log('Proceeding with:', selectedSource);
              }
            }}
            disabled={!selectedSource}
            className="bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700"
          >
            Next →
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default ImportDialog;

