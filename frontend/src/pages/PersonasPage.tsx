import { useState, useEffect, useCallback } from 'react';
import { useProject } from '../contexts/ProjectContext';
import { fetchPersonas, updatePersona, deletePersona, type SavedPersona } from '../lib/api';
import Card from '../components/ui/Card';

export default function PersonasPage() {
  const { project } = useProject();
  const projectId = project?.id ?? null;

  const [personas, setPersonas] = useState<SavedPersona[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState({ name: '', role_description: '', question_style: '' });
  const [saving, setSaving] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [deleting, setDeleting] = useState(false);

  const loadPersonas = useCallback(async () => {
    if (!projectId) return;
    try {
      setError(null);
      const data = await fetchPersonas(projectId);
      setPersonas(data);
    } catch (err) {
      setError((err as Error).message || 'Failed to load personas');
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    setLoading(true);
    loadPersonas();
  }, [loadPersonas]);

  const handleEdit = (p: SavedPersona) => {
    setEditingId(p.id);
    setEditForm({
      name: p.name,
      role_description: p.role_description,
      question_style: p.question_style,
    });
  };

  const handleSave = async () => {
    if (!projectId || editingId === null) return;
    setSaving(true);
    try {
      await updatePersona(projectId, editingId, editForm);
      setEditingId(null);
      await loadPersonas();
    } catch (err) {
      setError((err as Error).message || 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (!projectId) return;
    setDeleting(true);
    try {
      await deletePersona(projectId, id);
      setConfirmDeleteId(null);
      await loadPersonas();
    } catch (err) {
      setError((err as Error).message || 'Failed to delete');
    } finally {
      setDeleting(false);
    }
  };

  if (!projectId) {
    return (
      <div className="mx-auto max-w-4xl pt-8">
        <Card padding="lg" className="py-16 text-center">
          <p className="text-sm text-text-muted">Select a project to manage personas.</p>
        </Card>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl pt-8">
      <div className="mb-8 flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent/15">
          <svg
            className="h-5 w-5 text-accent"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.5}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z"
            />
          </svg>
        </div>
        <div>
          <h1 className="text-xl font-semibold text-text-primary">Personas</h1>
          <p className="text-sm text-text-secondary">
            Manage saved personas for test set generation.
          </p>
        </div>
      </div>

      {error && (
        <Card variant="error" padding="md" className="mb-6">
          {error}
        </Card>
      )}

      {loading ? (
        <div className="py-16 text-center">
          <div className="inline-block h-6 w-6 animate-spin rounded-full border-2 border-accent border-t-transparent" />
          <p className="mt-3 text-sm text-text-muted">Loading personas...</p>
        </div>
      ) : personas.length === 0 ? (
        <Card padding="lg" className="py-16 text-center">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-card border border-border mb-4">
            <svg
              className="h-7 w-7 text-text-muted"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={1.5}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z"
              />
            </svg>
          </div>
          <h3 className="text-sm font-medium text-text-primary mb-1">No personas yet</h3>
          <p className="text-micro text-text-muted max-w-xs mx-auto">
            Generate personas from the Test page using "Auto Generate" with a knowledge graph.
          </p>
        </Card>
      ) : (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-sm text-text-secondary">
              {personas.length} persona{personas.length !== 1 ? 's' : ''}
            </p>
          </div>

          {personas.map((p) => (
            <div key={p.id} className="rounded-xl border border-border bg-card p-4">
              {editingId === p.id ? (
                <div className="space-y-3">
                  <div>
                    <label className="mb-1 block text-xs font-medium text-text-secondary">
                      Name
                    </label>
                    <input
                      type="text"
                      value={editForm.name}
                      onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                      className="w-full rounded-lg border border-border bg-input px-3 py-2 text-sm text-text-primary focus:border-accent focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-text-secondary">
                      Role Description
                    </label>
                    <textarea
                      value={editForm.role_description}
                      onChange={(e) =>
                        setEditForm({ ...editForm, role_description: e.target.value })
                      }
                      rows={3}
                      className="w-full rounded-lg border border-border bg-input px-3 py-2 text-sm text-text-primary focus:border-accent focus:outline-none resize-none"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-text-secondary">
                      Question Style
                    </label>
                    <textarea
                      value={editForm.question_style}
                      onChange={(e) => setEditForm({ ...editForm, question_style: e.target.value })}
                      rows={2}
                      className="w-full rounded-lg border border-border bg-input px-3 py-2 text-sm text-text-primary focus:border-accent focus:outline-none resize-none"
                    />
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={handleSave}
                      disabled={
                        saving || !editForm.name.trim() || !editForm.role_description.trim()
                      }
                      className="rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white transition hover:bg-accent/90 disabled:opacity-40"
                    >
                      {saving ? 'Saving...' : 'Save'}
                    </button>
                    <button
                      onClick={() => setEditingId(null)}
                      className="rounded-lg px-3 py-1.5 text-xs text-text-muted hover:text-text-secondary"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <p className="font-medium text-text-primary">{p.name}</p>
                    <p className="mt-1 text-sm text-text-secondary">{p.role_description}</p>
                    {p.question_style && (
                      <p className="mt-1 text-xs text-text-muted italic">{p.question_style}</p>
                    )}
                    <p className="mt-2 text-micro text-text-muted">
                      Created {new Date(p.created_at).toLocaleDateString()}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <button
                      onClick={() => handleEdit(p)}
                      className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-text-secondary transition hover:border-accent hover:text-accent"
                    >
                      Edit
                    </button>
                    {confirmDeleteId === p.id ? (
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => handleDelete(p.id)}
                          disabled={deleting}
                          className="rounded-lg bg-red-500/20 px-3 py-1.5 text-xs font-medium text-red-300 transition hover:bg-red-500/30 disabled:opacity-40"
                        >
                          {deleting ? '...' : 'Confirm'}
                        </button>
                        <button
                          onClick={() => setConfirmDeleteId(null)}
                          className="rounded-lg px-2 py-1.5 text-xs text-text-muted hover:text-text-secondary"
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setConfirmDeleteId(p.id)}
                        className="rounded-lg px-2 py-1.5 text-xs text-text-muted transition hover:text-red-400"
                        title="Delete persona"
                      >
                        <svg
                          className="h-4 w-4"
                          fill="none"
                          viewBox="0 0 24 24"
                          stroke="currentColor"
                          strokeWidth={1.5}
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0"
                          />
                        </svg>
                      </button>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
