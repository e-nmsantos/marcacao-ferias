import { VacationRequest, VacationStatus } from '../App';
import { format } from 'date-fns';
import { pt } from 'date-fns/locale';
import { Check, X, Clock, Trash2 } from 'lucide-react';

interface VacationListProps {
  vacations: VacationRequest[];
  onUpdateStatus: (id: string, status: VacationStatus) => void;
  onDelete: (id: string) => void;
}

export function VacationList({ vacations, onUpdateStatus, onDelete }: VacationListProps) {
  const getStatusColor = (status: VacationStatus) => {
    switch (status) {
      case 'approved':
        return 'bg-green-100 text-green-800';
      case 'rejected':
        return 'bg-red-100 text-red-800';
      case 'pending':
        return 'bg-orange-100 text-orange-800';
    }
  };

  const getStatusText = (status: VacationStatus) => {
    switch (status) {
      case 'approved':
        return 'Aprovado';
      case 'rejected':
        return 'Rejeitado';
      case 'pending':
        return 'Pendente';
    }
  };

  const calculateDays = (start: Date, end: Date) => {
    const diffTime = end.getTime() - start.getTime();
    if (diffTime < 0) return null;
    return Math.floor(diffTime / (1000 * 60 * 60 * 24)) + 1;
  };

  const sortedVacations = [...vacations].sort((a, b) => {
    if (a.status === 'pending' && b.status !== 'pending') return -1;
    if (a.status !== 'pending' && b.status === 'pending') return 1;
    return b.requestedAt.getTime() - a.requestedAt.getTime();
  });

  return (
    <div className="space-y-4">
      {sortedVacations.length === 0 ? (
        <div className="text-center py-12">
          <Clock className="w-12 h-12 text-gray-400 mx-auto mb-3" />
          <p className="text-gray-600">Ainda não existem pedidos de férias</p>
        </div>
      ) : (
        sortedVacations.map(vacation => {
          const duration = calculateDays(vacation.startDate, vacation.endDate);

          return (
            <div
              key={vacation.id}
              className="p-4 border border-gray-200 rounded-lg hover:shadow-md transition-shadow"
            >
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-3 mb-2">
                    <h3 className="font-semibold text-gray-900">{vacation.employeeName}</h3>
                    <span
                      className={`px-3 py-1 rounded-full text-xs font-medium ${getStatusColor(
                        vacation.status
                      )}`}
                    >
                      {getStatusText(vacation.status)}
                    </span>
                  </div>
                  <div className="space-y-1 text-sm text-gray-600">
                    <p>
                      <span className="font-medium">Período:</span>{' '}
                      {format(vacation.startDate, "d 'de' MMMM", { locale: pt })} até{' '}
                      {format(vacation.endDate, "d 'de' MMMM 'de' yyyy", { locale: pt })}
                    </p>
                    <p>
                      <span className="font-medium">Duração:</span>{' '}
                      {duration === null ? 'Intervalo inválido' : `${duration} dias`}
                    </p>
                    {vacation.reason && (
                      <p>
                        <span className="font-medium">Motivo:</span> {vacation.reason}
                      </p>
                    )}
                    <p className="text-xs text-gray-500">
                      Pedido em {format(vacation.requestedAt, "d 'de' MMMM 'às' HH:mm", { locale: pt })}
                    </p>
                  </div>
                </div>
                <div className="flex gap-2 ml-4">
                  {vacation.status === 'pending' && (
                    <>
                      <button
                        onClick={() => onUpdateStatus(vacation.id, 'approved')}
                        className="p-2 text-green-600 hover:bg-green-50 rounded-lg transition-colors"
                        title="Aprovar"
                      >
                        <Check className="w-5 h-5" />
                      </button>
                      <button
                        onClick={() => onUpdateStatus(vacation.id, 'rejected')}
                        className="p-2 text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                        title="Rejeitar"
                      >
                        <X className="w-5 h-5" />
                      </button>
                    </>
                  )}
                  <button
                    onClick={() => onDelete(vacation.id)}
                    className="p-2 text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
                    title="Eliminar"
                  >
                    <Trash2 className="w-5 h-5" />
                  </button>
                </div>
              </div>
            </div>
          );
        })
      )}
    </div>
  );
}
