import * as React from "react"
import { cn } from "@/lib/utils"

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "destructive" | "outline" | "secondary" | "ghost" | "link"
  size?: "default" | "sm" | "lg" | "icon"
  asChild?: boolean
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", size = "default", asChild = false, ...props }, ref) => {
    const Comp = asChild ? 'span' : 'button';
    return (
      <Comp
        className={cn(
          "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-xl text-sm font-semibold tracking-wide transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[rgb(var(--color-ring))] focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 shadow-sm",
          {
            "bg-[rgb(var(--color-primary))] text-[rgb(var(--color-primary-foreground))] hover:brightness-110 hover:-translate-y-0.5 active:translate-y-0":
              variant === "default",
            "bg-[rgb(var(--color-destructive))] text-[rgb(var(--color-destructive-foreground))] hover:brightness-110":
              variant === "destructive",
            "border border-[rgb(var(--color-border))] bg-[rgb(var(--color-card))]/75 backdrop-blur-sm text-[rgb(var(--color-foreground))] hover:bg-[rgb(var(--color-muted))]":
              variant === "outline",
            "bg-[rgb(var(--color-secondary))] text-[rgb(var(--color-secondary-foreground))] hover:brightness-110":
              variant === "secondary",
            "text-[rgb(var(--color-foreground))] hover:bg-[rgb(var(--color-muted))] hover:text-[rgb(var(--color-primary))] shadow-none": variant === "ghost",
            "text-[rgb(var(--color-primary))] underline-offset-4 hover:underline shadow-none": variant === "link",
          },
          {
            "h-10 px-4 py-2": size === "default",
            "h-9 rounded-lg px-3 text-xs": size === "sm",
            "h-11 rounded-xl px-8": size === "lg",
            "h-10 w-10 rounded-xl": size === "icon",
          },
          className
        )}
        ref={ref as any}
        {...props}
      />
    )
  }
)
Button.displayName = "Button"

export { Button }
