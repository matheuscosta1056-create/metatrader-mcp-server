#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Utility functions for MetaTrader MCP Server.

This module provides helper functions for common operations.
"""

import os
import numpy as np
import pandas as pd
import pytz
from datetime import datetime
from typing import List, Dict, Any, Optional, Union, Tuple


# Timezone of the broker's trade server. B3 brokers run on Brasília time.
# Override with the MT5_SERVER_TIMEZONE environment variable if needed.
DEFAULT_SERVER_TIMEZONE = "America/Sao_Paulo"


def get_server_timezone() -> str:
    return os.getenv("MT5_SERVER_TIMEZONE") or DEFAULT_SERVER_TIMEZONE


def server_time_to_local(value: Any, unit: str = "s") -> Any:
    """
    Convert MT5 timestamps to timezone-aware datetimes in the server timezone.

    MT5 returns times as seconds since epoch, but they encode the trade
    server's wall-clock time, not UTC. A position opened at 12:27 in
    Brasília comes back as the epoch value of 12:27 UTC. The correct
    conversion is therefore to read the value as a naive wall-clock time and
    attach the server timezone, never to convert from UTC.

    This is the single place where MT5 times are converted. It accepts a
    pandas Series or a scalar and returns the same kind.
    """
    tz = get_server_timezone()

    if isinstance(value, pd.Series):
        if value.empty:
            return value
        naive = pd.to_datetime(value, unit=unit)
        return naive.dt.tz_localize(
            tz,
            ambiguous=np.zeros(len(naive), dtype=bool),
            nonexistent="shift_forward",
        )

    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    return pd.Timestamp(int(value), unit=unit).tz_localize(
        tz, ambiguous=False, nonexistent="shift_forward"
    )


def convert_positions_to_dataframe(
    positions: Any,
    columns_mapping: Optional[Dict[str, str]] = None,
    sort_by: Optional[str] = "time",
    ascending: bool = False,
    enhance_order_types: bool = True
) -> pd.DataFrame:
    """
    Convert MetaTrader5 positions to a pandas DataFrame with selected fields.
    
    Args:
        positions: MetaTrader5 positions (tuple of named tuples)
        columns_mapping: Dictionary mapping original column names to new names
                        Default mapping handles common position fields
        sort_by: Column name to sort by (after renaming)
        ascending: Sort order (True for ascending, False for descending)
        enhance_order_types: Whether to convert numeric order types to human-readable strings
        
    Returns:
        pd.DataFrame: DataFrame with selected and renamed columns
    """
    # Return empty DataFrame if positions is None or empty
    if positions is None or len(positions) == 0:
        # Create empty DataFrame with expected columns
        default_columns = ['id', 'time', 'symbol', 'type', 'volume', 
                          'open', 'stop_loss', 'take_profit', 'profit']
        return pd.DataFrame(columns=default_columns)
    
    # Default columns mapping if not provided
    if columns_mapping is None:
        columns_mapping = {
            'ticket': 'id',
            'time': 'time',
            'symbol': 'symbol',
            'type': 'type',
            'volume': 'volume',
            'price_open': 'open',
            'sl': 'stop_loss',
            'tp': 'take_profit',
            'profit': 'profit'
        }
    
    # Convert named tuples to list of dictionaries
    positions_list = [position._asdict() for position in positions]
    
    # Create DataFrame from positions list
    df = pd.DataFrame(positions_list)
    
    # If DataFrame is empty, return empty DataFrame with expected columns
    if df.empty:
        return pd.DataFrame(columns=list(columns_mapping.values()))
    
    # Create a new DataFrame with only available columns
    result = pd.DataFrame()
    
    # Check each column and add it if available
    for original_col, new_col in columns_mapping.items():
        if original_col in df.columns:
            result[new_col] = df[original_col]
        else:
            # Add empty column for missing data
            result[new_col] = None
    
    # Convert time from MT5 time integer to DataFrame suitable time format
    if 'time' in result.columns and result['time'].notna().any():
        result['time'] = server_time_to_local(result['time'])

    # Pending orders carry an expiration time (0 means no expiration)
    if 'expiration' in result.columns and result['expiration'].notna().any():
        expiration = result['expiration']
        result['expiration'] = server_time_to_local(expiration.where(expiration > 0))
    
    # Sort the DataFrame if sort_by is provided
    if sort_by is not None and sort_by in result.columns:
        result = result.sort_values(by=sort_by, ascending=ascending)
    
    # Enhance order types if requested
    if enhance_order_types and 'type' in result.columns and not result.empty:
        result = enhance_dataframe_order_types(result)
    
    return result


def enhance_dataframe_order_types(
    df: pd.DataFrame,
    type_column: str = 'type',
    preserve_original: bool = True,
    original_column: str = 'type_code'
) -> pd.DataFrame:
    """
    Enhance a DataFrame by converting numeric order type codes to human-readable strings.
    
    Args:
        df: DataFrame containing order type codes
        type_column: Name of the column containing order type codes
        preserve_original: Whether to preserve the original numeric codes
        original_column: Name of the column to store original numeric codes if preserved
        
    Returns:
        pd.DataFrame: Enhanced DataFrame with human-readable order types
    """
    from .types import OrderType
    
    # Return original DataFrame if it's empty or doesn't have the type column
    if df.empty or type_column not in df.columns:
        return df
    
    # Create a copy to avoid modifying the original DataFrame
    result = df.copy()
    
    # Store original values if requested
    if preserve_original:
        result[original_column] = result[type_column]
    
    # Convert numeric codes to human-readable strings using our enhanced OrderType Enum
    result[type_column] = result[type_column].map(
        lambda x: OrderType.to_string(x) if pd.notna(x) else x
    )
    
    return result


def enhance_dataframe_order_states(
    df: pd.DataFrame,
    state_column: str = 'state',
    preserve_original: bool = True,
    original_column: str = 'state_code'
) -> pd.DataFrame:
    """
    Enhance a DataFrame by converting numeric order state codes to human-readable strings.
    
    Args:
        df: DataFrame containing order state codes
        state_column: Name of the column containing order state codes
        preserve_original: Whether to preserve the original numeric codes
        original_column: Name of the column to store original numeric codes if preserved
        
    Returns:
        pd.DataFrame: Enhanced DataFrame with human-readable order states
    """
    from .types import OrderState
    
    # Return original DataFrame if it's empty or doesn't have the state column
    if df.empty or state_column not in df.columns:
        return df
    
    # Create a copy to avoid modifying the original DataFrame
    result = df.copy()
    
    # Store original values if requested
    if preserve_original:
        result[original_column] = result[state_column]
    
    # Convert numeric codes to human-readable strings using our enhanced OrderState Enum
    result[state_column] = result[state_column].map(
        lambda x: OrderState.to_string(x) if pd.notna(x) else x
    )
    
    return result


def enhance_dataframe_order_filling(
    df: pd.DataFrame,
    filling_column: str = 'type_filling',
    preserve_original: bool = True,
    original_column: str = 'filling_code'
) -> pd.DataFrame:
    """
    Enhance a DataFrame by converting numeric order filling codes to human-readable strings.
    
    Args:
        df: DataFrame containing order filling codes
        filling_column: Name of the column containing order filling codes
        preserve_original: Whether to preserve the original numeric codes
        original_column: Name of the column to store original numeric codes if preserved
        
    Returns:
        pd.DataFrame: Enhanced DataFrame with human-readable order filling types
    """
    from .types import OrderFilling
    
    # Return original DataFrame if it's empty or doesn't have the filling column
    if df.empty or filling_column not in df.columns:
        return df
    
    # Create a copy to avoid modifying the original DataFrame
    result = df.copy()
    
    # Store original values if requested
    if preserve_original:
        result[original_column] = result[filling_column]
    
    # Convert numeric codes to human-readable strings using our enhanced OrderFilling Enum
    result[filling_column] = result[filling_column].map(
        lambda x: OrderFilling.to_string(x) if pd.notna(x) else x
    )
    
    return result


def enhance_dataframe_order_lifetime(
    df: pd.DataFrame,
    lifetime_column: str = 'type_time',
    preserve_original: bool = True,
    original_column: str = 'lifetime_code'
) -> pd.DataFrame:
    """
    Enhance a DataFrame by converting numeric order lifetime codes to human-readable strings.
    
    Args:
        df: DataFrame containing order lifetime codes
        lifetime_column: Name of the column containing order lifetime codes
        preserve_original: Whether to preserve the original numeric codes
        original_column: Name of the column to store original numeric codes if preserved
        
    Returns:
        pd.DataFrame: Enhanced DataFrame with human-readable order lifetime types
    """
    from .types import OrderTime
    
    # Return original DataFrame if it's empty or doesn't have the lifetime column
    if df.empty or lifetime_column not in df.columns:
        return df
    
    # Create a copy to avoid modifying the original DataFrame
    result = df.copy()
    
    # Store original values if requested
    if preserve_original:
        result[original_column] = result[lifetime_column]
    
    # Convert numeric codes to human-readable strings using our enhanced OrderTime Enum
    result[lifetime_column] = result[lifetime_column].map(
        lambda x: OrderTime.to_string(x) if pd.notna(x) else x
    )
    
    return result


def convert_orders_to_dataframe(
    orders: Any,
    columns_mapping: Optional[Dict[str, str]] = None,
    sort_by: Optional[str] = "time_setup",
    ascending: bool = False,
    enhance_order_types: bool = True,
    enhance_order_states: bool = True,
    enhance_order_filling: bool = True,
    enhance_order_lifetime: bool = True
) -> pd.DataFrame:
    """
    Convert MetaTrader5 pending orders to a pandas DataFrame with selected fields.
    
    Args:
        orders: MetaTrader5 orders (tuple of named tuples)
        columns_mapping: Dictionary mapping original column names to new names
                        Default mapping handles common order fields
        sort_by: Column name to sort by (after renaming)
        ascending: Sort order (True for ascending, False for descending)
        enhance_order_types: Whether to convert numeric order types to human-readable strings
        enhance_order_states: Whether to convert numeric order states to human-readable strings
        enhance_order_filling: Whether to convert numeric order filling types to human-readable strings
        enhance_order_lifetime: Whether to convert numeric order lifetime types to human-readable strings
        
    Returns:
        pd.DataFrame: DataFrame with selected and renamed columns
    """
    # Return empty DataFrame if orders is None or empty
    if orders is None or len(orders) == 0:
        # Create empty DataFrame with expected columns
        default_columns = ['id', 'time', 'symbol', 'type', 'volume', 
                          'open', 'stop_loss', 'take_profit', 'state', 'type_time', 'expiration']
        return pd.DataFrame(columns=default_columns)
    
    # Default columns mapping if not provided
    if columns_mapping is None:
        columns_mapping = {
            'ticket': 'id',
            'time_setup': 'time',
            'symbol': 'symbol',
            'type': 'type',
            'volume_current': 'volume',
            'price_open': 'open',
            'sl': 'stop_loss',
            'tp': 'take_profit',
            'state': 'state',
            'type_time': 'type_time',
            'type_filling': 'type_filling',
            'time_expiration': 'expiration'
        }
    
    # Use the existing conversion function with the specific mapping
    result = convert_positions_to_dataframe(
        orders,
        columns_mapping=columns_mapping,
        sort_by=sort_by,
        ascending=ascending,
        enhance_order_types=enhance_order_types
    )
    
    # Additionally enhance order states if requested
    if enhance_order_states and not result.empty and 'state' in result.columns:
        result = enhance_dataframe_order_states(result)
    
    # Additionally enhance order filling types if requested
    if enhance_order_filling and not result.empty and 'type_filling' in result.columns:
        result = enhance_dataframe_order_filling(result)
    
    # Additionally enhance order lifetime types if requested
    if enhance_order_lifetime and not result.empty and 'type_time' in result.columns:
        result = enhance_dataframe_order_lifetime(result)

    # Remove unnecessary fields
    for field in ['type_code', 'state_code', 'filling_code', 'lifetime_code']:
        if field in result.columns:
            result.drop(columns=[field], inplace=True)
    
    return result
