from .get_all_positions import get_all_positions
from .close_position import close_position
from ._batch import run_batch

def close_all_positions(connection):
    """
    Close all open positions.

    Args:
        connection: The connection object to the MetaTrader platform.

    Returns:
        A dictionary containing an error flag, a message, and the number of positions closed.
    """
    positions = get_all_positions(connection)
    return run_batch(positions["id"], lambda id: close_position(connection, id), "Close all positions")
