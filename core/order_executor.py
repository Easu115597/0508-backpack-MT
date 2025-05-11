# core/

import logging

class OrderExecutor:
    def __init__(self, client, symbol, precision_manager=None):
        self.client = client
        self.symbol = symbol
        self.logger = logging.getLogger(__name__)
        self.precision_manager = precision_manager

    async def place_limit_order(self, side, price, size):
        try:
            # 使用精度管理器格式化價格和數量
            if self.precision_manager:
                formatted_price = await self.precision_manager.format_price(self.symbol, price)
                formatted_size = await self.precision_manager.format_quantity(self.symbol, size)
            else:
                # 如果沒有精度管理器，使用默認格式化
                formatted_price = round(price, 1)
                formatted_size = round(size, 3)
        
            order = await self.client.execute_order({
                "symbol": self.symbol,
                "side": side,
                "orderType": "Limit",
                "price": str(formatted_price),
                "quantity": str(formatted_size),
                "timeInForce": "GTC"
            })
            self.logger.info(f"限價單成功: {side} {size}@{price}")
            return order
        except Exception as e:
            self.logger.error(f"Limit order failed: {e}")
            return None
    
    async def place_orders(self, order_plan):
        """批量下單"""
        placed_orders = []
        for order in order_plan:
            try:
                # 移除symbol參數，只傳遞方法定義中的參數
                result = await self.place_limit_order(
                    side=order["side"],
                    price=order["price"],
                    size=order["quantity"]
                )
                if result and 'id' in result:
                    placed_orders.append(result)
                    self.logger.info(f"成功掛單: {order['side']} {order['quantity']}@{order['price']}")
                else:
                    self.logger.error(f"掛單失敗: {result}")
                    
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
