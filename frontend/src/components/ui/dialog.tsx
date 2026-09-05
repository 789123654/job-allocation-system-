import * as RadixDialog from "@radix-ui/react-dialog";
import { cn } from "@/utils/cn";

export const Dialog = RadixDialog.Root;
export const DialogTrigger = RadixDialog.Trigger;
export const DialogClose = RadixDialog.Close;

export function DialogContent({ className, children }: RadixDialog.DialogContentProps) {
  return (
    <RadixDialog.Portal>
      <RadixDialog.Overlay className="fixed inset-0 bg-black/40" />
      <RadixDialog.Content
        className={cn(
          "fixed top-1/2 left-1/2 w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-(--radius-ledger) border border-(--color-ledger-border) bg-(--color-ledger-surface) p-6",
          "focus-visible:outline-none",
          className,
        )}
      >
        {children}
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
