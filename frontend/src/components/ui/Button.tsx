import { type ButtonHTMLAttributes } from 'react';
import Spinner from './Spinner';

type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  loading?: boolean;
}

const variantClasses: Record<ButtonVariant, string> = {
  primary: 'bg-accent text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50',
  secondary:
    'border border-border text-text-primary hover:bg-input disabled:cursor-not-allowed disabled:opacity-50',
  danger:
    'bg-score-low/15 text-score-low hover:bg-score-low/25 disabled:cursor-not-allowed disabled:opacity-50',
  ghost:
    'text-text-secondary hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-50',
};

export default function Button({
  variant = 'primary',
  loading = false,
  className = '',
  children,
  disabled,
  ...props
}: ButtonProps) {
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors ${variantClasses[variant]} ${className}`}
      disabled={disabled || loading}
      {...props}
    >
      {loading && <Spinner size="sm" />}
      {children}
    </button>
  );
}
