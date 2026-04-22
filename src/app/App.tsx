import { useState, useEffect } from 'react';
import { Calendar, Users, Plus, Check, X, Clock } from 'lucide-react';
import { VacationCalendar } from './components/VacationCalendar';
import { VacationForm } from './components/VacationForm';
import { VacationList } from './components/VacationList';

export type VacationStatus = 'pending' | 'approved' | 'rejected';

export interface VacationRequest {
  id: string;
  employeeName: string;
  startDate: Date;
  endDate: Date;
  status: VacationStatus;
  reason?: string;
  requestedAt: Date;
}

const STORAGE_KEY = 'vacation-requests';

function parseDateInput(value: string): Date {
  const [year, month, day] = value.split('-').map(Number);
  return new Date(year, month - 1, day, 12, 0, 0, 0);
}

function formatDateInput(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

const DEFAULT_VACATIONS: VacationRequest[] = [
  {
    id: '1',
    employeeName: 'Maria Silva',
    startDate: new Date(2026, 3, 25),
    endDate: new Date(2026, 4, 2),
    status: 'approved',
    reason: 'Férias de verão',
    requestedAt: new Date(2026, 2, 15),
  },
  {
    id: '2',
    employeeName: 'João Santos',
    startDate: new Date(2026, 4, 10),
    endDate: new Date(2026, 4, 17),
    status: 'pending',
    reason: 'Viagem familiar',
    requestedAt: new Date(2026, 3, 20),
  },
  {
    id: '3',
    employeeName: 'Ana Costa',
    startDate: new Date(2026, 5, 1),
    endDate: new Date(2026, 5, 15),
    status: 'approved',
    requestedAt: new Date(2026, 3, 10),
  },
];

function serializeVacations(vacations: VacationRequest[]): string {
  return JSON.stringify(vacations.map(v => ({
    ...v,
    startDate: formatDateInput(v.startDate),
    endDate: formatDateInput(v.endDate),
    requestedAt: v.requestedAt.toISOString(),
  })));
}

function deserializeVacations(json: string): VacationRequest[] {
  try {
    const data = JSON.parse(json);
    return (data as Record<string, unknown>[]).map(v => ({
      ...(v as Omit<VacationRequest, 'startDate' | 'endDate' | 'requestedAt'>),
      startDate: parseDateInput(v.startDate as string),
      endDate: parseDateInput(v.endDate as string),
      requestedAt: new Date(v.requestedAt as string),
    }));
  } catch {
    return [];
  }
}

function loadVacations(): VacationRequest[] {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (!stored) return [...DEFAULT_VACATIONS];
  const loaded = deserializeVacations(stored);
  return loaded.length > 0 ? loaded : [...DEFAULT_VACATIONS];
}

export default function App() {
  const [activeTab, setActiveTab] = useState<'calendar' | 'requests'>('calendar');
  const [showForm, setShowForm] = useState(false);
  const [vacations, setVacations] = useState<VacationRequest[]>(loadVacations);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, serializeVacations(vacations));
  }, [vacations]);

  const handleAddVacation = (vacation: Omit<VacationRequest, 'id' | 'status' | 'requestedAt'>) => {
    const newVacation: VacationRequest = {
      ...vacation,
      id: Date.now().toString(),
      status: 'pending',
      requestedAt: new Date(),
    };
    setVacations([...vacations, newVacation]);
    setShowForm(false);
  };

  const handleUpdateStatus = (id: string, status: VacationStatus) => {
    setVacations(vacations.map(v => v.id === id ? { ...v, status } : v));
  };

  const handleDeleteVacation = (id: string) => {
    setVacations(vacations.filter(v => v.id !== id));
  };

  const stats = {
    total: vacations.length,
    pending: vacations.filter(v => v.status === 'pending').length,
    approved: vacations.filter(v => v.status === 'approved').length,
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white shadow-sm border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 py-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-blue-600 rounded-lg">
                <Users className="w-6 h-6 text-white" />
              </div>
              <div>
                <h1 className="text-2xl font-bold text-gray-900">Gestão de Férias</h1>
                <p className="text-sm text-gray-600">Organize as férias da sua equipa</p>
              </div>
            </div>
            <button
              onClick={() => setShowForm(true)}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
            >
              <Plus className="w-5 h-5" />
              Novo Pedido
            </button>
          </div>
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-4 py-8">
        <div className="grid grid-cols-3 gap-4 mb-8">
          <div className="bg-white p-6 rounded-lg shadow-sm border border-gray-200">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-600">Total de Pedidos</p>
                <p className="text-3xl font-bold text-gray-900 mt-1">{stats.total}</p>
              </div>
              <Calendar className="w-10 h-10 text-blue-600" />
            </div>
          </div>
          <div className="bg-white p-6 rounded-lg shadow-sm border border-gray-200">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-600">Pendentes</p>
                <p className="text-3xl font-bold text-orange-600 mt-1">{stats.pending}</p>
              </div>
              <Clock className="w-10 h-10 text-orange-600" />
            </div>
          </div>
          <div className="bg-white p-6 rounded-lg shadow-sm border border-gray-200">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-600">Aprovados</p>
                <p className="text-3xl font-bold text-green-600 mt-1">{stats.approved}</p>
              </div>
              <Check className="w-10 h-10 text-green-600" />
            </div>
          </div>
        </div>

        <div className="bg-white rounded-lg shadow-sm border border-gray-200">
          <div className="border-b border-gray-200">
            <div className="flex">
              <button
                onClick={() => setActiveTab('calendar')}
                className={`px-6 py-4 font-medium transition-colors ${
                  activeTab === 'calendar'
                    ? 'text-blue-600 border-b-2 border-blue-600'
                    : 'text-gray-600 hover:text-gray-900'
                }`}
              >
                <div className="flex items-center gap-2">
                  <Calendar className="w-5 h-5" />
                  Calendário
                </div>
              </button>
              <button
                onClick={() => setActiveTab('requests')}
                className={`px-6 py-4 font-medium transition-colors ${
                  activeTab === 'requests'
                    ? 'text-blue-600 border-b-2 border-blue-600'
                    : 'text-gray-600 hover:text-gray-900'
                }`}
              >
                <div className="flex items-center gap-2">
                  <Users className="w-5 h-5" />
                  Pedidos
                </div>
              </button>
            </div>
          </div>

          <div className="p-6">
            {activeTab === 'calendar' ? (
              <VacationCalendar vacations={vacations} />
            ) : (
              <VacationList
                vacations={vacations}
                onUpdateStatus={handleUpdateStatus}
                onDelete={handleDeleteVacation}
              />
            )}
          </div>
        </div>
      </div>

      {showForm && (
        <VacationForm
          onSubmit={handleAddVacation}
          onClose={() => setShowForm(false)}
        />
      )}
    </div>
  );
}
