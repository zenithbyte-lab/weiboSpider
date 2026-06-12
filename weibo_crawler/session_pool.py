import json
import re
import time
import random
import queue
import requests
from urllib.parse import quote
from pathlib import Path

COOKIE_ROTATE_INTERVAL = 8

MOBILE_USER_AGENTS = [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 15_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.7 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 13; SM-S901B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 11; SM-A515F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 10; Redmi Note 9 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Mobile Safari/537.36"
]

def get_randomized_headers(referer: str = "https://m.weibo.cn/") -> dict:
    ua = random.choice(MOBILE_USER_AGENTS)
    rand_ip = f"{random.randint(1, 254)}.{random.randint(1, 254)}.{random.randint(1, 254)}.{random.randint(1, 254)}"
    return {
        "User-Agent": ua,
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": random.choice(["zh-CN,zh;q=0.9,en;q=0.8", "zh-CN,zh;q=0.9", "zh-Hans;q=0.9,en-US;q=0.8"]),
        "Referer": referer,
        "X-Forwarded-For": rand_ip,
        "Client-IP": rand_ip,
        "X-Real-IP": rand_ip,
        "X-Client-IP": rand_ip
    }

class WorkerClient:
    def __init__(self, worker_url: str, token: str, cached_cookies: dict = None):
        self.worker_url = worker_url
        self.token = token
        self.cookie = cached_cookies or {}
        self.request_count = 0

    def request_through_worker(self, target_url: str, method: str = "GET", headers: dict | None = None, body: str | None = None, timeout: int = 30) -> requests.Response:
        req_headers = get_randomized_headers(target_url)
        if headers:
            req_headers.update(headers)
        if self.cookie:
            cookie_parts = [f"{k}={v}" for k, v in self.cookie.items()]
            req_headers["Cookie"] = "; ".join(cookie_parts)
        payload = {
            "url": target_url,
            "method": method,
            "headers": req_headers
        }
        if body is not None:
            payload["body"] = body
        worker_headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        resp = requests.post(self.worker_url, json=payload, headers=worker_headers, timeout=timeout)
        return resp

    def bootstrap(self, max_retries: int = 3) -> bool:
        search_url = "https://m.weibo.cn/search?containerid=100103type%3D1%26q%3D%E5%B0%BC%E5%B8%95%E7%97%85%E6%AF%92"
        for attempt in range(1, max_retries + 1):
            try:
                print(f"[{self.worker_url}] Bootstrapping cookies (attempt {attempt}/{max_retries})...", flush=True)
                resp = self.request_through_worker(search_url, method="GET")
                if resp.status_code != 200:
                    continue
                req_id_match = re.search(r'var request_id = "([^"]+)"', resp.text)
                return_url_match = re.search(r'var return_url = "([^"]+)"', resp.text)
                if not req_id_match or not return_url_match:
                    continue
                req_id = req_id_match.group(1)
                return_url = return_url_match.group(1)
                post_body = f"cb=visitor_gray_callback&ver=20250916&request_id={req_id}&tid=&from=weibo&webdriver=undefined&rid={int(time.time()*1000)}&return_url={quote(return_url)}"
                headers2 = {
                    "Origin": "https://visitor.passport.weibo.cn",
                    "Referer": "https://visitor.passport.weibo.cn/visitor/visitor",
                    "Content-Type": "application/x-www-form-urlencoded"
                }
                resp2 = self.request_through_worker("https://visitor.passport.weibo.cn/visitor/genvisitor2", method="POST", headers=headers2, body=post_body)
                if resp2.status_code != 200:
                    continue
                match = re.search(r'visitor_gray_callback\((.*?)\);', resp2.text)
                if not match:
                    continue
                res_data = json.loads(match.group(1))
                if res_data.get("retcode") != 20000000:
                    continue
                self.cookie = {
                    "SUB": res_data["data"]["sub"],
                    "SUBP": res_data["data"]["subp"],
                    "WEIBOCN_FROM": "1110003030"
                }
                self.request_count = 0
                print(f"[{self.worker_url}] Bootstrap success!", flush=True)
                return True
            except Exception as e:
                print(f"[{self.worker_url}] Bootstrap error: {e}", flush=True)
                time.sleep(1)
        return False

    def get_comments(self, mid_id: str, max_count: int = 10, timeout: int = 30) -> list:
        result = []
        max_id = 0
        max_id_type = 0
        is_end = False

        while not is_end and len(result) < max_count:
            self.request_count += 1
            if self.request_count > COOKIE_ROTATE_INTERVAL:
                print(f"[{self.worker_url}] Request count {self.request_count} > {COOKIE_ROTATE_INTERVAL}, rotating cookies...", flush=True)
                self.cookie = {}
                self.request_count = 0

            if not self.cookie:
                if not self.bootstrap():
                    break

            url = f"https://m.weibo.cn/comments/hotflow?id={mid_id}&mid={mid_id}&max_id_type={max_id_type}"
            if max_id > 0:
                url += f"&max_id={max_id}"

            headers = {
                "Accept": "application/json, text/plain, */*",
                "Referer": f"https://m.weibo.cn/detail/{mid_id}"
            }

            try:
                resp = self.request_through_worker(url, method="GET", headers=headers, timeout=timeout)
                is_captcha = "captcha/show" in resp.text or "微博验证" in resp.text or "Sina Visitor System" in resp.text or resp.status_code in (401, 403, 418)
                if is_captcha:
                    print(f"[{self.worker_url}] Blocked (status_code={resp.status_code}). Re-bootstrapping...", flush=True)
                    self.cookie = {}
                    self.request_count = 0
                    if not self.bootstrap():
                        break
                    resp = self.request_through_worker(url, method="GET", headers=headers, timeout=timeout)

                if resp.status_code != 200:
                    print(f"[{self.worker_url}] Failed to get comments status={resp.status_code}", flush=True)
                    break

                res_json = resp.json()
                if res_json.get("ok") != 1:
                    break

                data = res_json.get("data", {})
                comment_list = data.get("data", [])
                if not comment_list:
                    break

                result.extend(comment_list)
                
                max_id = data.get("max_id", 0)
                max_id_type = data.get("max_id_type", 0)
                is_end = max_id == 0

                if not is_end and len(result) < max_count:
                    time.sleep(random.uniform(0.5, 1.0))

            except Exception as e:
                print(f"[{self.worker_url}] Get comments exception: {e}", flush=True)
                break

        return result[:max_count]

    def get_detail(self, bid: str, timeout: int = 30) -> dict:
        self.request_count += 1
        if self.request_count > COOKIE_ROTATE_INTERVAL:
            print(f"[{self.worker_url}] Request count {self.request_count} > {COOKIE_ROTATE_INTERVAL}, rotating cookies...", flush=True)
            self.cookie = {}
            self.request_count = 0

        if not self.cookie:
            if not self.bootstrap():
                return {"status": "bootstrap_failed", "mblog": None}

        url = f"https://m.weibo.cn/detail/{bid}"
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/json,text/plain,*/*",
            "Referer": "https://m.weibo.cn/"
        }
        try:
            resp = self.request_through_worker(url, method="GET", headers=headers, timeout=timeout)
            is_captcha = "captcha/show" in resp.text or "微博验证" in resp.text or "Sina Visitor System" in resp.text or resp.status_code in (401, 403, 418)
            if is_captcha:
                print(f"[{self.worker_url}] Blocked (status_code={resp.status_code}). Re-bootstrapping...", flush=True)
                self.cookie = {}
                self.request_count = 0
                if not self.bootstrap():
                    return {"status": "captcha_bootstrap_failed", "mblog": None}
                resp = self.request_through_worker(url, method="GET", headers=headers, timeout=timeout)

            if resp.status_code != 200:
                return {"status": f"http_{resp.status_code}", "mblog": None}

            match = re.search(r"var \$render_data = (\[.*?\])\[0\]", resp.text, re.S)
            if not match:
                return {"status": "render_missing", "mblog": None}
            
            try:
                render = json.loads(match.group(1))
                status = (render[0] or {}).get("status") if render else None
                if isinstance(status, dict):
                    return {"status": "ok", "mblog": status}
                else:
                    return {"status": "empty_status", "mblog": None}
            except Exception:
                return {"status": "json_error", "mblog": None}
        except Exception as e:
            return {"status": f"exception_{e}", "mblog": None}

class WorkerClientPool:
    def __init__(self, urls: list, token: str, cookies_path: Path):
        self.clients_queue = queue.Queue()
        self.cookies_path = cookies_path
        cached_cookies = {}
        if self.cookies_path.exists():
            try:
                cached_cookies = json.loads(self.cookies_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        for url in urls:
            client = WorkerClient(url, token, cached_cookies.get(url))
            self.clients_queue.put(client)

    def get_client(self) -> WorkerClient:
        return self.clients_queue.get()

    def release_client(self, client: WorkerClient):
        self.clients_queue.put(client)

    def save_all_cookies(self):
        cookies_dict = {}
        temp_list = []
        while not self.clients_queue.empty():
            client = self.clients_queue.get()
            if client.cookie:
                cookies_dict[client.worker_url] = client.cookie
            temp_list.append(client)
        for client in temp_list:
            self.clients_queue.put(client)
        try:
            self.cookies_path.parent.mkdir(parents=True, exist_ok=True)
            self.cookies_path.write_text(json.dumps(cookies_dict, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
