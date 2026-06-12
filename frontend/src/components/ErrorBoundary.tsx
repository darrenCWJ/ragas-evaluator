import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * Top-level error boundary. Without it, any render-time throw anywhere in the
 * tree blanks the whole app with no recovery path.
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Unhandled render error:', error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="flex min-h-screen items-center justify-center bg-deep p-8">
        <div className="max-w-lg rounded-xl border border-border bg-elevated p-8 text-center">
          <h1 className="mb-2 text-lg font-semibold text-text-primary">Something went wrong</h1>
          <p className="mb-4 break-words text-sm text-text-secondary">
            {this.state.error.message || 'An unexpected error occurred.'}
          </p>
          <div className="flex justify-center gap-3">
            <button
              onClick={() => this.setState({ error: null })}
              className="rounded-lg border border-border px-4 py-2 text-sm text-text-primary hover:bg-input"
            >
              Try again
            </button>
            <button
              onClick={() => window.location.reload()}
              className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:opacity-90"
            >
              Reload app
            </button>
          </div>
        </div>
      </div>
    );
  }
}
