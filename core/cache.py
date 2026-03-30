import hashlib
import os
import pickle
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Any

class Cache:
    def __init__(self, cache_dir: str = ".cache", max_age: int = 86400):
        """初始化缓存
        
        Args:
            cache_dir: 缓存目录
            max_age: 缓存最大年龄（秒），默认24小时
        """
        self.cache_dir = Path(cache_dir)
        self.max_age = max_age
        # 创建缓存目录
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_cache_path(self, key: str) -> Path:
        """获取缓存文件路径
        
        Args:
            key: 缓存键
        
        Returns:
            缓存文件路径
        """
        # 使用MD5哈希作为文件名，避免特殊字符
        hash_key = hashlib.md5(key.encode()).hexdigest()
        return self.cache_dir / f"{hash_key}.cache"
    
    def get(self, key: str) -> Optional[Any]:
        """获取缓存
        
        Args:
            key: 缓存键
        
        Returns:
            缓存值，如果不存在或已过期则返回None
        """
        cache_path = self._get_cache_path(key)
        if not cache_path.exists():
            return None
        
        try:
            with open(cache_path, 'rb') as f:
                data = pickle.load(f)
            
            # 检查缓存是否过期
            timestamp = data.get('timestamp', 0)
            if datetime.now().timestamp() - timestamp > self.max_age:
                # 删除过期缓存
                cache_path.unlink()
                return None
            
            return data.get('value')
        except Exception:
            # 如果读取失败，删除缓存文件
            if cache_path.exists():
                cache_path.unlink()
            return None
    
    def set(self, key: str, value: Any) -> bool:
        """设置缓存
        
        Args:
            key: 缓存键
            value: 缓存值
        
        Returns:
            是否设置成功
        """
        try:
            cache_path = self._get_cache_path(key)
            data = {
                'value': value,
                'timestamp': datetime.now().timestamp()
            }
            with open(cache_path, 'wb') as f:
                pickle.dump(data, f)
            return True
        except Exception:
            return False
    
    def clear(self) -> None:
        """清空所有缓存"""
        for cache_file in self.cache_dir.glob("*.cache"):
            try:
                cache_file.unlink()
            except Exception:
                pass
    
    def clear_expired(self) -> int:
        """清理过期缓存
        
        Returns:
            清理的缓存数量
        """
        count = 0
        for cache_file in self.cache_dir.glob("*.cache"):
            try:
                with open(cache_file, 'rb') as f:
                    data = pickle.load(f)
                timestamp = data.get('timestamp', 0)
                if datetime.now().timestamp() - timestamp > self.max_age:
                    cache_file.unlink()
                    count += 1
            except Exception:
                # 如果读取失败，删除缓存文件
                try:
                    cache_file.unlink()
                    count += 1
                except Exception:
                    pass
        return count

# 创建全局缓存实例
cache = Cache()
