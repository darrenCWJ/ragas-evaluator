import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react';
import { fetchAuthStatus, fetchCurrentUser, logoutUser, UNAUTHORIZED_EVENT } from '../lib/api';
import type { AuthUser } from '../lib/api';

interface AuthContextValue {
  /** Signed-in user, or null when anonymous / open mode. */
  user: AuthUser | null;
  /** True until the initial status + session check completes. */
  loading: boolean;
  /** False = open mode (no accounts yet): no login enforcement anywhere. */
  authEnabled: boolean;
  /** Whether new accounts can self-register. */
  registrationOpen: boolean;
  /** Re-check auth status and current session (e.g. after login/register). */
  refresh: () => Promise<void>;
  /** End the session server-side and clear the local user. */
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [authEnabled, setAuthEnabled] = useState(false);
  const [registrationOpen, setRegistrationOpen] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const status = await fetchAuthStatus();
      setAuthEnabled(status.auth_enabled);
      setRegistrationOpen(status.registration_open);
      if (!status.auth_enabled) {
        setUser(null);
        return;
      }
      try {
        setUser(await fetchCurrentUser());
      } catch {
        // 401 — no active session
        setUser(null);
      }
    } catch {
      // Status endpoint unreachable — fall back to open mode so the app
      // stays usable; API calls will surface their own errors.
      setAuthEnabled(false);
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      await logoutUser();
    } finally {
      setUser(null);
    }
  }, []);

  useEffect(() => {
    // Initial session check — async data load on mount (same pattern as useFetch);
    // every setState inside refresh() happens after an await, not synchronously.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refresh();
  }, [refresh]);

  // Any non-auth API call returning 401 means the session is gone —
  // clear the user so the route guard redirects to /login.
  useEffect(() => {
    const onUnauthorized = () => setUser(null);
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, authEnabled, registrationOpen, refresh, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
