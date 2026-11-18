import { CheckCircle2, Clock, Link2Off, LogIn, Users } from 'lucide-react';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ApiError, post } from '../../api/client';
import { Button } from '../../components/ui/Button';
import { Alert, EmptyState, ErrorAlert, Loading } from '../../components/ui/Feedback';
import { Card, PageHeader } from '../../components/ui/Layout';
import { useAuth } from '../../context/Auth';
import { dateTime } from '../../lib/format';
import { useApi } from '../../lib/hooks';
import { POLICY_LABEL } from './labels';

/** Abre un enlace de invitación (/unirse/<token>). La sesión ya está iniciada: el token no autentica. */
export default function JoinPage() {
  const { token = '' } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();
  const preview = useApi<any>(`/invitations/${encodeURIComponent(token)}`);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  const goToGroup = (gid: string) => navigate(`/grupos/${gid}`, { replace: true });   // quita el token de la barra de direcciones

  const accept = async () => {
    setBusy(true);
    setError(null);
    try {
      setResult(await post(`/invitations/${encodeURIComponent(token)}/accept`));
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };

  if (preview.loading && !preview.data) return <Loading label="Validando la invitación…" />;
  if (preview.error) {
    return (
      <EmptyState title={preview.error.status === 429 ? 'Demasiados intentos' : 'No se puede usar esta invitación'}
        icon={<Link2Off size={40} aria-hidden />}>
        <p>{preview.error.message}</p>
        <Link to="/grupos" className="btn btn-outline">Ir a mis grupos</Link>
      </EmptyState>
    );
  }
  const p = preview.data;
  const g = p.group;

  if (result) {
    const done = result.result === 'unido' || result.result === 'ya_integrante';
    return (
      <div className="stack" style={{ maxWidth: 640 }}>
        <Alert kind={done ? 'success' : 'info'} title={done ? (result.result === 'unido' ? `Ya es integrante de «${g.name}»` : 'Ya pertenecía a este grupo')
          : 'Solicitud enviada'}>
          {done ? 'El administrador ya lo ve en la lista de integrantes.' : `${g.owner_name} debe aprobar su ingreso. Le avisaremos aquí mismo.`}
        </Alert>
        <div><Button variant="primary" icon={done ? <CheckCircle2 size={18} /> : <Clock size={18} />} onClick={() => goToGroup(result.group)}>Ir al grupo</Button></div>
      </div>
    );
  }

  return (
    <div className="stack" style={{ maxWidth: 640 }}>
      <PageHeader title="Invitación a un grupo de trabajo" description={`Sesión iniciada como ${user?.full_name}.`} />
      <Card title={<h2 className="row" style={{ gap: 8 }}><Users size={22} aria-hidden /> {g.name}</h2>}>
        <div className="card-body stack">
          {g.description && <p style={{ margin: 0 }}>{g.description}</p>}
          <dl className="dl">
            <dt>Administrador</dt><dd>{g.owner_name}</dd>
            <dt>Integrantes</dt><dd>{g.member_count}</dd>
            <dt>Ingreso</dt><dd>{POLICY_LABEL[g.join_policy]}</dd>
            <dt>Enlace válido hasta</dt><dd>{dateTime(p.invitation.expires_at)}</dd>
          </dl>
          <ErrorAlert error={error} />
          {p.is_owner ? (
            <Alert kind="info">Usted es el administrador de este grupo; no necesita unirse.</Alert>
          ) : p.my_status === 'activo' ? (
            <Alert kind="success">Ya pertenece a este grupo.</Alert>
          ) : p.my_status === 'pendiente' ? (
            <Alert kind="warning">Su solicitud está pendiente de aprobación.</Alert>
          ) : (
            <p className="muted" style={{ margin: 0 }}>Al unirse, el administrador verá su nombre y su estado de conexión. Sus permisos en
              POS-PY no cambian.</p>
          )}
          <div className="row">
            {p.is_owner || p.my_status
              ? <Button variant="primary" onClick={() => goToGroup(g.public_id)}>Ir al grupo</Button>
              : <Button variant="primary" size="lg" busy={busy} icon={<LogIn size={20} />} onClick={accept}>Unirme al grupo</Button>}
            <Link to="/grupos" className="btn btn-ghost">Ahora no</Link>
          </div>
        </div>
      </Card>
    </div>
  );
}
