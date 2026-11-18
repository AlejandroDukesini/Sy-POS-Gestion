import { Wifi, WifiOff } from 'lucide-react';
import { Badge } from '../../components/ui/Feedback';
import { dateTime } from '../../lib/format';
import { CONNECTION_KIND, CONNECTION_LABELS } from '../../lib/realtime';

export const MEMBER_STATUS: Record<string, string> = {
  activo: 'Integrante', pendiente: 'Pendiente de aprobación', retirado: 'Salió del grupo',
  eliminado: 'Retirado por el administrador', rechazado: 'Solicitud rechazada',
};
const MEMBER_KIND: Record<string, 'success' | 'warning' | 'danger' | undefined> = {
  activo: 'success', pendiente: 'warning', eliminado: 'danger', rechazado: 'danger',
};
export const INVITATION_STATUS: Record<string, string> = {
  vigente: 'Vigente', vencida: 'Vencida', revocada: 'Revocada', completa: 'Sin cupo', grupo_cerrado: 'Grupo cerrado',
};
const INVITATION_KIND: Record<string, 'success' | 'warning' | 'danger' | undefined> = {
  vigente: 'success', vencida: 'warning', revocada: 'danger', completa: 'warning',
};
export const POLICY_LABEL: Record<string, string> = {
  automatica: 'Ingreso inmediato con el enlace', aprobacion: 'El administrador aprueba cada ingreso',
};

export function MemberBadge({ status }: { status: string }) {
  return <Badge kind={MEMBER_KIND[status]}>{MEMBER_STATUS[status] ?? status}</Badge>;
}

export function InvitationBadge({ status }: { status: string }) {
  return <Badge kind={INVITATION_KIND[status]}>{INVITATION_STATUS[status] ?? status}</Badge>;
}

export function GroupStatusBadge({ status }: { status: string }) {
  return <Badge kind={status === 'activo' ? 'success' : undefined}>{status === 'activo' ? 'Activo' : 'Cerrado'}</Badge>;
}

/** Estado de conexión en tiempo real: icono + texto (nunca solo color). */
export function ConnectionBadge({ status, since }: { status: string; since?: string | null }) {
  const Icon = status === 'conectado' || status === 'conectando' ? Wifi : WifiOff;
  return (
    <span title={since ? `Última vez: ${dateTime(since)}` : undefined}>
      <Badge kind={CONNECTION_KIND[status]}>
        <Icon size={14} aria-hidden style={{ verticalAlign: '-2px', marginRight: 4 }} />
        {CONNECTION_LABELS[status] ?? status}
      </Badge>
    </span>
  );
}

const EVENT_TEXT: Record<string, (e: any) => string> = {
  grupo_creado: (e) => `${e.actor_name} creó el grupo`,
  grupo_actualizado: (e) => `${e.actor_name} actualizó los datos del grupo`,
  grupo_cerrado: (e) => `${e.actor_name} cerró el grupo${e.details?.enlaces_revocados ? ` y revocó ${e.details.enlaces_revocados} enlace(s)` : ''}`,
  grupo_reabierto: (e) => `${e.actor_name} reabrió el grupo`,
  invitacion_creada: (e) => `${e.actor_name} generó el enlace ${e.details?.enlace ?? ''} (${e.details?.cupo} personas, ${e.details?.horas} h)`,
  invitacion_revocada: (e) => `${e.actor_name} revocó el enlace ${e.details?.enlace ?? ''}`,
  integrante_unido: (e) => `${e.subject_name} se unió con un enlace`,
  solicitud_ingreso: (e) => `${e.subject_name} pidió unirse`,
  solicitud_aprobada: (e) => `${e.actor_name} aprobó el ingreso de ${e.subject_name}`,
  solicitud_rechazada: (e) => `${e.actor_name} rechazó la solicitud de ${e.subject_name}`,
  integrante_retirado: (e) => `${e.actor_name} retiró a ${e.subject_name}`,
  integrante_salio: (e) => `${e.subject_name} salió del grupo`,
};

export function eventText(e: any): string {
  return EVENT_TEXT[e.type]?.(e) ?? e.type;
}
