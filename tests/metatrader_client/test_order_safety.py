"""
Offline tests for order safety: retcode checks, SL/TP on positions and
market orders, and server time conversion. MetaTrader5 calls are faked, so
no terminal is needed.
"""

import calendar
import importlib
from collections import namedtuple
from datetime import datetime

import MetaTrader5 as mt5
import pandas as pd
import pytest

from metatrader_client.order.modify_position import modify_position, round_to_tick
from metatrader_client.order.place_market_order import place_market_order
from metatrader_client.order._batch import run_batch
from metatrader_client.utils import server_time_to_local

# The order package re-exports send_order under the module's name
send_order_module = importlib.import_module("metatrader_client.order.send_order")


Position = namedtuple("Position", "ticket time time_msc time_update time_update_msc type symbol volume price_open sl tp price_current")
SymbolInfo = namedtuple("SymbolInfo", "trade_tick_size point digits filling_mode")
Result = namedtuple("Result", "retcode comment order deal price volume")
Deal = namedtuple("Deal", "ticket position_id price")
Tick = namedtuple("Tick", "bid ask")

WIN = SymbolInfo(trade_tick_size=5.0, point=1.0, digits=0, filling_mode=2)
WDO = SymbolInfo(trade_tick_size=0.5, point=0.001, digits=3, filling_mode=2)
T_1227 = calendar.timegm(datetime(2026, 9, 28, 12, 27).timetuple())


class FakeMarket:
	def __init__(self, connection):
		pass

	def get_symbols(self, symbol):
		return [symbol]


class FakeTerminal:
	"""Holds positions and answers order_send like a broker would."""

	def __init__(self, positions, symbol_info=WIN, retcode=10009, store_sltp=True):
		self.positions = { p.ticket: p for p in positions }
		self.symbol_info = symbol_info
		self.retcode = retcode
		self.store_sltp = store_sltp
		self.requests = []

	def positions_get(self, ticket=None, symbol=None):
		if ticket is not None:
			p = self.positions.get(ticket)
			return (p,) if p else ()
		return tuple(p for p in self.positions.values() if symbol is None or p.symbol == symbol)

	def order_send(self, request):
		self.requests.append(request)
		if self.retcode != 10009:
			return Result(self.retcode, "Invalid request", 0, 0, 0.0, 0.0)
		if request["action"] == mt5.TRADE_ACTION_SLTP:
			if not request.get("symbol"):
				return Result(10013, "Invalid request", 0, 0, 0.0, 0.0)
			if self.store_sltp:
				p = self.positions[request["position"]]
				self.positions[p.ticket] = p._replace(sl=request["sl"], tp=request["tp"])
			return Result(10009, "Request executed", 0, 0, 0.0, 0.0)
		if request["action"] == mt5.TRADE_ACTION_DEAL:
			ticket = 555
			price = 120003.0 if request["type"] == mt5.ORDER_TYPE_BUY else 119998.0
			position_type = mt5.POSITION_TYPE_BUY if request["type"] == mt5.ORDER_TYPE_BUY else mt5.POSITION_TYPE_SELL
			self.positions[ticket] = Position(ticket, T_1227, 0, T_1227, 0, position_type, request["symbol"], request["volume"], price, 0.0, 0.0, price)
			return Result(10009, "Request executed", ticket, 777, 0.0, request["volume"])
		return Result(10009, "Request executed", 0, 0, 0.0, 0.0)

	def history_deals_get(self, ticket=None):
		return (Deal(777, 555, self.positions[555].price_open),) if 555 in self.positions else ()


@pytest.fixture
def terminal(monkeypatch):
	def install(t):
		monkeypatch.setattr(send_order_module, "MT5Market", FakeMarket)
		monkeypatch.setattr(mt5, "positions_get", t.positions_get, raising=False)
		monkeypatch.setattr(mt5, "order_send", t.order_send, raising=False)
		monkeypatch.setattr(mt5, "history_deals_get", t.history_deals_get, raising=False)
		monkeypatch.setattr(mt5, "symbol_info", lambda symbol: t.symbol_info, raising=False)
		monkeypatch.setattr(mt5, "symbol_select", lambda symbol, enable: True, raising=False)
		monkeypatch.setattr(mt5, "symbol_info_tick", lambda symbol: Tick(120000.0, 120005.0), raising=False)
		monkeypatch.setattr(mt5, "last_error", lambda: (1, "Success"), raising=False)
		return t
	return install


def sell_position(**kwargs):
	values = dict(ticket=1, time=T_1227, time_msc=0, time_update=T_1227, time_update_msc=0, type=mt5.POSITION_TYPE_SELL, symbol="WINZ26", volume=1.0, price_open=120000.0, sl=0.0, tp=0.0, price_current=120000.0)
	values.update(kwargs)
	return Position(**values)


# Bug 1: modify_position

def test_modify_position_sends_symbol_and_rounds_to_tick(terminal):
	t = terminal(FakeTerminal([sell_position()]))
	result = modify_position(None, 1, stop_loss=120203, take_profit=119598)
	assert result["error"] is False, result["message"]
	request = t.requests[-1]
	assert request["symbol"] == "WINZ26"
	assert request["position"] == 1
	assert request["sl"] == 120205.0
	assert request["tp"] == 119600.0
	assert result["data"]["sl"] == 120205.0


def test_modify_position_rounds_wdo_to_half_point():
	assert round_to_tick(5432.26, WDO) == 5432.5
	assert round_to_tick(5432.24, WDO) == 5432.0


def test_modify_position_not_found(terminal):
	terminal(FakeTerminal([]))
	result = modify_position(None, 99, stop_loss=1)
	assert result["error"] is True
	assert "not found" in result["message"]


@pytest.mark.parametrize("sl,tp", [(119800, None), (None, 120200)])
def test_modify_position_rejects_inverted_side_on_sell(terminal, sl, tp):
	t = terminal(FakeTerminal([sell_position()]))
	result = modify_position(None, 1, stop_loss=sl, take_profit=tp)
	assert result["error"] is True
	assert t.requests == []


def test_modify_position_rejects_inverted_side_on_buy(terminal):
	t = terminal(FakeTerminal([sell_position(type=mt5.POSITION_TYPE_BUY)]))
	result = modify_position(None, 1, stop_loss=120200)
	assert result["error"] is True
	assert t.requests == []


def test_modify_position_errors_when_sltp_not_stored(terminal):
	terminal(FakeTerminal([sell_position()], store_sltp=False))
	result = modify_position(None, 1, stop_loss=120200)
	assert result["error"] is True
	assert "not confirmed" in result["message"]


# Bug 2: false success

def test_rejected_retcode_is_an_error(terminal):
	terminal(FakeTerminal([sell_position()], retcode=10013))
	result = modify_position(None, 1, stop_loss=120200)
	assert result["error"] is True
	assert "10013" in result["message"]
	assert "Invalid request" in result["message"]


def test_none_result_is_an_error(monkeypatch):
	monkeypatch.setattr(mt5, "last_error", lambda: (-2, "Invalid params"), raising=False)
	response = send_order_module.check_trade_result(None)
	assert response["success"] is False
	assert "-2" in response["message"]


def test_placed_retcode_only_for_pending(monkeypatch):
	monkeypatch.setattr(mt5, "last_error", lambda: (1, "Success"), raising=False)
	placed = Result(10008, "Placed", 1, 0, 0.0, 0.0)
	assert send_order_module.check_trade_result(placed)["success"] is False
	assert send_order_module.check_trade_result(placed, (10009, 10008))["success"] is True


def test_batch_reports_failures():
	result = run_batch([1, 2], lambda id: { "error": id == 2, "message": "retcode 10013" }, "Close all positions")
	assert result["error"] is True
	assert result["data"]["done"] == [1]
	assert "10013" in result["message"]


# Bug 3: SL/TP on market orders

def test_market_order_applies_points_from_execution_price(terminal):
	t = terminal(FakeTerminal([]))
	result = place_market_order(None, type="BUY", symbol="WINZ26", volume=1, stop_points=200, take_points=400)
	assert result["error"] is False, result["message"]
	deal_request = t.requests[0]
	assert deal_request["sl"] == 0.0 and deal_request["tp"] == 0.0
	sltp = t.requests[-1]
	# executed at 120003 -> SL 119803 -> 119805, TP 120403 -> 120405 on a 5 tick
	assert sltp["sl"] == 119805.0
	assert sltp["tp"] == 120405.0
	assert result["data"]["sl"] == 119805.0


def test_market_order_reports_unprotected_position(terminal):
	terminal(FakeTerminal([], store_sltp=False))
	result = place_market_order(None, type="SELL", symbol="WINZ26", volume=1, stop_points=200)
	assert result["error"] is True
	assert "WITHOUT PROTECTION" in result["message"]
	assert "555" in result["message"]


def test_market_order_without_protection_is_unchanged(terminal):
	t = terminal(FakeTerminal([]))
	result = place_market_order(None, type="BUY", symbol="WINZ26", volume=1)
	assert result["error"] is False
	assert len(t.requests) == 1


# Bug 4: time zone

def test_server_time_is_brasilia_wall_clock():
	converted = server_time_to_local(T_1227)
	assert converted.isoformat() == "2026-09-28T12:27:00-03:00"
	series = server_time_to_local(pd.Series([T_1227]))
	assert series.iloc[0].isoformat() == "2026-09-28T12:27:00-03:00"


def test_modify_position_returns_brasilia_time(terminal):
	terminal(FakeTerminal([sell_position()]))
	result = modify_position(None, 1, stop_loss=120200)
	assert result["data"]["time"] == "2026-09-28T12:27:00-03:00"
