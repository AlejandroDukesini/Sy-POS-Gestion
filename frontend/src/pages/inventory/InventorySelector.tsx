import { ArrowRight, Boxes, PackageOpen, Search } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button } from '../../components/ui/Button';
import { Badge, EmptyState } from '../../components/ui/Feedback';
import { SelectField, TextField } from '../../components/ui/Form';
import { Pagination } from '../../components/ui/Table';
import { useInventory, type InventoryOption } from '../../context/Inventory';
import { dateTime, qty } from '../../lib/format';

const PAGE = 9;
const STATUS_KIND = { activo: 'success', inactivo: 'warning', archivado: undefined } as const;

/** Panel de selección: se muestra cuando la persona tiene 3 o más inventarios. Datos reales de cada inventario. */
export function InventorySelector() {
  const { options, current, select } = useInventory();
  const navigate = useNavigate();
  const [q, setQ] = useState('');
  const [group, setGroup] = useState('');
  const [status, setStatus] = useState('');
  const [page, setPage] = useState(1);
  const groups = useMemo(() => [...new Map(options.filter((o) => o.group).map((o) => [o.group!.public_id, o.group!.name])).entries()], [options]);
  const term = q.trim().toLowerCase();
  const filtered = options.filter((o) => (!term || o.name.toLowerCase().includes(term) || (o.group?.name ?? '').toLowerCase().includes(term)
    || o.first_products.some((p) => p.description.toLowerCase().includes(term)))
    && (!group || (group === 'sin' ? !o.group : o.group?.public_id === group)) && (!status || o.status === status));
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE));
  const shown = filtered.slice((Math.min(page, pages) - 1) * PAGE, Math.min(page, pages) * PAGE);
  const enter = (o: InventoryOption) => {
    select(o.key);
    navigate('/inventario');
  };

  return (
    <div className="stack">
      <div className="row">
        <div className="grow" style={{ minWidth: 220 }}>
          <TextField label="Buscar inventario" type="search" value={q} onChange={(v) => { setQ(v); setPage(1); }}
            placeholder="Nombre, grupo o producto" autoComplete="off" />
        </div>
        <div style={{ minWidth: 200 }}>
          <SelectField label="Grupo" value={group} onChange={(v) => { setGroup(v); setPage(1); }} placeholder="Todos"
            options={[...groups.map(([value, label]) => ({ value, label })), ...(options.some((o) => !o.group) ? [{ value: 'sin', label: 'Sin grupo' }] : [])]} />
        </div>
        <div style={{ minWidth: 160 }}>
          <SelectField label="Estado" value={status} onChange={(v) => { setStatus(v); setPage(1); }} placeholder="Todos"
            options={[{ value: 'activo', label: 'Activos' }, { value: 'inactivo', label: 'Inactivos' }, { value: 'archivado', label: 'Archivados' }]} />
        </div>
      </div>
      {!shown.length ? <EmptyState title="Ningún inventario coincide" icon={<Search size={40} aria-hidden />} /> : (
        <ul className="inventory-cards" aria-label="Inventarios">
          {shown.map((o) => (
            <li key={o.key}>
              <article className={`card inventory-card${o.key === current?.key ? ' current' : ''}`} aria-labelledby={`inv-${o.key}`}>
                <div className="inventory-card-head">
                  <span className="muted">{o.group ? `Grupo ${o.group.name}` : 'Sin grupo asociado'}</span>
                  <Badge kind={STATUS_KIND[o.status]}>{o.status === 'activo' ? 'Activo' : o.status === 'inactivo' ? 'Inactivo' : 'Archivado'}</Badge>
                </div>
                <h3 id={`inv-${o.key}`}><Boxes size={20} aria-hidden /> {o.name}</h3>
                {o.first_products.length ? (
                  <ul className="inventory-card-products" aria-label={`Primeros productos de ${o.name}`}>
                    {o.first_products.map((p) => (
                      <li key={p.code}><strong>{p.code}</strong> {p.description} <span className="muted">· {qty(p.stock)} {p.unit}</span></li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted inventory-card-empty"><PackageOpen size={18} aria-hidden /> Aún no tiene productos.</p>
                )}
                <dl className="inventory-card-stats">
                  <div><dt>Productos</dt><dd>{o.products}</dd></div>
                  <div><dt>Existencias</dt><dd>{qty(o.stock)}</dd></div>
                  <div><dt>Última actualización</dt><dd>{o.last_update ? dateTime(o.last_update) : '—'}</dd></div>
                </dl>
                <Button variant={o.key === current?.key ? 'outline' : 'primary'} icon={<ArrowRight size={18} />} onClick={() => enter(o)}
                  aria-label={`Ingresar a ${o.name}`}>{o.key === current?.key ? 'Seguir en este inventario' : 'Ingresar'}</Button>
              </article>
            </li>
          ))}
        </ul>
      )}
      {pages > 1 && <Pagination page={Math.min(page, pages)} pages={pages} total={filtered.length} onPage={setPage} />}
    </div>
  );
}
