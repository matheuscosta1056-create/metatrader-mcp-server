from .get_pending_orders_by_symbol import get_pending_orders_by_symbol
from .cancel_pending_order import cancel_pending_order
from ._batch import run_batch

def cancel_pending_orders_by_symbol(connection, symbol: str):
    """
    Cancel all pending orders with the given symbol name.

    Args:
        connection: The connection object to the MetaTrader platform.
        symbol: The symbol name of the orders to be canceled.

    Returns:
        A dictionary with an error flag, a message, and the order data if
        successful.
    """
    pending_orders = get_pending_orders_by_symbol(connection, symbol)
    return run_batch(pending_orders["id"], lambda id: cancel_pending_order(connection, id), f"Cancel {symbol} pending orders")
