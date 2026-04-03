import { type ButtonHTMLAttributes } from "react";

type ButtonVariant = "primary" | "secondary" | "danger" | "success" | "ghost";
type ButtonSize = "sm" | "md";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

const variantClasses: Record<ButtonVariant, string> = {
  primary:
    "bg-accent text-white hover:bg-accent/80",
  secondary:
    "border border-border text-text-secondary hover:bg-elevated hover:text-text-primary",
  danger:
    "bg-red-500/20 text-red-300 hover:bg-red-500/30",
  success:
    "border border-green-500/30 text-green-400 hover:bg-green-500/10",
  ghost:
    "text-text-secondary hover:bg-elevated hover:text-text-primary",
};

const sizeClasses: Record<ButtonSize, string> = {
  sm: "px-3 py-1.5 text-xs",
  md: "px-4 py-2 text-sm",
};

export default function Button({
  variant = "primary",
  size = "md",
  className = "",
  children,
  ...props
}: ButtonProps) {
  return (
    <button
      className={`
        rounded-lg font-medium transition-colors
        disabled:cursor-not-allowed disabled:opacity-40
        ${variantClasses[variant]}
        ${sizeClasses[size]}
        ${className}
      `}
      {...props}
    >
      {children}
    </button>
  );
}
