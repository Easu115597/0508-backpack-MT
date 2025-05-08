import asyncio
import time
from collections import defaultdict

class OrderMonitor:
    def __init__(self, client, symbol: str):
        self.client = client
        self.symbol = symbol
        self.open_orders = {}  # order_id: {info}
        self.filled_orders = []  # list of filled order_ids
        self.active_orders = {}
        
        self.order_status_cache = defaultdict(lambda: "unknown")
        self.logger = logging.getLogger(__name__)

    def track_order(self, order):
        """
        加入新的掛單進追蹤池
        """
        self.open_orders[order["order_id"]] = order
        self.active_orders[order_id] = symbol
        self.order_status_cache[order_id] = "new"

    def untrack_all(self):
        """
        清空所有追蹤的掛單（例如止盈後全撤單情況）
        """
        self.open_orders.clear()

    def get_filled_order_ids(self):
        return self.filled_orders

    async def check_orders(self):
        """
        逐一查詢目前追蹤的掛單狀態，偵測是否成交或取消
        """
        to_remove = []
        for order_id, order in self.open_orders.items():
            try:
                result = await self.client.get_order(order_id)
                status = result.get("status")

                if status == "filled":
                    self.filled_orders.append(order_id)
                    to_remove.append(order_id)

                elif status == "cancelled":
                    to_remove.append(order_id)

            except Exception as e:
                print(f"[OrderMonitor] 查詢訂單 {order_id} 時發生錯誤: {e}")

        for oid in to_remove:
            self.open_orders.pop(oid, None)

    async def loop_check(self, interval=2):
        while True:
            await self.check_orders()
            await asyncio.sleep(interval)

    def has_open_orders(self):
        return len(self.open_orders) > 0

    def reset(self):
        self.open_orders = {}
        self.filled_orders = []

    async def update_statuses(self):
        for order_id, symbol in list(self.active_orders.items()):
            try:
                order_data = await self.client.get_order(order_id=order_id)
                status = order_data.get("status")

                if status != self.order_status_cache[order_id]:
                    self.logger.info(f"Order {order_id} status updated: {status}")
                    self.order_status_cache[order_id] = status

                if status == "filled":
                    self.filled_orders[order_id] = symbol
                    del self.active_orders[order_id]

                elif status in ["cancelled", "rejected", "expired"]:
                    del self.active_orders[order_id]

            except Exception as e:
                self.logger.warning(f"Order status check failed: {e}")

    def get_filled_orders(self):
        return self.filled_orders.copy()

    def clear_filled_orders(self):
        self.filled_orders.clear()

    async def cancel_all(self):
        for order_id in list(self.active_orders.keys()):
            try:
                await self.client.cancel_order(order_id)
                self.logger.info(f"Cancelled order: {order_id}")
            except Exception as e:
                self.logger.warning(f"Failed to cancel order {order_id}: {e}")
        self.active_orders.clear()
