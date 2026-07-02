import { cn } from "@/lib/utils";
import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

const buttonVariants = cva(
  "relative inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-xl text-sm font-medium transition-all duration-300 ease-[cubic-bezier(0.22,1,0.36,1)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none disabled:opacity-50 overflow-hidden isolate",
  {
    variants: {
      variant: {
        default:
          "bg-gradient-to-br from-blue-600 to-indigo-600 text-white shadow-[0_6px_20px_-8px_rgba(37,99,235,0.55)] hover:shadow-[0_10px_28px_-8px_rgba(79,70,229,0.55)] hover:-translate-y-0.5 shine-on-hover",
        solid:
          "bg-blue-600 text-white hover:bg-blue-700 dark:bg-blue-600 dark:hover:bg-blue-700",
        destructive:
          "bg-red-600 text-white hover:bg-red-700 dark:bg-red-600 dark:hover:bg-red-700 shadow-[0_6px_20px_-8px_rgba(220,38,38,0.55)]",
        outline:
          "border border-zinc-300/80 bg-white/60 backdrop-blur text-zinc-900 hover:border-zinc-400 hover:bg-white dark:border-zinc-700/80 dark:bg-zinc-950/40 dark:text-zinc-100 dark:hover:border-zinc-600 dark:hover:bg-zinc-900",
        secondary:
          "bg-zinc-100 text-zinc-900 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-50 dark:hover:bg-zinc-700",
        ghost:
          "hover:bg-zinc-100 dark:hover:bg-zinc-800",
        "ghost-glass":
          "bg-white/5 text-current ring-1 ring-inset ring-white/15 hover:bg-white/10 backdrop-blur",
        link:
          "text-blue-600 underline-offset-4 hover:underline dark:text-blue-400",
      },
      size: {
        default: "h-10 px-5 py-2",
        sm: "h-9 px-3.5 text-xs",
        lg: "h-12 px-7 text-base",
        icon: "h-10 w-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => {
    return (
      <button
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    );
  }
);
Button.displayName = "Button";

export { Button, buttonVariants };
