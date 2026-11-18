import { Navigate, Route, Routes } from 'react-router-dom';
import { LinkTabs, PageHeader } from '../../components/ui/Layout';
import { useAuth } from '../../context/Auth';
import NotesTab from './NotesTab';
import { TaskBoard } from './TaskBoard';

export { TASK_STATUS } from './TaskBoard';

/** Notas y tareas: notas personales, tareas personales y tareas asignadas (con o sin grupo de trabajo). */
export default function TasksPage() {
  const { can } = useAuth();
  const manager = can('tareas.gestionar');
  return (
    <div className="stack">
      <PageHeader title="Notas y tareas" description={manager
        ? 'Sus notas y tareas personales, y las tareas que asigna a los integrantes de sus grupos.'
        : 'Sus notas, sus tareas personales y las tareas que le asignaron.'} />
      <LinkTabs label="Apartados" tabs={[
        { to: '/tareas/notas', label: 'Mis notas' },
        { to: '/tareas/mias', label: 'Mis tareas' },
        { to: '/tareas/asignadas', label: manager ? 'Tareas asignadas' : 'Asignadas a mí' },
      ]} />
      <Routes>
        <Route index element={<Navigate to="asignadas" replace />} />
        <Route path="notas" element={<NotesTab />} />
        <Route path="mias" element={<TaskBoard key="personal" kind="personal" />} />
        <Route path="asignadas" element={<TaskBoard key="asignadas" kind="asignadas" />} />
        <Route path="*" element={<Navigate to="/tareas" replace />} />
      </Routes>
    </div>
  );
}
