import * as RadixSelect from "@radix-ui/react-select";
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
  return (
    <RadixSelect.Portal>
      <RadixSelect.Content
        className={cn(
          "overflow-hidden rounded-(--radius-ledger) border border-(--color-ledger-border) bg-(--color-ledger-surface) shadow-md",
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
