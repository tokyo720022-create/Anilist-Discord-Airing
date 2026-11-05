#!/usr/bin/env python3
"""Cached AniList airing radar with batched Discord alerts and a daily board."""
import json, logging, os, time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import requests

API = "https://graphql.anilist.co"
USERNAME = os.getenv("ANILIST_USERNAME", "Orewatokyo").strip()
TOKEN = os.getenv("ANILIST_TARGET_TOKEN", "").strip()
WEBHOOK = os.getenv("DISCORD_AIRING_WEBHOOK", "").strip()
ALERT_FILE, CACHE_FILE, BOARD_FILE = map(Path, ("db_anime_airing.json", "airing_cache.json", "daily_board.json"))
IST = ZoneInfo("Asia/Kolkata")
CACHE_TTL, TIMEOUT, RETRIES = 12 * 3600, 20, 4

LIST_QUERY = '''query ($name: String, $page: Int) { Page(page:$page,perPage:50) { pageInfo { hasNextPage } mediaList(userName:$name,type:ANIME) { mediaId } } }'''
AIRING_QUERY = '''query ($page:Int,$ids:[Int],$from:Int,$to:Int) { Page(page:$page,perPage:50) { pageInfo { hasNextPage } airingSchedules(mediaId_in:$ids,airingAt_greater:$from,airingAt_lesser:$to,sort:TIME) { id airingAt episode media { id title { romaji english } coverImage { extraLarge color } } } } }'''


def read_json(path, default):
    if not path.exists(): return default
    try:
        with path.open(encoding="utf-8") as stream: value = json.load(stream)
        return value if isinstance(value, type(default)) else default
    except (OSError, ValueError):
        logging.exception("Could not read %s", path)
        raise


def write_json(path, value):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


HTTP = requests.Session()
HTTP.headers.update({"Accept":"application/json", "Content-Type":"application/json"})
if TOKEN: HTTP.headers["Authorization"] = f"Bearer {TOKEN}"


def graphql(query, variables):
    for attempt in range(RETRIES):
        try: response = HTTP.post(API, json={"query":query,"variables":variables}, timeout=TIMEOUT)
        except requests.RequestException as exc:
            if attempt == RETRIES - 1: raise RuntimeError(f"AniList network error: {exc}") from exc
            time.sleep(min(2 ** attempt, 16)); continue
        if response.status_code == 200:
            body = response.json()
            if body.get("errors"): raise RuntimeError(f"AniList GraphQL error: {body['errors']}")
            return body.get("data") or {}
        if response.status_code == 429 or response.status_code >= 500:
            try: delay = max(float(response.headers.get("Retry-After", 0)), min(2 ** attempt, 20))
            except (TypeError, ValueError): delay = min(2 ** attempt, 20)
            time.sleep(delay); continue
        response.raise_for_status()
    raise RuntimeError("AniList request exhausted retries")


def get_media_ids(now):
    cache = read_json(CACHE_FILE, {})
    if cache.get("username") == USERNAME and now - int(cache.get("updated_at", 0)) < CACHE_TTL and cache.get("media_ids"):
        ids = sorted(set(map(int, cache["media_ids"])))
        logging.info("Using cached anime IDs: %d", len(ids)); return ids
    ids, page = [], 1
    while True:
        data = graphql(LIST_QUERY, {"name":USERNAME,"page":page}).get("Page") or {}
        ids.extend(int(x["mediaId"]) for x in data.get("mediaList",[]) if x.get("mediaId"))
        if not (data.get("pageInfo") or {}).get("hasNextPage"): break
        page += 1
    ids = sorted(set(ids))
    if not ids: raise RuntimeError(f"AniList returned no anime IDs for {USERNAME}")
    write_json(CACHE_FILE, {"username":USERNAME,"updated_at":now,"media_ids":ids})
    logging.info("Refreshed anime ID cache: %d", len(ids)); return ids


def get_airings(ids, start, end):
    found = {}
    for offset in range(0, len(ids), 500):
        page, batch = 1, ids[offset:offset+500]
        while True:
            data = graphql(AIRING_QUERY, {"page":page,"ids":batch,"from":start,"to":end}).get("Page") or {}
            for item in data.get("airingSchedules",[]):
                media = item.get("media") or {}; title = media.get("title") or {}; cover = media.get("coverImage") or {}
                mid = int(media.get("id") or 0)
                if not mid: continue
                name = title.get("english") or title.get("romaji") or f"Anime {mid}"
                airing = {"media_id":mid,"title":name,"romaji":title.get("romaji") or name,"episode":int(item["episode"]),"airing_at":int(item["airingAt"]),"cover":cover.get("extraLarge"),"color":cover.get("color")}
                found[(mid,airing["episode"])] = airing
            if not (data.get("pageInfo") or {}).get("hasNextPage"): break
            page += 1
    return sorted(found.values(), key=lambda x:x["airing_at"])


def webhook_request(method, url, payload):
    for attempt in range(RETRIES):
        try: response = HTTP.request(method, url, json=payload, timeout=TIMEOUT)
        except requests.RequestException as exc:
            if attempt == RETRIES-1: logging.error("Discord request failed: %s",exc); return None
            time.sleep(min(2**attempt,16)); continue
        if response.status_code in (200,201):
            try: return response.json()
            except ValueError: return {}
        if response.status_code == 204: return {}
        if response.status_code == 429 or response.status_code >= 500:
            try: delay=max(float(response.headers.get("Retry-After",0)),float(response.json().get("retry_after",0)))
            except (ValueError,TypeError): delay=min(2**attempt,16)
            time.sleep(max(delay,min(2**attempt,16))); continue
        logging.error("Discord HTTP %s: %s",response.status_code,response.text[:300]); return None
    return None


def alert_embed(a, kind):
    labels={"3h":"AIRING SOON","30m":"30-MINUTE WARNING","1h":"FINAL COUNTDOWN"}
    colors={"3h":0x5865F2,"30m":0xF0B232,"1h":0xED4245}; stamp=a["airing_at"]
    embed={"author":{"name":f"📡 TOKYO'S AIRING RADAR / {labels[kind]}"},"title":a["title"][:256],"url":f"https://anilist.co/anime/{a['media_id']}/","description":f"**EPISODE {a['episode']}**\n*{a['romaji']}*\n\n⏳ **Airs <t:{stamp}:R>**","color":colors[kind],"fields":[{"name":"🗓️ BROADCAST","value":f"<t:{stamp}:F>","inline":True},{"name":"🔔 REMINDER","value":labels[kind],"inline":True}],"footer":{"text":"ANILIST • AUTOMATIC AIRING TRACKER"}}
    if a.get("cover"): embed["thumbnail"]={"url":a["cover"]}
    return embed


def send_due_alerts(airings, state, now):
    pending=[]
    for a in airings:
        left=a["airing_at"]-now
        if left <= 0: continue
        key=f"{a['media_id']}_ep{a['episode']}"; old=state.get(key,[])
        if isinstance(old,str): old=[old]
        # Final one-hour notice supersedes the 30-minute notice if a run was delayed.
        kind = "1h" if left <= 3600 and "1h" not in old else ("30m" if left <= 1800 and "30m" not in old else ("3h" if left <= 10800 and left > 3600 and "3h" not in old else None))
        if kind: pending.append((key,kind,alert_embed(a,kind)))
    sent=0
    for i in range(0,len(pending),10):
        group=pending[i:i+10]
        result=webhook_request("POST",WEBHOOK+"?wait=true",{"embeds":[x[2] for x in group]})
        if result is None: continue
        for key,kind,_ in group:
            old=state.get(key,[]); old=[old] if isinstance(old,str) else old
            state[key]=sorted(set(old+[kind])); sent+=1
    return sent


def update_daily_board(airings, now):
    local=datetime.fromtimestamp(now,IST); start=local.replace(hour=0,minute=0,second=0,microsecond=0); end=(start+timedelta(days=1))
    todays=[a for a in airings if start.timestamp() <= a["airing_at"] < end.timestamp()]
    lines=[f"**<t:{a['airing_at']}:t>** • [{a['title'][:90]}](https://anilist.co/anime/{a['media_id']}/) — Ep. **{a['episode']}**" for a in todays[:35]]
    if len(todays)>35: lines.append(f"…and {len(todays)-35} more.")
    embed={"author":{"name":"📅 TOKYO'S DAILY AIRING BOARD"},"title":local.strftime("%A • %d %B %Y"),"description":("\n".join(lines) if lines else "No upcoming episodes are listed for today. Enjoy your anime-free hours! 🍵")[:4000],"color":0x2ECC71,"footer":{"text":f"{len(todays)} episode(s) • AniList • Times shown in India (IST)"}}
    if todays and todays[0].get("cover"): embed["thumbnail"]={"url":todays[0]["cover"]}
    state=read_json(BOARD_FILE,{})
    if state.get("date")==local.date().isoformat() and state.get("message_id"):
        result=webhook_request("PATCH",WEBHOOK.rstrip("/")+f"/messages/{state['message_id']}",{"embeds":[embed]})
        if result is not None: return
    result=webhook_request("POST",WEBHOOK+"?wait=true",{"embeds":[embed]})
    if result and result.get("id"): write_json(BOARD_FILE,{"date":local.date().isoformat(),"message_id":str(result["id"])})


def prune_history(state, ids, airings):
    active=set(ids); newest={}
    for a in airings: newest[a["media_id"]]=max(newest.get(a["media_id"],0),a["episode"])
    removed=0
    for key in list(state):
        try: mid,ep=key.split("_ep",1); mid,ep=int(mid),int(ep)
        except (ValueError,AttributeError): continue
        if mid not in active or (mid in newest and ep < newest[mid]-3): del state[key]; removed+=1
    if removed: logging.info("Removed %d stale alert-history entries",removed)


def main():
    logging.basicConfig(level=logging.INFO,format="%(asctime)s UTC | %(levelname)s | %(message)s")
    if not USERNAME or not WEBHOOK: raise RuntimeError("Missing AniList username or DISCORD_AIRING_WEBHOOK secret")
    now=int(time.time()); ids=get_media_ids(now); airings=get_airings(ids,now-60,now+24*3600)
    history=read_json(ALERT_FILE,{})
    prune_history(history,ids,airings)
    sent=send_due_alerts(airings,history,now)
    write_json(ALERT_FILE,history)
    update_daily_board(airings,now)
    logging.info("HEALTH OK | tracked=%d | next-24h=%d | alerts-sent=%d",len(ids),len(airings),sent)

if __name__ == "__main__": main()
