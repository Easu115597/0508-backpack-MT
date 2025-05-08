# core/

import logging

class OrderExecutor:
    def __init__(self, client, monitor):
        self.client = client
        self.monitor = monitor
        self.logger = logging.getLogger(__name__)

    async def place_limit_order(self, symbol, side, price, size):
        try:
            order = await self.client.place_order(
                symbol=symbol,
                side=side,
                order_type="limit",
                price=price,
                size=size
            )
            order_id = order["order_id"]
            self.monitor.track_order(order_id, symbol)
            self.logger.info(f"Placed limit order: {order_id} {side} {size}@{price}")
            return order_id
        except Exception as e:
            self.logger.error(f"Limit order failed: {e}")
            return None

    async def place_market_order(self, symbol, side, size):
        try:
            order = await self.client.place_order(
                symbol=symbol,
                side=side,
                order_type="market",
                size=size
            )
            order_id = order["order_id"]
            self.logger.info(f"Placed market order: {order_id} {side} {size}@market")
            return order_id
        except Exception as e:
            self.logger.error(f"Market order failed: {e}")
            return None
        
    async def cancel_all_orders(self, symbol):
        try:
            result = await self.client.cancel_all_orders(symbol=symbol)
            self.logger.info(f"Canceled all orders for {symbol}")
            return result
        except Exception as e:
            self.logger.error(f"Cancel all orders failed: {e}")
            return None

    async def close_position(self, symbol, size):
        """Close position with market order"""
        side = "sell"  # For long positions
        return await self.place_market_order(symbol, side, size)
