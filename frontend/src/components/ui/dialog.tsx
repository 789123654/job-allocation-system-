import * as RadixDialog from "@radix-ui/react-dialog";
import { createContext, useContext, useState } from "react";
import { cn } from "@/utils/cn";

export const Dialog = RadixDialog.Root;
export const DialogTrigger = RadixDialog.Trigger;
export const DialogClose = RadixDialog.Close;

// Real bug, 2026-09-16/17 — a Select (components/ui/select.tsx) opened inside a Dialog renders
// its dropdown in its OWN Portal, a DOM sibling of the Dialog's Portal under document.body, not a
// descendant of DialogContent, even though it appears "inside" the dialog visually. Two separate,
// confirmed-via-live-evidence consequences of that sibling relationship, both chased and patched
// individually before this fix replaced them:
// 1. Radix Dialog's own outside-click detection could misclassify a click on the Select's dropdown
//    as "outside" the Dialog and dismiss it (patched via onPointerDownOutside below, now moot).
// 2. Nested @radix-ui/react-dismissable-layer instances (Dialog's own modal layer + the Select's
//    dropdown layer) each compute their own `pointer-events: auto | none` from a shared layer-index
//    Set — confirmed via a live `getComputedStyle(...).pointerEvents` dump in the real app that
//    this computation was NOT reliably granting the Select's own layer "auto" at click time, so
//    clicks silently fell through to the Dialog's Overlay underneath. Neither z-index nor a CSS
//    `!important` pointer-events override fixed this reliably (both tried, both left real evidence
//    of clicks still landing on the Overlay).
// The actual fix: give the Select somewhere else to portal to. Passing DialogContent's own DOM
// node as the Select's Portal `container` (via this context) makes the dropdown a genuine
// *descendant* of DialogContent instead of a sibling portal — eliminating both problems at the
// source instead of patching their symptoms, since a descendant can never be "outside" its own
// ancestor for outside-click purposes, and never needs a separate pointer-events-disabled layer
// stacked against the Dialog's.
const DialogContentContainerContext = createContext<HTMLDivElement | null>(null);
export function useDialogContentContainer() {
  return useContext(DialogContentContainerContext);
}

export function DialogContent({ className, children }: RadixDialog.DialogContentProps) {
  const [container, setContainer] = useState<HTMLDivElement | null>(null);
  return (
    <RadixDialog.Portal>
      <RadixDialog.Overlay className="fixed inset-0 bg-black/40" />
      <RadixDialog.Content
        ref={setContainer}
        className={cn(
          "fixed top-1/2 left-1/2 w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-(--radius-ledger) border border-(--color-ledger-border) bg-(--color-ledger-surface) p-6",
          "focus-visible:outline-none",
          className,
        )}
        onPointerDownOutside={(event) => {
          // Kept as defense-in-depth for any future popper-based child that doesn't use
          // useDialogContentContainer (e.g. a Popover added later without this wiring) — not load-
          // bearing for Select anymore now that it portals inside DialogContent directly.
          const target = event.target as HTMLElement | null;
          const insidePopper = !!target?.closest("[data-radix-popper-content-wrapper]");
          if (insidePopper) {
            event.preventDefault();
          }
        }}
      >
        <DialogContentContainerContext.Provider value={container}>
          {children}
        </DialogContentContainerContext.Provider>
      </RadixDialog.Content>
    </RadixDialog.Portal>
  );
}

export function DialogTitle({ className, ...props }: RadixDialog.DialogTitleProps) {
  return (
    <RadixDialog.Title
      className={cn("mb-4 text-lg font-semibold text-(--color-ledger-text)", className)}
      {...props}
    />
  );
}
