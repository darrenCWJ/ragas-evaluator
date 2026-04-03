import { type HTMLAttributes } from "react";

type BadgeVariant =
  | "accent"
  | "success"
  | "warning"
  | "danger"
  | "info"
  | "muted";

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
  pill?: boolean;
}

const variantClasses: Record<BadgeVariant, string> = {
  accent: "bg-accent/15 text-accent",
  success: "bg-green-500/15 text-green-300",
  warning: "bg-yellow-500/15 text-yellow-300",
  danger: "bg-red-500/15 text-red-300",
  info: "bg-blue-500/15 text-blue-300",
  muted: "bg-elevated text-text-muted",
};

export default function Badge({
  variant = "muted",
  pill = false,
  className = "",
  children,
  ...props
}: BadgeProps) {
  return (
    <span
      className={`
        inline-flex items-center px-2 py-0.5 text-2xs font-bold uppercase tracking-wider
        ${pill ? "rounded-full" : "rounded"}
        ${variantClasses[variant]}
        ${className}
      `}
      {...props}
    >
      {children}
    </span>
  );
}
