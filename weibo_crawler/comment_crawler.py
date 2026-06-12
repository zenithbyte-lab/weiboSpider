import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from .session_pool import WorkerClientPool
from .search_crawler import clean_text

def parse_created_at_comments(value: str) -> str:
    from datetime import datetime
    for fmt in ("%a %b %d %H:%M:%S %z %Y", "%a %b %d %H:%M:%S %Y"):
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    return value

def run_comment_crawling(config, pool: WorkerClientPool, valid_posts: list):
    print("Checking comments cache...", flush=True)
    
    # Load comments cache
    comments_cache = {}
    if config.comments_cache_path.exists():
        try:
            comments_cache = json.loads(config.comments_cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Find posts needing comments crawling
    todo_comments_posts = []
    for p in valid_posts:
        bid = str(p.get("bid") or p.get("mblogid") or p.get("id") or "")
        c_count = int(p.get("comments_count") or 0)
        cached = comments_cache.get(bid)
        needed_comments = min(config.max_comments, c_count)
        if cached is None or (len(cached) < needed_comments):
            todo_comments_posts.append(p)
            if cached is not None:
                comments_cache.pop(bid, None)

    print(f"Posts remaining to crawl comments: {len(todo_comments_posts)}", flush=True)

    # Concurrently crawl comments
    if todo_comments_posts:
        comments_lock = threading.Lock()
        comments_counter = 0

        def comment_worker_task(post):
            nonlocal comments_counter
            mid = str(post.get("id") or "")
            bid = str(post.get("bid") or post.get("mblogid") or mid)
            if not mid:
                return bid, []

            client = pool.get_client()
            try:
                raw_comments = client.get_comments(mid, max_count=config.max_comments)
                parsed_comments = []
                for c in raw_comments[:config.max_comments]:
                    user = c.get("user") or {}
                    parsed_comments.append({
                        "id": str(c.get("id") or ""),
                        "text": clean_text(str(c.get("text") or "")),
                        "created_at": parse_created_at_comments(str(c.get("created_at") or "")),
                        "like_count": int(c.get("like_count") or 0),
                        "user_nickname": user.get("screen_name") or "",
                        "user_id": str(user.get("id") or ""),
                        "source": clean_text(str(c.get("source") or ""))  # IP发布属地
                    })
                
                with comments_lock:
                    comments_counter += 1
                    comments_cache[bid] = parsed_comments
                    if comments_counter % 10 == 0:
                        with config.comments_cache_path.open("w", encoding="utf-8") as cf:
                            json.dump(comments_cache, cf, ensure_ascii=False, indent=2)
                        pool.save_all_cookies()
                    print(f"[Comment {comments_counter}/{len(todo_comments_posts)}] Success fetch {len(parsed_comments)} comments for bid={bid}", flush=True)
                return bid, parsed_comments
            finally:
                pool.release_client(client)

        max_workers = min(len(config.worker_urls), len(todo_comments_posts))
        print(f"Starting comments crawl with {max_workers} worker threads...", flush=True)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(comment_worker_task, p): p for p in todo_comments_posts}
            for fut in as_completed(futures):
                try:
                    fut.result()
                except Exception as e:
                    print(f"Comment task error: {e}", flush=True)
            
        with config.comments_cache_path.open("w", encoding="utf-8") as cf:
            json.dump(comments_cache, cf, ensure_ascii=False, indent=2)
        pool.save_all_cookies()
        print("Comments crawling finished!", flush=True)
    else:
        print("All comments are already cached.", flush=True)

    return comments_cache
