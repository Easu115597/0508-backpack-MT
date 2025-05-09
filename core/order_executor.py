# core/

import logging

class OrderExecutor:
    def __init__(self, client, symbol):
        self.client = client
        self.symbol = symbol
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
        
    async def place_orders(self, order_plan):
        """批量下單"""
        placed_orders = []
        for order in order_plan:
            try:
                result = await self.place_limit_order(
                    symbol=self.symbol,
                    side=order["side"],
                    price=order["price"],
                    size=order["quantity"]
                )
                if result:
                    placed_orders.append(result)
            except Exception as e:
                self.logger.error(f"下單失敗: {e}")
        return placed_orders

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
