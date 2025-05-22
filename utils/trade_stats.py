# 文件路徑: utils/trade_stats.py
import time
import json
import os
from datetime import datetime

class TradeStats:
    def __init__(self, symbol, log_dir="logs"):
        self.symbol = symbol
        self.total_cycles = 0
        self.successful_cycles = 0
        self.total_profit = 0
        self.trades = []
        self.start_time = time.time()
        self.current_cycle = None
        
        # 創建日誌目錄
        self.log_dir = log_dir
        os.makedirs(self.log_dir, exist_ok=True)
        
        # 加載歷史數據(如果存在)
        self.stats_file = f"{self.log_dir}/{symbol}_stats.json"
        self._load_stats()
    
    def _load_stats(self):
        """從文件加載歷史統計數據"""
        try:
            if os.path.exists(self.stats_file):
                with open(self.stats_file, 'r') as f:
                    data = json.load(f)
                    self.total_cycles = data.get('total_cycles', 0)
                    self.successful_cycles = data.get('successful_cycles', 0)
                    self.total_profit = data.get('total_profit', 0)
                    self.trades = data.get('trades', [])
        except Exception as e:
            print(f"加載統計數據失敗: {e}")
    
    def _save_stats(self):
        """保存統計數據到文件"""
        try:
            data = {
                'symbol': self.symbol,
                'total_cycles': self.total_cycles,
                'successful_cycles': self.successful_cycles,
                'total_profit': self.total_profit,
                'trades': self.trades,
                'last_updated': datetime.now().isoformat()
            }
            with open(self.stats_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"保存統計數據失敗: {e}")
    
    def record_cycle_start(self):
        """記錄新交易循環的開始"""
        self.current_cycle = {
            'cycle_id': self.total_cycles + 1,
            'symbol': self.symbol,
            'start_time': datetime.now().isoformat(),
            'orders': [],
            'filled_orders': [],
            'profit': 0,
            'status': 'active'
        }
        self.total_cycles += 1
        self._save_stats()
        return self.current_cycle
    
    def record_order(self, order):
        """記錄訂單信息"""
        if self.current_cycle:
            self.current_cycle['orders'].append(order)
            self._save_stats()
    
    def record_filled_order(self, order):
        """記錄成交訂單"""
        if self.current_cycle:
            self.current_cycle['filled_orders'].append(order)
            self._save_stats()
    
    def record_cycle_end(self, profit):
        """記錄交易循環結束"""
        if self.current_cycle:
            self.current_cycle['end_time'] = datetime.now().isoformat()
            self.current_cycle['profit'] = profit
            self.current_cycle['status'] = 'completed'
            
            duration = datetime.fromisoformat(self.current_cycle['end_time']) - \
                      datetime.fromisoformat(self.current_cycle['start_time'])
            self.current_cycle['duration_seconds'] = duration.total_seconds()
            
            self.total_profit += profit
            if profit > 0:
                self.successful_cycles += 1
            
            self.trades.append(self.current_cycle)
            self._save_stats()
            
            completed_cycle = self.current_cycle
            self.current_cycle = None
            return completed_cycle
        return None
    
    def get_stats(self):
        """獲取統計摘要"""
        running_time = (time.time() - self.start_time) / 3600  # 小時
        return {
            'symbol': self.symbol,
            'total_cycles': self.total_cycles,
            'successful_cycles': self.successful_cycles,
            'success_rate': (self.successful_cycles / self.total_cycles * 100) if self.total_cycles > 0 else 0,
            'total_profit': self.total_profit,
            'average_profit': (self.total_profit / self.total_cycles) if self.total_cycles > 0 else 0,
            'running_time_hours': running_time,
            'current_cycle': self.current_cycle
        }
    
    def print_summary(self):
        """打印統計摘要"""
        stats = self.get_stats()
        print(f"\n===== {self.symbol} 交易統計 =====")
        print(f"總循環數: {stats['total_cycles']}")
        print(f"成功循環: {stats['successful_cycles']} ({stats['success_rate']:.2f}%)")
        print(f"總利潤: {stats['total_profit']:.8f}")
        print(f"平均每循環利潤: {stats['average_profit']:.8f}")
        print(f"運行時間: {stats['running_time_hours']:.2f} 小時")
        if self.current_cycle:
            print(f"當前循環: #{self.current_cycle['cycle_id']} ({self.current_cycle['status']})")
        print("=============================\n")