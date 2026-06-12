import { useState } from 'react';

/**
 * State helper for the inline confirm-then-act pattern:
 * first click arms the confirmation for one id, second click confirms.
 */
export function useConfirm<Id = number>() {
  const [confirmingId, setConfirmingId] = useState<Id | null>(null);
  return {
    confirmingId,
    requestConfirm: (id: Id) => setConfirmingId(id),
    clear: () => setConfirmingId(null),
    isConfirming: (id: Id) => confirmingId === id,
  };
}
