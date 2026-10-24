import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { ApiError, get, onUnauthorized, post } from '../api/client';
import { configureFormat } from '../lib/format';

export interface User {
  id: number;
  username: string;
  full_name: string;
  role: 'admin' | 'employee';
  permissions: string[];
}

export interface Company {
  name: string;
  primary_color: string;
  currency_symbol: string;
  timezone: string;
}

interface AuthState {
  status: 'loading' | 'anonymous' | 'authenticated';
  user: User | null;
  company: Company | null;
  mustChangePassword: boolean;
  desktop: boolean;
  can: (...perms: string[]) => boolean;
  canAny: (...perms: string[]) => boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  expiredMessage: string;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthState['status']>('loading');
  const [user, setUser] = useState<User | null>(null);
  const [company, setCompany] = useState<Company | null>(null);
  const [mustChangePassword, setMustChange] = useState(false);
  const [desktop, setDesktop] = useState(false);
  const [expiredMessage, setExpired] = useState('');

  const refresh = useCallback(async () => {
    try {
      const me = await get('/me');
      setUser(me.user);
      setCompany(me.company);
      setMustChange(me.must_change_password);
      setDesktop(Boolean(me.desktop));
      configureFormat(me.company.currency_symbol, me.company.timezone);
      document.documentElement.style.setProperty('--brand', me.company.primary_color);
      setStatus('authenticated');
    } catch (err) {
      if (err instanceof ApiError && err.offline && user) return;   // sin conexión: se conserva la sesión visible
      setUser(null);
      setStatus('anonymous');
    }
  }, [user]);

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    onUnauthorized(() => {
      setUser(null);
      setStatus((s) => {
        if (s === 'authenticated') setExpired('Su sesión terminó (por inactividad o por un cambio en su cuenta). Ingrese de nuevo.');
        return 'anonymous';
      });
    });
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    await post('/auth/login', { username, password });
    setExpired('');
    await refresh();
  }, [refresh]);

  const logout = useCallback(async () => {
    try {
      await post('/auth/logout');
    } finally {
      if ('caches' in window) {
        const keys = await caches.keys();
        await Promise.all(keys.filter((k) => k.startsWith('pospy-catalogo')).map((k) => caches.delete(k)));
      }
      setUser(null);
      setStatus('anonymous');
    }
  }, []);

  const value = useMemo<AuthState>(() => {
    const perms = new Set(user?.permissions ?? []);
    return {
      status, user, company, mustChangePassword, desktop, login, logout, refresh, expiredMessage,
      can: (...p) => p.every((x) => perms.has(x)),
      canAny: (...p) => p.some((x) => perms.has(x)),
    };
  }, [status, user, company, mustChangePassword, desktop, login, logout, refresh, expiredMessage]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth fuera de AuthProvider');
  return ctx;
}
