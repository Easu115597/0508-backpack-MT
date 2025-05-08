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
        self.total_bought = 0  # 解決'total_bought'屬性缺失問題
        self.entry_price = None
        self.avg_price = 0
        self.filled_orders = []

    def generate_entry_orders(self):
        """生成首次入場訂單計劃"""
        current_price = self.get_current_price()
        self.logger.info(f"生成入場訂單，當前價格: {current_price}")
        
        # 分配資金到各層
        allocated_funds = self.allocate_funds()
        
        orders = []
        base_price = current_price * (1 - self.settings.PRICE_STEP_DOWN)
        
        # 首單
        orders.append({
            "price": round(base_price, 1),  # 根據交易所精度調整
            "quantity": round(allocated_funds[0] / base_price, 5),
            "type": "limit",
            "side": "buy"
        })
        
        return orders
    
    def generate_orders(self):
        """兼容舊方法，調用generate_entry_orders"""
        return self.generate_entry_orders()
    
    def generate_additional_orders(self):
        """生成加倉訂單計劃"""
        if not self.entry_price:
            self.logger.warning("未設置入場價格，無法生成加倉訂單")
            return []
            
        allocated_funds = self.allocate_funds()
        orders = []
        
        # 從第二層開始
        for i in range(1, min(len(allocated_funds), self.settings.MAX_LAYERS)):
            price = self.entry_price * (1 - self.settings.PRICE_STEP_DOWN * i)
            quantity = allocated_funds[i] / price
            
            orders.append({
                "price": round(price, 1),
                "quantity": round(quantity, 5),
                "type": "limit",
                "side": "buy"
            })
            
        return orders
    
    def allocate_funds(self):
        """分配資金到各層"""
        total = self.settings.ENTRY_SIZE_USDT
        allocations = []
        
        # 計算總權重
        total_weight = sum(self.settings.MULTIPLIER ** i for i in range(self.settings.MAX_LAYERS))
        
        # 按權重分配資金
        for i in range(self.settings.MAX_LAYERS):
            weight = self.settings.MULTIPLIER ** i
            allocation = total * weight / total_weight
            allocations.append(allocation)
            
        return allocations
    
    def calculate_pnl(self, avg_entry_price, current_price):
        """計算當前盈虧百分比"""
        if not avg_entry_price or avg_entry_price == 0:
            return 0
        return (current_price - avg_entry_price) / avg_entry_price
    
    def should_take_profit(self, pnl):
        """判斷是否達到止盈條件"""
        return pnl >= self.settings.TAKE_PROFIT_PCT
    
    def should_stop_loss(self, pnl):
        """判斷是否達到止損條件"""
        return pnl <= self.settings.STOP_LOSS_PCT
    
    def should_add_order(self, pnl):
        """判斷是否應該加倉"""
        # 當價格下跌超過一定幅度時加倉
        return pnl < -self.settings.PRICE_STEP_DOWN and len(self.active_orders) < self.settings.MAX_LAYERS
    
    def get_current_price(self):
        """獲取當前市場價格"""
        # 實際實現應該調用API
        return 95000  # 示例價格
    
    def update_avg_price(self, new_price, new_quantity):
        """更新平均持倉價格"""
        if self.total_bought == 0:
            self.avg_price = new_price
        else:
            total_value = self.avg_price * self.total_bought + new_price * new_quantity
            self.total_bought += new_quantity
            self.avg_price = total_value / self.total_bought if self.total_bought > 0 else 0
    
    def reset(self):
        """重設策略狀態"""
        self.active_orders.clear()
        self.filled_orders.clear()
        self.total_bought = 0
        self.entry_price = None
        self.avg_price = 0
