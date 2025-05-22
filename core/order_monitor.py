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
    
    async def check_for_filled_orders(self):
        """基於無法獲取訂單的訊息推斷訂單成交"""
        self.logger.info(f"檢查訂單成交狀態，當前活動訂單數: {len(self.active_orders)}")
        
        # 嘗試使用成交歷史API
        try:
            fill_history = await self.client.get_fill_history(self.symbol)
            if fill_history:
                self.logger.info(f"獲取到 {len(fill_history)} 條成交歷史記錄")
                # 處理成交歷史...
        except Exception as e:
            self.logger.error(f"獲取成交歷史失敗: {e}")
        
        # 嘗試使用持倉API
        try:
            positions = await self.client.get_positions(self.symbol)
            if positions:
                for position in positions:
                    if float(position.get('positionAmt', 0)) > 0:
                        self.logger.info(f"發現持倉: {position}")
                        # 處理持倉信息...
        except Exception as e:
            self.logger.error(f"獲取持倉信息失敗: {e}")
        
        # 基於"無法獲取訂單"訊息推斷訂單成交
        filled_orders = []
        
        # 檢查self.active_orders的類型
        if isinstance(self.active_orders, dict):
            for order_id in list(self.active_orders.keys()):
                try:
                    order_data = await self.client.get_order(order_id, self.symbol)
                    if order_data is None:
                        # 無法獲取訂單，可能已成交
                        self.logger.info(f"推斷訂單 {order_id} 可能已成交")
                        filled_order = self.active_orders.pop(order_id)
                        filled_orders.append(filled_order)
                except Exception as e:
                    self.logger.warning(f"訂單狀態檢查失敗: {e}")
        elif isinstance(self.active_orders, list):
            # 如果是列表，需要通過索引處理
            i = 0
            while i < len(self.active_orders):
                order = self.active_orders[i]
                if isinstance(order, dict) and 'id' in order:
                    order_id = order['id']
                    try:
                        order_data = await self.client.get_order(order_id, self.symbol)
                        if order_data is None:
                            # 無法獲取訂單，可能已成交
                            self.logger.info(f"推斷訂單 {order_id} 可能已成交")
                            filled_order = self.active_orders.pop(i)
                            filled_orders.append(filled_order)
                            continue  # 不增加i，因為列表長度已減少
                    except Exception as e:
                        self.logger.warning(f"訂單狀態檢查失敗: {e}")
                i += 1
        
        if filled_orders:
            # 計算平均價格 - 添加類型檢查
            total_value = 0
            total_quantity = 0
            
            for order in filled_orders:
                if isinstance(order, dict):
                    price = order.get('price', 0)
                    quantity = order.get('quantity', 0)
                    if isinstance(price, (int, float)) and isinstance(quantity, (int, float)):
                        total_value += price * quantity
                        total_quantity += quantity
            
            avg_price = total_value / total_quantity if total_quantity > 0 else 0
            
            self.logger.info(f"推斷已成交訂單數: {len(filled_orders)}, 平均價格: {avg_price}")
            
            # 返回第一個成交訂單作為示例
            if filled_orders and isinstance(filled_orders[0], dict):
                filled_order = filled_orders[0]
                filled_order['price'] = avg_price
                filled_order['quantity'] = total_quantity
                
                # 確保self.filled_orders是字典
                if not hasattr(self, 'filled_orders'):
                    self.filled_orders = {}
                
                order_id = filled_order.get('id', str(len(self.filled_orders)))
                self.filled_orders[order_id] = filled_order
                return filled_order
        
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
