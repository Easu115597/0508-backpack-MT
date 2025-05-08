# config/settings.py

import os
from dotenv import load_dotenv

load_dotenv()  # 自動讀取 .env 參數

API_URL = "https://api.backpack.exchange"
API_VERSION = "v1"
DEFAULT_WINDOW = 5000

API_KEY = os.getenv("BACKPACK_API_KEY")
API_SECRET = os.getenv("BACKPACK_API_SECRET")
SYMBOL = os.getenv("SYMBOL", "SOL_USDC")

API_URL = os.getenv("API_URL", "https://api.backpack.exchange")
API_VERSION = os.getenv("API_VERSION", "v1")
DEFAULT_WINDOW = int(os.getenv("DEFAULT_WINDOW", 5000))

# 策略參數
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", 0.02))      # 1%
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", -0.3))         # -30%
PRICE_STEP_DOWN = float(os.getenv("PRICE_STEP_DOWN", 0.005))     # -0.5%
MULTIPLIER = float(os.getenv("MULTIPLIER", 2))
USE_MARKET_ORDER = os.getenv("USE_MARKET_ORDER", "false").lower() == "true"
ENTRY_SIZE_USDT = float(os.getenv("ENTRY_SIZE_USDT", 10))

# 監控設定
ORDER_TIMEOUT_SEC = int(os.getenv("ORDER_TIMEOUT_SEC", 20))

# 其他設定可擴充...

class Settings:
    def __init__(self):
        self.api_url = API_URL
        self.api_version = API_VERSION
        self.default_window = DEFAULT_WINDOW
        self.API_KEY = API_KEY
        self.API_SECRET = API_SECRET
        
    @classmethod
    def get_instance(cls):
        return cls()
