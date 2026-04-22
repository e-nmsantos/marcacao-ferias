import { VacationRequest } from '../App';
import { format, eachDayOfInterval, isSameDay, startOfMonth, endOfMonth, startOfWeek, endOfWeek, addMonths, subMonths } from 'date-fns';
import { pt } from 'date-fns/locale';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { useState, useMemo } from 'react';

interface VacationCalendarProps {
  vacations: VacationRequest[];
}

export function VacationCalendar({ vacations }: VacationCalendarProps) {
  const [currentMonth, setCurrentMonth] = useState(new Date());
  const today = new Date();

  const monthStart = startOfMonth(currentMonth);
  const monthEnd = endOfMonth(currentMonth);
  const calendarStart = startOfWeek(monthStart, { weekStartsOn: 1 });
  const calendarEnd = endOfWeek(monthEnd, { weekStartsOn: 1 });

  const days = eachDayOfInterval({ start: calendarStart, end: calendarEnd });
  const weekDays = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom'];

  const vacationsByDay = useMemo(() => {
    const map = new Map<string, VacationRequest[]>();
    for (const vacation of vacations) {
      if (vacation.status !== 'approved') continue;
      if (vacation.endDate < vacation.startDate) continue;
      const vacationDays = eachDayOfInterval({ start: vacation.startDate, end: vacation.endDate });
      for (const day of vacationDays) {
        const key = format(day, 'yyyy-MM-dd');
        if (!map.has(key)) map.set(key, []);
        map.get(key)!.push(vacation);
      }
    }
    return map;
  }, [vacations]);

  const getVacationsForDay = (day: Date) => vacationsByDay.get(format(day, 'yyyy-MM-dd')) ?? [];

  const isCurrentMonth = (day: Date) => {
    return day.getMonth() === currentMonth.getMonth();
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-semibold text-gray-900">
          {format(currentMonth, 'MMMM yyyy', { locale: pt })}
        </h2>
        <div className="flex gap-2">
          <button
            onClick={() => setCurrentMonth(subMonths(currentMonth, 1))}
            className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
          >
            <ChevronLeft className="w-5 h-5" />
          </button>
          <button
            onClick={() => setCurrentMonth(today)}
            className="px-4 py-2 hover:bg-gray-100 rounded-lg transition-colors text-sm font-medium"
          >
            Hoje
          </button>
          <button
            onClick={() => setCurrentMonth(addMonths(currentMonth, 1))}
            className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
          >
            <ChevronRight className="w-5 h-5" />
          </button>
        </div>
      </div>

      <div className="grid grid-cols-7 gap-2">
        {weekDays.map(day => (
          <div key={day} className="text-center text-sm font-semibold text-gray-600 py-2">
            {day}
          </div>
        ))}
        {days.map((day, index) => {
          const dayVacations = getVacationsForDay(day);
          const isToday = isSameDay(day, today);

          return (
            <div
              key={index}
              className={`min-h-24 p-2 border rounded-lg ${
                isCurrentMonth(day) ? 'bg-white' : 'bg-gray-50'
              } ${isToday ? 'ring-2 ring-blue-600' : ''}`}
            >
              <div
                className={`text-sm font-medium mb-1 ${
                  isCurrentMonth(day) ? 'text-gray-900' : 'text-gray-400'
                } ${isToday ? 'text-blue-600' : ''}`}
              >
                {format(day, 'd')}
              </div>
              <div className="space-y-1">
                {dayVacations.slice(0, 2).map(vacation => (
                  <div
                    key={vacation.id}
                    className="text-xs px-2 py-1 bg-blue-100 text-blue-800 rounded truncate"
                    title={vacation.employeeName}
                  >
                    {vacation.employeeName}
                  </div>
                ))}
                {dayVacations.length > 2 && (
                  <div className="text-xs px-2 py-1 bg-gray-100 text-gray-600 rounded text-center">
                    +{dayVacations.length - 2} mais
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-6 p-4 bg-gray-50 rounded-lg">
        <h3 className="font-semibold text-gray-900 mb-3">Legenda</h3>
        <div className="flex flex-wrap gap-4">
          <div className="flex items-center gap-2">
            <div className="w-4 h-4 bg-blue-100 border border-blue-200 rounded"></div>
            <span className="text-sm text-gray-700">Férias aprovadas</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-4 h-4 ring-2 ring-blue-600 rounded"></div>
            <span className="text-sm text-gray-700">Hoje</span>
          </div>
        </div>
      </div>
    </div>
  );
}
