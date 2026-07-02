'use client';

import * as React from 'react';

export type OpenRuleDialogFn = (edgeId: string, sourceProp: string, targetProp: string) => void;

export const OpenRuleDialogContext = React.createContext<OpenRuleDialogFn | null>(null);

export function useOpenRuleDialog(): OpenRuleDialogFn | null {
  return React.useContext(OpenRuleDialogContext);
}
