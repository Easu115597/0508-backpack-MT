import asyncio
import logging
import time
from core.order_executor import OrderExecutor
from core.strategy import MartingaleStrategy
from core.order_monitor import OrderMonitor
from api.client import BackpackAPIClient
from utils.logger import init_logger  # optional: logging setup
from config import settings  # 包含 API 金鑰、參數設定等
from utils.precision_manager import PrecisionManager
from utils.trade_stats import TradeStats

from ws_client.client import BackpackWebSocketClient

logger = init_logger(__name__) if 'init_logger' in globals() else logging.getLogger(__name__)


class MartingaleRunner:
    def __init__(self, client, symbol, settings, logger):
        self.settings = settings
        self.logger = logger
        
        # 在內部創建client
        self.client = BackpackAPIClient(
            api_key=settings.API_KEY,
            secret_key=settings.SECRET_KEY
        )
        self.symbol = symbol

        # 創建WebSocket連接
        # import asyncio
        # self.ws_task = asyncio.create_task(self.client.connect_websocket(self.symbol, self.handle_websocket_message))
        # self.logger.info("WebSocket連接已啟動")

        # 創建WebSocket客戶端
        self.ws = BackpackWebSocketClient(
            api_key=settings.API_KEY,
            secret_key=settings.SECRET_KEY,
            symbol=self.symbol,
            logger=logger
        )
        
        # 註冊訂單更新回調
        self.ws.on("account.orderUpdate", self.on_order_update)
        

        # 添加交易統計
        self.stats = TradeStats(symbol)
        
        # 創建精度管理器
        self.precision_manager = PrecisionManager(client, logger)

        # 初始化策略組件
        self.strategy = MartingaleStrategy(settings, logger, self.client, precision_manager=self.precision_manager)
        self.executor = OrderExecutor(self.client, self.symbol, self.precision_manager)
        self.monitor = OrderMonitor(self.client, self.symbol)
        
        # 添加missing_order_count屬性
        self.missing_order_count = 0

        # 初始化狀態變量
        self.active_orders = []
        self.holding_position = False
        self.entry_price = None
        self.total_bought = 0
        
        self.logger.info(f"[OK] Runner 初始化完成: Symbol={self.symbol}")

    async def reset(self):
        """重置策略狀態"""
        try:
            # 取消所有活動訂單
            if isinstance(self.active_orders, dict):
                # 如果是字典，使用keys()方法
                for order_id in list(self.active_orders.keys()):
                    try:
                        await self.client.cancel_order(order_id, self.symbol)
                        self.logger.info(f"取消訂單 {order_id}")
                    except Exception as e:
                        self.logger.error(f"取消訂單失敗: {e}")
            elif isinstance(self.active_orders, list):
                # 如果是列表，直接遍歷
                for order in self.active_orders:
                    if 'id' in order:
                        order_id = order['id']
                        try:
                            await self.client.cancel_order(order_id, self.symbol)
                            self.logger.info(f"取消訂單 {order_id}")
                        except Exception as e:
                            self.logger.error(f"取消訂單失敗: {e}")
            
            # 清理狀態
            self.active_orders = []
            if hasattr(self, 'monitor'):
                self.monitor.active_orders = {}
                self.monitor.filled_orders = {}
            self.holding_position = False
            self.entry_price = None
            self.total_bought = 0
            
            # 重置策略
            if hasattr(self, 'strategy') and hasattr(self.strategy, 'reset'):
                self.strategy.reset()
            
            self.logger.info("策略狀態已重置")
            return True
        except Exception as e:
            self.logger.error(f"重置失敗: {e}")
            return False

    async def check_risk_limits(self):
        """檢查風險限制，決定是否需要緊急停止"""
        if hasattr(self.settings, 'EMERGENCY_STOP') and self.settings.EMERGENCY_STOP:
            self.logger.warning("緊急停止開關已啟用，執行緊急平倉")
            await self.emergency_stop()
            return True
        
        if self.holding_position and self.entry_price:
            try:
                ticker_data = await self.client.get_ticker(self.symbol)
                if ticker_data and 'lastPrice' in ticker_data:
                    current_price = float(ticker_data['lastPrice'])
                    
                    # 計算當前虧損百分比
                    loss_pct = (current_price - self.entry_price) / self.entry_price
                    
                    if hasattr(self.settings, 'MAX_LOSS_PCT') and loss_pct <= self.settings.MAX_LOSS_PCT:
                        self.logger.warning(f"達到最大虧損限制: {loss_pct:.4%}, 執行緊急平倉")
                        await self.emergency_stop()
                        return True
            except Exception as e:
                self.logger.error(f"檢查風險限制失敗: {e}")
        
        return False

    async def emergency_stop(self):
        """執行緊急停止，平掉所有倉位並取消所有訂單"""
        try:
            # 取消所有活動訂單
            cancel_result = await self.client.cancel_all_orders(self.symbol)
            self.logger.info(f"緊急停止: 取消所有訂單 - {cancel_result}")
            
            # 平掉所有倉位
            if self.holding_position and self.total_bought > 0:
                close_result = await self.executor.close_position(self.symbol, self.total_bought)
                self.logger.info(f"緊急停止: 平倉完成 - {close_result}")
            
            # 重置狀態
            await self.reset()
            
            # 記錄緊急停止事件
            if hasattr(self, 'stats') and hasattr(self.stats, 'record_emergency_stop'):
                self.stats.record_emergency_stop()
            
            return True
        except Exception as e:
            self.logger.error(f"緊急停止失敗: {e}")
            return False
        
    async def on_order_update(self, data):
        """處理訂單更新"""
        try:
            self.logger.info(f"收到訂單更新: {data}")
            
            # 檢查是否是訂單成交消息
            event_type = data.get("e")
            if event_type == "orderFill":
                # 處理訂單成交
                order_id = data.get("i")  # 訂單ID
                price = float(data.get("L", 0))  # 成交價格
                quantity = float(data.get("l", 0))  # 成交數量
                side = data.get("S")  # 買賣方向
                
                self.logger.info(f"訂單成交: ID={order_id}, 價格={price}, 數量={quantity}, 方向={side}")
                
                # 更新持倉狀態
                if side == "BUY":
                    self.holding_position = True
                    
                    # 更新入場價格
                    if not self.entry_price:
                        self.entry_price = price
                        self.total_bought = quantity
                    else:
                        # 計算新的平均入場價格
                        total_value = self.entry_price * self.total_bought + price * quantity
                        self.total_bought += quantity
                        self.entry_price = total_value / self.total_bought if self.total_bought > 0 else 0
                    
                    self.logger.info(f"更新持倉: 總數量={self.total_bought}, 平均價格={self.entry_price}")
                    
                    # 計算止盈價格
                    take_profit_price = self.entry_price * (1 + self.settings.TAKE_PROFIT_PCT)
                    self.logger.info(f"預計止盈價格: {take_profit_price:.2f}")
                    
                    # 可選：立即掛出止盈單
                    try:
                        tp_order = await self.executor.place_take_profit_order(
                            self.symbol, 
                            self.total_bought, 
                            take_profit_price
                        )
                        if tp_order:
                            self.logger.info(f"止盈單已掛出: {tp_order}")
                    except Exception as e:
                        self.logger.error(f"掛出止盈單失敗: {e}")
                
                # 記錄成交訂單
                if hasattr(self.stats, 'record_filled_order'):
                    filled_order = {
                        'id': order_id,
                        'price': price,
                        'quantity': quantity,
                        'side': side,
                        'status': 'FILLED'
                    }
                    self.stats.record_filled_order(filled_order)
            
            # 處理其他訂單事件
            elif event_type == "orderNew":
                self.logger.info(f"新訂單創建: {data}")
            elif event_type == "orderCancelled":
                self.logger.info(f"訂單取消: {data}")
        except Exception as e:
            self.logger.error(f"處理訂單更新失敗: {e}")

    

    async def run(self):
        """主運行循環"""
        # 開始第一個交易循環
        self.stats.record_cycle_start()
        self.logger.info(f"開始新的交易循環 #{self.stats.total_cycles}")
        
        # 初始連接WebSocket
        try:
            await self.ws.connect()
            # 使用一致的訂閱方法
            if hasattr(self.ws, 'subscribe_account_updates'):
                await self.ws.subscribe_account_updates()
            else:
                await self.ws.subscribe("account.orderUpdate")
            self.logger.info("WebSocket連接已啟動並訂閱訂單更新")
        except Exception as e:
            self.logger.error(f"啟動WebSocket失敗: {e}")
        
        while True:
            try:
                # 檢查風險限制
                if hasattr(self, 'check_risk_limits') and await self.check_risk_limits():
                    self.logger.warning("風險限制觸發，等待重新啟動")
                    await asyncio.sleep(300)  # 等待5分鐘後重新啟動
                    self.stats.record_cycle_start()
                    self.logger.info(f"重新啟動交易循環 #{self.stats.total_cycles}")
                    continue
                
                # 檢查WebSocket連接狀態 - 只在連接斷開時重連
                if self.ws and not self.ws.is_connected():
                    self.logger.warning("WebSocket連接已斷開，嘗試重新連接")
                    try:
                        await self.ws.connect()
                        # 使用一致的訂閱方法
                        if hasattr(self.ws, 'subscribe_account_updates'):
                            await self.ws.subscribe_account_updates()
                        else:
                            await self.ws.subscribe("account.orderUpdate")
                        self.logger.info("WebSocket重新連接成功")
                    except Exception as e:
                        self.logger.error(f"WebSocket重新連接失敗: {e}")
                
                # 檢查是否已有活動訂單
                active_orders_count = len(self.active_orders)
                
                if active_orders_count > 0:
                    self.logger.info(f"當前有 {active_orders_count} 個活動訂單，等待成交")
                    
                    # 決定使用WebSocket還是REST API檢測訂單成交
                    if self.ws and self.ws.is_connected():
                        # 如果WebSocket連接正常，不使用REST API
                        filled_order = None  # WebSocket會通過回調處理訂單成交
                    else:
                        # 如果WebSocket連接失敗，嘗試使用REST API
                        filled_order = await self.monitor.check_for_filled_orders()
                        
                        # 如果上面方法失敗，嘗試使用其他方法
                        if not filled_order:
                            try:
                                # 嘗試使用持倉查詢
                                positions = await self.client.get_positions(self.symbol)
                                if positions:
                                    for position in positions:
                                        position_amt = float(position.get('positionAmt', 0))
                                        if position_amt > 0:
                                            self.logger.info(f"通過持倉查詢發現成交: {position}")
                                            # 創建一個虛擬成交訂單
                                            filled_order = {
                                                'id': f"position_{int(time.time())}",
                                                'price': float(position.get('entryPrice', 0)),
                                                'quantity': position_amt,
                                                'side': 'Bid',
                                                'status': 'FILLED'
                                            }
                            except Exception as e:
                                self.logger.error(f"持倉查詢失敗: {e}")
                            
                            # 如果上面方法都失敗，嘗試使用成交歷史
                            if not filled_order:
                                try:
                                    fill_history = await self.client.get_fill_history(self.symbol)
                                    if fill_history and len(fill_history) > 0:
                                        # 找出最近的成交記錄
                                        recent_fill = fill_history[0]
                                        self.logger.info(f"通過成交歷史發現成交: {recent_fill}")
                                        # 創建一個虛擬成交訂單
                                        filled_order = {
                                            'id': recent_fill.get('orderId', f"fill_{int(time.time())}"),
                                            'price': float(recent_fill.get('price', 0)),
                                            'quantity': float(recent_fill.get('qty', 0)),
                                            'side': recent_fill.get('side', 'Bid'),
                                            'status': 'FILLED'
                                        }
                                except Exception as e:
                                    self.logger.error(f"成交歷史查詢失敗: {e}")
                        
                        # 如果檢測到成交
                        if filled_order:
                            self.holding_position = True
                            self.entry_price = filled_order['price']
                            self.total_bought = filled_order.get('quantity', 0)
                            self.logger.info(f"訂單成交確認：{filled_order}")
                            
                            # 記錄成交訂單
                            if hasattr(self.stats, 'record_filled_order'):
                                self.stats.record_filled_order(filled_order)
                            
                            # 計算止盈價格
                            take_profit_price = self.entry_price * (1 + self.settings.TAKE_PROFIT_PCT)
                            self.logger.info(f"預計止盈價格: {take_profit_price:.2f}")
                            
                            # 掛出止盈單
                            try:
                                tp_order = await self.executor.place_take_profit_order(
                                    self.symbol, 
                                    self.total_bought, 
                                    take_profit_price
                                )
                                if tp_order:
                                    self.logger.info(f"止盈單已掛出: {tp_order}")
                            except Exception as e:
                                self.logger.error(f"掛出止盈單失敗: {e}")
                            
                            # 清空活動訂單列表
                            self.active_orders = []
                            if hasattr(self.monitor, 'active_orders'):
                                self.monitor.active_orders = {}
                
                elif not self.holding_position:
                    # 準備掛新單，先取消所有未成交訂單
                    self.logger.info("準備掛新單，先取消所有未成交訂單")
                    try:
                        cancel_result = await self.client.cancel_all_orders(self.symbol)
                        if cancel_result:
                            self.logger.info(f"成功取消所有未成交訂單: {cancel_result}")
                            # 清空本地訂單記錄
                            self.active_orders = []
                            if hasattr(self.monitor, 'active_orders'):
                                self.monitor.active_orders = {}
                    except Exception as e:
                        self.logger.error(f"取消訂單失敗: {e}")
                    
                    # 重置missing_order_count
                    if hasattr(self, 'missing_order_count'):
                        self.missing_order_count = 0
                    
                    self.logger.info("尚未持倉，開始掛單")
                    
                    # 一次性掛出所有層級的訂單
                    order_plan = await self.strategy.generate_orders()
                    self.active_orders = await self.executor.place_orders(order_plan)
                    
                    if self.active_orders:
                        self.logger.info(f"成功掛出 {len(self.active_orders)} 個限價單")
                        
                        # 記錄訂單
                        if hasattr(self.stats, 'record_order'):
                            for order in self.active_orders:
                                self.stats.record_order(order)
                        
                        if hasattr(self.monitor, 'track_orders'):
                            self.monitor.track_orders(self.active_orders)
                    else:
                        self.logger.warning("所有限價單掛單失敗，等待下次重試")
                        await asyncio.sleep(60)
                        continue
                
                elif self.holding_position:
                    # 已持倉，檢查是否需要止盈
                    try:
                        ticker_data = await self.client.get_ticker(self.symbol)
                        if ticker_data and 'lastPrice' in ticker_data:
                            current_price = float(ticker_data['lastPrice'])
                            
                            # 計算盈虧
                            if self.entry_price is not None:
                                pnl = (current_price - self.entry_price) / self.entry_price
                                self.logger.info(f"目前價格：{current_price}，入場價：{self.entry_price}，PNL：{pnl:.4%}")
                                
                                # 檢查是否達到止盈條件
                                if pnl >= self.settings.TAKE_PROFIT_PCT:
                                    self.logger.info(f"達到止盈條件 {pnl:.4%} >= {self.settings.TAKE_PROFIT_PCT:.4%}")
                                    
                                    # 計算本輪利潤
                                    profit = (current_price - self.entry_price) * self.total_bought
                                    self.logger.info(f"達到止盈，本輪利潤: {profit:.4f} USDC")
                                    
                                    # 執行平倉
                                    close_result = await self.executor.close_position(self.symbol, self.total_bought)
                                    if close_result:
                                        self.logger.info(f"平倉成功: {close_result}")
                                        
                                        # 記錄循環結束
                                        if hasattr(self.stats, 'record_cycle_end'):
                                            cycle_stats = self.stats.record_cycle_end(profit)
                                            cycle_id = cycle_stats.get('cycle_id', 'unknown') if cycle_stats else 'unknown'
                                            self.logger.info(f"交易循環 #{cycle_id} 完成，利潤: {profit:.4f} USDC")
                                        
                                            # 打印統計摘要
                                            stats = self.stats.get_stats()
                                            self.logger.info(f"總計完成 {stats.get('total_cycles', 0)} 個循環，總利潤: {stats.get('total_profit', 0):.4f} USDC")
                                        
                                        # 重置狀態
                                        await self.reset()
                                        
                                        # 開始新的循環
                                        if hasattr(self.stats, 'record_cycle_start'):
                                            self.stats.record_cycle_start()
                                            self.logger.info(f"開始新的交易循環 #{self.stats.total_cycles}")
                                        continue
                                    else:
                                        self.logger.error("平倉失敗")
                            else:
                                self.logger.warning("入場價格未設置，無法計算PNL")
                                # 嘗試重置狀態或檢查持倉
                                await self.reset()
                                continue
                        else:
                            self.logger.warning("無法獲取當前價格")
                    except Exception as e:
                        self.logger.error(f"檢查止盈失敗: {e}")
                
                # 等待一段時間再檢查
                await asyncio.sleep(60)
                
            except Exception as e:
                self.logger.exception(f"主迴圈發生錯誤：{e}")
                await asyncio.sleep(3)

    
    async def on_ws_message(self, data):
        """處理WebSocket消息"""
        try:
            # 處理不同類型的消息
            event_type = data.get('e')
            
            if event_type == 'orderFill':
                # 處理訂單成交
                side = data.get('S')
                quantity = float(data.get('l', '0'))  # 此次成交數量
                price = float(data.get('L', '0'))     # 此次成交價格
                order_id = data.get('i')              # 訂單 ID
                
                self.logger.info(f"訂單成交: ID={order_id}, 價格={price}, 數量={quantity}, 方向={side}")
                
                # 更新持倉狀態
                if side == 'BUY':
                    self.holding_position = True
                    
                    # 更新入場價格
                    if not self.entry_price:
                        self.entry_price = price
                        self.total_bought = quantity
                    else:
                        # 計算新的平均入場價格
                        total_value = self.entry_price * self.total_bought + price * quantity
                        self.total_bought += quantity
                        self.entry_price = total_value / self.total_bought if self.total_bought > 0 else 0
                    
                    self.logger.info(f"更新持倉: 總數量={self.total_bought}, 平均價格={self.entry_price}")
                    
                    # 計算止盈價格
                    take_profit_price = self.entry_price * (1 + self.settings.TAKE_PROFIT_PCT)
                    self.logger.info(f"預計止盈價格: {take_profit_price:.2f}")
        except Exception as e:
            self.logger.error(f"處理WebSocket消息失敗: {e}")

    


async def main():
    client = BackpackAPIClient(
        api_key=settings.API_KEY,
        secret_key=settings.SECRET_KEY
    )
    runner = MartingaleRunner(client, settings.SYMBOL, settings, logger)
    await runner.run()


if __name__ == "__main__":
    asyncio.run(main())
