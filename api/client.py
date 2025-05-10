# api/client.py
import time
import json
import base64
import hmac
import hashlib
import requests
import logging
import nacl.signing
import aiohttp
from datetime import datetime


# 配置常量
API_URL = "https://api.backpack.exchange"
API_VERSION = "v1"
DEFAULT_WINDOW = 5000

logger = logging.getLogger(__name__)

class BackpackAPIClient:
    def __init__(self, api_key=None, secret_key=None, symbol=None):
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = API_URL  # 確保使用正確的變數名
        self.default_window = DEFAULT_WINDOW
        self.symbol = symbol
        self.time_offset = 0
        self.logger = logging.getLogger(__name__)
        self._sync_server_time()
    
    def _sync_server_time(self):
        """同步服務器時間"""
        try:
            response = requests.get(f"{self.base_url}/api/v1/time")
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict) and 'serverTime' in data:
                    self.time_offset = data['serverTime'] - int(time.time() * 1000)
                    return True
            return False
        except Exception as e:
            logger.error(f"時間同步失敗: {str(e)}")
            return False

    def _generate_signature(self, params, instruction="orderExecute"):
        try:
            timestamp = str(int(time.time() * 1000))
            window = str(self.default_window)
            
            # 排序參數並轉換為查詢字符串
            if isinstance(params, dict):
                # 轉換布爾值
                params_copy = params.copy()
                for k, v in params_copy.items():
                    if isinstance(v, bool):
                        params_copy[k] = str(v).lower()
                
                # 按字母順序排序
                sorted_params = sorted(params_copy.items())
                param_str = "&".join([f"{k}={v}" for k, v in sorted_params])
            else:
                param_str = params
            
            # 構建簽名消息
            message = f"instruction={instruction}&{param_str}&timestamp={timestamp}&window={window}"
            
            # 使用PyNaCl生成ED25519簽名
            import nacl.signing
            import base64
            
            # 解碼私鑰
            private_key_bytes = base64.b64decode(self.secret_key)
            signing_key = nacl.signing.SigningKey(private_key_bytes)
            
            # 簽名
            signed = signing_key.sign(message.encode('ascii'))
            signature = base64.b64encode(signed.signature).decode()
            
            # 返回簽名、時間戳和窗口
            return {
                "signature": signature,
                "timestamp": timestamp,
                "window": window
            }
        except Exception as e:
            self.logger.error(f"簽名生成失敗: {str(e)}")
            return None
    
    def _generate_headers(self, instruction, params):
        sig_data = self._generate_signature(params, instruction)
        if not sig_data:
            return {}
        
        headers = {
            "X-API-KEY": self.api_key,
            "X-SIGNATURE": sig_data["signature"],
            "X-TIMESTAMP": sig_data["timestamp"],
            "X-WINDOW": sig_data["window"],
            "Content-Type": "application/json"
        }
        return headers
        
    async def public_request(self, endpoint, params=None):
        """發送公共API請求"""
        try:
            url = f"{self.base_url}/api/v1/{endpoint}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        self.logger.error(f"公共請求失敗: {response.status}, {await response.text()}")
                        return None
        except Exception as e:
            self.logger.error(f"公共請求異常: {e}")
            return None
        
    async def get_order(self, order_id, symbol):
        """獲取訂單狀態"""
        try:
            # 嘗試獲取單個訂單
            endpoint = "/api/v1/order"
            params = {"orderId": order_id, "symbol": symbol}
            instruction = "orderQuery"
            
            headers = self._generate_headers(instruction, params)
            
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}{endpoint}", params=params, headers=headers) as response:
                    if response.status == 200:
                        return await response.json()
                    elif response.status == 404:
                        # 如果訂單不存在，嘗試從訂單歷史中查詢
                        return await self.get_order_from_history(order_id, symbol)
                    else:
                        error_msg = f"狀態碼: {response.status}, 消息: {await response.text()}"
                        self.logger.warning(f"獲取訂單失敗: {error_msg}")
                        return None
        except Exception as e:
            self.logger.error(f"獲取訂單異常: {str(e)}")
            return None
        
    async def get_order_from_history(self, order_id, symbol):
        """從訂單歷史中查詢訂單"""
        try:
            endpoint = "/api/v1/orders/history"
            params = {"orderId": order_id, "symbol": symbol}
            instruction = "orderHistoryQueryAll"
            
            headers = self._generate_headers(instruction, params)
            
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}{endpoint}", params=params, headers=headers) as response:
                    if response.status == 200:
                        orders = await response.json()
                        for order in orders:
                            if order.get('id') == order_id:
                                return order
                    return None
        except Exception as e:
            self.logger.error(f"獲取訂單歷史異常: {str(e)}")
            return None
        
    async def get_all_orders(self, symbol):
        """獲取所有訂單（包括活動和歷史）"""
        try:
            # 先獲取活動訂單
            active_orders = await self.get_active_orders(symbol)
            
            # 再獲取歷史訂單
            history_orders = await self.get_order_history(symbol)
            
            # 合併結果
            return active_orders + history_orders
        except Exception as e:
            self.logger.error(f"獲取所有訂單異常: {str(e)}")
            return []
    
    async def get_ticker(self, symbol):
        """獲取指定交易對的行情信息"""
        try:
            # 直接使用requests而非依賴public_request
            url = f"{self.base_url}/api/v1/ticker"
            params = {"symbol": symbol}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        self.logger.error(f"獲取行情失敗: {response.status}, {await response.text()}")
                        return None
        except Exception as e:
            self.logger.error(f"獲取行情異常: {e}")
            return None
    
    async def place_order(self, symbol, side, order_type, price=None, size=None):
        """兼容性方法，內部調用execute_order"""
        order_details = {
            "symbol": symbol,
            "side": side,
            "orderType": order_type
        }
        
        if order_type.lower() == "limit":
            order_details["price"] = str(price)
            order_details["quantity"] = str(size)
            order_details["timeInForce"] = "GTC"
        else:  # Market
            order_details["quantity"] = str(size)
        
        return await self.execute_order(order_details)
    
    def get_market_limits(self, symbol):
        """獲取市場限制"""
        endpoint = "/api/v1/markets"
        try:
            response = requests.get(f"{self.base_url}{endpoint}")
            if response.status_code == 200:
                normalized_symbol = symbol.replace('-', '_').upper()
                for market in response.json():
                    if market.get('symbol') == normalized_symbol:
                        return {
                            'base_precision': int(market.get('basePrecision', 8)),
                            'quote_precision': int(market.get('quotePrecision', 8)),
                            'min_order_size': float(market.get('minOrderSize', 0.00001)),
                            'tick_size': float(market.get('tickSize', 0.0001))
                        }
                logger.error(f"未找到交易對 {normalized_symbol}")
            return {}
        except Exception as e:
            logger.error(f"市場限制解析異常: {str(e)}")
            return {}
    
    async def execute_order(self, order_details):
        """執行訂單（異步方法）"""
        endpoint = "/api/v1/order"
        instruction = "orderExecute"
        
        # 確保交易對格式正確
        order_details['symbol'] = order_details['symbol'].replace('-', '_').upper()
        
        # 市價單處理
        if order_details.get('orderType') == 'Market':
            order_details.pop('price', None)
            if 'quoteQuantity' in order_details:
                order_details['quoteQuantity'] = str(order_details['quoteQuantity'])
        
        # 限價單處理
        else:
            if 'price' in order_details:
                order_details['price'] = str(order_details['price'])
            if 'quantity' in order_details:
                order_details['quantity'] = str(order_details['quantity'])
        
        # 布爾值處理 - 嘗試不同格式
        if 'postOnly' in order_details:
            # 移除postOnly參數，看看是否能解決問題
            del order_details['postOnly']
        
        # 生成請求頭
        headers = self._generate_headers(instruction, order_details)
        
        try:
            # 使用aiohttp進行異步請求
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}{endpoint}",
                    json=order_details,
                    headers=headers
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        error_msg = f"狀態碼: {response.status}, 消息: {await response.text()}"
                        self.logger.warning(f"請求失敗 (1/3): {error_msg}")
                        return {"error": error_msg}
                    
        except Exception as e:
            self.logger.error(f"訂單執行失敗: {str(e)}")
            return {"error": str(e)}
    
    def get_balance(self, asset=None):
        """獲取賬戶餘額"""
        endpoint = "/api/v1/balance"
        instruction = "balanceQuery"
        params = {}
        if asset:
            params["asset"] = asset
        
        headers = self._generate_headers(instruction, params)
        
        try:
            response = requests.get(
                f"{self.base_url}{endpoint}",
                headers=headers,
                params=params
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                error_msg = f"狀態碼: {response.status_code}, 消息: {response.text}"
                logger.warning(f"請求失敗: {error_msg}")
                return {"error": error_msg}
                
        except Exception as e:
            logger.error(f"獲取餘額失敗: {str(e)}")
            return {"error": str(e)}
    
    def get_open_orders(self, symbol=None):
        """獲取未成交訂單"""
        endpoint = "/api/v1/orders"
        instruction = "orderQueryAll"
        params = {}
        if symbol:
            params["symbol"] = symbol.replace('-', '_').upper()
        
        headers = self._generate_headers(instruction, params)
        
        try:
            response = requests.get(
                f"{self.base_url}{endpoint}",
                headers=headers,
                params=params
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                error_msg = f"狀態碼: {response.status_code}, 消息: {response.text}"
                logger.warning(f"請求失敗: {error_msg}")
                return {"error": error_msg}
                
        except Exception as e:
            logger.error(f"獲取未成交訂單失敗: {str(e)}")
            return {"error": str(e)}
    
    async def cancel_all_orders(self, symbol):
        """取消指定交易對的所有未成交訂單"""
        try:
            endpoint = "/api/v1/orders"
            payload = {"symbol": symbol}
            instruction = "orderCancelAll"
            
            # 生成請求頭
            headers = self._generate_headers(instruction, payload)
            
            # 使用aiohttp進行異步請求
            async with aiohttp.ClientSession() as session:
                async with session.delete(
                    f"{self.base_url}{endpoint}",
                    json=payload,  # 使用json參數
                    headers=headers
                ) as response:
                    if response.status == 200:
                        return await response.json()  # 確保返回的是協程
                    else:
                        error_msg = f"狀態碼: {response.status}, 消息: {await response.text()}"
                        self.logger.warning(f"取消所有訂單失敗: {error_msg}")
                        return None
                                                        
        except Exception as e:
            self.logger.error(f"取消所有訂單異常: {str(e)}")
            return None
    
    def get_fill_history(self, symbol=None, limit=100):
        """獲取成交歷史"""
        endpoint = "/wapi/v1/history/fills"
        instruction = "fillHistoryQueryAll"
        params = {"limit": str(limit)}
        if symbol:
            params["symbol"] = symbol.replace('-', '_').upper()
        
        headers = self._generate_headers(instruction, params)
        
        try:
            response = requests.get(
                f"{self.base_url}{endpoint}",
                headers=headers,
                params=params
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                error_msg = f"狀態碼: {response.status_code}, 消息: {response.text}"
                logger.warning(f"請求失敗: {error_msg}")
                return {"error": error_msg}
                
        except Exception as e:
            logger.error(f"獲取成交歷史失敗: {str(e)}")
            return {"error": str(e)}
        
    async def get_market_info(self, symbol):
        """獲取市場資訊，包括精度"""
        try:
            endpoint = "/api/v1/market"
            params = {"symbol": symbol}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}{endpoint}", params=params) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        self.logger.error(f"獲取市場資訊失敗: {response.status}, {await response.text()}")
                        return None
        except Exception as e:
            self.logger.error(f"獲取市場資訊異常: {e}")
            return None
