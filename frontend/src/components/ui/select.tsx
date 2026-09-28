import * as RadixSelect from "@radix-ui/react-select";
import { useDialogContentContainer } from "@/components/ui/dialog";
import { cn } from "@/utils/cn";

// Real Radix Select subcomponent API verified against the installed package's own type
// declarations (node_modules/@radix-ui/react-select/dist/index.d.mts) before writing this file —
// not assumed from memory, since no installed skill documents Radix Select specifically (only
// tauri-official/react-official are installed, neither covers this library).
export const Select = RadixSelect.Root;
export const SelectValue = RadixSelect.Value;
export const SelectGroup = RadixSelect.Group;

export function SelectTrigger({ className, children, ...props }: RadixSelect.SelectTriggerProps) {
  return (
    <RadixSelect.Trigger
      className={cn(
        "flex w-full items-center justify-between rounded-(--radius-ledger) border border-(--color-ledger-border) bg-(--color-ledger-surface) px-3 py-2 text-sm",
        "focus-visible:outline-none",
        "data-[placeholder]:text-(--color-ledger-text-muted)",
        className,
      )}
      {...props}
    >
      {children}
      <RadixSelect.Icon className="ml-2 text-(--color-ledger-text-muted)">▾</RadixSelect.Icon>
    </RadixSelect.Trigger>
  );
}

export function SelectContent({ className, children, ...props }: RadixSelect.SelectContentProps) {
  // Real fix, 2026-09-17 (see the long comment on DialogContentContainerContext in dialog.tsx for
  // the full chain of evidence: z-index and a CSS `!important` pointer-events override were both
  // tried and neither reliably worked, because two nested @radix-ui/react-dismissable-layer
  // instances — this Select's dropdown and the enclosing modal Dialog — weren't reliably agreeing
  // on which one gets `pointer-events: auto`). When rendered inside a DialogContent, portal into
  // that DialogContent's own DOM node instead of the default document.body — a genuine descendant
  // never needs a competing dismissable-layer stack against its ancestor Dialog in the first
  // place. Outside any Dialog (e.g. owner-dashboard-page.tsx's filter Selects), the hook returns
  // null and RadixSelect.Portal falls back to its own default (document.body), unchanged.
  const dialogContainer = useDialogContentContainer();
  return (
    <RadixSelect.Portal container={dialogContainer ?? undefined}>
      <RadixSelect.Content
        className={cn(
          // z-50 kept as cheap defense-in-depth for the document.body fallback case (no enclosing
          // Dialog) — not load-bearing for the Dialog case anymore now that it portals inside.
          "z-50 overflow-hidden rounded-(--radius-ledger) border border-(--color-ledger-border) bg-(--color-ledger-surface) shadow-md",
          className,
        )}
        {...props}
      >
        <RadixSelect.Viewport className="p-1">{children}</RadixSelect.Viewport>
      </RadixSelect.Content>
    </RadixSelect.Portal>
  );
}

export function SelectItem({ className, children, ...props }: RadixSelect.SelectItemProps) {
  return (
    <RadixSelect.Item
      className={cn(
        "cursor-pointer rounded-(--radius-ledger) px-2 py-1.5 text-sm outline-none",
        "data-[highlighted]:bg-(--color-ledger-border) data-[highlighted]:outline-none",
        className,
      )}
      {...props}
    >
      <RadixSelect.ItemText>{children}</RadixSelect.ItemText>
    </RadixSelect.Item>
  );
}
