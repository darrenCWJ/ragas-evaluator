import { type TextareaHTMLAttributes } from 'react';

/** Standard themed textarea. Forwards all native textarea props. */
export default function TextArea({
  className = '',
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={`w-full rounded-lg border border-border bg-input px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-none ${className}`}
      {...props}
    />
  );
}
