import { RefreshCw } from 'lucide-react';
import { useRegisterSW } from 'virtual:pwa-register/react';
import { Button } from '../ui/Button';

/**
 * Estrategia de actualización de la PWA: la versión nueva se descarga en segundo plano y la persona
 * decide cuándo aplicarla (nunca se recarga a mitad de una venta).
 */
export function UpdatePrompt() {
  const { needRefresh: [needRefresh, setNeedRefresh], updateServiceWorker } = useRegisterSW({
    onRegisterError: () => { /* sin service worker (p. ej. http en otra máquina): la app funciona igual en línea */ },
  });
  if (!needRefresh) return null;
  return (
    <div className="offline-banner" role="status" style={{ background: 'var(--info-soft)', color: 'var(--on-info-soft)' }}>
      <RefreshCw size={20} aria-hidden />
      <span className="grow">Hay una versión nueva de POS-PY. Actualice cuando termine la operación en curso.</span>
      <Button size="sm" variant="primary" onClick={() => updateServiceWorker(true)}>Actualizar ahora</Button>
      <Button size="sm" variant="ghost" onClick={() => setNeedRefresh(false)}>Más tarde</Button>
    </div>
  );
}
