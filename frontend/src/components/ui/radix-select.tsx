import * as React from "react"
import * as SelectPrimitive from "@radix-ui/react-select"
import { Check, CaretDown, CaretUp } from "@phosphor-icons/react"

import { cn } from "@/lib/utils"

const RadixSelect = SelectPrimitive.Root

const RadixSelectGroup = SelectPrimitive.Group

const RadixSelectValue = SelectPrimitive.Value

const RadixSelectTrigger = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Trigger>
>(({ className, children, ...props }, ref) => (
  <SelectPrimitive.Trigger
    ref={ref}
    className={cn(
      "flex h-12 w-full items-center justify-between rounded-xl border border-[rgb(var(--color-input))] bg-[rgb(var(--color-card))]/85 px-3 py-2 text-sm text-[rgb(var(--color-foreground))] ring-offset-[rgb(var(--color-card))] placeholder:text-[rgb(var(--color-muted-foreground))] focus:outline-none focus:ring-2 focus:ring-[rgb(var(--color-ring))] focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 transition-all",
      className
    )}
    {...props}
  >
    {children}
    <SelectPrimitive.Icon asChild>
      <CaretDown className="h-4 w-4 opacity-50" />
    </SelectPrimitive.Icon>
  </SelectPrimitive.Trigger>
))
RadixSelectTrigger.displayName = SelectPrimitive.Trigger.displayName

const RadixSelectContent = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Content>
>(({ className, children, position = "popper", ...props }, ref) => (
  <SelectPrimitive.Portal>
    <SelectPrimitive.Content
      ref={ref}
      className={cn(
        "relative z-50 max-h-96 min-w-[8rem] overflow-hidden rounded-2xl border border-[rgb(var(--color-border))] bg-[rgb(var(--color-card))] text-[rgb(var(--color-foreground))] shadow-md animate-fade-in",
        position === "popper" &&
          "data-[side=bottom]:translate-y-1 data-[side=left]:-translate-x-1 data-[side=right]:translate-x-1 data-[side=top]:-translate-y-1",
        className
      )}
      position={position}
      {...props}
    >
      <SelectPrimitive.ScrollUpButton className="flex cursor-default items-center justify-center py-1 bg-[rgb(var(--color-card))]">
        <CaretUp className="h-4 w-4" />
      </SelectPrimitive.ScrollUpButton>
      <SelectPrimitive.Viewport
        className={cn(
          "p-1",
          position === "popper" &&
            "h-[var(--radix-select-trigger-height)] w-full min-w-[var(--radix-select-trigger-width)]"
        )}
      >
        {children}
      </SelectPrimitive.Viewport>
      <SelectPrimitive.ScrollDownButton className="flex cursor-default items-center justify-center py-1 bg-[rgb(var(--color-card))]">
        <CaretDown className="h-4 w-4" />
      </SelectPrimitive.ScrollDownButton>
    </SelectPrimitive.Content>
  </SelectPrimitive.Portal>
))
RadixSelectContent.displayName = SelectPrimitive.Content.displayName

const RadixSelectLabel = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Label>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Label>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.Label
    ref={ref}
    className={cn("py-1.5 pl-8 pr-2 text-sm font-semibold text-[rgb(var(--color-muted-foreground))]", className)}
    {...props}
  />
))
RadixSelectLabel.displayName = SelectPrimitive.Label.displayName

const RadixSelectItem = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Item>
>(({ className, children, ...props }, ref) => (
  <SelectPrimitive.Item
    ref={ref}
    className={cn(
      "relative flex w-full cursor-default select-none items-center rounded-xl py-2.5 pl-8 pr-2 text-sm outline-none focus:bg-[rgb(var(--color-muted))] focus:text-[rgb(var(--color-foreground))] data-[disabled]:pointer-events-none data-[disabled]:opacity-50 active:bg-[rgb(var(--color-muted))] transition-colors",
      className
    )}
    {...props}
  >
    <span className="absolute left-2 flex h-3.5 w-3.5 items-center justify-center">
      <SelectPrimitive.ItemIndicator>
        <Check className="h-4 w-4" />
      </SelectPrimitive.ItemIndicator>
    </span>

    <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
  </SelectPrimitive.Item>
))
RadixSelectItem.displayName = SelectPrimitive.Item.displayName

const RadixSelectSeparator = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Separator>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Separator>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.Separator
    ref={ref}
    className={cn("-mx-1 my-1 h-px bg-[rgb(var(--color-muted))]", className)}
    {...props}
  />
))
RadixSelectSeparator.displayName = SelectPrimitive.Separator.displayName

export {
  RadixSelect,
  RadixSelectGroup,
  RadixSelectValue,
  RadixSelectTrigger,
  RadixSelectContent,
  RadixSelectLabel,
  RadixSelectItem,
  RadixSelectSeparator,
}
