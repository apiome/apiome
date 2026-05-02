import type { ActionContext, ActionDescribeResult, ActionDescriptor } from './types.js';

export class ActionRegistry {
  private static _instance: ActionRegistry | undefined;

  static instance(): ActionRegistry {
    ActionRegistry._instance ??= new ActionRegistry();
    return ActionRegistry._instance;
  }

  /** Keyword / category / resource filter over registered actions (Epic 3+). */
  search(_query: string, _ctx: ActionContext): ActionDescriptor[] {
    return [];
  }

  describe(_actionId: string, _ctx: ActionContext): ActionDescribeResult | null {
    return null;
  }

  /** Dispatch execution once actions land in `registry/actions/` (Epic 3+). */
  execute(_actionId: string, _args: Record<string, unknown>, _ctx: ActionContext): unknown {
    void _actionId;
    void _args;
    void _ctx;
    return { ok: false, message: 'No actions registered yet (registry bootstrap).' };
  }
}
