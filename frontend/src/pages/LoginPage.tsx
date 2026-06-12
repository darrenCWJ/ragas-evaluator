import { useState, type FormEvent } from 'react';
import { useNavigate, Navigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { loginUser, registerUser, ApiError } from '../lib/api';
import { Card, Button, TextInput, FormField, ErrorAlert, Spinner } from '../components/ui';

const MIN_PASSWORD_LENGTH = 8;

type Tab = 'login' | 'register';

function friendlyAuthError(err: unknown, tab: Tab): string {
  if (err instanceof ApiError) {
    if (err.status === 429) {
      return 'Too many login attempts — wait a minute and try again.';
    }
    if (err.status === 401 && tab === 'login') {
      return 'Invalid email or password.';
    }
    return err.message;
  }
  return err instanceof Error ? err.message : 'Request failed';
}

export default function LoginPage() {
  const { user, loading, authEnabled, registrationOpen, refresh } = useAuth();
  const navigate = useNavigate();

  // In open mode the only sensible action is registering the first admin.
  const [tab, setTab] = useState<Tab>('login');
  const [email, setEmail] = useState('');
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center bg-deep">
        <Spinner size="lg" />
      </div>
    );
  }

  if (authEnabled && user) {
    return <Navigate to="/start" replace />;
  }

  const activeTab: Tab = authEnabled ? tab : 'register';
  const showRegisterTab = !authEnabled || registrationOpen;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (activeTab === 'register' && password.length < MIN_PASSWORD_LENGTH) {
      setError(`Password must be at least ${MIN_PASSWORD_LENGTH} characters.`);
      return;
    }
    setSubmitting(true);
    try {
      if (activeTab === 'register') {
        await registerUser({ email, name, password });
      } else {
        await loginUser({ email, password });
      }
      await refresh();
      navigate('/start');
    } catch (err) {
      setError(friendlyAuthError(err, activeTab));
    } finally {
      setSubmitting(false);
    }
  };

  const switchTab = (next: Tab) => {
    setTab(next);
    setError(null);
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-deep p-4">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="mb-6 flex items-center justify-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent/20">
            <span className="text-base font-bold text-accent">R</span>
          </div>
          <div>
            <div className="text-base font-semibold text-text-primary leading-tight">Tribunal</div>
            <div className="text-2xs font-medium uppercase tracking-widest text-text-muted">
              Ragas Platform
            </div>
          </div>
        </div>
        <p className="mb-6 text-center text-sm text-text-secondary">
          Test your AI agent, see exactly what went wrong, and verify your fixes actually work.
        </p>

        <Card padding="lg" className="space-y-4">
          {authEnabled ? (
            /* Tabs */
            <div className="flex rounded-lg bg-input p-1">
              <button
                type="button"
                onClick={() => switchTab('login')}
                className={`flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                  activeTab === 'login'
                    ? 'bg-card text-text-primary'
                    : 'text-text-muted hover:text-text-secondary'
                }`}
              >
                Sign in
              </button>
              {showRegisterTab && (
                <button
                  type="button"
                  onClick={() => switchTab('register')}
                  className={`flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                    activeTab === 'register'
                      ? 'bg-card text-text-primary'
                      : 'text-text-muted hover:text-text-secondary'
                  }`}
                >
                  Register
                </button>
              )}
            </div>
          ) : (
            /* Open mode: first account bootstraps auth */
            <div className="rounded-lg border border-accent/30 bg-accent/5 px-3 py-2.5 text-xs text-text-secondary">
              No accounts exist yet — the first account to register becomes the admin and activates
              login for everyone.
            </div>
          )}

          <ErrorAlert message={error} onDismiss={() => setError(null)} />

          <form onSubmit={handleSubmit} className="space-y-3">
            <FormField label="Email">
              <TextInput
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                autoComplete="email"
                required
              />
            </FormField>
            {activeTab === 'register' && (
              <FormField label="Name">
                <TextInput
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Your name"
                  autoComplete="name"
                  required
                />
              </FormField>
            )}
            <FormField
              label="Password"
              hint={
                activeTab === 'register' ? `At least ${MIN_PASSWORD_LENGTH} characters` : undefined
              }
            >
              <TextInput
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                autoComplete={activeTab === 'register' ? 'new-password' : 'current-password'}
                required
              />
            </FormField>
            <Button type="submit" loading={submitting} className="w-full">
              {activeTab === 'register' ? 'Create account' : 'Sign in'}
            </Button>
          </form>

          {authEnabled && !registrationOpen && (
            <p className="text-center text-xs text-text-muted">
              Registration is disabled — ask an admin for an account.
            </p>
          )}
        </Card>
      </div>
    </div>
  );
}
