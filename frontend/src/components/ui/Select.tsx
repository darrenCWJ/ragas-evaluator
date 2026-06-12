import { type SelectHTMLAttributes } from 'react';

/** Standard themed select. Forwards all native select props. */
export default function Select({
  className = '',
  children,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={`w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary focus:border-border-focus focus:outline-none ${className}`}
      {...props}
    >
      {children}
    </select>
  );
}
