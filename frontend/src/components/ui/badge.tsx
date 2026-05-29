import * as React from "react"
import { cn } from "@/lib/utils"

export interface BadgeProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: "default" | "secondary" | "destructive" | "outline"
}

function Badge({ className, variant = "default", ...props }: BadgeProps) {
  return (
    <div
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-bold uppercase tracking-wide transition-colors focus:outline-none focus:ring-2 focus:ring-[rgb(var(--color-ring))] focus:ring-offset-2",
        {
          "border-transparent bg-[rgb(var(--color-primary))] text-[rgb(var(--color-primary-foreground))] hover:brightness-110":
            variant === "default",
          "border-transparent bg-[rgb(var(--color-secondary))] text-[rgb(var(--color-secondary-foreground))] hover:brightness-110":
            variant === "secondary",
          "border-transparent bg-[rgb(var(--color-destructive))] text-[rgb(var(--color-destructive-foreground))] hover:brightness-110":
            variant === "destructive",
          "border-[rgb(var(--color-border))] text-[rgb(var(--color-foreground))] bg-[rgb(var(--color-card))]/70": variant === "outline",
        },
        className
      )}
      {...props}
    />
  )
}

export { Badge }
