#!/usr/bin/env python3
import argparse
from pathlib import Path
from weibo_crawler import (
    CrawlerConfig,
    WorkerClientPool,
    run_search,
    run_detail_enrichment,
    run_comment_crawling,
    build_excel_workbook
)

def main():
    parser = argparse.ArgumentParser(description="微博关键词多模多协程分布式爬虫工具")
    parser.add_argument(
        "--config", 
        type=str, 
        default="config.json", 
        help="配置文件路径 (默认: config.json)"
    )
    parser.add_argument(
        "--skip-search", 
        action="store_true", 
        help="跳过第一步的关键词搜索 (仅处理缓存与详情评论)"
    )
    args = parser.parse_args()
    
    # 1. Load config
    project_dir = Path(__file__).resolve().parent
    config_path = project_dir / args.config
    
    config = CrawlerConfig(config_path)
    print("=" * 60)
    print(" 🚀 微博分布式爬虫启动中 ")
    print(f" 📂 工作根目录: {config.project_root}")
    print(f" 🔑 检索关键词: {config.keyword}")
    print(f" 📅 时间过滤范围: {config.start_date_str} 至 {config.end_date_str}")
    print(f" ⚙️  并发 Worker 数量: {config.workers_count}")
    print(f" 💬 评论条数上限/帖: {config.max_comments}")
    print(f" 📊 输出 Excel 路径: {config.output_xlsx}")
    print("=" * 60, flush=True)

    # 2. Init Worker Session Pool
    pool = WorkerClientPool(config.worker_urls, config.proxy_token, config.cookies_path)

    # 3. Step 1: Run keyword search
    if not args.skip_search:
        run_search(config, pool)
    else:
        print("Skipped search step (--skip-search is enabled).", flush=True)

    # 4. Step 2: Detail enrichment (full text + validation)
    detail_cache = run_detail_enrichment(config, pool)

    # 5. Extract all valid in-range posts
    valid_posts = []
    for bid, item in detail_cache.items():
        mblog = item.get("mblog")
        if item.get("status") in ("ok", "cached") and isinstance(mblog, dict):
            # Safe parse and check
            from weibo_crawler import parse_created_at
            created = mblog.get("created_at", "")
            dt = parse_created_at(created)
            if dt and config.start_date <= dt.date() <= config.end_date:
                valid_posts.append(mblog)

    print(f"Total valid posts ready for comments crawling: {len(valid_posts)}", flush=True)

    # 6. Step 3: Comments crawling
    comments_cache = run_comment_crawling(config, pool, valid_posts)

    # 7. Step 4: Build Excel sheet
    build_excel_workbook(config, valid_posts, comments_cache)
    
    print("=" * 60)
    print(" 🎉 微博爬虫流程全部运行完毕！")
    print(f" 📂 最终数据集: {config.output_xlsx}")
    print("=" * 60)

if __name__ == "__main__":
    main()
