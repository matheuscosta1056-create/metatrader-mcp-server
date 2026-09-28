from .get_all_pending_orders import get_all_pending_orders
from .cancel_pending_order import cancel_pending_order
from ._batch import run_batch

def cancel_all_pending_orders(connection):
    """
    Cancels all pending orders.

    :param connection: MetaTrader 5 connection object.
    :return: A dictionary with the result of the operation.
    """
    pending_orders = get_all_pending_orders(connection)
    return run_batch(pending_orders["id"], lambda id: cancel_pending_order(connection, id), "Cancel all pending orders")
