# api/client.py
import time
import json
import base64
import hmac
import hashlib
import requests
import logging
import nacl.signing
from datetime import datetime


# 配置常量
API_URL = "https://api.backpack.exchange"
API_VERSION = "v1"
DEFAULT_WINDOW = 5000

logger = logging.getLogger(__name__)

class BackpackAPIClient:
    def __init__(self, api_key=None, secret_key=None):
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = API_URL  # 確保使用正確的變數名
        self.time_offset = 0
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

    def _generate_signature(self, message):
        try:
            # Ensure message is ASCII only
            message = message.encode('ascii', errors='ignore').decode('ascii')
            private_key = nacl.signing.SigningKey(base64.b64decode(self.secret_key))
            signature = base64.b64encode(private_key.sign(message.encode('ascii')).signature).decode()
            return signature
        except Exception as e:
            self.logger.error(f"簽名生成失敗: {str(e)}")
            return ""
    
    def _generate_headers(self, instruction, params=None):
        """生成API請求頭"""
        timestamp = str(int(time.time() * 1000) + self.time_offset)
        window = str(DEFAULT_WINDOW)
        
        # 構建簽名消息
        message = f"instruction={instruction}"
        if params:
            sorted_params = sorted(params.items())
            param_str = "&".join([f"{k}={v}" for k, v in sorted_params])
            if param_str:
                message += f"&{param_str}"
        message += f"&timestamp={timestamp}&window={window}"
        
        # 生成簽名
        signature = self._generate_signature(message)
        
        return {
            "X-API-KEY": self.api_key,
            "X-SIGNATURE": signature,
            "X-TIMESTAMP": timestamp,
            "X-WINDOW": window,
            "Content-Type": "application/json"
        }
    
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
    
    def execute_order(self, order_details):
        """執行訂單"""
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
        
        # 布爾值轉字符串
        if 'postOnly' in order_details:
            order_details['postOnly'] = str(order_details['postOnly']).lower()
        
        # 生成請求頭
        headers = self._generate_headers(instruction, order_details)
        
        try:
            response = requests.post(
                f"{self.base_url}{endpoint}",
                json=order_details,
                headers=headers
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                error_msg = f"狀態碼: {response.status_code}, 消息: {response.text}"
                logger.warning(f"請求失敗 (1/3): {error_msg}")
                return {"error": error_msg}
                
        except Exception as e:
            logger.error(f"訂單執行失敗: {str(e)}")
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
    
    def cancel_all_orders(self, symbol=None):
        """取消所有訂單"""
        endpoint = "/api/v1/orders"
        instruction = "orderCancelAll"
        params = {}
        if symbol:
            params["symbol"] = symbol.replace('-', '_').upper()
        
        headers = self._generate_headers(instruction, params)
        
        try:
            response = requests.delete(
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
            logger.error(f"取消訂單失敗: {str(e)}")
            return {"error": str(e)}
    
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
