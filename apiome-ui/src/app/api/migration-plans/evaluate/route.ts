import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/app/api/auth/[...nextauth]/route';
import { getTenantById } from '@lib/db/helper';
import { createRestAuthHeaders, REST_API_BASE_URL } from '@lib/rest-auth';

export const dynamic = 'force-dynamic';

/** Request body: record data and rules for the current class (from migration plan). */
interface EvaluateBody {
  recordData: Record<string, unknown>;
  rules: Record<string, { name?: string; inputProperties: string[]; ruleType: string; ruleContent: string; outputProperties: string[] }>;
}

type RuleEntry = { inputProperties: string[]; ruleType: string; ruleContent: string; outputProperties: string[] };

/**
 * Apply a single rule to input values (strings) and return output values.
 * Mirrors MigrationRuleDialog tryEvaluateRule; supports 'simple' and 'script' only (no SparkSQL in Node).
 */
function applyRule(
  rule: RuleEntry,
  inputValues: Record<string, string>
): { ok: true; outputs: unknown[] } | { ok: false; error: string } {
  const { ruleType, ruleContent, inputProperties, outputProperties } = rule;
  const orderedInputs = inputProperties.map((p) => inputValues[p] ?? '');

  if (ruleType === 'sparkSql') {
    return { ok: false, error: 'SparkSQL rules cannot be evaluated in this context.' };
  }

  try {
    if (ruleType === 'simple') {
      if (!ruleContent?.trim()) {
        return { ok: true, outputs: outputProperties.map(() => '') };
      }
      const fn = new Function(...inputProperties, `return (${ruleContent});`);
      const result = fn(...orderedInputs);
      if (outputProperties.length === 1) {
        const out = result === undefined ? '' : String(result);
        return { ok: true, outputs: [out] };
      }
      const arr = Array.isArray(result) ? result : [result];
      const outputs = outputProperties.map((_, i) => (arr[i] === undefined ? '' : String(arr[i])));
      return { ok: true, outputs };
    }

    if (ruleType === 'script') {
      if (!ruleContent?.trim()) {
        return { ok: true, outputs: outputProperties.map(() => '') };
      }
      const fn = new Function(...inputProperties, ruleContent);
      const result = fn(...orderedInputs);
      if (outputProperties.length === 1) {
        const out = result === undefined ? '' : String(result);
        return { ok: true, outputs: [out] };
      }
      const arr = Array.isArray(result)
        ? result
        : result && typeof result === 'object' && outputProperties.every((p) => p in (result as object))
          ? outputProperties.map((p) => (result as Record<string, unknown>)[p])
          : [result];
      const outputs = outputProperties.map((_, i) => (arr[i] === undefined ? '' : String(arr[i])));
      return { ok: true, outputs };
    }

    return { ok: false, error: 'Unknown rule type.' };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return { ok: false, error: message };
  }
}

/**
 * Apply all migration rules to a record. Starts from a copy of the record; each rule reads from
 * the current state (so rules can chain) and writes to output properties.
 */
function applyRulesToRecord(
  recordData: Record<string, unknown>,
  rules: Record<string, RuleEntry>
): { transformedData: Record<string, unknown>; rulesAppliedCount: number; error?: string } {
  const transformedData = JSON.parse(JSON.stringify(recordData)) as Record<string, unknown>;
  let rulesAppliedCount = 0;

  const toStr = (v: unknown): string => (v === undefined || v === null ? '' : String(v));

  for (const rule of Object.values(rules)) {
    if (!rule || typeof rule !== 'object' || !rule.inputProperties || !rule.outputProperties) continue;
    const hasContent = typeof rule.ruleContent === 'string' && rule.ruleContent.trim().length > 0;
    const inputValues: Record<string, string> = {};
    for (const p of rule.inputProperties) {
      inputValues[p] = toStr(transformedData[p]);
    }
    if (hasContent) {
      const result = applyRule(rule, inputValues);
      if (!result.ok) {
        return { transformedData, rulesAppliedCount, error: result.error };
      }
      result.outputs.forEach((val, i) => {
        const key = rule.outputProperties[i];
        if (key !== undefined) {
          transformedData[key] = val;
        }
      });
      rulesAppliedCount += 1;
    }
  }

  return { transformedData, rulesAppliedCount };
}

/**
 * Apply migration rules to a record and return transformed data.
 * Uses backend evaluate endpoint when available; otherwise applies rules in this route.
 */
export async function POST(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
    }
    const tenantId = (session.user as { current_tenant_id?: string }).current_tenant_id;
    if (!tenantId) {
      return NextResponse.json({ success: false, error: 'No tenant selected' }, { status: 400 });
    }

    let body: EvaluateBody;
    try {
      body = await request.json();
    } catch {
      return NextResponse.json({ success: false, error: 'Invalid JSON body' }, { status: 400 });
    }
    const { recordData, rules } = body;
    if (recordData === undefined || typeof recordData !== 'object' || recordData === null) {
      return NextResponse.json({ success: false, error: 'recordData is required and must be an object' }, { status: 400 });
    }
    if (rules === undefined || typeof rules !== 'object' || rules === null) {
      return NextResponse.json({ success: false, error: 'rules is required and must be an object' }, { status: 400 });
    }

    const tenant = await getTenantById(tenantId);
    if (!tenant?.slug) {
      return NextResponse.json({ success: false, error: 'Tenant slug not found' }, { status: 400 });
    }

    // Count rules that have actual transformation content (non-passthrough)
    const rulesAppliedCount = Object.values(rules).filter(
      (r) => r && typeof r === 'object' && (r.ruleContent?.trim?.()?.length ?? 0) > 0
    ).length;

    // Try backend evaluate endpoint if available; otherwise passthrough
    const evaluateUrl = `${REST_API_BASE_URL}/migration-plans/${encodeURIComponent(tenant.slug)}/evaluate`;
    const res = await fetch(evaluateUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...createRestAuthHeaders(session.user as { user_id?: string; email?: string | null; name?: string | null; current_tenant_id?: string }),
      },
      body: JSON.stringify({ record_data: recordData, rules }),
    }).catch(() => null);

    let transformedData: Record<string, unknown>;
    let rulesAppliedCountOut = rulesAppliedCount;
    let applyError: string | undefined;

    if (res?.ok) {
      const data = await res.json().catch(() => ({}));
      transformedData = data.transformed_data ?? data.transformedData ?? recordData;
      if (typeof data.rules_applied_count === 'number') rulesAppliedCountOut = data.rules_applied_count;
    } else {
      const applied = applyRulesToRecord(recordData, rules);
      transformedData = applied.transformedData;
      rulesAppliedCountOut = applied.rulesAppliedCount;
      applyError = applied.error;
    }

    return NextResponse.json({
      success: applyError ? false : true,
      ...(applyError && { error: applyError }),
      transformedData,
      rulesAppliedCount: rulesAppliedCountOut,
    });
  } catch (error) {
    console.error('Error evaluating migration rules:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
