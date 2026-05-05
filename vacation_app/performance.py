"""Performance optimization utilities for the vacation app.

Provides caching, lazy-loading, and efficient data retrieval patterns.
"""

from datetime import date, timedelta
from typing import Optional

import streamlit as st

from vacation_app.calendar_utils import portugal_holidays as _portugal_holidays


@st.cache_data(ttl=3600)
def cached_portugal_holidays(year: int, municipality: str) -> dict[date, str]:
    """
    Cached version of portugal_holidays() with 1-hour TTL.
    
    Prevents expensive holiday calculations on every render.
    Automatically invalidates after 1 hour or on cache clear.
    
    Args:
        year: Year for holiday calculation
        municipality: Municipality name for local holiday
        
    Returns:
        Dict mapping date to holiday name
    """
    return _portugal_holidays(year, municipality)


def lazy_load_vacations(
    vacations: list[dict],
    current_date: Optional[date] = None,
    months_before: int = 1,
    months_after: int = 1,
) -> list[dict]:
    """
    Filter vacation data to current month ± nearby months.
    
    Reduces memory usage and computation when working with large datasets.
    Useful for calendar views where you only need nearby periods.
    
    Args:
        vacations: Full list of vacation records
        current_date: Reference date (defaults to today)
        months_before: Include months before current
        months_after: Include months after current
        
    Returns:
        Filtered list of vacations in the relevant period
    """
    if not vacations:
        return []
    
    if current_date is None:
        current_date = date.today()
    
    # Calculate period bounds
    year = current_date.year
    month = current_date.month
    
    # First day of range
    start_month = month - months_before
    start_year = year
    if start_month < 1:
        start_month += 12
        start_year -= 1
    start = date(start_year, start_month, 1)
    
    # Last day of range
    end_month = month + months_after
    end_year = year
    if end_month > 12:
        end_month -= 12
        end_year += 1
    # First day of next month minus one day = last day of target month
    next_month = end_month + 1 if end_month < 12 else 1
    next_year = end_year if end_month < 12 else end_year + 1
    last_day = date(next_year, next_month, 1) - timedelta(days=1)
    end = last_day
    
    # Filter vacations with overlapping dates
    filtered = [
        v for v in vacations
        if v.get("start_date") and v.get("end_date") and not (
            v["end_date"] < start or v["start_date"] > end
        )
    ]
    
    return filtered


def optimize_dataframe_display(df, hide_index: bool = True, max_rows: Optional[int] = None) -> None:
    """
    Display DataFrame with performance optimizations.
    
    Uses Streamlit's built-in optimizations for large tables.
    
    Args:
        df: Pandas DataFrame to display
        hide_index: Hide row index column
        max_rows: Limit displayed rows (None = no limit)
    """
    kwargs = {
        "use_container_width": True,
        "hide_index": hide_index,
    }
    
    if max_rows is not None:
        # Paginate large tables
        st.dataframe(df.head(max_rows), **kwargs)
        if len(df) > max_rows:
            st.caption(f"Mostrando primeiras {max_rows} de {len(df)} registos")
    else:
        st.dataframe(df, **kwargs)


@st.cache_data
def build_months_list(start_date: date, end_date: date) -> list[tuple[int, int]]:
    """
    Cache month list for period navigation.
    
    Returns list of (year, month) tuples for efficient nav.
    """
    months = []
    current = start_date.replace(day=1)
    end = end_date.replace(day=1)
    
    while current <= end:
        months.append((current.year, current.month))
        # Move to next month
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)
    
    return months


def profile_metric(label: str, value: str | int | float, delta: Optional[str] = None) -> None:
    """
    Display a metric with optional delta for performance monitoring.
    
    Useful for showing cache hit rates, load times, etc.
    """
    col1, col2 = st.columns(2)
    with col1:
        st.metric(label, value)
    if delta:
        with col2:
            st.caption(delta)
