# utils/logger.py

import logging
import sys
import os
from datetime import datetime

def init_logger(name="app", level=logging.INFO, enable_file_logging=True):
    """初始化日誌系統
    
    Args:
        name: 日誌器名稱
        level: 日誌級別
        enable_file_logging: 是否啟用文件日誌
        
    Returns:
        配置好的日誌器實例
    """
    # 獲取日誌器
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False
    
    # 清除現有處理器
    if logger.handlers:
        logger.handlers.clear()
    
    # 設置日誌格式
    console_formatter = logging.Formatter("[%(asctime)s] %(levelname)s - %(message)s", "%Y-%m-%d %H:%M:%S")
    
    # 創建控制台處理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    # 如果啟用文件日誌
    if enable_file_logging:
        # 創建日誌目錄
        os.makedirs("logs", exist_ok=True)
        
        # 創建文件處理器
        log_file = f"logs/{datetime.now().strftime('%Y%m%d_%H%M%S')}_{name}.log"
        file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    
    return logger
