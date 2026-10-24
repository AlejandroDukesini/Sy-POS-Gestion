import { FileText, History, ShoppingCart } from 'lucide-react';
import { lazy } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { LinkTabs } from '../../components/ui/Layout';
import { useAuth } from '../../context/Auth';
import { SaleDetail, SalesHistory } from './SalesHistory';

const PosPage = lazy(() => import('./PosPage'));
const DocumentsPage = lazy(() => import('./DocumentsPage'));

export default function SellPage() {
  const { can } = useAuth();
  const tabs = [
    ...(can('ventas.vender') ? [{ to: '/vender', label: 'Punto de venta', end: true, icon: <ShoppingCart size={20} aria-hidden /> }] : []),
    ...(can('documentos.ver') ? [{ to: '/vender/documentos', label: 'Cotizaciones y órdenes', icon: <FileText size={20} aria-hidden /> }] : []),
    ...(can('ventas.historial') ? [{ to: '/vender/historial', label: 'Historial', icon: <History size={20} aria-hidden /> }] : []),
  ];
  const first = tabs[0]?.to ?? '/';
  return (
    <>
      <LinkTabs label="Secciones de ventas" tabs={tabs} />
      <Routes>
        <Route index element={can('ventas.vender') ? <PosPage /> : <Navigate to={first} replace />} />
        <Route path="documentos/*" element={<DocumentsPage />} />
        <Route path="historial" element={<SalesHistory />} />
        <Route path="historial/:id" element={<SaleDetail />} />
      </Routes>
    </>
  );
}
