/**
 * Example: Complete Radix UI conversion of a form section
 * This shows the pattern to follow for converting PropertyFormFields
 */

import React from 'react';
import { cn } from '../../../../../lib/utils';
import { Input } from '../../ui/Input';
import { Textarea } from '../../ui/Textarea';
import { Checkbox } from '../../ui/Checkbox';
import { Label } from '../../ui/Label';
import { RadioGroup, RadioGroupItem } from '../../ui/RadioGroup';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '../../ui/Tooltip';
import { Collapsible, CollapsibleContent } from '../../ui/Collapsible';
import { FormField } from '../../ui/FormField';
import { Info, Settings, Plus, Trash2 } from 'lucide-react';

// Custom hook for dark mode
const useDarkMode = () => {
  const [isDark, setIsDark] = React.useState(false);

  React.useEffect(() => {
    const checkDarkMode = () => {
      setIsDark(document.documentElement.classList.contains('dark'));
    };

    checkDarkMode();

    const observer = new MutationObserver(checkDarkMode);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class'],
    });

    return () => observer.disconnect();
  }, []);

  return isDark;
};

interface SectionHeaderProps {
  icon: React.ReactNode;
  title: string;
  subtitle?: string;
  badge?: string;
}

const SectionHeader: React.FC<SectionHeaderProps> = ({ icon, title, subtitle, badge }) => {
  const isDark = useDarkMode();

  return (
    <div className="flex items-center gap-3 mb-5 pb-3 border-b border-indigo-600/10">
      <div className="p-2 rounded-xl bg-indigo-600/10 flex items-center justify-center">
        {icon}
      </div>
      <div className="flex-1">
        <h3 className={cn(
          'text-base font-semibold tracking-tight',
          isDark ? 'text-gray-100' : 'text-gray-900'
        )}>
          {title}
        </h3>
        {subtitle && (
          <p className={cn(
            'text-xs',
            isDark ? 'text-gray-400' : 'text-gray-600'
          )}>
            {subtitle}
          </p>
        )}
      </div>
      {badge && (
        <span className={cn(
          'px-3 py-1 rounded-lg text-xs font-semibold uppercase tracking-wider',
          isDark
            ? 'bg-gradient-to-br from-indigo-900 to-indigo-800 text-indigo-200'
            : 'bg-gradient-to-br from-indigo-50 to-indigo-100 text-indigo-700'
        )}>
          {badge}
        </span>
      )}
    </div>
  );
};

interface ExampleFormData {
  title?: string;
  description?: string;
  required?: boolean;
  nullable?: boolean;
  readOnly?: boolean;
  deprecated?: boolean;
  deprecationMessage?: string;
  additionalProperties?: 'default' | 'true' | 'false';
}

interface ExampleFormProps {
  data: ExampleFormData;
  onChange: (field: keyof ExampleFormData, value: any) => void;
}

/**
 * Example form section showing proper Radix UI conversion
 */
export const ExampleFormSection: React.FC<ExampleFormProps> = ({ data, onChange }) => {
  const isDark = useDarkMode();

  return (
    <div className={cn(
      'flex flex-col gap-0 min-h-full',
      isDark ? 'bg-gray-900' : 'bg-gray-50'
    )}>
      {/* SECTION 1: Basic Information */}
      <div className={cn(
        'p-6 border-b',
        isDark ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
      )}>
        <SectionHeader
          icon={<Info className="text-indigo-600" size={18} />}
          title="Basic Information"
          subtitle="Core property details"
        />

        <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
          <FormField label="Title" helperText="Display title">
            <Input
              value={data.title || ''}
              onChange={(e) => onChange('title', e.target.value)}
              className="rounded-lg"
            />
          </FormField>

          <FormField
            label="Description"
            helperText="What this property represents"
            className="md:col-span-2"
          >
            <Textarea
              rows={2}
              value={data.description || ''}
              onChange={(e) => onChange('description', e.target.value)}
              className="rounded-lg"
            />
          </FormField>
        </div>
      </div>

      {/* SECTION 2: Property Behavior (Metadata flags) */}
      <div className={cn(
        'p-6 border-b',
        isDark
          ? 'bg-gradient-to-br from-gray-800 to-gray-900 border-gray-700'
          : 'bg-gradient-to-br from-gray-50 to-gray-100 border-gray-200'
      )}>
        <SectionHeader
          icon={<Settings className="text-indigo-600" size={18} />}
          title="Property Behavior"
          subtitle="Access and visibility controls"
        />

        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4">
          {/* Required */}
          <div
            className={cn(
              'p-4 rounded-2xl border transition-all duration-200 cursor-pointer',
              'hover:-translate-y-0.5',
              data.required
                ? 'bg-red-50 dark:bg-red-950/30 border-red-300 dark:border-red-800 shadow-lg shadow-red-500/20'
                : 'bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-700 shadow-sm hover:shadow-md'
            )}
            onClick={() => onChange('required', !data.required)}
          >
            <div className="flex items-start gap-3">
              <Checkbox
                checked={data.required || false}
                onCheckedChange={(checked) => onChange('required', checked)}
                className={cn(data.required && 'data-[state=checked]:bg-red-600 data-[state=checked]:border-red-600')}
              />
              <div>
                <p className={cn(
                  'text-sm font-semibold',
                  data.required ? 'text-red-700 dark:text-red-400' : 'text-gray-700 dark:text-gray-300'
                )}>
                  Required
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                  Must be provided
                </p>
              </div>
            </div>
          </div>

          {/* Nullable */}
          <div
            className={cn(
              'p-4 rounded-2xl border transition-all duration-200 cursor-pointer',
              'hover:-translate-y-0.5',
              data.nullable
                ? 'bg-purple-50 dark:bg-purple-950/30 border-purple-300 dark:border-purple-800 shadow-lg shadow-purple-500/20'
                : 'bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-700 shadow-sm hover:shadow-md'
            )}
            onClick={() => onChange('nullable', !data.nullable)}
          >
            <div className="flex items-start gap-3">
              <Checkbox
                checked={data.nullable || false}
                onCheckedChange={(checked) => onChange('nullable', checked)}
                className={cn(data.nullable && 'data-[state=checked]:bg-purple-600 data-[state=checked]:border-purple-600')}
              />
              <div>
                <p className={cn(
                  'text-sm font-semibold',
                  data.nullable ? 'text-purple-700 dark:text-purple-400' : 'text-gray-700 dark:text-gray-300'
                )}>
                  Nullable
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                  Can be null
                </p>
              </div>
            </div>
          </div>

          {/* Read Only */}
          <div
            className={cn(
              'p-4 rounded-2xl border transition-all duration-200 cursor-pointer',
              'hover:-translate-y-0.5',
              data.readOnly
                ? 'bg-blue-50 dark:bg-blue-950/30 border-blue-300 dark:border-blue-800 shadow-lg shadow-blue-500/20'
                : 'bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-700 shadow-sm hover:shadow-md'
            )}
            onClick={() => onChange('readOnly', !data.readOnly)}
          >
            <div className="flex items-start gap-3">
              <Checkbox
                checked={data.readOnly || false}
                onCheckedChange={(checked) => onChange('readOnly', checked)}
                className={cn(data.readOnly && 'data-[state=checked]:bg-blue-600 data-[state=checked]:border-blue-600')}
              />
              <div>
                <p className={cn(
                  'text-sm font-semibold',
                  data.readOnly ? 'text-blue-700 dark:text-blue-400' : 'text-gray-700 dark:text-gray-300'
                )}>
                  Read Only
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                  Output only
                </p>
              </div>
            </div>
          </div>

          {/* Deprecated */}
          <div
            className={cn(
              'p-4 rounded-2xl border transition-all duration-200 cursor-pointer',
              'hover:-translate-y-0.5',
              data.deprecated
                ? 'bg-amber-50 dark:bg-amber-950/30 border-amber-300 dark:border-amber-800 shadow-lg shadow-amber-500/20'
                : 'bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-700 shadow-sm hover:shadow-md'
            )}
            onClick={() => onChange('deprecated', !data.deprecated)}
          >
            <div className="flex items-start gap-3">
              <Checkbox
                checked={data.deprecated || false}
                onCheckedChange={(checked) => onChange('deprecated', checked)}
                className={cn(data.deprecated && 'data-[state=checked]:bg-amber-600 data-[state=checked]:border-amber-600')}
              />
              <div>
                <p className={cn(
                  'text-sm font-semibold',
                  data.deprecated ? 'text-amber-700 dark:text-amber-400' : 'text-gray-700 dark:text-gray-300'
                )}>
                  Deprecated
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                  Avoid using
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Deprecation Message - Collapsible */}
        <Collapsible open={data.deprecated} className="mt-5">
          <CollapsibleContent className="transition-all duration-300 data-[state=open]:animate-in data-[state=closed]:animate-out">
            <FormField
              label="Deprecation Message"
              className={cn(
                'p-4 rounded-lg border',
                isDark ? 'bg-gray-900 border-amber-800/30' : 'bg-white border-amber-300'
              )}
            >
              <Textarea
                rows={2}
                value={data.deprecationMessage || ''}
                onChange={(e) => onChange('deprecationMessage', e.target.value)}
                placeholder="e.g., Use newProperty instead. Will be removed in v2.0."
                className="border-amber-300/30"
              />
            </FormField>
          </CollapsibleContent>
        </Collapsible>
      </div>

      {/* SECTION 3: Radio Group Example */}
      <div className={cn(
        'p-6',
        isDark ? 'bg-gray-800' : 'bg-white'
      )}>
        <SectionHeader
          icon={<Settings className="text-indigo-600" size={18} />}
          title="Additional Properties"
          subtitle="Control for object properties"
        />

        <FormField label="Additional Properties">
          <RadioGroup
            value={data.additionalProperties || 'default'}
            onValueChange={(value) => onChange('additionalProperties', value as any)}
          >
            <RadioGroupItem value="default" label="Default (allows additional)" />
            <RadioGroupItem value="true" label="Allow additional properties" />
            <RadioGroupItem value="false" label="Strict (no extra properties)" />
          </RadioGroup>
        </FormField>
      </div>
    </div>
  );
};

export default ExampleFormSection;

