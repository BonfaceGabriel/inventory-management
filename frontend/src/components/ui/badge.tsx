import * as React from "react"
import { cn } from "@/lib/utils"

export interface BadgeProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: "default" | "secondary" | "destructive" | "outline"
}

function Badge({ className, variant = "default", ...props }: BadgeProps) {
  return (
    <div
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-orange-500 focus:ring-offset-2",
        {
          "border-transparent bg-orange-500 text-white hover:bg-orange-600":
            variant === "default",
          "border-transparent bg-teal-500 text-white hover:bg-teal-600":
            variant === "secondary",
          "border-transparent bg-red-500 text-white hover:bg-red-600":
            variant === "destructive",
          "border-gray-300 dark:border-gray-600 text-gray-900 dark:text-gray-100": variant === "outline",
        },
        className
      )}
      {...props}
    />
  )
}

export { Badge }
