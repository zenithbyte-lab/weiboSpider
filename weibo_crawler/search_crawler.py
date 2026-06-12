import json
import re
import time
import random
from pathlib import Path
from urllib.parse import quote
from datetime import datetime, date, timedelta
from .session_pool import WorkerClientPool

def clean_text(value: str) -> str:
    import html
    value = re.sub(r"<br\s*/?>", "\n", value or "", flags=re.I)
    value = re.sub(r"<[^>]+>", "", value)
    return html.unescape(value).replace("\u200b", "").strip()

def parse_created_at(value: str, today: date = None) -> datetime | None:
    today = today or date.today()
    value = (value or "").strip()
    if not value:
        return None
    now = datetime.now()
    if "刚刚" in value:
        return now
    minute = re.search(r"(\d+)\s*分钟前", value)
    if minute:
        return now - timedelta(minutes=int(minute.group(1)))
    hour = re.search(r"(\d+)\s*小时前", value)
    if hour:
        return now - timedelta(hours=int(hour.group(1)))
    if value.startswith("今天"):
        return datetime.combine(today, datetime.min.time())
    if value.startswith("昨天"):
        return datetime.combine(today - timedelta(days=1), datetime.min.time())
    for fmt in ("%a %b %d %H:%M:%S %z %Y", "%a %b %d %H:%M:%S %Y"):
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed.replace(tzinfo=None)
        except ValueError:
            pass
    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:\s+(\d{1,2}):(\d{1,2}))?", value)
    if match:
        year, month, day, hour_s, minute_s = match.groups()
        return datetime(int(year), int(month), int(day), int(hour_s or 0), int(minute_s or 0))
    if re.fullmatch(r"\d{1,2}-\d{1,2}(?:\s+\d{1,2}:\d{1,2})?", value):
        left, *time_part = value.split()
        month, day = map(int, left.split("-"))
        hour_i = minute_i = 0
        if time_part:
            hour_i, minute_i = map(int, time_part[0].split(":"))
        return datetime(today.year, month, day, hour_i, minute_i)
    return None

def collect_mblogs(cards: list, out: list = None) -> list:
    out = out if out is not None else []
    for card in cards or []:
        mblog = card.get("mblog")
        if isinstance(mblog, dict):
            out.append(mblog)
        group = card.get("card_group")
        if isinstance(group, list):
            collect_mblogs(group, out)
    return out

def fetch_search_page(client, keyword: str, page: int, search_type: int = 1) -> dict:
    url = f"https://m.weibo.cn/api/container/getIndex?containerid=100103type%3D{search_type}%26q%3D{quote(keyword)}&page={page}"
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Referer": f"https://m.weibo.cn/search?containerid=100103type%3D{search_type}%26q%3D{quote(keyword)}"
    }
    try:
        resp = client.request_through_worker(url, method="GET", headers=headers)
        if resp.status_code != 200:
            return {"ok": 0, "status": resp.status_code}
        return resp.json()
    except Exception as e:
        return {"ok": 0, "error": str(e)}

def run_search(config, pool: WorkerClientPool):
    print("Starting search crawler...", flush=True)
    
    # Load progress
    progress = {}
    if config.progress_path.exists():
        try:
            progress = json.loads(config.progress_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    seen_bids = set()
    if config.raw_path.exists():
        with config.raw_path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    item = json.loads(line)
                    if item.get("bid"):
                        seen_bids.add(item["bid"])
                except Exception:
                    pass

    # Modes: 1=Comprehensive, 61=Real-time
    search_types = [1, 61]
    
    for st in search_types:
        task_key = f"{config.keyword}_{st}"
        if progress.get(f"{task_key}_completed"):
            print(f"Task '{task_key}' already marked completed in progress.json, skipping.", flush=True)
            continue
            
        start_page = progress.get(f"{task_key}_last_page", 0) + 1
        print(f"Executing search: type={st} starting from page={start_page}...", flush=True)
        
        completed = True
        for page in range(start_page, config.max_pages + 1):
            client = pool.get_client()
            try:
                payload = fetch_search_page(client, config.keyword, page, search_type=st)
                
                text_content = str(payload.get("text") or "")
                is_blocked = (
                    payload.get("ok") != 1 and 
                    ("captcha" in text_content or "验证" in text_content or payload.get("status") in (401, 403, 418))
                )
                
                if payload.get("ok") != 1:
                    if is_blocked:
                        print(f"Blocked on task={task_key} page={page}. Bootstrapping client...", flush=True)
                        client.cookie = {}
                        client.bootstrap()
                        completed = False
                        progress[f"{task_key}_last_page"] = page - 1
                        break
                    else:
                        print(f"Search task={task_key} reached end at page={page}.", flush=True)
                        progress[f"{task_key}_last_page"] = page - 1
                        break
                
                cards = (payload.get("data") or {}).get("cards") or []
                mblogs = collect_mblogs(cards)
                print(f"[{task_key}] Page {page}: Cards count={len(cards)} | Mblogs count={len(mblogs)}", flush=True)
                
                if not mblogs:
                    progress[f"{task_key}_last_page"] = page
                    break
                    
                new_found = 0
                with config.raw_path.open("a", encoding="utf-8") as f:
                    for mblog in mblogs:
                        bid = str(mblog.get("bid") or mblog.get("mblogid") or mblog.get("id") or "")
                        if not bid or bid in seen_bids:
                            continue
                        seen_bids.add(bid)
                        new_found += 1
                        mblog["matched_keyword"] = config.keyword
                        f.write(json.dumps({"bid": bid, "mblog": mblog}, ensure_ascii=False) + "\n")
                
                print(f"  -> Added {new_found} new posts to search_mblogs.jsonl", flush=True)
                
                progress[f"{task_key}_last_page"] = page
                
                # Save progress
                with config.progress_path.open("w", encoding="utf-8") as pf:
                    json.dump(progress, pf, ensure_ascii=False, indent=2)
                pool.save_all_cookies()
                
                time.sleep(random.uniform(0.8, 1.5))
            finally:
                pool.release_client(client)
                
        if completed:
            progress[f"{task_key}_completed"] = True
            with config.progress_path.open("w", encoding="utf-8") as pf:
                json.dump(progress, pf, ensure_ascii=False, indent=2)
                
    print("Search crawling process completed successfully.", flush=True)
