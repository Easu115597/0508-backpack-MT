# main/martingale_runner.py

import asyncio
import logging
from core.order_executor import OrderExecutor
from core.strategy import MartingaleStrategy
from core.order_monitor import OrderMonitor
from api.client import BackpackAPIClient
from utils.logger import init_logger  # optional: logging setup
from config import settings  # 包含 API 金鑰、參數設定等

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
        
        # 初始化策略組件
        self.strategy = MartingaleStrategy(settings, logger, self.client)
        self.executor = OrderExecutor(self.client, self.symbol)
        self.monitor = OrderMonitor(self.client, self.symbol)
        
        # 初始化狀態變量
        self.active_orders = []
        self.holding_position = False
        self.entry_price = None
        
        self.logger.info(f"[OK] Runner 初始化完成: Symbol={self.symbol}")

    async def reset(self):
        logger.info("重置狀態，取消所有掛單")
        await self.executor.cancel_all_orders()
        self.active_orders.clear()
        self.holding_position = False
        self.entry_price = None

    async def run(self):
        while True:
            try:
                if not self.holding_position:
                    self.logger.info("尚未持倉，開始掛單")
                    try:
                        # 生成所有層級的限價單
                        order_plan = await self.strategy.generate_orders()
                        
                        # 批量下單
                        self.active_orders = await self.executor.place_orders(order_plan)
                        if self.active_orders:
                            self.logger.info(f"成功掛出 {len(self.active_orders)} 個限價單")
                            self.monitor.track_orders(self.active_orders)
                        else:
                            self.logger.warning("所有限價單掛單失敗，等待下次重試")
                            await asyncio.sleep(10)
                            continue
                    except Exception as e:
                        self.logger.error(f"掛單失敗: {str(e)}")
                        await asyncio.sleep(5)
                        continue

                    # 等待首單成交
                    filled_order = await self.monitor.wait_for_first_fill()
                    if filled_order:
                        self.holding_position = True
                        self.entry_price = filled_order['price']
                        self.logger.info(f"首單成交：{filled_order}")
                else:
                    # 已持倉，檢查是否需要止盈或加倉
                    try:
                        current_price = await self.client.get_price(self.symbol)
                        if not self.entry_price or self.entry_price <= 0:
                            self.logger.warning("入場價格無效，無法計算PNL")
                            await asyncio.sleep(5)
                            continue
                            
                        pnl = self.strategy.calculate_pnl(
                            avg_entry_price=self.entry_price,
                            current_price=current_price
                        )

                        self.logger.info(f"目前價格：{current_price}，PNL：{pnl:.4f}")

                        if self.strategy.should_take_profit(pnl):
                            self.logger.info("達到止盈，平倉並重置")
                            await self.executor.close_position()
                            await self.reset()
                            await asyncio.sleep(1)
                            continue

                        if self.strategy.should_add_order(pnl):
                            self.logger.info("應補單，執行補倉邏輯")
                            new_orders = self.strategy.generate_additional_orders()
                            extra_orders = await self.executor.place_orders(new_orders)
                            if extra_orders:
                                self.monitor.track_orders(extra_orders)
                                self.active_orders.extend(extra_orders)
                                self.logger.info(f"成功掛出 {len(extra_orders)} 個補單")
                    except Exception as e:
                        self.logger.error(f"持倉管理錯誤: {str(e)}")

                await asyncio.sleep(1)

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
