import { useState, type FormEvent } from 'react';
import { useFetch } from '../../hooks/useFetch';
import {
  fetchProjectMembers,
  addProjectMember,
  removeProjectMember,
  type ProjectMember,
} from '../../lib/api';
import { Card, Button, TextInput, ErrorAlert, Spinner } from '../ui';

interface ProjectMembersPanelProps {
  projectId: number;
}

/**
 * Owner + members of the selected project, with add-by-email and remove.
 * Any member can view; add/remove failures (403/404/409) surface in the alert.
 */
export default function ProjectMembersPanel({ projectId }: ProjectMembersPanelProps) {
  const members = useFetch(() => fetchProjectMembers(projectId), [projectId]);
  const [email, setEmail] = useState('');
  const [actionError, setActionError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [removingId, setRemovingId] = useState<number | null>(null);

  const handleAdd = async (e: FormEvent) => {
    e.preventDefault();
    if (!email.trim()) return;
    setActionError(null);
    setAdding(true);
    try {
      await addProjectMember(projectId, email.trim());
      setEmail('');
      await members.reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to add member');
    } finally {
      setAdding(false);
    }
  };

  const handleRemove = async (member: ProjectMember) => {
    setActionError(null);
    setRemovingId(member.id);
    try {
      await removeProjectMember(projectId, member.id);
      await members.reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to remove member');
    } finally {
      setRemovingId(null);
    }
  };

  return (
    <Card padding="lg" className="space-y-4">
      <div>
        <h2 className="text-sm font-semibold text-text-primary">Project members</h2>
        <p className="mt-0.5 text-xs text-text-muted">People who can view and edit this project.</p>
      </div>

      <ErrorAlert message={actionError} onDismiss={() => setActionError(null)} />

      {members.loading ? (
        <div className="flex justify-center py-4">
          <Spinner />
        </div>
      ) : members.error ? (
        <ErrorAlert message={members.error} />
      ) : (
        <div className="space-y-1.5">
          {members.data?.owner && (
            <div className="flex items-center justify-between gap-2 rounded-lg bg-elevated/60 px-3 py-2">
              <div className="min-w-0">
                <div className="truncate text-sm text-text-primary">{members.data.owner.name}</div>
                <div className="truncate text-xs text-text-muted">{members.data.owner.email}</div>
              </div>
              <span className="shrink-0 rounded bg-accent/15 px-1.5 py-0.5 text-2xs font-semibold uppercase tracking-wider text-accent">
                Owner
              </span>
            </div>
          )}
          {members.data?.members.map((m) => (
            <div
              key={m.id}
              className="flex items-center justify-between gap-2 rounded-lg px-3 py-2 hover:bg-elevated/40"
            >
              <div className="min-w-0">
                <div className="truncate text-sm text-text-primary">{m.name}</div>
                <div className="truncate text-xs text-text-muted">{m.email}</div>
              </div>
              <button
                onClick={() => handleRemove(m)}
                disabled={removingId === m.id}
                className="shrink-0 rounded-md px-2 py-1 text-xs text-score-low transition hover:bg-score-low/10 disabled:opacity-50"
              >
                {removingId === m.id ? 'Removing…' : 'Remove'}
              </button>
            </div>
          ))}
          {members.data && !members.data.owner && members.data.members.length === 0 && (
            <p className="px-1 py-2 text-xs text-text-muted">No members yet.</p>
          )}
        </div>
      )}

      <form onSubmit={handleAdd} className="flex items-center gap-2">
        <TextInput
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="teammate@example.com"
          aria-label="Member email"
        />
        <Button type="submit" variant="secondary" loading={adding} className="shrink-0">
          Add
        </Button>
      </form>
    </Card>
  );
}
