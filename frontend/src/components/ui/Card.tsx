import { type HTMLAttributes } from "react";

type CardVariant = "default" | "muted" | "elevated" | "error" | "warning" | "info";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  variant?: CardVariant;
  padding?: "sm" | "md" | "lg";
}

const variantClasses: Record<CardVariant, string> = {
  default: "border border-border bg-card",
  muted: "border border-border bg-card/60",
  elevated: "border border-border bg-elevated",
  error: "border border-red-500/30 bg-red-500/10 text-red-300",
  warning: "border border-yellow-500/30 bg-yellow-500/10 text-yellow-300",
  info: "border border-blue-500/20 bg-blue-500/5 text-blue-300",
};

const paddingClasses = {
  sm: "px-4 py-2.5",
  md: "px-4 py-3",
  lg: "px-5 py-4",
};

export default function Card({
  variant = "default",
  padding = "md",
  className = "",
  children,
  ...props
}: CardProps) {
  return (
    <div
      className={`rounded-xl ${variantClasses[variant]} ${paddingClasses[padding]} ${className}`}
      {...props}
    >
      {children}
    </div>
  );
}
