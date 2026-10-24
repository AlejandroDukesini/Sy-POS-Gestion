/**
 * Formato de presentación (no cálculos de negocio): la API envía importes como texto decimal exacto
 * ("1234.50") y aquí solo se muestran con separadores colombianos.
 */

let currencySymbol = '$';
let timeZone = 'America/Bogota';

export function configureFormat(symbol: string, tz: string) {
  currencySymbol = symbol || '$';
  timeZone = tz || 'America/Bogota';
}

function group(integer: string): string {
  return integer.replace(/\B(?=(\d{3})+(?!\d))/g, '.');
}

/** "1234567.50" -> "$ 1.234.567,50"; "1234.00" -> "$ 1.234". */
export function money(value: string | number | null | undefined, symbol = currencySymbol): string {
  if (value === null || value === undefined || value === '') return '—';
  const text = typeof value === 'number' ? value.toFixed(2) : String(value);
  const negative = text.startsWith('-');
  const [integer, frac = ''] = text.replace('-', '').split('.');
  const cents = (frac + '00').slice(0, 2);
  const body = group(integer.replace(/^0+(?=\d)/, '')) + (cents !== '00' ? `,${cents}` : '');
  return `${negative ? '-' : ''}${symbol} ${body}`;
}

/** Cantidad: "2.5" -> "2,5"; "1000" -> "1.000". */
export function qty(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—';
  const text = String(value);
  const negative = text.startsWith('-');
  const [integer, frac] = text.replace('-', '').split('.');
  return `${negative ? '-' : ''}${group(integer)}${frac ? `,${frac}` : ''}`;
}

export function pct(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—';
  return `${String(value).replace('.', ',')} %`;
}

/** Normaliza lo que escribe una persona ("12.500", "12500,5") al formato que espera la API ("12500.5"). */
export function toApiNumber(text: string): string {
  const t = text.trim().replace(/\$|\s/g, '');
  if (!t) return '';
  if (t.includes(',') && t.includes('.')) {
    return t.lastIndexOf(',') > t.lastIndexOf('.') ? t.replace(/\./g, '').replace(',', '.') : t.replace(/,/g, '');
  }
  if (t.includes(',')) return (t.match(/,/g) ?? []).length > 1 ? t.replace(/,/g, '') : t.replace(',', '.');
  if (/^-?\d{1,3}(\.\d{3})+$/.test(t)) return t.replace(/\./g, '');
  return t;
}

/** Fecha de negocio "2026-10-24" -> "24/10/2026". */
export function date(value: string | null | undefined): string {
  if (!value) return '—';
  const [y, m, d] = value.slice(0, 10).split('-');
  return `${d}/${m}/${y}`;
}

/** Instante UTC -> fecha y hora en la zona de la empresa. */
export function dateTime(value: string | null | undefined): string {
  if (!value) return '—';
  return new Intl.DateTimeFormat('es-CO', {
    timeZone, day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  }).format(new Date(value));
}

export function today(): string {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' })
    .format(new Date());
  return parts;
}

export function daysFromToday(days: number): string {
  const d = new Date(`${today()}T12:00:00`);
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

export function monthStart(): string {
  return `${today().slice(0, 8)}01`;
}
