import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from .session_pool import WorkerClientPool
from .search_crawler import parse_created_at

def run_detail_enrichment(config, pool: WorkerClientPool):
    print("Checking detail cache enrichment...", flush=True)
    
    # Load detail cache
    detail_cache = {}
    if config.detail_cache_path.exists():
        try:
            detail_cache = json.loads(config.detail_cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Read target range posts from search_mblogs.jsonl
    all_raw_posts = []
    seen_bids = set()
    if config.raw_path.exists():
        with config.raw_path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    item = json.loads(line)
                    mblog = item.get("mblog")
                    bid = item.get("bid")
                    if mblog and bid and bid not in seen_bids:
                        created = mblog.get("created_at", "")
                        dt = parse_created_at(created)
                        if dt and config.start_date <= dt.date() <= config.end_date:
                            seen_bids.add(bid)
                            all_raw_posts.append(mblog)
                except Exception:
                    pass

    print(f"Total in-range posts in search_mblogs.jsonl: {len(all_raw_posts)}", flush=True)

    # Collect missing details
    todo_details = []
    for p in all_raw_posts:
        bid = str(p.get("bid") or p.get("mblogid") or p.get("id") or "")
        cached = detail_cache.get(bid)
        if cached is None or cached.get("status") not in ("ok", "cached"):
            todo_details.append(p)

    if todo_details:
        print(f"Detail cache needs enrichment for {len(todo_details)} posts. Starting concurrent detail crawling...", flush=True)
        detail_lock = threading.Lock()
        detail_counter = 0

        def detail_worker_task(post):
            nonlocal detail_counter
            bid = str(post.get("bid") or post.get("mblogid") or post.get("id") or "")
            client = pool.get_client()
            try:
                res = client.get_detail(bid)
                status = res.get("status")
                final_mblog = res.get("mblog") or post
                with detail_lock:
                    detail_counter += 1
                    detail_cache[bid] = {"status": status, "mblog": final_mblog}
                    if detail_counter % 10 == 0:
                        # Save detail cache
                        with config.detail_cache_path.open("w", encoding="utf-8") as df:
                            json.dump(detail_cache, df, ensure_ascii=False, indent=2)
                        pool.save_all_cookies()
                    print(f"[Detail {detail_counter}/{len(todo_details)}] bid={bid} status={status}", flush=True)
            finally:
                pool.release_client(client)

        max_workers = min(len(config.worker_urls), len(todo_details))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(detail_worker_task, p): p for p in todo_details}
            for fut in as_completed(futures):
                try:
                    fut.result()
                except Exception as e:
                    print(f"Detail task error: {e}", flush=True)

        with config.detail_cache_path.open("w", encoding="utf-8") as df:
            json.dump(detail_cache, df, ensure_ascii=False, indent=2)
        pool.save_all_cookies()
        print("Detail enrichment completed successfully!", flush=True)
    else:
        print("Detail cache is already fully up-to-date.", flush=True)
        
    return detail_cache
