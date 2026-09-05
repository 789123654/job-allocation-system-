import { forwardRef, type LabelHTMLAttributes } from "react";
import { cn } from "@/utils/cn";

export const Label = forwardRef<HTMLLabelElement, LabelHTMLAttributes<HTMLLabelElement>>(
  ({ className, ...props }, ref) => (
    <label
      ref={ref}
      className={cn("mb-1 block text-sm font-medium text-(--color-ledger-text)", className)}
      {...props}
    />
  ),
);
Label.displayName = "Label";
