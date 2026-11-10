'use client';

/**
 * The §Overlays layering specimen of the gallery (SUX-1.1, apiome#6748).
 *
 * The worst case the stacking scale has to survive, as one click path: a drawer, a dialog
 * opened from inside it, and a select opened inside that dialog. Each one portals to
 * `<body>`, so only the `--z-*` steps decide who is on top — the drawer and dialog on
 * `modal`, their scrims on `overlay`, the listbox on `popover`. `e2e/hive-z-index-scale.spec.ts`
 * walks this path and checks the listbox is the topmost element where it is drawn.
 */

import * as React from 'react';

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  Drawer,
  DrawerBody,
  DrawerContent,
  DrawerDescription,
  DrawerHeader,
  DrawerTitle,
  DrawerTrigger,
  FormField,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/app/components/ui';

/**
 * A drawer that opens a dialog that holds a select.
 *
 * @returns The trigger button; the drawer, dialog and listbox mount in portals on demand.
 */
export function LayeringShowcase() {
  const [dialogOpen, setDialogOpen] = React.useState(false);

  return (
    <Drawer>
      <DrawerTrigger asChild>
        <Button variant="outline">Open layered drawer</Button>
      </DrawerTrigger>
      <DrawerContent>
        <DrawerHeader>
          <DrawerTitle>Layering</DrawerTitle>
          <DrawerDescription>A dialog opened from a drawer, with a select inside it.</DrawerDescription>
        </DrawerHeader>
        <DrawerBody>
          <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
            <DialogTrigger asChild>
              <Button variant="primary">Open dialog in drawer</Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Move to domain</DialogTitle>
                <DialogDescription>The list opens above this dialog and the drawer under it.</DialogDescription>
              </DialogHeader>
              <FormField label="Domain" htmlFor="ds-layering-domain">
                <Select>
                  <SelectTrigger id="ds-layering-domain" aria-label="Domain">
                    <SelectValue placeholder="None" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="finance">Finance</SelectItem>
                    <SelectItem value="logistics">Logistics</SelectItem>
                    <SelectItem value="identity">Identity</SelectItem>
                  </SelectContent>
                </Select>
              </FormField>
              <DialogFooter>
                <Button variant="outline" onClick={() => setDialogOpen(false)}>
                  Done
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </DrawerBody>
      </DrawerContent>
    </Drawer>
  );
}
