import asyncio
import time
from core.backpack_client import BackpackAPIClient
from core.order_monitor import OrderMonitor
from core.order_executor import OrderExecutor
from core.strategy import MartingaleStrategy

class MartingaleRunner:
    def __init__(self, client: BackpackAPIClient, symbol: str, config: dict):
        self.client = client
        self.symbol = symbol
        self.config = config

        self.monitor = OrderMonitor(client)
        self.executor = OrderExecutor(client, symbol, self.monitor, config)
        self.strategy = MartingaleStrategy(config)

        self.active = True

    async def run(self):
        asyncio.create_task(self.monitor.loop_check(interval=1))  # 啟動訂單檢查

        while self.active:
            await self.monitor.sync_orders_status()  # 強制同步所有掛單狀態
            filled_orders = self.monitor.get_filled_orders()

            # 如果有成交單，更新策略
            if filled_orders:
                for order in filled_orders:
                    self.strategy.record_filled_order(order)

                self.monitor.remove_filled_orders()  # 移除已處理的成交單

            # 判斷是否需要止盈
            if self.strategy.should_take_profit():
                print("止盈達成，取消掛單並平倉")
                await self.executor.cancel_all()
                await self.executor.take_profit_exit(self.strategy.get_total_position())
                self.strategy.reset()
                self.monitor.reset()
                await asyncio.sleep(1)
                continue

            # 判斷是否需要加碼或補單
            new_orders = self.strategy.next_orders()
            for order in new_orders:
                await self.executor.place_order(order)

            await asyncio.sleep(2)


# 實際啟動
if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--symbol', required=True)
    args = parser.parse_args()

    # 初始化 API client 與策略參數
    client = BackpackAPIClient()
    config = {
        'price_step_down': 0.01,
        'take_profit_pct': 0.015,
        'stop_loss_pct': 0.05,
        'multiplier': 2,
        'use_market_order': False,
        'entry_price': None,
        'base_order_size': 10  # 例如 10 USDC 倉位
    }

    runner = MartingaleRunner(client, args.symbol, config)
    asyncio.run(runner.run())
