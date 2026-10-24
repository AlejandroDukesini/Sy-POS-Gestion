import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { get, put } from '../api/client';
import { applyPrefs, loadLocal, normalize, storeLocal, type Prefs } from '../lib/prefs';
import { useAuth } from './Auth';

interface PrefsState {
  prefs: Prefs;
  preview: (changes: Partial<Prefs>) => void;
  save: (changes: Partial<Prefs>) => Promise<void>;
  reset: () => void;
}

const PrefsContext = createContext<PrefsState | null>(null);

export function PrefsProvider({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const [saved, setSaved] = useState<Prefs>(loadLocal);
  const [draft, setDraft] = useState<Prefs>(saved);

  useEffect(() => {
    if (status !== 'authenticated') return;
    get('/prefs').then((p) => {
      const value = normalize(p);
      setSaved(value);
      setDraft(value);
      storeLocal(value);
    }).catch(() => { /* sin conexión: se usan las preferencias locales */ });
  }, [status]);

  useEffect(() => {
    applyPrefs(draft);
    if (draft.theme !== 'system') return;
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const listener = () => applyPrefs(draft);
    media.addEventListener('change', listener);
    return () => media.removeEventListener('change', listener);
  }, [draft]);

  const preview = useCallback((changes: Partial<Prefs>) => setDraft((d) => ({ ...d, ...changes })), []);
  const reset = useCallback(() => setDraft(saved), [saved]);
  const save = useCallback(async (changes: Partial<Prefs>) => {
    const next = normalize({ ...saved, ...changes });
    const stored = normalize(await put('/prefs', next));
    setSaved(stored);
    setDraft(stored);
    storeLocal(stored);
  }, [saved]);

  const value = useMemo(() => ({ prefs: draft, preview, save, reset }), [draft, preview, save, reset]);
  return <PrefsContext.Provider value={value}>{children}</PrefsContext.Provider>;
}

export function usePrefs(): PrefsState {
  const ctx = useContext(PrefsContext);
  if (!ctx) throw new Error('usePrefs fuera de PrefsProvider');
  return ctx;
}
