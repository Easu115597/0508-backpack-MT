import asyncio
import time
import logging
from collections import defaultdict

class OrderMonitor:
    def __init__(self, client, symbol: str):
        self.client = client
        self.symbol = symbol
        
        self.open_orders = {}  # order_id: {info}
        self.filled_orders = {}  # 改為字典: order_id: order_info
        self.active_orders = {}
        
        self.order_status_cache = defaultdict(lambda: "unknown")
        self.logger = logging.getLogger(__name__)

    def track_order(self, order):
        """
        加入新的掛單進追蹤池
        """
        order_id = order["id"]  # 修正: 使用正確的ID字段
        self.open_orders[order_id] = order
        self.active_orders[order_id] = self.symbol  # 修正: 使用self.symbol
        self.order_status_cache[order_id] = "new"
        self.logger.info(f"開始追蹤訂單: {order_id}")

    def track_orders(self, orders):
        """批量追蹤多個訂單"""
        for order in orders:
            self.track_order(order)

    async def wait_for_first_fill(self, timeout=60):
        """等待第一筆成交訂單，有超時機制"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            await self.update_statuses()
            if self.filled_orders:
                # 返回第一個成交的訂單
                order_id = next(iter(self.filled_orders))
                return self.filled_orders[order_id]
            await asyncio.sleep(1)
        return None

    async def update_statuses(self):
        for order_id in list(self.active_orders.keys()):
            try:
                # 傳入symbol參數
                order_data = await self.client.get_order(order_id, self.symbol)
                if order_data and 'status' in order_data:
                    status = order_data.get("status")
                    # 處理訂單狀態...
                else:
                    self.logger.warning(f"無法獲取訂單 {order_id} 的狀態")
            except Exception as e:
                self.logger.warning(f"訂單狀態檢查失敗: {e}")

    def get_filled_orders(self):
        """獲取所有已成交訂單"""
        return self.filled_orders.copy()

    def clear_filled_orders(self):
        """清空已成交訂單記錄"""
        self.filled_orders.clear()

    async def cancel_all(self):
        """取消所有活動訂單"""
        for order_id in list(self.active_orders.keys()):
            try:
                await self.client.cancel_order(order_id)
                self.logger.info(f"已取消訂單: {order_id}")
            except Exception as e:
                self.logger.warning(f"取消訂單 {order_id} 失敗: {e}")
        self.active_orders.clear()
