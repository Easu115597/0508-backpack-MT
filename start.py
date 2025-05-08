

import os
import asyncio
import argparse
from dotenv import load_dotenv
from core.strategy import MartingaleStrategy
from main.martingale_runner import MartingaleRunner
from config.settings import Settings
from utils.logger import init_logger

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

    # Start runner
    runner = MartingaleRunner(settings, logger)
    await runner.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Bot stopped manually.")
