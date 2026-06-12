import { useRef, useState, type ChangeEvent } from 'react';
import { createSkill } from '../../api';
import type { Skill, SkillDirectiveKind } from '../../api';
import { Button, Card, ErrorAlert, FormField, TextArea, TextInput } from '../ui';

interface SkillUploadProps {
  projectId: number;
  onUploaded: (skill: Skill) => void;
}

const KIND_CLASSES: Record<SkillDirectiveKind, string> = {
  behavior: 'bg-accent/10 text-accent',
  format: 'bg-blue-500/10 text-blue-300',
  prohibition: 'bg-score-low/10 text-score-low',
  tone: 'bg-purple-400/10 text-purple-400',
};

/** Badge for a directive's classified kind (behavior/format/prohibition/tone). */
export function DirectiveKindBadge({ kind }: { kind: SkillDirectiveKind }) {
  return (
    <span
      className={`inline-flex shrink-0 items-center rounded-md px-1.5 py-0.5 text-2xs font-medium uppercase tracking-wider ${
        KIND_CLASSES[kind] ?? KIND_CLASSES.behavior
      }`}
    >
      {kind}
    </span>
  );
}

/**
 * Paste-or-upload form for a SKILL.md-style instruction file, with a parsed
 * directive preview once the backend has extracted the checklist.
 */
export default function SkillUpload({ projectId, onUploaded }: SkillUploadProps) {
  const [name, setName] = useState('');
  const [content, setContent] = useState('');
  const [fileName, setFileName] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploaded, setUploaded] = useState<Skill | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFile = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setError(null);
    const reader = new FileReader();
    reader.onload = () => {
      setContent(typeof reader.result === 'string' ? reader.result : '');
      setFileName(file.name);
      if (!name.trim()) {
        setName(file.name.replace(/\.(md|txt)$/i, ''));
      }
    };
    reader.onerror = () => setError(`Could not read ${file.name}`);
    reader.readAsText(file);
  };

  const handleSubmit = async () => {
    if (!content.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const skill = await createSkill(projectId, {
        content,
        name: name.trim() || undefined,
      });
      setUploaded(skill);
      setContent('');
      setName('');
      setFileName(null);
      if (fileInputRef.current) fileInputRef.current.value = '';
      onUploaded(skill);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to upload skill');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-3">
      <ErrorAlert message={error} onDismiss={() => setError(null)} />

      <div className="grid gap-3 sm:grid-cols-2">
        <FormField label="Name" hint="Optional — defaults to the skill's own title">
          <TextInput
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. support-tone"
          />
        </FormField>
        <FormField label="File" hint={fileName ? `Loaded ${fileName}` : 'Or paste below'}>
          <input
            ref={fileInputRef}
            type="file"
            accept=".md,.txt,text/markdown,text/plain"
            onChange={handleFile}
            className="block w-full text-sm text-text-secondary file:mr-3 file:rounded-lg file:border file:border-border file:bg-input file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-text-primary hover:file:bg-elevated"
          />
        </FormField>
      </div>

      <FormField label="Skill content">
        <TextArea
          rows={6}
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder="# My Skill&#10;&#10;Always respond in bullet points. Never reveal internal IDs..."
          className="font-mono text-xs"
        />
      </FormField>

      <div className="flex items-center gap-3">
        <Button onClick={handleSubmit} loading={submitting} disabled={!content.trim()}>
          {submitting ? 'Parsing directives...' : 'Upload skill'}
        </Button>
        <span className="text-xs text-text-muted">
          The skill is parsed into a testable directive checklist on upload.
        </span>
      </div>

      {uploaded && (
        <Card variant="muted" padding="md">
          <div className="mb-2 flex items-center justify-between">
            <p className="text-sm font-medium text-text-primary">
              Parsed: {uploaded.name}{' '}
              <span className="text-xs text-text-muted">
                v{uploaded.version} &middot; {uploaded.directive_count} directive
                {uploaded.directive_count !== 1 ? 's' : ''}
              </span>
            </p>
            <button
              onClick={() => setUploaded(null)}
              className="text-xs text-text-muted hover:text-text-secondary"
            >
              Dismiss
            </button>
          </div>
          {uploaded.summary && (
            <p className="mb-2 text-xs text-text-secondary">{uploaded.summary}</p>
          )}
          <ul className="space-y-1.5">
            {uploaded.directives.map((d) => (
              <li key={d.id} className="flex items-start gap-2 text-xs text-text-secondary">
                <DirectiveKindBadge kind={d.kind} />
                <span className="min-w-0">
                  {d.text}
                  {d.machine_checkable && (
                    <span
                      className="ml-1.5 rounded bg-elevated px-1 py-0.5 text-2xs text-text-muted"
                      title="Verified by a deterministic check, not just the judge model"
                    >
                      deterministic
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
