import { type InputHTMLAttributes, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  error?: boolean;
}

export default function Input({ error, className = "", ...props }: InputProps) {
  return (
    <input
      className={`
        w-full rounded-lg border bg-input px-3 py-1.5 text-sm
        text-text-primary placeholder:text-text-muted
        focus:outline-none
        ${error ? "border-red-500 focus:border-red-500" : "border-border focus:border-border-focus"}
        ${className}
      `}
      {...props}
    />
  );
}

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  error?: boolean;
}

export function Select({ error, className = "", children, ...props }: SelectProps) {
  return (
    <select
      className={`
        w-full rounded-lg border bg-input px-3 py-1.5 text-sm
        text-text-primary
        focus:outline-none
        ${error ? "border-red-500 focus:border-red-500" : "border-border focus:border-border-focus"}
        ${className}
      `}
      {...props}
    >
      {children}
    </select>
  );
}

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  error?: boolean;
}

export function Textarea({ error, className = "", ...props }: TextareaProps) {
  return (
    <textarea
      className={`
        w-full rounded-lg border bg-input px-3 py-2 text-sm
        text-text-primary placeholder:text-text-muted
        focus:outline-none
        ${error ? "border-red-500 focus:border-red-500" : "border-border focus:border-border-focus"}
        ${className}
      `}
      {...props}
    />
  );
}
