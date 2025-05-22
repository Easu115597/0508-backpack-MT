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

from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.layout import Layout # 可選，用於更複雜的佈局



logger = init_logger(__name__) if 'init_logger' in globals() else logging.getLogger(__name__)


class MartingaleRunner:
    def __init__(self, client, symbol, settings, logger):
        self.settings = settings
        self.logger = logger
        self._live_display = None # 用於存儲Live實例

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
        
        # 添加調試日誌
        #self.logger.info(f"executor對象是否有place_limit_order方法: {hasattr(self.executor, 'place_limit_order')}")
        #self.logger.info(f"executor對象是否有place_take_profit_order方法: {hasattr(self.executor, 'place_take_profit_order')}")


        # 註冊訂單更新回調
        self.ws.on("account.orderUpdate", self.on_order_update)
       

        # 添加交易統計
        self.stats = TradeStats(symbol)

        # 添加tp_order_id屬性來跟踪當前的止盈單
        self.tp_order_id = None
        
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
        self._live_display = None
        self.current_market_price = None 

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
                # 訂單已成交
                order_id = data.get("i")
                price = float(data.get("L", 0))  # 成交價格
                quantity = float(data.get("l", 0))  # 成交數量
                side = data.get("S")
                
                self.logger.info(f"訂單成交: ID={order_id}, 價格={price}, 數量={quantity}, 方向={side}")
                
                # 更新持倉狀態
                if side == "Bid":  # 買入訂單
                    self.holding_position = True
                    
                    # 更新入場價格
                    if not hasattr(self, 'entry_price') or self.entry_price is None:
                        self.entry_price = price
                        self.total_bought = quantity
                    else:
                        # 計算新的平均入場價格
                        total_value = self.entry_price * self.total_bought + price * quantity
                        self.total_bought += quantity
                        self.entry_price = total_value / self.total_bought if self.total_bought > 0 else 0
                    
                    self.logger.info(f"更新持倉: 總數量={self.total_bought}, 平均價格={self.entry_price}")
                    
                    # 從活動訂單列表中移除已成交的訂單
                    self.active_orders = [order for order in self.active_orders if order.get('id') != order_id]
                    
                    # 計算新的止盈價格
                    take_profit_price = self.entry_price * (1 + self.settings.TAKE_PROFIT_PCT)
                    self.logger.info(f"更新止盈價格: {take_profit_price:.2f}")
                    
                    # 取消之前的止盈單（如果有）
                    if hasattr(self, 'tp_order_id') and self.tp_order_id:
                        try:
                            cancel_result = await self.client.cancel_order(self.tp_order_id, self.symbol)
                            self.logger.info(f"已取消舊的止盈單: {self.tp_order_id}, 結果: {cancel_result}")
                            self.tp_order_id = None
                        except Exception as e:
                            self.logger.error(f"取消舊止盈單失敗: {e}")
                    
                    # 掛出新的止盈單
                    try:
                        # 使用executor的place_limit_order方法
                        tp_order = await self.executor.place_limit_order(
                            side="Ask",  # 賣出方向
                            price=take_profit_price,
                            size=self.total_bought  # 使用size而不是quantity
                        )
                        if tp_order:
                            self.tp_order_id = tp_order.get('id')
                            self.logger.info(f"新止盈單已掛出: {tp_order}")
                    except Exception as e:
                        self.logger.error(f"掛出止盈單失敗: {e}")
                
                # 如果是止盈單成交
                elif side == "Ask" and self.holding_position:  # 賣出訂單
                    self.logger.info(f"止盈單成交: 價格={price}, 數量={quantity}")
                    
                    # 計算利潤
                    profit = (price - self.entry_price) * quantity
                    self.logger.info(f"止盈成功，利潤: {profit:.4f} USDC")
                    
                    # 取消所有剩餘的買單
                    try:
                        cancel_result = await self.client.cancel_all_orders(self.symbol)
                        self.logger.info(f"已取消所有剩餘訂單: {cancel_result}")
                        self.active_orders = []
                    except Exception as e:
                        self.logger.error(f"取消剩餘訂單失敗: {e}")
                    
                    # 重置持倉狀態
                    self.holding_position = False
                    self.entry_price = None
                    self.total_bought = 0
                    self.tp_order_id = None
                    
                    # 記錄循環結束
                    if hasattr(self.stats, 'record_cycle_end'):
                        cycle_stats = self.stats.record_cycle_end(profit)
                        cycle_id = cycle_stats.get('cycle_id', 'unknown') if cycle_stats else 'unknown'
                        self.logger.info(f"交易循環 #{cycle_id} 完成，利潤: {profit:.4f} USDC")
                    
                    # 開始新的循環
                    if hasattr(self.stats, 'record_cycle_start'):
                        self.stats.record_cycle_start()
                        self.logger.info(f"開始新的交易循環 #{self.stats.total_cycles}")
                    
                    # 以止盈價格向下price_step_down開始掛新的5階梯訂單
                    current_price = price
                    self.logger.info(f"以止盈價格 {current_price} 為基準，開始掛新的入場訂單")
                    
                    # 生成新的訂單計劃
                    order_plan = []
                    for i in range(self.settings.MAX_LAYERS):
                        # 只在首單用ENTRY_GAP_AFTER_TP，其餘用PRICE_STEP_DOWN
                        if i == 0 and hasattr(self.settings, 'ENTRY_GAP_AFTER_TP') and self.settings.ENTRY_GAP_AFTER_TP:
                            gap = self.settings.ENTRY_GAP_AFTER_TP
                        else:
                            gap = self.settings.PRICE_STEP_DOWN
                        step_price = current_price * current_price * (1 - gap * (i + 1))
                        step_amount = self.settings.FIRST_ORDER_AMOUNT * (2 ** i)
                        order_plan.append({
                            'price': step_price,
                            'quantity': step_amount / step_price
                        })
                    
                    # 掛出新的入場訂單
                    self.active_orders = await self.executor.place_orders(order_plan)
                    if self.active_orders:
                        self.logger.info(f"成功掛出 {len(self.active_orders)} 個新的限價單")
        except Exception as e:
            self.logger.error(f"處理訂單更新失敗: {e}")

    def _generate_status_panel(self):
        """生成狀態面板的rich渲染對象"""
        table = Table(title=f"Martingale Bot Status ({self.symbol})", show_header=False, box=None)
        table.add_column("Parameter", style="cyan", no_wrap=True)
        table.add_column("Value", style="bright_green")

        table.add_row("Cycle #", str(self.stats.total_cycles))
        status_string = "Holding Position" if self.holding_position else "Awaiting Entry"
        if self.active_orders:
            status_string += f" ({len(self.active_orders)} active buy orders)"
        if hasattr(self, 'tp_order_id') and self.tp_order_id:
             status_string += " (TP order active)"
        table.add_row("Status", status_string)
        
        table.add_row("Total Bought", f"{self.total_bought:.4f} {self.symbol.split('_')[0]}" if hasattr(self, 'total_bought') and self.total_bought is not None else "N/A")
        table.add_row("Avg Entry Price", f"{self.entry_price:.2f}" if hasattr(self, 'entry_price') and self.entry_price is not None else "N/A")
        
        current_price_str = f"{self.current_market_price:.2f}" if hasattr(self, 'current_market_price') and self.current_market_price else "Fetching..."
        table.add_row("Current Price", current_price_str)

        if hasattr(self, 'entry_price') and self.entry_price and hasattr(self, 'current_market_price') and self.current_market_price:
            pnl_percentage = ((self.current_market_price - self.entry_price) / self.entry_price) * 100
            pnl_color = "green" if pnl_percentage >= 0 else "red"
            table.add_row("Current PNL", Text(f"{pnl_percentage:.2f}%", style=pnl_color))
        else:
            table.add_row("Current PNL", "N/A")

        tp_price_str = f"{self.entry_price * (1 + self.settings.TAKE_PROFIT_PCT):.2f}" if hasattr(self, 'entry_price') and self.entry_price else "N/A"
        table.add_row("Take Profit At", tp_price_str)

        table.add_row("Total Profit", f"{self.stats.total_profit:.4f} USDC")
        
        # 您可以添加更多行，例如最近的錯誤、WebSocket連接狀態等

        return Panel(table, title="[b]Bot Overview[/b]", border_style="blue", expand=False)

    async def _update_current_market_price(self):
        # 這個輔助方法需要您實現，以獲取當前市場價格用於PNL計算
        # 這可能需要調用 self.client.get_ticker(self.symbol)
        try:
            ticker = await self.client.get_ticker(self.symbol)
            if ticker and 'lastPrice' in ticker:
                self.current_market_price = float(ticker['lastPrice'])
            else:
                self.current_market_price = None #或者保持舊值
        except Exception as e:
            self.logger.warning(f"Failed to fetch current market price: {e}")
            self.current_market_price = None #或者保持舊值


    async def run(self):
        """主運行循環"""
        # 開始第一個交易循環
        if hasattr(self.stats, 'record_cycle_start'): self.stats.record_cycle_start()
        self.logger.info(f"開始新的交易循環 #{self.stats.total_cycles if hasattr(self, 'stats') else 'N/A'}")
        
        # 初始連接WebSocket
        try:
            await self.ws.connect()
            if hasattr(self.ws, 'subscribe_account_updates'):
                await self.ws.subscribe_account_updates()
            else:
                await self.ws.subscribe("account.orderUpdate")
            self.logger.info("WebSocket連接已啟動並訂閱訂單更新")
        except Exception as e:
            self.logger.error(f"啟動WebSocket失敗: {e}")

        # 獲取初始市場價格
        await self._update_current_market_price()
        
        with Live(self._generate_status_panel(), refresh_per_second=1, screen=False, vertical_overflow="visible") as live:
            self._live_display = live
            while True:
                try:
                    # 更新當前市場價格用於面板顯示
                    await self._update_current_market_price()

                    # 檢查風險限制
                    if hasattr(self, 'check_risk_limits') and await self.check_risk_limits():
                        self.logger.warning("風險限制觸發，等待重新啟動")
                        await asyncio.sleep(300)
                        if hasattr(self.stats, 'record_cycle_start'): self.stats.record_cycle_start()
                        self.logger.info(f"重新啟動交易循環 #{self.stats.total_cycles if hasattr(self, 'stats') else 'N/A'}")
                        continue
                    
                    # 檢查WebSocket連接狀態 - 只在連接斷開時重連
                    if self.ws and not self.ws.is_connected():
                        self.logger.warning("WebSocket連接已斷開，嘗試重新連接")
                        try:
                            await self.ws.connect()
                            if hasattr(self.ws, 'subscribe_account_updates'):
                                await self.ws.subscribe_account_updates()
                            else:
                                await self.ws.subscribe("account.orderUpdate")
                            self.logger.info("WebSocket重新連接成功")
                        except Exception as e:
                            self.logger.error(f"WebSocket重新連接失敗: {e}")
                    
                    active_orders_count = len(self.active_orders)
                    
                    if active_orders_count > 0:
                        self.logger.info(f"當前有 {active_orders_count} 個活動訂單，等待成交")
                        
                        if not (self.ws and self.ws.is_connected()):
                            self.logger.info("WebSocket未連接，嘗試通過REST API檢查訂單成交")
                            filled_order = await self.monitor.check_for_filled_orders()
                            
                            if not filled_order:
                                try:
                                    positions = await self.client.get_positions(self.symbol)
                                    if positions:
                                        for position in positions:
                                            position_amt = float(position.get('positionAmt', 0))
                                            if position_amt > 0:
                                                self.logger.info(f"通過持倉查詢發現成交: {position}")
                                                filled_order = {
                                                    'id': f"position_{int(time.time())}",
                                                    'price': float(position.get('entryPrice', 0)),
                                                    'quantity': position_amt,
                                                    'side': 'Bid', # 注意這裡可能需要確認是 'Bid' 還是 'BUY'
                                                    'status': 'FILLED'
                                                }
                                                break # 假設只處理一個持倉
                                except Exception as e:
                                    self.logger.error(f"持倉查詢失敗: {e}")
                                
                            if not filled_order:
                                try:
                                    fill_history = await self.client.get_fill_history(self.symbol)
                                    if fill_history and len(fill_history) > 0:
                                        recent_fill = fill_history[0]
                                        self.logger.info(f"通過成交歷史發現成交: {recent_fill}")
                                        filled_order = {
                                            'id': recent_fill.get('orderId', f"fill_{int(time.time())}"),
                                            'price': float(recent_fill.get('price', 0)),
                                            'quantity': float(recent_fill.get('qty', 0)),
                                            'side': recent_fill.get('side', 'Bid'), # 同上，確認 'Bid' 或 'BUY'
                                            'status': 'FILLED'
                                        }
                                except Exception as e:
                                    self.logger.error(f"成交歷史查詢失敗: {e}")
                            
                            if filled_order: # 如果REST API檢測到成交
                                # 這裡需要調用類似 on_order_update 的邏輯來處理成交
                                # 或者確保 on_order_update 可以被手動觸發
                                self.logger.info(f"REST API檢測到成交，手動處理: {filled_order}")
                                # 假設您有一個方法可以模擬WebSocket的成交處理
                                # await self.on_order_update(filled_order) # 注意: on_order_update 的參數格式需要匹配
                                # 簡單處理:
                                self.holding_position = True
                                current_entry_price = self.entry_price if self.entry_price is not None else 0
                                current_total_bought = self.total_bought if self.total_bought is not None else 0
                                
                                total_value = current_entry_price * current_total_bought + filled_order['price'] * filled_order['quantity']
                                self.total_bought = current_total_bought + filled_order['quantity']
                                self.entry_price = total_value / self.total_bought if self.total_bought > 0 else 0
                                
                                self.logger.info(f"更新持倉: 總數量={self.total_bought}, 平均價格={self.entry_price}")
                                self.active_orders = [o for o in self.active_orders if o.get('id') != filled_order.get('id')]

                                # 重新計算並掛止盈單
                                take_profit_price = self.entry_price * (1 + self.settings.TAKE_PROFIT_PCT)
                                self.logger.info(f"預計止盈價格: {take_profit_price:.2f}")
                                if hasattr(self, 'tp_order_id') and self.tp_order_id:
                                    try:
                                        await self.client.cancel_order(self.tp_order_id, self.symbol) # 確保 cancel_order 方法存在
                                        self.logger.info(f"已取消舊的止盈單: {self.tp_order_id}")
                                        self.tp_order_id = None
                                    except Exception as e:
                                        self.logger.error(f"取消舊止盈單失敗: {e}")
                                try:
                                    tp_order = await self.executor.place_take_profit_order(
                                        self.symbol, 
                                        self.total_bought, 
                                        take_profit_price
                                    )
                                    if tp_order and tp_order.get('id'):
                                        self.tp_order_id = tp_order.get('id')
                                        self.logger.info(f"新止盈單已掛出: {tp_order}")
                                    else:
                                        self.logger.error(f"通過REST檢測成交後，掛出止盈單失敗: {tp_order}")
                                except Exception as e:
                                    self.logger.error(f"通過REST檢測成交後，掛出止盈單時發生錯誤: {e}")

                                

                    # WebSocket連接正常時，等待 on_order_update 回調處理成交
                    
                    # 您原有的 "如果檢測到成交" 邏輯塊，主要用於REST API檢測到的成交
                    # 但由於上面已經處理了 filled_order，這裡的邏輯可能需要調整或移除
                    # 如果 filled_order 在WebSocket正常時為None，這部分不會執行
                    # if filled_order: ... (這部分邏輯可能與上面重複，需要小心處理)

                    elif not self.holding_position:
                        self.logger.info("準備掛新單，先取消所有未成交訂單")
                        try:
                            cancel_result = await self.client.cancel_all_orders(self.symbol)
                            if cancel_result:
                                self.logger.info(f"成功取消所有未成交訂單: {cancel_result}")
                                self.active_orders = []
                                if hasattr(self.monitor, 'active_orders'): self.monitor.active_orders = {}
                        except Exception as e:
                            self.logger.error(f"取消訂單失敗: {e}")
                        
                        if hasattr(self, 'missing_order_count'): self.missing_order_count = 0
                        
                        self.logger.info("尚未持倉，開始掛單")
                        order_plan = await self.strategy.generate_orders()
                        new_orders = await self.executor.place_orders(order_plan)
                        if new_orders:
                            self.active_orders.extend(new_orders) # 將新訂單添加到列表中
                            self.logger.info(f"成功掛出 {len(new_orders)} 個限價單")
                            if hasattr(self.stats, 'record_order'):
                                for order in new_orders: self.stats.record_order(order)
                            if hasattr(self.monitor, 'track_orders'): self.monitor.track_orders(new_orders)
                        else:
                            self.logger.warning("所有限價單掛單失敗，等待下次重試")
                            await asyncio.sleep(60)
                            continue
                    
                    elif self.holding_position:
                        # 已持倉，檢查是否需要止盈 (這部分主要由on_order_update處理止盈單成交)
                        # 但這裡可以保留一個基於市價的備用止盈檢查，以防WebSocket消息遺失
                        try:
                            # ticker_data = await self.client.get_ticker(self.symbol) # 已移到 _update_current_market_price
                            if self.current_market_price and self.entry_price is not None:
                                # pnl = (self.current_market_price - self.entry_price) / self.entry_price # 已經在 _generate_status_panel 計算
                                # self.logger.info(f"目前價格：{self.current_market_price}，入場價：{self.entry_price}，PNL：{pnl:.4%}")
                                
                                # 檢查是否達到止盈條件 (主要由WebSocket的止盈單成交觸發)
                                # 但這裡可以有一個備用的市價止盈，如果止盈單意外失效
                                # if pnl >= self.settings.TAKE_PROFIT_PCT:
                                #     self.logger.info(f"市價達到止盈條件，嘗試市價平倉")
                                #     # ... (執行市價平倉邏輯，然後重置) ...

                                # 確保止盈單仍然存在，如果不存在且持倉，可能需要重新掛單
                                if hasattr(self, 'tp_order_id') and not self.tp_order_id and self.total_bought > 0:
                                    self.logger.warning("持倉中但沒有有效的止盈單ID，嘗試重新掛止盈單")
                                    take_profit_price = self.entry_price * (1 + self.settings.TAKE_PROFIT_PCT)
                                    try:
                                        tp_order = await self.executor.place_take_profit_order(
                                            self.symbol, 
                                            self.total_bought, 
                                            take_profit_price
                                        )
                                        if tp_order and tp_order.get('id'):
                                            self.tp_order_id = tp_order.get('id')
                                            self.logger.info(f"重新掛出止盈單成功: {tp_order}")
                                        else:
                                            self.logger.error(f"重新掛出止盈單失敗: {tp_order}")
                                    except Exception as e:
                                        self.logger.error(f"重新掛出止盈單時發生錯誤: {e}")
                            # elif self.entry_price is None and self.holding_position: # 移到 on_order_update 處理
                            #     self.logger.warning("入場價格未設置，無法計算PNL")
                            #     await self.reset()
                            #     continue
                            # else: # current_market_price is None
                            #     self.logger.warning("無法獲取當前價格用於止盈檢查")
                        except Exception as e:
                            self.logger.error(f"檢查止盈失敗: {e}")
                    
                    # 更新Live Display
                    if self._live_display:
                        self._live_display.update(self._generate_status_panel())

                    # 獲取休眠時間
                    try:
                        sleep_interval = self.settings.MAIN_LOOP_SLEEP_INTERVAL
                    except AttributeError:
                        sleep_interval = 60 # 默認值
                        self.logger.debug(f"'MAIN_LOOP_SLEEP_INTERVAL' not found in settings, using default: {sleep_interval}s")
                    
                    await asyncio.sleep(sleep_interval) # 使用獲取到的或默認的休眠時間
                    
                    
                    
                except asyncio.CancelledError:
                    self.logger.info("Run loop cancelled.")
                    if self._live_display: self._live_display.stop() # 確保Live display停止
                    break
                except Exception as e:
                    self.logger.exception(f"主迴圈發生錯誤：{e}")
                    if self._live_display:
                        error_panel = Panel(Text(f"An error occurred in main loop: {str(e)[:200]}...", style="bold red"), title="[b]MAIN LOOP ERROR[/b]", border_style="red")
                        self._live_display.update(error_panel)
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