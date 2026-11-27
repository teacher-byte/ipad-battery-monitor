"""從 Jamf Pro 抓全校 iPad 電量，算出需要追蹤的平板，輸出成監控後台用的 data.json。

只用 Python 標準函式庫（GitHub Actions 不必安裝套件）。
帳密只從環境變數讀取：
  JAMF_URL               例：https://xxxx.jamfcloud.com
  JAMF_CLIENT_ID / JAMF_CLIENT_SECRET   （建議：Jamf「API 角色與用戶端」建立的唯讀用戶端）
  或 JAMF_USER / JAMF_PASSWORD           （沒有用戶端時退而使用帳號密碼）
  GCHAT_WEBHOOK          （選填）Google Chat 聊天室的 Webhook 網址，有新問題時推播
  JAMF_SEND_UPDATE_INVENTORY=1           （選填）請所有平板立刻回報最新電量
  JAMF_UPDATE_INTERVAL_MIN=60            （選填）上面的指令多久送一次，預設 60 分鐘

學校名稱、分車規則、判斷門檻都在專案根目錄的 config.json，其他學校只要改那個檔。

輸出的 data.json 只放「裝置名稱、電量、回報時間、機型」，不放序號、IP、UDID 等資訊。
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

UTC = dt.timezone.utc
HISTORY_MAX = 80
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_config(path=None):
    """讀 config.json（學校名稱、分車、門檻），並設定下面會用到的全域值。"""
    global CFG, TPE, LOW, CRITICAL, NIGHT_FULL, STALE_HOURS, HISTORY_DAYS, NIGHT_START, NIGHT_END, CARTS, OTHER
    CFG = json.load(open(path or os.path.join(ROOT, "config.json"), encoding="utf-8"))
    th = CFG.get("thresholds", {})
    LOW = th.get("low", 50)                  # 低於這個百分比 → 需要追蹤
    CRITICAL = th.get("critical", 20)        # 低於這個百分比 → 危險
    NIGHT_FULL = th.get("nightFull", 80)     # 半夜還在充電車裡，電量應該要超過這個值
    STALE_HOURS = th.get("staleHours", 72)   # 超過這麼久沒回報 → 失聯
    HISTORY_DAYS = CFG.get("historyDays", 14)
    TPE = dt.timezone(dt.timedelta(hours=CFG.get("utcOffsetHours", 8)))  # 學校所在時區
    hm = lambda s: tuple(int(x) for x in s.split(":"))
    NIGHT_START = hm(CFG.get("night", {}).get("start", "00:00"))
    NIGHT_END = hm(CFG.get("night", {}).get("end", "07:30"))
    # 依 Jamf 使用者名稱（或裝置名稱）裡的代號分車
    CARTS = [(c["prefix"].upper(), c["label"], c.get("kind", "student")) for c in CFG.get("carts", [])]
    OTHER = CFG.get("otherLabel", "其他")
    return CFG


def log(*a):
    print(*a, file=sys.stderr, flush=True)


class Jamf:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.token = None
        self.kind = None

    def _req(self, method, path, headers=None, data=None, timeout=60, raw=False):
        r = urllib.request.Request(self.base + path, method=method, headers=headers or {}, data=data)
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            body = resp.read()
            if raw:
                return body
            return json.loads(body) if body else None

    def login(self, use_client=True):
        cid, secret = os.environ.get("JAMF_CLIENT_ID"), os.environ.get("JAMF_CLIENT_SECRET")
        if use_client and cid and secret:
            data = urllib.parse.urlencode({"client_id": cid, "client_secret": secret,
                                           "grant_type": "client_credentials"}).encode()
            res = self._req("POST", "/api/oauth/token",
                            {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}, data)
            self.token, self.kind = res["access_token"], "oauth"
            log("以 API 用戶端登入 Jamf")
        else:
            user, pw = os.environ["JAMF_USER"], os.environ["JAMF_PASSWORD"]
            basic = base64.b64encode(f"{user}:{pw}".encode()).decode()
            res = self._req("POST", "/api/v1/auth/token", {"Authorization": "Basic " + basic, "Accept": "application/json"})
            self.token, self.kind = res["token"], "basic"
            log("以帳號密碼登入 Jamf")

    def login_and_fetch(self):
        """先用 API 用戶端；登入或讀取失敗、而且還有帳號密碼時，自動改用帳號密碼（切換期間不中斷）。"""
        try:
            self.login()
            return self.mobile_devices()
        except urllib.error.HTTPError as e:
            tried_client = os.environ.get("JAMF_CLIENT_ID") and os.environ.get("JAMF_CLIENT_SECRET")
            if not tried_client or self.kind == "basic" or not (os.environ.get("JAMF_USER") and os.environ.get("JAMF_PASSWORD")):
                raise
            log("API 用戶端無法讀取平板資料：HTTP", e.code, "，改用帳號密碼")
            self.token = None
            self.login(use_client=False)
            return self.mobile_devices()

    def get(self, path):
        return self._req("GET", path, {"Authorization": "Bearer " + self.token, "Accept": "application/json"})

    def post(self, path, raw=False):
        return self._req("POST", path, {"Authorization": "Bearer " + self.token, "Accept": "application/json"}, b"", raw=raw)

    def logout(self):
        try:
            if self.token and self.kind == "basic":  # OAuth 權杖會自己過期，不必登出
                self.post("/api/v1/auth/invalidate-token")
        except Exception:
            pass

    def mobile_devices(self):
        out, page = [], 0
        while True:
            d = self.get(f"/api/v2/mobile-devices/detail?section=GENERAL&section=HARDWARE"
                         f"&section=USER_AND_LOCATION&page={page}&page-size=200&sort=displayName%3Aasc")
            out += d["results"]
            if len(out) >= d["totalCount"] or not d["results"]:
                return out
            page += 1


def parse_time(s):
    if not s:
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", s)
    return dt.datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC) if m else None


def iso(t):
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if t else None


def classify(username: str, name: str):
    key = (username or name or "").upper()
    for prefix, label, kind in CARTS:
        if re.search(rf"(^|[-_]){prefix}[-_]", key) or key.startswith(prefix + "-"):
            m = re.search(r"-(\d+)\s*$", key)
            return prefix, label, kind, (int(m.group(1)) if m else None)
    return "OTHER", OTHER, "other", None


def is_night(t: dt.datetime):
    hm = t.astimezone(TPE).timetuple()[3:5]
    if NIGHT_START <= NIGHT_END:
        return NIGHT_START <= hm < NIGHT_END
    return hm >= NIGHT_START or hm < NIGHT_END  # 例如 22:00～06:00 跨過午夜


def night_date(t: dt.datetime):
    """這筆回報屬於哪一晚：跨午夜的時段（例如 22:00～06:00）算到隔天。"""
    local = t.astimezone(TPE)
    if NIGHT_START > NIGHT_END and local.timetuple()[3:5] >= NIGHT_START:
        local += dt.timedelta(days=1)
    return local.strftime("%Y-%m-%d")


def build(devs, prev, now):
    prev_by_id = {str(d["id"]): d for d in prev.get("devices", [])}
    cutoff = now - dt.timedelta(days=HISTORY_DAYS)
    out = []
    for x in devs:
        g, h, ul = x.get("general") or {}, x.get("hardware") or {}, x.get("userAndLocation") or {}
        did = str(x.get("mobileDeviceId"))
        name = g.get("displayName") or ""
        user = ul.get("username") or ""
        cart, cart_label, kind, slot = classify(user, name)
        bat = h.get("batteryLevel")
        rep = parse_time(g.get("lastInventoryUpdateDate"))
        contact = parse_time(g.get("lastContactDate"))

        hist = [list(p) for p in prev_by_id.get(did, {}).get("history", [])]
        if rep and bat is not None and all(p[0] != iso(rep) for p in hist):
            hist.append([iso(rep), bat])
        # 依時間排好：Jamf 偶爾會把「回報時間」倒回比較舊的一筆，不排序的話最新一筆會算錯
        uniq = {p[0]: p for p in hist if parse_time(p[0]) and parse_time(p[0]) >= cutoff}  # 同一時間只留一筆
        hist = sorted(uniq.values(), key=lambda p: parse_time(p[0]))[-HISTORY_MAX:]

        flags = []
        night_of = None  # 「半夜沒充飽」是哪一晚（台灣日期），每晚各提醒一次
        age_h = (now - rep).total_seconds() / 3600 if rep else None
        if bat is not None:
            if bat < CRITICAL:
                flags.append("critical")
            elif bat < LOW:
                flags.append("low")
        if age_h is None or age_h > STALE_HOURS:
            flags.append("stale")
        if kind == "student":
            # 半夜（預設 00:00–07:30）回報時電量還不到 80% → 很可能整晚沒充到電
            recent_night = [p for p in hist if is_night(parse_time(p[0]))
                            and (now - parse_time(p[0])).total_seconds() < 20 * 3600]
            # 但之後若已回升到 80% 以上，就代表其實有在充，不必再追
            if recent_night and recent_night[-1][1] < NIGHT_FULL and hist[-1][1] < NIGHT_FULL:
                flags.append("night")
                night_of = night_date(parse_time(recent_night[-1][0]))
            # 跟「至少 2 小時前」的那次回報比：兩次都低於 50%，而且沒有回升
            # （平板每小時回報一次，只比相鄰兩次的話永遠湊不到 2 小時）
            if len(hist) >= 2:
                t2, b2 = parse_time(hist[-1][0]), hist[-1][1]
                older = [p for p in hist[:-1] if (t2 - parse_time(p[0])).total_seconds() >= 2 * 3600]
                if older:
                    b1 = older[-1][1]
                    if b1 < LOW and b2 < LOW and b2 <= b1 + 2:
                        flags.append("persist")
        trend = None
        if len(hist) >= 2 and rep and hist[-1][0] == iso(rep):
            trend = hist[-1][1] - hist[-2][1]

        out.append({
            "id": did, "name": name, "user": user, "cart": cart, "cartLabel": cart_label,
            "kind": kind, "slot": slot, "model": h.get("model") or "", "battery": bat,
            "reportedAt": iso(rep), "contactAt": iso(contact), "trend": trend,
            "flags": flags, "nightOf": night_of, "history": hist,
        })
    return out


def summarize(devices):
    s = {"total": len(devices)}
    for f in ("critical", "low", "night", "persist", "stale"):
        s[f] = sum(1 for d in devices if f in d["flags"])
    s["needCheck"] = sum(1 for d in devices if d["kind"] == "student" and "stale" not in d["flags"] and
                         any(f in d["flags"] for f in ("critical", "low", "night", "persist")))
    return s


ALERT_FLAGS = ("critical", "night", "persist")


def alert_tags(d):
    """這台現在要通知的標記；「半夜沒充飽」帶上是哪一晚，例如 night@2026-11-27。"""
    tags = {f for f in d["flags"] if f in ALERT_FLAGS and f != "night"}
    if "night" in d["flags"]:
        tags.add("night@" + (d.get("nightOf") or ""))
    return tags


def notify(devices, prev, now):
    """同一台平板出現「新的」問題標記才推播。

    alerted 記的是每台「已經通知過的標記」，例如 {"123": "critical,night@2026-11-27"}。
    平板每小時回報一次也不會重複通知；某個標記解除後又出現，才會再通知。
    「半夜沒充飽」每晚各算一次：前一晚通知過、隔天半夜還是沒充飽，會再提醒一次。
    """
    hook = os.environ.get("GCHAT_WEBHOOK")
    by_id = {d["id"]: d for d in devices}
    known = {}
    for k, v in prev.get("alerted", {}).items():
        d = by_id.get(k)
        if not d:
            continue
        cur = alert_tags(d)
        if re.match(r"\d{4}-", str(v)):
            # 舊格式（記回報時間）：當作現在的標記都通知過了，避免改版後一次重推；
            # 「連續低電量」是這版才修好的判斷，第一次出現仍要通知
            known[k] = cur - {"persist"}
        else:
            old = set(filter(None, str(v).split(",")))
            if "night" in old:  # 沒有日期的舊寫法：當作這一晚已經通知過
                old = (old - {"night"}) | {t for t in cur if t.startswith("night@")}
            known[k] = old & cur  # 已解除的標記拿掉，之後再出現會再通知
    fresh = []
    for d in devices:
        if (d["kind"] == "student" and d["reportedAt"] and "stale" not in d["flags"]
                and alert_tags(d) - known.get(d["id"], set())):
            fresh.append(d)
    if hook and fresh:
        reason = {"critical": "電量危險", "night": "半夜沒充飽", "persist": "連續低電量"}
        lines = [f"🔋 *平板電量警示*（{now.astimezone(TPE):%m/%d %H:%M}）新發現 {len(fresh)} 台需要檢查充電線："]
        for d in sorted(fresh, key=lambda d: (d["cart"], d["slot"] or 0))[:30]:
            tags = "、".join(reason[f] for f in d["flags"] if f in reason)
            lines.append(f"• {d['cartLabel']} {d['slot'] or ''} 號（{d['name']}）{d['battery']}%｜{tags}")
        site = os.environ.get("SITE_URL")
        if site:
            lines.append(f"👉 監控後台：{site}")
        try:
            req = urllib.request.Request(hook, method="POST", data=json.dumps({"text": chr(10).join(lines)}).encode(),
                                         headers={"Content-Type": "application/json; charset=UTF-8"})
            urllib.request.urlopen(req, timeout=20).read()
            for d in fresh:  # 推播成功才記「已通知」，失敗下次會再推
                known[d["id"]] = known.get(d["id"], set()) | alert_tags(d)
            log(f"已推播 {len(fresh)} 台")
        except Exception as e:  # 推播失敗不影響後台更新
            log("推播失敗：", type(e).__name__)
    # 只保留還有問題標記的平板，避免紀錄無限長大
    return {k: ",".join(sorted(v)) for k, v in known.items() if v}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prev", default="prev.json")
    ap.add_argument("--out", default="site/data.json")
    ap.add_argument("--config", default=None, help="預設是專案根目錄的 config.json")
    a = ap.parse_args()
    load_config(a.config)
    try:
        prev = json.load(open(a.prev, encoding="utf-8"))
    except Exception:
        prev = {}
    now = dt.datetime.now(UTC)
    jamf = Jamf(os.environ["JAMF_URL"])
    try:
        devs = jamf.login_and_fetch()
        last_cmd = parse_time(prev.get("inventoryCommandAt"))
        interval = float(os.environ.get("JAMF_UPDATE_INTERVAL_MIN") or 60)
        if os.environ.get("JAMF_SEND_UPDATE_INVENTORY") == "1":
            # 排程每 15 分鐘跑一次，但「請平板回報」只照設定的間隔送（預設每小時一次）；
            # 留 5 分鐘緩衝，避免 GitHub 排程延遲造成整整跳過一小時
            if last_cmd is None or (now - last_cmd).total_seconds() >= (interval - 5) * 60:
                ids = ",".join(str(d["mobileDeviceId"]) for d in devs if (d.get("general") or {}).get("managed"))
                try:
                    jamf.post(f"/JSSResource/mobiledevicecommands/command/UpdateInventory/id/{ids}", raw=True)
                    last_cmd = now
                    log(f"已請 {ids.count(',') + 1} 台平板回報最新電量")
                except urllib.error.HTTPError as e:
                    log("送出更新電量指令失敗：", e.code)
                except Exception as e:
                    log("送出更新電量指令失敗：", type(e).__name__)
            else:
                log(f"距上次請平板回報不到 {interval:.0f} 分鐘，這次略過")
    finally:
        jamf.logout()

    devices = build(devs, prev, now)
    data = {
        "generatedAt": iso(now),
        "school": CFG.get("school", {}),
        "thresholds": {"low": LOW, "critical": CRITICAL, "nightFull": NIGHT_FULL, "staleHours": STALE_HOURS,
                       "nightStart": "%02d:%02d" % NIGHT_START, "nightEnd": "%02d:%02d" % NIGHT_END},
        "carts": [label for _, label, _ in CARTS] + [OTHER],
        "summary": summarize(devices),
        "devices": devices,
        "alerted": notify(devices, prev, now),
        "inventoryCommandAt": iso(last_cmd),
    }
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    log("完成：", json.dumps(data["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
