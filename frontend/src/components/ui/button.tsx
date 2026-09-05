import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "@/utils/cn";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost";
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "primary", disabled, ...props }, ref) => (
    <button
      ref={ref}
      disabled={disabled}
      className={cn(
        "inline-flex items-center justify-center rounded-(--radius-ledger) px-4 py-2 text-sm font-medium transition-colors",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--color-ledger-accent)",
        "disabled:pointer-events-none disabled:opacity-50",
        variant === "primary" &&
          "bg-(--color-ledger-accent) text-(--color-ledger-accent-fg) hover:opacity-90",
        variant === "ghost" && "hover:bg-(--color-ledger-border)/40",
        className,
      )}
      {...props}
    />
  ),
);
Button.displayName = "Button";
