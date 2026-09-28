import math
from typing import Optional, Union

import MetaTrader5 as mt5

from ..types import TradeRequestActions
from ..utils import server_time_to_local
from .send_order import send_order


def round_to_tick(price: float, symbol_info) -> float:
	"""
	Round a price to the symbol's tick size (e.g. 5 on WIN, 0.5 on WDO).
	"""
	tick_size = getattr(symbol_info, "trade_tick_size", 0) or getattr(symbol_info, "point", 0)
	digits = getattr(symbol_info, "digits", 5)
	if not tick_size:
		return round(float(price), digits)
	return round(round(float(price) / tick_size) * tick_size, digits)


def position_to_dict(position) -> dict:
	"""
	Convert an MT5 position to a dict with times in the server timezone.
	"""
	data = position._asdict()
	for key in ("time", "time_update"):
		if data.get(key):
			data[key] = server_time_to_local(data[key]).isoformat()
	for key in ("time_msc", "time_update_msc"):
		data.pop(key, None)
	return data


def modify_position(
	connection,
	id: Union[str, int],
	*,
	stop_loss: Optional[Union[int, float]] = None,
	take_profit: Optional[Union[int, float]] = None,
):
	"""
	Modify an existing position's stop loss and take profit levels.

	The position is looked up by ticket, SL and TP are rounded to the
	symbol's tick size and checked against the position side (for a BUY the
	SL must be below the current price and the TP above it, the opposite
	for a SELL). After the server accepts the request, the position is read
	again to confirm that SL and TP were stored.

	Args:
		connection: The connection object to the MetaTrader platform.
		id: The unique identifier (ticket) of the position to modify.
		stop_loss: The new stop loss level. If None, the current stop loss
			level is retained. 0 removes it.
		take_profit: The new take profit level. If None, the current take
			profit level is retained. 0 removes it.

	Returns:
		A dictionary containing an error flag, a message, and the position
		data if successful.
	"""

	try:
		position_id = int(id)
	except (TypeError, ValueError):
		return { "error": True, "message": f"Invalid position ID {id}", "data": None }

	positions = mt5.positions_get(ticket=position_id)
	if not positions:
		return { "error": True, "message": f"Position {position_id} not found", "data": None }
	position = positions[0]
	symbol = position.symbol

	symbol_info = mt5.symbol_info(symbol)
	if symbol_info is None:
		return { "error": True, "message": f"Failed to get symbol info for {symbol}", "data": None }

	sl = float(stop_loss) if stop_loss is not None else float(position.sl)
	tp = float(take_profit) if take_profit is not None else float(position.tp)
	sl = round_to_tick(sl, symbol_info) if sl else 0.0
	tp = round_to_tick(tp, symbol_info) if tp else 0.0

	# Validate the side against the current price
	price = float(position.price_current)
	is_buy = position.type == mt5.POSITION_TYPE_BUY
	side = "BUY" if is_buy else "SELL"
	if is_buy:
		if sl and sl >= price:
			return { "error": True, "message": f"Invalid SL {sl} for {side} position {position_id}: SL must be below the current price {price}", "data": None }
		if tp and tp <= price:
			return { "error": True, "message": f"Invalid TP {tp} for {side} position {position_id}: TP must be above the current price {price}", "data": None }
	else:
		if sl and sl <= price:
			return { "error": True, "message": f"Invalid SL {sl} for {side} position {position_id}: SL must be above the current price {price}", "data": None }
		if tp and tp >= price:
			return { "error": True, "message": f"Invalid TP {tp} for {side} position {position_id}: TP must be below the current price {price}", "data": None }

	response = send_order(
		connection,
		action = TradeRequestActions.SLTP,
		symbol = symbol,
		position = position_id,
		stop_loss = sl,
		take_profit = tp,
	)

	if response["success"] is False:
		return { "error": True, "message": f"Modify position {position_id} failed: {response['message']}", "data": None }

	# Read the position back and confirm SL/TP were stored
	positions = mt5.positions_get(ticket=position_id)
	if not positions:
		return { "error": True, "message": f"Position {position_id} not found after modification, SL/TP not confirmed", "data": None }
	updated = positions[0]

	tolerance = (getattr(symbol_info, "trade_tick_size", 0) or getattr(symbol_info, "point", 0)) / 2 or 1e-9
	if not math.isclose(updated.sl, sl, abs_tol=tolerance) or not math.isclose(updated.tp, tp, abs_tol=tolerance):
		return {
			"error": True,
			"message": f"Position {position_id} SL/TP not confirmed: requested SL {sl} TP {tp}, stored SL {updated.sl} TP {updated.tp}",
			"data": position_to_dict(updated),
		}

	return {
		"error": False,
		"message": f"Modify position {position_id} success, SL at {updated.sl}, TP at {updated.tp}, current price {updated.price_current}",
		"data": position_to_dict(updated),
	}
