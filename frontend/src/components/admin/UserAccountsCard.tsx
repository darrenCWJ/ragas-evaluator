import { useState } from 'react';
import { useAuth } from '../../contexts/AuthContext';
import { useFetch } from '../../hooks/useFetch';
import {
  fetchAuthStatus,
  fetchUsers,
  updateLoginEnforcement,
  updateUserRole,
  type LoginEnforcement,
  type UserRole,
} from '../../lib/api';
import { Card, Select, Spinner, ErrorAlert } from '../ui';

/**
 * Login enforcement toggle — decide whether the app requires sign-in,
 * independent of whether accounts exist. Visible in open mode too, so
 * enforcement can be switched back on after being disabled.
 */
function LoginEnforcementControl() {
  const status = useFetch(fetchAuthStatus, []);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const mode: LoginEnforcement = status.data?.login_enforcement ?? 'auto';
  const enforced = status.data?.auth_enabled ?? false;
  const usersExist = status.data?.users_exist ?? false;

  const handleChange = async (next: LoginEnforcement) => {
    setSaving(true);
    setError(null);
    try {
      await updateLoginEnforcement(next);
      await status.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update login enforcement');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-2">
      <ErrorAlert message={error} onDismiss={() => setError(null)} />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm text-text-primary">Require sign-in</p>
          <p className="text-xs text-text-muted">
            {mode === 'off'
              ? 'Open access — anyone can use the app without an account.'
              : usersExist
                ? 'Sign-in is required for everyone.'
                : 'Will activate once the first account is registered.'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`rounded-full px-2 py-0.5 text-2xs ${
              enforced ? 'bg-score-high/10 text-score-high' : 'bg-elevated text-text-muted'
            }`}
          >
            {enforced ? 'enforced' : 'open'}
          </span>
          <Select
            value={mode}
            disabled={saving || status.loading}
            onChange={(e) => handleChange(e.target.value as LoginEnforcement)}
            className="w-44"
            aria-label="Login enforcement mode"
          >
            <option value="auto">Auto (on once accounts exist)</option>
            <option value="on">On — always require</option>
            <option value="off">Off — open access</option>
          </Select>
        </div>
      </div>
    </div>
  );
}

/** Body is mounted only while expanded, so the admin list loads on demand. */
function UserAccountsBody() {
  const users = useFetch(fetchUsers, []);
  const [actionError, setActionError] = useState<string | null>(null);
  const [updatingId, setUpdatingId] = useState<number | null>(null);

  const handleRoleChange = async (userId: number, role: UserRole) => {
    setActionError(null);
    setUpdatingId(userId);
    try {
      await updateUserRole(userId, role);
    } catch (err) {
      // 409 (last admin) and 403 surface here
      setActionError(err instanceof Error ? err.message : 'Failed to update role');
    } finally {
      setUpdatingId(null);
      await users.reload();
    }
  };

  if (users.loading) {
    return (
      <div className="flex justify-center py-6">
        <Spinner />
      </div>
    );
  }
  if (users.error) {
    return <ErrorAlert message={users.error} />;
  }

  return (
    <div className="space-y-3">
      <ErrorAlert message={actionError} onDismiss={() => setActionError(null)} />
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs text-text-muted">
            <th className="px-2 py-2 font-medium">Name</th>
            <th className="px-2 py-2 font-medium">Email</th>
            <th className="px-2 py-2 font-medium">Projects</th>
            <th className="px-2 py-2 font-medium">Joined</th>
            <th className="px-2 py-2 font-medium">Role</th>
          </tr>
        </thead>
        <tbody>
          {(users.data ?? []).map((u) => (
            <tr key={u.id} className="border-b border-border/50 last:border-0">
              <td className="px-2 py-2 text-text-primary">{u.name}</td>
              <td className="px-2 py-2 text-xs text-text-secondary">{u.email}</td>
              <td className="px-2 py-2 text-xs text-text-muted">{u.project_count}</td>
              <td className="px-2 py-2 text-xs text-text-muted">
                {u.created_at ? new Date(u.created_at).toLocaleDateString() : '—'}
              </td>
              <td className="px-2 py-2">
                <Select
                  value={u.role}
                  disabled={updatingId === u.id}
                  onChange={(e) => handleRoleChange(u.id, e.target.value as UserRole)}
                  className="w-28"
                  aria-label={`Role for ${u.email}`}
                >
                  <option value="user">user</option>
                  <option value="admin">admin</option>
                </Select>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Access control: login-enforcement toggle plus (when enforced and the
 * caller is an admin) the collapsible account-management table.
 *
 * The toggle stays visible in open mode — otherwise enforcement could never
 * be switched back on after being disabled. Non-admin signed-in users see
 * nothing.
 */
export default function UserAccountsCard() {
  const { user, authEnabled } = useAuth();
  const [open, setOpen] = useState(false);

  // Enforced mode: admins only. Open mode: visible (same trust level under
  // which the first admin registers).
  if (authEnabled && user?.role !== 'admin') return null;

  return (
    <Card padding="lg" className="space-y-4">
      <LoginEnforcementControl />
      {authEnabled && user?.role === 'admin' && (
        <div className="border-t border-border pt-3">
          <button
            onClick={() => setOpen((prev) => !prev)}
            className="flex w-full items-center justify-between text-left"
            aria-expanded={open}
          >
            <span className="text-sm font-medium text-text-primary">User accounts (admin)</span>
            <span className="text-xs text-text-muted">{open ? 'Hide' : 'Show'}</span>
          </button>
          {open && (
            <div className="mt-4">
              <UserAccountsBody />
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
