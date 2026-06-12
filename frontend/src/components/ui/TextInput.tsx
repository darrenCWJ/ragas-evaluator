import { type InputHTMLAttributes } from 'react';

/** Standard themed text input. Forwards all native input props. */
export default function TextInput({
  className = '',
  ...props
}: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={`w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-none ${className}`}
      {...props}
    />
  );
}
