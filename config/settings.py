# config/settings.py

import os
from dotenv import load_dotenv

load_dotenv()  # 自動讀取 .env 參數

API_URL = "https://api.backpack.exchange"
API_VERSION = "v1"
DEFAULT_WINDOW = 5000

API_KEY = os.getenv("BACKPACK_API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
SYMBOL = os.getenv("SYMBOL", "SOL_USDC")

WS_URL = "wss://ws.backpack.exchange"
DEFAULT_WINDOW = 5000  # 默認窗口值，單位為毫秒

# 策略參數
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", 0.01))      # 3.3%
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", -0.3))         # -30%
PRICE_STEP_DOWN = float(os.getenv("PRICE_STEP_DOWN", 0.005))     # -1.5%
MULTIPLIER = float(os.getenv("MULTIPLIER", 1.3))
USE_MARKET_ORDER = os.getenv("USE_MARKET_ORDER", "false").lower() == "false"
ENTRY_SIZE_USDT = float(os.getenv("ENTRY_SIZE_USDT", 100))
MAX_LAYERS = int(os.getenv("MAX_LAYERS", 5))  # 默認3層
FIRST_ORDER_AMOUNT = float(os.getenv("FIRST_ORDER_AMOUNT", 40))  # 首單固定金額

# 風險管理參數
MAX_LOSS_PCT = float(os.getenv("MAX_LOSS_PCT", -0.1))  # 最大虧損比例，默認-10%
EMERGENCY_STOP = os.getenv("EMERGENCY_STOP", "false").lower() == "true"  # 緊急停止開關
SLIPPAGE_TOLERANCE = float(os.getenv("SLIPPAGE_TOLERANCE", 0.001))  # 滑點容忍度，默認0.1%

# 監控設定
ORDER_TIMEOUT_SEC = int(os.getenv("ORDER_TIMEOUT_SEC", 20))

# 其他設定可擴充...

class Settings:
    def __init__(self):
        self.api_url = API_URL
        self.api_version = API_VERSION
        self.default_window = DEFAULT_WINDOW
        self.API_KEY = API_KEY
        self.SECRET_KEY = SECRET_KEY
        # 添加所有策略需要的屬性
        self.ENTRY_SIZE_USDT = ENTRY_SIZE_USDT
        self.MAX_LAYERS = MAX_LAYERS
        self.MULTIPLIER = MULTIPLIER
        self.TAKE_PROFIT_PCT = TAKE_PROFIT_PCT
        self.STOP_LOSS_PCT = STOP_LOSS_PCT
        self.PRICE_STEP_DOWN = PRICE_STEP_DOWN
        self.USE_MARKET_ORDER = USE_MARKET_ORDER
        self.SYMBOL = SYMBOL
        self.ORDER_TIMEOUT_SEC = ORDER_TIMEOUT_SEC
        self.FIRST_ORDER_AMOUNT = 0  # 預設值為0，表示不使用固定首單金額
        self.EMERGENCY_STOP = False  # 默認關閉緊急停止
    
    @classmethod
    def get_instance(cls):
        return cls()
    
    @property
    def API_SECRET(self):
        return self.SECRET_KEY
