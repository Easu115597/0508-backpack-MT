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
    def __init__(self, settings, logger, client=None,precision_manager=None):
        self.settings = settings
        self.logger = logger
        self.client = client
        self.precision_manager = precision_manager
        # 初始化策略狀態
        self.active_orders = []
        self.total_bought = 0  # 解決'total_bought'屬性缺失問題
        self.entry_price = None
        self.avg_price = 0
        self.filled_orders = []

    async def generate_entry_orders(self):
        """生成所有層級的訂單"""
        current_price = await self.get_current_price()
        self.logger.info(f"生成入場訂單，當前價格: {current_price}")
        
        # 分配資金到各層
        allocated_funds = self.allocate_funds()

       
        
        orders = []
        # 為每一層生成訂單
        for i in range(self.settings.MAX_LAYERS):
            # 計算價格 - 每層遞減
            price = current_price * (1 - self.settings.PRICE_STEP_DOWN * (i + 1))
            
            # 計算數量
            quantity = allocated_funds[i] / price

            # 使用精度管理器格式化價格和數量
            formatted_price = await self.precision_manager.format_price(self.settings.SYMBOL, price)
            formatted_quantity = await self.precision_manager.format_quantity(self.settings.SYMBOL, quantity)
            
            orders.append({
                "price": formatted_price,  # 根據交易所精度調整
                "quantity": formatted_quantity,
                "type": "limit",
                "side": "Bid"  # 使用"Bid"而非"buy"
            })
            
        return orders
    
    async def generate_orders(self):
        """兼容舊方法，調用generate_entry_orders"""
        return await self.generate_entry_orders()
    
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
                "type": "Limit",
                "side": "buy"
            })
            
        return orders
    
    def allocate_funds(self):
        """分配資金到各層 - 首單固定金額"""
        total = self.settings.ENTRY_SIZE_USDT
        
        # 檢查是否使用固定首單金額
        if self.settings.FIRST_ORDER_AMOUNT > 0:
            first_order_amount = self.settings.FIRST_ORDER_AMOUNT
            remaining_amount = total - first_order_amount  # 剩餘金額
            
            allocations = [first_order_amount]  # 首單固定金額
            
            # 計算剩餘層數的總權重
            remaining_layers = self.settings.MAX_LAYERS - 1
            if remaining_layers > 0:  # 確保至少有一個剩餘層
                total_weight = sum(self.settings.MULTIPLIER ** i for i in range(remaining_layers))
                
                # 按權重分配剩餘資金
                for i in range(1, self.settings.MAX_LAYERS):
                    weight = self.settings.MULTIPLIER ** (i-1)
                    allocation = remaining_amount * weight / total_weight
                    allocations.append(allocation)
            
            return allocations
        else:
            # 原始的資金分配邏輯
            total_weight = sum(self.settings.MULTIPLIER ** i for i in range(self.settings.MAX_LAYERS))
            allocations = []
            
            for i in range(self.settings.MAX_LAYERS):
                weight = self.settings.MULTIPLIER ** i
                allocation = total * weight / total_weight
                allocations.append(allocation)
            
            return allocations
    
    def calculate_pnl(self, avg_entry_price, current_price):
        """計算當前盈虧百分比"""
        if not avg_entry_price or avg_entry_price <= 0:
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
    
    async def get_current_price(self):
        """獲取當前市場價格"""
        try:
            if hasattr(self.client, 'get_ticker'):
                ticker = await self.client.get_ticker(self.settings.SYMBOL)
                if ticker and 'lastPrice' in ticker:
                    return float(ticker['lastPrice'])
            # 如果API調用失敗，使用入場價格作為備用
            self.logger.warning("無法獲取市場價格，使用入場價格作為備用")
            return float(self.settings.ENTRY_PRICE)
        except Exception as e:
            self.logger.error(f"獲取價格失敗: {str(e)}")
            return float(self.settings.ENTRY_PRICE)
    
    def update_avg_price(self, new_price, new_quantity):
        """更新平均持倉價格"""
        if self.total_bought == 0:
            self.avg_price = new_price
        else:
            total_value = self.avg_price * self.total_bought + new_price * new_quantity
            self.total_bought += new_quantity
            self.avg_price = total_value / self.total_bought if self.total_bought > 0 else 0

    def track_order(self, order_id, price, quantity):
        """追蹤訂單狀態"""
        self.active_orders.append({
            "id": order_id,
            "price": price,
            "quantity": quantity,
            "status": "new"
        })
        self.logger.info(f"追蹤新訂單: {order_id} @ {price}")

    def handle_filled_order(self, order_data):
        """處理已成交訂單"""
        order_id = order_data.get("id")
        price = float(order_data.get("price", 0))
        quantity = float(order_data.get("executedQuantity", 0))
        
        # 更新持倉均價
        self.update_avg_price(price, quantity)
        
        # 移除活動訂單，添加到已成交訂單
        self.active_orders = [o for o in self.active_orders if o["id"] != order_id]
        self.filled_orders.append(order_data)
        
        self.logger.info(f"訂單成交: {order_id} | 價格: {price} | 數量: {quantity}")
        self.logger.info(f"更新後持倉均價: {self.avg_price} | 總持倉: {self.total_bought}")
    
    def reset(self):
        """重設策略狀態"""
        self.active_orders.clear()
        self.filled_orders.clear()
        self.total_bought = 0
        self.entry_price = None
        self.avg_price = 0