


import asyncio
import argparse
from dotenv import load_dotenv
import os
from main.martingale_runner import MartingaleRunner
from config.settings import Settings
from utils.logger import init_logger
from api.client import BackpackAPIClient

load_dotenv()  # 載入.env文件

api_key = os.getenv("BACKPACK_API_KEY")
secret_key = os.getenv("BACKPACK_API_SECRET")
client = BackpackAPIClient(api_key=api_key, secret_key=secret_key)
order = client.execute_order({
    "symbol": "BTC_USDC",
    "side": "Bid",
    "orderType": "Market",
    "quoteQuantity": 10
})

def parse_args():
    parser = argparse.ArgumentParser(description="Martingale Trading Bot")
    parser.add_argument('--mode', choices=['live', 'paper'], default='live', help='Trading mode')
    parser.add_argument('--symbol', type=str, help='Override trading symbol from config')
    return parser.parse_args()

async def main():
    # Load environment variables
    load_dotenv()
    args = parse_args()

    # Initialize config and logger
    settings = Settings()
    if args.symbol:
        settings.SYMBOL = args.symbol
    settings.MODE = args.mode

    logger = init_logger(name="MartingaleBot")

    logger.info("Starting Martingale Bot in %s mode on symbol %s", settings.MODE, settings.SYMBOL)

    # 創建API客戶端 - 修改參數名稱
    client = BackpackAPIClient(
        api_key=settings.API_KEY,
        secret_key=settings.API_SECRET  # 從api_secret改為secret_key
    )

    # Start runner - 傳入client參數
    runner = MartingaleRunner(client, settings.SYMBOL, settings, logger)
    await runner.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Bot stopped manually.")
