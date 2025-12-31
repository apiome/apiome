'use client';

import { useEffect, useState } from 'react';
import { Button } from '../../../components/ui/Button';
import { Badge } from '../../../components/ui/Badge';
import {
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Link2,
  Palette,
  FileText,
  Download,
  Plus,
  Clock,
  ShieldCheck,
  ShieldX
} from 'lucide-react';
import { getImportStatus } from '../../../../../lib/db/import-actions';

interface ImportCompletePanelProps {
  jobId: string;
}

interface VerificationResult {
  passed: boolean;
  classesVerified: number;
  propertiesVerified: number;
  mismatches: Array<{
    type: string;
    className: string;
    propertyName?: string;
    message: string;
  }>;
}

interface ImportSummary {
  success: number;
  warnings: number;
  failed: number;
  properties: number;
  totalTime?: number;
  sourceName?: string;
  projectName?: string;
  versionId?: string;
  schemas?: Array<{
    name: string;
    status: 'success' | 'warning' | 'failed';
  }>;
  verification?: VerificationResult;
}

export default function ImportCompletePanel({ jobId }: ImportCompletePanelProps) {
  const [summary, setSummary] = useState<ImportSummary | null>(null);
  const [state, setState] = useState<'completed' | 'failed' | 'canceled' | string>('completed');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const status = await getImportStatus(jobId);
        setState(status.state);

        // Extract summary from status
        if (status.summary) {
          const rawSummary = status.summary as any;
          setSummary({
            success: rawSummary.classesCreated ?? 0,
            warnings: rawSummary.warnings ?? 0,
            failed: rawSummary.failed ?? 0,
            properties: rawSummary.propertiesCreated ?? 0,
            totalTime: rawSummary.totalTime,
            sourceName: rawSummary.sourceName,
            projectName: rawSummary.projectName,
            versionId: rawSummary.versionId,
            schemas: rawSummary.classes?.map((c: any) => ({
              name: c.name,
              status: c.status
            })) || [],
            verification: rawSummary.verification ? {
              passed: rawSummary.verification.passed,
              classesVerified: rawSummary.verification.classesVerified,
              propertiesVerified: rawSummary.verification.propertiesVerified,
              mismatches: rawSummary.verification.mismatches || []
            } : undefined
          });
        }
      } catch (e) {
        console.error('Error fetching import status:', e);
      } finally {
        setLoading(false);
      }
    };

    fetchStatus();
  }, [jobId]);

  const formatDuration = (ms?: number) => {
    if (!ms) return 'N/A';
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)} seconds`;
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600"></div>
      </div>
    );
  }

  const isSuccess = state === 'completed';
  const isFailed = state === 'failed';

  return (
    <div className="space-y-6">
      {/* Success/Failure Header */}
      <div className="flex flex-col items-center justify-center py-8">
        <div className={`w-20 h-20 rounded-full flex items-center justify-center mb-4 ${
          isSuccess 
            ? 'bg-green-100 dark:bg-green-900/30' 
            : isFailed 
            ? 'bg-red-100 dark:bg-red-900/30'
            : 'bg-yellow-100 dark:bg-yellow-900/30'
        }`}>
          {isSuccess ? (
            <CheckCircle2 className="h-10 w-10 text-green-600 dark:text-green-400" />
          ) : isFailed ? (
            <XCircle className="h-10 w-10 text-red-600 dark:text-red-400" />
          ) : (
            <AlertTriangle className="h-10 w-10 text-yellow-600 dark:text-yellow-400" />
          )}
        </div>
        <h2 className="text-2xl font-bold text-gray-900 dark:text-white">
          {isSuccess ? 'Import Complete!' : isFailed ? 'Import Failed' : 'Import Canceled'}
        </h2>
        {!isSuccess && (
          <p className="text-gray-600 dark:text-gray-400 mt-2">
            {isFailed
              ? 'There was an error during the import process.'
              : 'The import was canceled before completion.'}
          </p>
        )}
      </div>

      {/* Import Summary */}
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Import Summary</h3>

        {/* Stats Grid */}
        <div className="grid grid-cols-4 gap-4 mb-6">
          <div className="bg-green-50 dark:bg-green-900/20 rounded-lg p-4 text-center border border-green-200 dark:border-green-800">
            <div className="text-3xl font-bold text-green-600 dark:text-green-400">
              {summary?.success || 0}
            </div>
            <div className="text-sm text-green-700 dark:text-green-300 flex items-center justify-center gap-1 mt-1">
              <CheckCircle2 className="h-4 w-4" />
              Success
            </div>
          </div>
          <div className="bg-yellow-50 dark:bg-yellow-900/20 rounded-lg p-4 text-center border border-yellow-200 dark:border-yellow-800">
            <div className="text-3xl font-bold text-yellow-600 dark:text-yellow-400">
              {summary?.warnings || 0}
            </div>
            <div className="text-sm text-yellow-700 dark:text-yellow-300 flex items-center justify-center gap-1 mt-1">
              <AlertTriangle className="h-4 w-4" />
              Warning
            </div>
          </div>
          <div className="bg-red-50 dark:bg-red-900/20 rounded-lg p-4 text-center border border-red-200 dark:border-red-800">
            <div className="text-3xl font-bold text-red-600 dark:text-red-400">
              {summary?.failed || 0}
            </div>
            <div className="text-sm text-red-700 dark:text-red-300 flex items-center justify-center gap-1 mt-1">
              <XCircle className="h-4 w-4" />
              Failed
            </div>
          </div>
          <div className="bg-indigo-50 dark:bg-indigo-900/20 rounded-lg p-4 text-center border border-indigo-200 dark:border-indigo-800">
            <div className="text-3xl font-bold text-indigo-600 dark:text-indigo-400">
              {summary?.properties || 0}
            </div>
            <div className="text-sm text-indigo-700 dark:text-indigo-300 flex items-center justify-center gap-1 mt-1">
              <Link2 className="h-4 w-4" />
              Properties
            </div>
          </div>
        </div>

        {/* Verification Status */}
        {summary?.verification && (
          <div className={`rounded-lg p-4 mb-6 border ${
            summary.verification.passed 
              ? 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800'
              : 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800'
          }`}>
            <div className="flex items-center gap-3 mb-2">
              {summary.verification.passed ? (
                <ShieldCheck className="h-6 w-6 text-green-600 dark:text-green-400" />
              ) : (
                <ShieldX className="h-6 w-6 text-red-600 dark:text-red-400" />
              )}
              <div className={`font-semibold ${
                summary.verification.passed 
                  ? 'text-green-900 dark:text-green-200'
                  : 'text-red-900 dark:text-red-200'
              }`}>
                {summary.verification.passed ? 'Import Verification Passed' : 'Import Verification Failed'}
              </div>
            </div>
            <div className={`text-sm ${
              summary.verification.passed 
                ? 'text-green-700 dark:text-green-300'
                : 'text-red-700 dark:text-red-300'
            }`}>
              {summary.verification.passed ? (
                <span>
                  Successfully verified {summary.verification.classesVerified} classes and{' '}
                  {summary.verification.propertiesVerified} properties match the imported schema.
                </span>
              ) : (
                <div className="space-y-2">
                  <span>
                    Found {summary.verification.mismatches.length} mismatches during verification.
                  </span>
                  {summary.verification.mismatches.slice(0, 5).map((mismatch, idx) => (
                    <div key={idx} className="pl-4 border-l-2 border-red-300 dark:border-red-700 text-xs">
                      <div className="font-medium">{mismatch.className}{mismatch.propertyName ? `.${mismatch.propertyName}` : ''}</div>
                      <div className="text-red-600 dark:text-red-400">{mismatch.message}</div>
                    </div>
                  ))}
                  {summary.verification.mismatches.length > 5 && (
                    <div className="text-xs italic">
                      ...and {summary.verification.mismatches.length - 5} more
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Metadata */}
        <div className="space-y-2 text-sm text-gray-600 dark:text-gray-400">
          <div className="flex items-center gap-2">
            <span className="font-medium text-gray-700 dark:text-gray-300">Total time:</span>
            <span>{formatDuration(summary?.totalTime)}</span>
          </div>
          {summary?.sourceName && (
            <div className="flex items-center gap-2">
              <span className="font-medium text-gray-700 dark:text-gray-300">Source:</span>
              <span>{summary.sourceName}</span>
            </div>
          )}
          {(summary?.projectName || summary?.versionId) && (
            <div className="flex items-center gap-2">
              <span className="font-medium text-gray-700 dark:text-gray-300">Target:</span>
              <span>
                {summary.projectName || 'Project'} / {summary.versionId || 'Version'}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Imported Schemas */}
      {summary?.schemas && summary.schemas.length > 0 && (
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Imported Schemas</h3>
          <div className="flex flex-wrap gap-2">
            {summary.schemas.map((schema, index) => (
              <Badge
                key={index}
                variant={
                  schema.status === 'success' ? 'success' :
                  schema.status === 'warning' ? 'warning' :
                  'error'
                }
                className="flex items-center gap-1"
              >
                {schema.status === 'success' ? (
                  <CheckCircle2 className="h-3 w-3" />
                ) : schema.status === 'warning' ? (
                  <AlertTriangle className="h-3 w-3" />
                ) : (
                  <XCircle className="h-3 w-3" />
                )}
                {schema.name}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {/* Next Actions */}
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Next Actions</h3>
        <div className="text-center py-8 text-gray-500 dark:text-gray-400">
          <div className="flex flex-wrap justify-center gap-4 mb-4 opacity-50">
            <Button variant="outline" disabled className="flex items-center gap-2">
              <Palette className="h-4 w-4" />
              View on Canvas
            </Button>
            <Button variant="outline" disabled className="flex items-center gap-2">
              <FileText className="h-4 w-4" />
              Generate Docs
            </Button>
            <Button variant="outline" disabled className="flex items-center gap-2">
              <Download className="h-4 w-4" />
              Export Report
            </Button>
          </div>
          <div className="flex flex-wrap justify-center gap-4 opacity-50">
            <Button variant="outline" disabled className="flex items-center gap-2">
              <Plus className="h-4 w-4" />
              Import Another
            </Button>
            <Button variant="outline" disabled className="flex items-center gap-2">
              <Clock className="h-4 w-4" />
              Schedule Re-import
            </Button>
          </div>
          <p className="mt-6 text-sm italic">Coming soon</p>
        </div>
      </div>
    </div>
  );
}

