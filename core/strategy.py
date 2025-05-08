# core/strategy.py

class Strategy:
    def __init__(self, entry_price, price_step_down, take_profit_pct, stop_loss_pct, multiplier, base_order_size):
        self.entry_price = entry_price
        self.price_step_down = price_step_down
        self.take_profit_pct = take_profit_pct
        self.stop_loss_pct = stop_loss_pct
        self.multiplier = multiplier
        self.base_order_size = base_order_size

    def calculate_order_prices(self, current_price, max_orders=3):
        prices = []
        for i in range(max_orders):
            price = round(self.entry_price * ((1 - self.price_step_down) ** i), 6)
            size = round(self.base_order_size * (self.multiplier ** i), 6)
            prices.append((price, size))
        return prices

    def should_take_profit(self, avg_entry_price, current_price):
        return current_price >= avg_entry_price * (1 + self.take_profit_pct)

    def should_stop_loss(self, avg_entry_price, current_price):
        return current_price <= avg_entry_price * (1 - self.stop_loss_pct)
    
class MartingaleStrategy:
    def __init__(self, settings, logger):
        self.settings = settings
        self.logger = logger
        # 初始化策略狀態
        self.active_orders = []

    def generate_orders(self, current_price, position_state):
        """
        根據當前價格與倉位狀態，產生應掛單的清單
        """
        # 範例：固定掛三單
        orders = []
        for i in range(3):
            price = current_price - i * self.settings.PRICE_STEP
            orders.append({
                "price": round(price, self.settings.PRICE_PRECISION),
                "size": self.settings.ORDER_SIZE
            })
        return orders

    def should_take_profit(self, current_price, avg_entry_price):
        """
        判斷是否達到止盈條件
        """
        return current_price >= avg_entry_price * (1 + self.settings.TAKE_PROFIT_PCT)

    def reset(self):
        """
        重設策略狀態
        """
        self.active_orders.clear()
