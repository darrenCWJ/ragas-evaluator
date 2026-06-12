import { useState } from 'react';
import { useAuth } from '../../contexts/AuthContext';
import { useFetch } from '../../hooks/useFetch';
import { fetchUsers, updateUserRole, type UserRole } from '../../lib/api';
import { Card, Select, Spinner, ErrorAlert } from '../ui';

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
 * Collapsible admin-only account management: list all users and change roles.
 * Renders nothing unless the signed-in user is an admin.
 */
export default function UserAccountsCard() {
  const { user, authEnabled } = useAuth();
  const [open, setOpen] = useState(false);

  if (!authEnabled || user?.role !== 'admin') return null;

  return (
    <Card padding="lg">
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
    </Card>
  );
}
