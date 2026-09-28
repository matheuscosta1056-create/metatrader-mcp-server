from typing import Union, Optional, Tuple

import MetaTrader5 as mt5

from ..types import TradeRequestActions
from .send_order import send_order
from .modify_position import modify_position


def _get_execution(result, symbol: str) -> Tuple[Optional[int], float]:
    """
    Find the position ticket and the real execution price of a market order.

    The deal carries both. On a netting account there is at most one
    position per symbol, so fall back to that when the deal is not found yet.
    """
    position_id = None
    price = float(getattr(result, "price", 0) or 0)

    deal_ticket = getattr(result, "deal", 0)
    if deal_ticket:
        deals = mt5.history_deals_get(ticket=deal_ticket)
        if deals:
            position_id = int(getattr(deals[0], "position_id", 0)) or None
            price = float(getattr(deals[0], "price", 0) or 0) or price

    if position_id is None:
        positions = mt5.positions_get(symbol=symbol)
        if positions and len(positions) == 1:
            position_id = int(positions[0].ticket)

    return position_id, price


def place_market_order(
    connection,
    *,
    type: str,
    symbol: str,
    volume: Union[float, int],
    stop_loss: Optional[float] = 0.0,
    take_profit: Optional[float] = 0.0,
    stop_points: Optional[float] = None,
    take_points: Optional[float] = None,
):
    """
    Places a market order for a specified financial instrument.

    The order is sent without SL/TP. When protection is requested, it is
    applied afterwards with TRADE_ACTION_SLTP based on the real execution
    price, and the position is read again to confirm SL/TP were stored.

    Args:
        connection: The MetaTrader 5 connection object.
        type: The type of market order, either "BUY" or "SELL".
        symbol: The trading instrument symbol (e.g., "WINZ25").
        volume: The volume of the trade operation in lots.
        stop_loss: Optional stop loss price.
        take_profit: Optional take profit price.
        stop_points: Optional stop loss distance from the execution price,
            in price units (e.g. 200 on WIN, 10 on WDO). Overrides stop_loss.
        take_points: Optional take profit distance from the execution price,
            in price units. Overrides take_profit.

    Returns:
        dict: A dictionary containing the result of the order operation. Includes an error flag,
              a message detailing the success or failure, and the data from the response.
    """

    type = type.upper()

    if type not in ["BUY", "SELL"]:
        return { "error": True, "message": f"Invalid type, should be BUY or SELL.", "data": None }

    for name, value in (("stop_points", stop_points), ("take_points", take_points)):
        if value is not None and value <= 0:
            return { "error": True, "message": f"Invalid {name} {value}, should be greater than 0.", "data": None }

    response = send_order(
        connection,
        action=TradeRequestActions.DEAL,
        order_type=type,
        symbol=symbol,
        volume=volume,
    )

    if response["success"] is False:
        return { "error": True, "message": response["message"], "data": None }

    data = response["data"]
    wants_protection = bool(stop_points or take_points or stop_loss or take_profit)
    if not wants_protection:
        return { "error": False, "message": f"{type} {symbol} {data.volume} LOT at {data.price} success (Order ID: {data.order})", "data": data }

    position_id, price = _get_execution(data, symbol)
    message = f"{type} {symbol} {data.volume} LOT at {price} success"
    if position_id is None:
        return {
            "error": True,
            "message": f"{message}, but the position was not found. The position may be OPEN WITHOUT PROTECTION (SL/TP not applied). Order ID: {data.order}",
            "data": data,
        }

    positions = mt5.positions_get(ticket=position_id)
    position_type = "BUY" if positions and positions[0].type == mt5.POSITION_TYPE_BUY else "SELL"
    if positions and position_type != type:
        return {
            "error": True,
            "message": f"{message}, but position {position_id} is now {position_type} (the order reduced an opposite position). SL/TP were NOT applied, position {position_id} is OPEN WITHOUT the requested protection.",
            "data": data,
        }

    if (stop_points or take_points) and not price:
        return {
            "error": True,
            "message": f"{message}, but the execution price is unknown. SL/TP were NOT applied, position {position_id} is OPEN WITHOUT PROTECTION.",
            "data": data,
        }

    direction = 1 if type == "BUY" else -1
    sl = price - direction * float(stop_points) if stop_points else (stop_loss or 0.0)
    tp = price + direction * float(take_points) if take_points else (take_profit or 0.0)

    protection = modify_position(connection, position_id, stop_loss=sl, take_profit=tp)
    if protection["error"]:
        return {
            "error": True,
            "message": f"{message}, but protection FAILED: position {position_id} is OPEN WITHOUT PROTECTION (SL/TP not confirmed). {protection['message']}",
            "data": protection["data"] or data,
        }

    return {
        "error": False,
        "message": f"{message} (Position ID: {position_id}), SL at {protection['data']['sl']}, TP at {protection['data']['tp']}",
        "data": protection["data"],
    }
