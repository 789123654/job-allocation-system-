import { forwardRef, type InputHTMLAttributes } from "react";
import { cn } from "@/utils/cn";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "w-full rounded-(--radius-ledger) border border-(--color-ledger-border) bg-(--color-ledger-surface) px-3 py-2 text-sm",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--color-ledger-accent)",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";
