import json
import os
from pathlib import Path
from datetime import datetime

class CrawlerConfig:
    def __init__(self, config_path: Path):
        self.project_root = config_path.parent
        
        # Load defaults
        self.keyword = "尼帕病毒"
        self.start_date_str = "2026-01-15"
        self.end_date_str = "2026-03-15"
        self.max_pages = 90
        self.max_comments = 10
        self.workers_count = 50
        self.proxy_token = "6GwzTEAATtoFmFAJdSxXVqktg4X2OixuAxLghkGkO1Q"
        self.output_dir_name = "outputs"
        
        # Read file if exists
        if config_path.exists():
            try:
                data = json.loads(config_path.read_text(encoding="utf-8"))
                self.keyword = data.get("keyword", self.keyword)
                self.start_date_str = data.get("start_date", self.start_date_str)
                self.end_date_str = data.get("end_date", self.end_date_str)
                self.max_pages = int(data.get("max_pages", self.max_pages))
                self.max_comments = int(data.get("max_comments", self.max_comments))
                self.workers_count = int(data.get("workers_count", self.workers_count))
                self.proxy_token = data.get("proxy_token", self.proxy_token)
                self.output_dir_name = data.get("output_dir", self.output_dir_name)
            except Exception as e:
                print(f"Warning: Failed to load config.json: {e}, using default settings.", flush=True)
                
        # Parse dates
        self.start_date = datetime.strptime(self.start_date_str, "%Y-%m-%d").date()
        self.end_date = datetime.strptime(self.end_date_str, "%Y-%m-%d").date()
        
        # Setup paths
        self.output_dir = self.project_root / self.output_dir_name
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.raw_path = self.output_dir / "search_mblogs.jsonl"
        self.detail_cache_path = self.output_dir / "detail_cache.json"
        self.comments_cache_path = self.output_dir / "comments_cache.json"
        self.progress_path = self.output_dir / "progress.json"
        self.cookies_path = self.output_dir / "weibo_mobile_cookies.json"
        self.output_xlsx = self.output_dir / f"微博_{self.keyword}_数据集_{self.start_date_str}_{self.end_date_str}.xlsx"
        
        # Worker URLs
        self.worker_urls = [
            f"https://dart-proxy-r3-{i:03d}.edge-lab-9731.workers.dev" 
            for i in range(1, self.workers_count + 1)
        ]
