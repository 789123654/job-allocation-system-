import * as RadixDropdownMenu from "@radix-ui/react-dropdown-menu";
import { cn } from "@/utils/cn";

export const DropdownMenu = RadixDropdownMenu.Root;
export const DropdownMenuTrigger = RadixDropdownMenu.Trigger;

export function DropdownMenuContent({
  className,
  ...props
}: RadixDropdownMenu.DropdownMenuContentProps) {
  return (
    <RadixDropdownMenu.Portal>
      <RadixDropdownMenu.Content
        align="end"
        sideOffset={4}
        className={cn(
          "min-w-40 rounded-(--radius-ledger) border border-(--color-ledger-border) bg-(--color-ledger-surface) p-1 shadow-md",
          className,
        )}
        {...props}
      />
    </RadixDropdownMenu.Portal>
  );
}

export function DropdownMenuItem({ className, ...props }: RadixDropdownMenu.DropdownMenuItemProps) {
  return (
    <RadixDropdownMenu.Item
      className={cn(
        "cursor-pointer rounded-(--radius-ledger) px-2 py-1.5 text-sm outline-none",
        "data-[highlighted]:bg-(--color-ledger-border)/40",
        className,
      )}
      {...props}
    />
  );
}
