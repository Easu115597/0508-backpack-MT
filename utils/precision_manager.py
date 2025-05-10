# 文件路徑: utils/precision_manager.py
import logging

class PrecisionManager:
    def __init__(self, client, logger):
        self.client = client
        self.logger = logger
        self.precision_cache = {}  # 緩存已獲取的精度資訊
        
    async def get_market_precision(self, symbol):
        """獲取指定交易對的精度資訊"""
        if symbol in self.precision_cache:
            return self.precision_cache[symbol]
            
        try:
            # 從交易所API獲取市場資訊
            market_info = await self.client.get_market_info(symbol)
            
            if market_info and 'filters' in market_info:
                precision = {
                    'price': {
                        'tickSize': float(market_info['filters']['price']['tickSize']),
                        'precision': self._calculate_precision(market_info['filters']['price']['tickSize'])
                    },
                    'quantity': {
                        'stepSize': float(market_info['filters']['quantity']['stepSize']),
                        'precision': self._calculate_precision(market_info['filters']['quantity']['stepSize'])
                    }
                }
                self.precision_cache[symbol] = precision
                return precision
        except Exception as e:
            self.logger.error(f"獲取{symbol}精度資訊失敗: {e}")
            
        # 如果獲取失敗，使用默認值
        default_precision = {
            'price': {'precision': 1},
            'quantity': {'precision': 3}
        }
        return default_precision
    
    def _calculate_precision(self, step_size_str):
        """根據步長計算精度"""
        step_size = float(step_size_str)
        if step_size == 0:
            return 0
            
        # 計算小數位數
        decimal_str = str(step_size).rstrip('0').rstrip('.') if '.' in str(step_size) else str(step_size)
        if '.' in decimal_str:
            return len(decimal_str.split('.')[1])
        return 0
        
    async def format_price(self, symbol, price):
        """格式化價格到正確精度"""
        precision = await self.get_market_precision(symbol)
        price_precision = precision['price']['precision']
        return round(float(price), price_precision)
        
    async def format_quantity(self, symbol, quantity):
        """格式化數量到正確精度"""
        precision = await self.get_market_precision(symbol)
        quantity_precision = precision['quantity']['precision']
        return round(float(quantity), quantity_precision)