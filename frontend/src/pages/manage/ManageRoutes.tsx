import { Activity, ArrowLeft, BarChart3, Building2, CreditCard, DatabaseBackup, FileSpreadsheet, FolderSync, Printer, ShieldCheck,
  SlidersHorizontal, Tags, Truck, Users, UserSquare2 } from 'lucide-react';
import type { ReactNode } from 'react';
import { Link, Route, Routes } from 'react-router-dom';
import { RequirePermission } from '../../App';
import { PageHeader } from '../../components/ui/Layout';
import { useAuth } from '../../context/Auth';
import { ActivityPage, ReportsPage } from './Activity';
import { BackupsPage } from './Backups';
import { CategoriesPage, PartiesPage, PaymentMethodsPage } from './Catalogs';
import { DocumentTypesPage } from './DocumentTypes';
import { IntegrationsPage } from './Integrations';
import { CompanyPage, PrintingPage, SettingsSection } from './Settings';
import { UsersPage } from './Users';

interface Item { to: string; title: string; desc: string; icon: ReactNode; perms: string[]; group: string }

export const MANAGE_ITEMS: Item[] = [
  { to: 'usuarios', title: 'Usuarios y permisos', desc: 'Cuentas, roles, permisos y bloqueos.', icon: <Users size={28} />, perms: ['gestion.usuarios'], group: 'Personas' },
  { to: 'clientes', title: 'Clientes', desc: 'Datos de clientes y días de crédito.', icon: <UserSquare2 size={28} />, perms: ['terceros.gestionar'], group: 'Personas' },
  { to: 'proveedores', title: 'Proveedores', desc: 'Datos de proveedores y plazos de pago.', icon: <Truck size={28} />, perms: ['terceros.gestionar'], group: 'Personas' },
  { to: 'categorias', title: 'Categorías de productos', desc: 'Agrupe el inventario para filtrar y reportar.', icon: <Tags size={28} />, perms: ['gestion.configuracion'], group: 'Operación' },
  { to: 'documentos', title: 'Tipos de documento y plantillas', desc: 'Cotizaciones, órdenes y otros documentos en Excel.', icon: <FileSpreadsheet size={28} />, perms: ['gestion.configuracion'], group: 'Operación' },
  { to: 'metodos-pago', title: 'Métodos de pago', desc: 'Efectivo, tarjeta, transferencia, crédito.', icon: <CreditCard size={28} />, perms: ['gestion.configuracion'], group: 'Operación' },
  { to: 'parametros', title: 'Ventas e inventario', desc: 'IVA, descuentos y reglas de existencias.', icon: <SlidersHorizontal size={28} />, perms: ['gestion.configuracion'], group: 'Operación' },
  { to: 'impresion', title: 'Impresión', desc: 'Impresora DIGITALPOS, papel y comprobantes.', icon: <Printer size={28} />, perms: ['gestion.configuracion'], group: 'Operación' },
  { to: 'integraciones', title: 'Integraciones de inventario', desc: 'Excel, carpeta de red, OneDrive y Google Drive.', icon: <FolderSync size={28} />, perms: ['gestion.integraciones'], group: 'Sistema' },
  { to: 'empresa', title: 'Empresa', desc: 'Nombre, logotipo, colores y datos de documentos.', icon: <Building2 size={28} />, perms: ['gestion.configuracion'], group: 'Sistema' },
  { to: 'seguridad', title: 'Sesiones y seguridad', desc: 'Inactividad, duración y bloqueos.', icon: <ShieldCheck size={28} />, perms: ['gestion.configuracion'], group: 'Sistema' },
  { to: 'respaldos', title: 'Copias de seguridad', desc: 'Crear, verificar, descargar y restaurar.', icon: <DatabaseBackup size={28} />, perms: ['gestion.respaldos'], group: 'Sistema' },
  { to: 'actividad', title: 'Historial de actividad', desc: 'Quién hizo qué y cuándo.', icon: <Activity size={28} />, perms: ['gestion.auditoria'], group: 'Sistema' },
  { to: 'reportes', title: 'Reportes operativos', desc: 'Ventas por día, productos y vendedores.', icon: <BarChart3 size={28} />, perms: ['gestion.auditoria'], group: 'Sistema' },
];

function Hub() {
  const { canAny } = useAuth();
  const visible = MANAGE_ITEMS.filter((i) => canAny(...i.perms));
  const groups = [...new Set(visible.map((i) => i.group))];
  return (
    <>
      <PageHeader title="Gestión" description="Administración de la empresa, personas, documentos y sistema." />
      {groups.map((g) => (
        <section key={g} className="stack">
          <h2>{g}</h2>
          <div className="tiles">
            {visible.filter((i) => i.group === g).map((i) => (
              <Link key={i.to} to={i.to} className="tile">
                <span className="tile-icon" aria-hidden>{i.icon}</span>
                <span><span className="tile-name">{i.title}</span><p className="tile-desc">{i.desc}</p></span>
              </Link>
            ))}
          </div>
        </section>
      ))}
    </>
  );
}

export function ManageBack({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return (
    <>
      <Link to="/gestion" className="btn btn-ghost" style={{ alignSelf: 'flex-start' }}><ArrowLeft size={20} aria-hidden /> Gestión</Link>
      <PageHeader title={title} description={description} actions={actions} />
    </>
  );
}

const guard = (to: string, el: ReactNode) => {
  const item = MANAGE_ITEMS.find((i) => i.to === to)!;
  return <RequirePermission any={item.perms}>{el}</RequirePermission>;
};

export default function ManageRoutes() {
  return (
    <Routes>
      <Route index element={<Hub />} />
      <Route path="usuarios" element={guard('usuarios', <UsersPage />)} />
      <Route path="clientes" element={guard('clientes', <PartiesPage kind="clientes" />)} />
      <Route path="proveedores" element={guard('proveedores', <PartiesPage kind="proveedores" />)} />
      <Route path="categorias" element={guard('categorias', <CategoriesPage />)} />
      <Route path="documentos/*" element={guard('documentos', <DocumentTypesPage />)} />
      <Route path="metodos-pago" element={guard('metodos-pago', <PaymentMethodsPage />)} />
      <Route path="parametros" element={guard('parametros', (
        <div className="stack"><ManageBack title="Ventas e inventario" />
          <SettingsSection section="ventas" /><SettingsSection section="inventario" /></div>))} />
      <Route path="impresion" element={guard('impresion', <PrintingPage />)} />
      <Route path="integraciones/*" element={guard('integraciones', <IntegrationsPage />)} />
      <Route path="empresa" element={guard('empresa', <CompanyPage />)} />
      <Route path="seguridad" element={guard('seguridad', (
        <div className="stack"><ManageBack title="Sesiones y seguridad" /><SettingsSection section="seguridad" /></div>))} />
      <Route path="respaldos" element={guard('respaldos', <BackupsPage />)} />
      <Route path="actividad" element={guard('actividad', <ActivityPage />)} />
      <Route path="reportes" element={guard('reportes', <ReportsPage />)} />
    </Routes>
  );
}
