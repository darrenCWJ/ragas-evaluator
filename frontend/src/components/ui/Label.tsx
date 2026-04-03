import { type LabelHTMLAttributes } from "react";

interface LabelProps extends LabelHTMLAttributes<HTMLLabelElement> {
  section?: boolean;
}

export default function Label({
  section = false,
  className = "",
  children,
  ...props
}: LabelProps) {
  return (
    <label
      className={`
        block font-medium
        ${section ? "text-sm uppercase tracking-wider text-text-secondary" : "mb-1 text-xs text-text-secondary"}
        ${className}
      `}
      {...props}
    >
      {children}
    </label>
  );
}
