import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight } from 'lucide-react';
import type { ReactNode } from 'react';
import { Button } from './Button';

export interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  numeric?: boolean;
  sortable?: boolean;
  width?: string;
}

interface TableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string | number;
  caption: string;
  selectedKey?: string | number | null;
  onSelect?: (row: T) => void;
  sort?: string;
  direction?: 'asc' | 'desc';
  onSort?: (key: string) => void;
  footer?: ReactNode;
}

export function DataTable<T>({ columns, rows, rowKey, caption, selectedKey, onSelect, sort, direction, onSort, footer }: TableProps<T>) {
  return (
    <div className="table-wrap">
      <table className="table">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} scope="col" className={c.numeric ? 'num' : undefined} style={c.width ? { width: c.width } : undefined}
                aria-sort={sort === c.key ? (direction === 'desc' ? 'descending' : 'ascending') : undefined}>
                {c.sortable && onSort ? (
                  <button type="button" className="th-sort" onClick={() => onSort(c.key)}>
                    {c.header}
                    {sort === c.key && (direction === 'desc' ? <ArrowDown size={16} aria-hidden /> : <ArrowUp size={16} aria-hidden />)}
                  </button>
                ) : c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const key = rowKey(row);
            const selected = selectedKey !== undefined && selectedKey === key;
            return (
              <tr key={key} className={[selected && 'is-selected', onSelect && 'is-clickable'].filter(Boolean).join(' ') || undefined}
                aria-selected={onSelect ? selected : undefined}
                tabIndex={onSelect ? 0 : undefined}
                onClick={onSelect ? () => onSelect(row) : undefined}
                onKeyDown={onSelect ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(row); } } : undefined}>
                {columns.map((c) => <td key={c.key} className={c.numeric ? 'num' : undefined}>{c.render(row)}</td>)}
              </tr>
            );
          })}
        </tbody>
        {footer && <tfoot>{footer}</tfoot>}
      </table>
    </div>
  );
}

export function Pagination({ page, pages, total, onPage }: { page: number; pages: number; total: number; onPage: (p: number) => void }) {
  return (
    <nav className="pagination" aria-label="Paginación">
      <span className="muted">{total} {total === 1 ? 'registro' : 'registros'} · página {page} de {pages}</span>
      <div className="row">
        <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => onPage(page - 1)} icon={<ChevronLeft size={18} />}>
          Anterior
        </Button>
        <Button size="sm" variant="outline" disabled={page >= pages} onClick={() => onPage(page + 1)} icon={<ChevronRight size={18} />}>
          Siguiente
        </Button>
      </div>
    </nav>
  );
}
