# main/martingale_runner.py

import asyncio
import logging
from core.order_executor import OrderExecutor
from core.strategy import MartingaleStrategy
from core.order_monitor import OrderMonitor
from api.client import BackpackAPIClient
from utils.logger import init_logger  # optional: logging setup
from config import settings  # 包含 API 金鑰、參數設定等
from utils.precision_manager import PrecisionManager
from utils.trade_stats import TradeStats

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

        # 添加交易統計
        self.stats = TradeStats(symbol)
        
        # 創建精度管理器
        self.precision_manager = PrecisionManager(client, logger)
       
        # 初始化策略組件
        self.strategy = MartingaleStrategy(settings, logger, self.client,precision_manager=self.precision_manager)
        self.executor = OrderExecutor(self.client, self.symbol, self.precision_manager)
        self.monitor = OrderMonitor(self.client, self.symbol)
        
        # 初始化狀態變量
        self.active_orders = []
        self.holding_position = False
        self.entry_price = None
        
        self.logger.info(f"[OK] Runner 初始化完成: Symbol={self.symbol}")

    async def reset(self):
        """重置策略狀態"""
        try:
            # 取消所有活動訂單
            for order_id in list(self.active_orders.keys()):
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
        if self.settings.EMERGENCY_STOP:
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
                    
                    if loss_pct <= self.settings.MAX_LOSS_PCT:
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
            if hasattr(self, 'stats'):
                self.stats.record_emergency_stop()
            
            return True
        except Exception as e:
            self.logger.error(f"緊急停止失敗: {e}")
            return False

    

    async def run(self):
        # 開始第一個交易循環
        self.stats.record_cycle_start()
        self.logger.info(f"開始新的交易循環 #{self.stats.total_cycles}")
        
        while True:
            try:
                # 檢查風險限制
                if await self.check_risk_limits():
                    self.logger.warning("風險限制觸發，等待重新啟動")
                    await asyncio.sleep(300)  # 等待5分鐘後重新啟動
                    self.stats.record_cycle_start()
                    self.logger.info(f"重新啟動交易循環 #{self.stats.total_cycles}")
                    continue
                
                # 檢查是否已有活動訂單
                active_orders_count = len(self.active_orders)
                
                if active_orders_count > 0:
                    self.logger.info(f"當前有 {active_orders_count} 個活動訂單，等待成交")
                    
                    # 更新訂單狀態
                    filled_order = await self.monitor.check_for_filled_orders()
                    if filled_order:
                        self.holding_position = True
                        self.entry_price = filled_order['price']
                        self.total_bought = filled_order.get('quantity', 0)  # 更新持倉數量
                        self.logger.info(f"訂單成交：{filled_order}")
                        
                        # 記錄成交訂單
                        self.stats.record_filled_order(filled_order)
                        
                        # 計算止盈價格
                        take_profit_price = self.entry_price * (1 + self.settings.TAKE_PROFIT_PCT)
                        self.logger.info(f"預計止盈價格: {take_profit_price:.2f}")
                elif not self.holding_position:
                    try:
                        # 在掛新單前先取消所有未成交訂單
                        self.logger.info(f"準備掛新單，先取消所有未成交訂單")
                        cancel_result = await self.client.cancel_all_orders(self.symbol)
                        if cancel_result:
                            self.logger.info(f"成功取消所有未成交訂單: {cancel_result}")
                            # 清空本地訂單記錄
                            self.active_orders = []
                    except Exception as e:
                        self.logger.error(f"取消訂單失敗: {e}")
                        # 即使取消失敗，也繼續嘗試掛新單
                    
                    self.logger.info("尚未持倉，開始掛單")
                    
                    # 一次性掛出所有層級的訂單
                    order_plan = await self.strategy.generate_orders()
                    self.active_orders = await self.executor.place_orders(order_plan)
                    
                    if self.active_orders:
                        self.logger.info(f"成功掛出 {len(self.active_orders)} 個限價單")
                        
                        # 記錄訂單
                        for order in self.active_orders:
                            self.stats.record_order(order)
                        
                        self.monitor.track_orders(self.active_orders)
                    else:
                        self.logger.warning("所有限價單掛單失敗，等待下次重試")
                        await asyncio.sleep(60)
                        continue
                else:
                    # 已持倉，檢查是否需要止盈或加倉
                    try:
                        ticker_data = await self.client.get_ticker(self.symbol)
                        if ticker_data and 'lastPrice' in ticker_data:
                            current_price = float(ticker_data['lastPrice'])
                            
                            pnl = self.strategy.calculate_pnl(self.entry_price, current_price)
                            self.logger.info(f"目前價格：{current_price}，PNL：{pnl:.4f}")
                            
                            if self.strategy.should_take_profit(pnl):
                                # 計算本輪利潤
                                profit = (current_price - self.entry_price) * self.total_bought
                                self.logger.info(f"達到止盈，本輪利潤: {profit:.4f} USDC")
                                
                                # 平倉
                                await self.executor.close_position(self.symbol, self.total_bought)
                                
                                # 記錄循環結束
                                cycle_stats = self.stats.record_cycle_end(profit)
                                self.logger.info(f"交易循環 #{cycle_stats['cycle_id']} 完成，利潤: {profit:.4f} USDC")
                                
                                # 打印統計摘要
                                stats = self.stats.get_stats()
                                self.logger.info(f"總計完成 {stats['total_cycles']} 個循環，總利潤: {stats['total_profit']:.4f} USDC")
                                
                                # 重置狀態
                                await self.reset()
                                
                                # 開始新的循環
                                self.stats.record_cycle_start()
                                self.logger.info(f"開始新的交易循環 #{self.stats.total_cycles}")
                                continue
                        else:
                            self.logger.warning("無法獲取當前價格")
                    except Exception as e:
                        self.logger.error(f"檢查止盈失敗: {e}")
                
                await asyncio.sleep(60)  # 減少檢查頻率，避免API限制
                    
            except Exception as e:
                self.logger.exception(f"主迴圈發生錯誤：{e}")
                await asyncio.sleep(3)

async def main():
    client = BackpackAPIClient(
        api_key=settings.API_KEY,
        secret_key=settings.SECRET_KEY
        
    )
    runner = MartingaleRunner(client, settings, logger)
    await runner.run()


if __name__ == "__main__":
    asyncio.run(main())
