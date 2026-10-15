
from __future__ import annotations
import json
from datetime import datetime
from decimal import Decimal
from urllib.parse import urljoin
import requests
import threading
import time
from sqlalchemy import delete, select
from db import SessionLocal
from models import EsportsProvider, EsportsGame, EsportsLeaderboardEntry, EsportsTournament, EsportsMatch, EsportsSyncLog, EsportsConfig

DEFAULT_GAMES = [
    ("league_of_legends", "League of Legends"),
    ("valorant", "VALORANT"),
    ("counter_strike_2", "Counter-Strike 2"),
    ("dota_2", "Dota 2"),
]
AUTO_SYNC_INTERVAL_SECONDS = 15 * 60
_auto_thread = None
_auto_lock = threading.Lock()


def _ensure_seed():
    with SessionLocal.begin() as s:
        def provider_by_type(ptype):
            return s.scalar(select(EsportsProvider).where(EsportsProvider.provider_type==ptype).limit(1))
        valorant=provider_by_type("HENRIKDEV_VALORANT")
        if valorant is None:
            valorant=EsportsProvider(name="HenrikDev VALORANT (Public)",provider_type="HENRIKDEV_VALORANT",base_url="https://api.henrikdev.xyz",api_key="",enabled=True,leaderboard_path_template="/valorant/v3/leaderboard/eu/pc",tournament_path_template="/valorant/v1/esports/schedule")
            s.add(valorant); s.flush()
        riot=provider_by_type("RIOT_LOL")
        if riot is None:
            riot=EsportsProvider(name="Riot Games League of Legends",provider_type="RIOT_LOL",base_url="https://europe.api.riotgames.com",api_key="",enabled=True,leaderboard_path_template="/lol/league/v4/challengerleagues/by-queue/RANKED_SOLO_5x5",tournament_path_template="/lol/tournament-v5/codes")
            s.add(riot); s.flush()
        panda=provider_by_type("PANDASCORE")
        if panda is None:
            panda=EsportsProvider(name="PandaScore Esports (13+ titles)",provider_type="PANDASCORE",base_url="https://api.pandascore.co",api_key="",enabled=True,leaderboard_path_template="/games/{code}/matches",tournament_path_template="/{code}/matches/upcoming")
            s.add(panda); s.flush()
        for code,name in DEFAULT_GAMES:
            row=s.scalar(select(EsportsGame).where(EsportsGame.code==code))
            provider_id=valorant.id if code=="valorant" else riot.id if code=="league_of_legends" else panda.id
            path="/valorant/v3/leaderboard/eu/pc" if code=="valorant" else "/lol/league/v4/challengerleagues/by-queue/RANKED_SOLO_5x5" if code=="league_of_legends" else ""
            if row is None:
                s.add(EsportsGame(code=code,name=name,provider_id=provider_id,tournament_enabled=False,leaderboard_visible=True,enabled=True,leaderboard_path=path))
            else:
                if not row.provider_id or row.provider_id not in {valorant.id,riot.id,panda.id}: row.provider_id=provider_id
                if code in {"valorant","league_of_legends"} and not row.leaderboard_path: row.leaderboard_path=path
        cfg=s.scalar(select(EsportsConfig).where(EsportsConfig.id==1))
        if cfg is None: s.add(EsportsConfig(id=1,default_provider_id=valorant.id,enabled=True))
    _start_auto_sync()

def _start_auto_sync():
    global _auto_thread
    with _auto_lock:
        if _auto_thread and _auto_thread.is_alive(): return
        _auto_thread=threading.Thread(target=_auto_sync_loop,name="pos-esports-auto-sync",daemon=True)
        _auto_thread.start()

def _auto_sync_loop():
    # Automatic refresh: real provider calls only; no generated/fake ranking data.
    while True:
        try:
            with SessionLocal() as s:
                cfg=s.get(EsportsConfig,1)
                games=s.scalars(select(EsportsGame).where(EsportsGame.enabled.is_(True))).all()
                now=datetime.now()
                due=[]
                for g in games:
                    provider=s.get(EsportsProvider,g.provider_id) if g.provider_id else None
                    if not provider or not provider.enabled or not provider.base_url: continue
                    if provider.provider_type.upper() in {"RIOT_LOL","PANDASCORE"} and not provider.api_key: continue
                    if not g.last_sync_at or (now-g.last_sync_at).total_seconds() >= AUTO_SYNC_INTERVAL_SECONDS: due.append(g.id)
                enabled=bool(cfg.enabled) if cfg else True
            if enabled:
                for gid in due:
                    try: sync_game(gid)
                    except Exception: pass
        except Exception: pass
        time.sleep(60)

def _game_row(g):
    return {"id":g.id,"code":g.code,"name":g.name,"provider_id":g.provider_id,"tournament_enabled":bool(g.tournament_enabled),"leaderboard_visible":bool(g.leaderboard_visible),"enabled":bool(g.enabled),"last_sync_at":g.last_sync_at.isoformat() if g.last_sync_at else None,"last_sync_status":g.last_sync_status,"last_sync_error":g.last_sync_error}

def snapshot():
    _ensure_seed()
    _start_auto_sync()
    with SessionLocal() as s:
        providers=s.scalars(select(EsportsProvider).order_by(EsportsProvider.name)).all()
        games=s.scalars(select(EsportsGame).order_by(EsportsGame.name)).all()
        entries=s.scalars(select(EsportsLeaderboardEntry).order_by(EsportsLeaderboardEntry.game_id,EsportsLeaderboardEntry.rank).limit(250)).all()
        tournaments=s.scalars(select(EsportsTournament).order_by(EsportsTournament.starts_at,EsportsTournament.id).limit(150)).all()
        matches=s.scalars(select(EsportsMatch).order_by(EsportsMatch.started_at,EsportsMatch.id).limit(150)).all()
        logs=s.scalars(select(EsportsSyncLog).order_by(EsportsSyncLog.id.desc()).limit(100)).all()
        cfg=s.get(EsportsConfig,1)
        return {"config":{"enabled":bool(cfg.enabled) if cfg else True,"organization_name":cfg.organization_name if cfg else "POS Professional Esports"},"providers":[{"id":p.id,"name":p.name,"provider_type":p.provider_type,"base_url":p.base_url,"api_key_set":bool(p.api_key),"leaderboard_path_template":p.leaderboard_path_template,"tournament_path_template":p.tournament_path_template,"enabled":bool(p.enabled)} for p in providers],"games":[_game_row(g) for g in games],"leaderboard":[{"id":e.id,"game_id":e.game_id,"game_code":e.game.code if e.game else "","player_id":e.external_player_id,"player_name":e.player_name,"rank":e.rank,"score":float(e.score or 0),"wins":e.wins,"kills":e.kills,"matches":e.matches,"region":e.region,"synced_at":e.synced_at.isoformat()} for e in entries],"tournaments":[{"id":t.id,"game_id":t.game_id,"game_code":t.game.code if t.game else "","external_id":t.external_id,"name":t.name,"status":t.status,"starts_at":t.starts_at.isoformat() if t.starts_at else None,"ends_at":t.ends_at.isoformat() if t.ends_at else None} for t in tournaments],"matches":[{"id":m.id,"tournament_id":m.tournament_id,"external_id":m.external_id,"round":m.round_name,"status":m.status,"winner":m.winner_player_id,"started_at":m.started_at.isoformat() if m.started_at else None} for m in matches],"sync_logs":[{"id":l.id,"provider_id":l.provider_id,"game_id":l.game_id,"sync_type":l.sync_type,"status":l.status,"http_status":l.http_status,"message":l.message,"started_at":l.started_at.isoformat(),"finished_at":l.finished_at.isoformat() if l.finished_at else None} for l in logs]}

def save_provider(data):
    _ensure_seed()
    with SessionLocal.begin() as s:
        row=s.get(EsportsProvider,int(data["id"])) if data.get("id") else EsportsProvider()
        row.name=str(data.get("name") or "Generic Esports Provider").strip(); row.provider_type=str(data.get("provider_type") or "GENERIC").strip().upper(); row.base_url=str(data.get("base_url") or "").strip().rstrip("/");
        if data.get("api_key"): row.api_key=str(data["api_key"])
        row.leaderboard_path_template=str(data.get("leaderboard_path_template") or "/games/{code}/leaderboard"); row.tournament_path_template=str(data.get("tournament_path_template") or "/games/{code}/tournaments"); row.enabled=bool(data.get("enabled",True)); s.add(row); s.flush(); return {"ok":True,"id":row.id}

def save_game(data):
    _ensure_seed()
    with SessionLocal.begin() as s:
        row=s.get(EsportsGame,int(data["id"])) if data.get("id") else EsportsGame()
        row.code=str(data.get("code") or "").strip().lower().replace(" ","_"); row.name=str(data.get("name") or row.code).strip()
        if not row.code or not row.name: raise ValueError("code واسم اللعبة مطلوبان")
        row.provider_id=int(data["provider_id"]) if data.get("provider_id") else None; row.tournament_enabled=bool(data.get("tournament_enabled",False)); row.leaderboard_visible=bool(data.get("leaderboard_visible",True)); row.enabled=bool(data.get("enabled",True)); row.leaderboard_path=str(data.get("leaderboard_path") or ""); row.tournament_path=str(data.get("tournament_path") or ""); s.add(row); s.flush(); return {"ok":True,"id":row.id}

def toggle_game(game_id:int,tournament_enabled=None,leaderboard_visible=None):
    with SessionLocal.begin() as s:
        g=s.get(EsportsGame,game_id)
        if not g: raise ValueError("اللعبة غير موجودة")
        if tournament_enabled is not None: g.tournament_enabled=bool(tournament_enabled)
        if leaderboard_visible is not None: g.leaderboard_visible=bool(leaderboard_visible)
        return {"ok":True,"game":_game_row(g)}

def _pick_list(payload,keys):
    if isinstance(payload,list): return payload
    if isinstance(payload,dict):
        for k in keys:
            v=payload.get(k)
            if isinstance(v,list): return v
        data=payload.get("data")
        if isinstance(data,list): return data
        if isinstance(data,dict):
            for k in keys:
                v=data.get(k)
                if isinstance(v,list): return v
    return []

def _dt(v):
    if not v: return None
    try: return datetime.fromisoformat(str(v).replace("Z","+00:00")).replace(tzinfo=None)
    except Exception: return None

def sync_game(game_id:int,timeout=10):
    _ensure_seed(); started=datetime.now()
    with SessionLocal.begin() as s:
        g=s.get(EsportsGame,game_id)
        if not g: raise ValueError("اللعبة غير موجودة")
        provider=s.get(EsportsProvider,g.provider_id) if g.provider_id else None
        log=EsportsSyncLog(provider_id=provider.id if provider else None,game_id=g.id,sync_type="LEADERBOARD",status="RUNNING",started_at=started); s.add(log); s.flush(); log_id=log.id
    if not provider or not provider.enabled or not provider.base_url:
        msg="Provider Base URL غير مضبوط؛ لم يتم تنفيذ اتصال خارجي."
        with SessionLocal.begin() as s:
            g=s.get(EsportsGame,game_id); g.last_sync_at=datetime.now(); g.last_sync_status="CONFIG_REQUIRED"; g.last_sync_error=msg; l=s.get(EsportsSyncLog,log_id); l.status="CONFIG_REQUIRED"; l.message=msg; l.finished_at=datetime.now()
        return {"ok":False,"status":"CONFIG_REQUIRED","message":msg}
    headers={"Accept":"application/json"}
    ptype=provider.provider_type.upper()
    if provider.api_key:
        if ptype=="RIOT_LOL": headers["X-Riot-Token"]=provider.api_key
        elif ptype=="PANDASCORE": headers["Authorization"]=f"Bearer {provider.api_key}"
        else: headers["Authorization"]=f"Bearer {provider.api_key}"; headers["X-API-Key"]=provider.api_key
    base=provider.base_url.rstrip("/")+"/"; lb_path=(g.leaderboard_path or provider.leaderboard_path_template).format(code=g.code); url=urljoin(base,lb_path)
    try:
        if ptype=="RIOT_LOL" and not provider.api_key:
            raise RuntimeError("Riot API Key غير مضبوط؛ افتح Provider وأدخل X-Riot-Token")
        if ptype=="PANDASCORE" and not provider.api_key:
            raise RuntimeError("PandaScore API Key غير مضبوط؛ افتح Provider وأدخل المفتاح")
        resp=requests.get(url,headers=headers,timeout=timeout); status=resp.status_code; resp.raise_for_status(); payload=resp.json()
        if ptype=="HENRIKDEV_VALORANT":
            rows=list((payload.get("data") or {}).get("players") or []) if isinstance(payload,dict) else []
        elif ptype=="RIOT_LOL":
            raw=list(payload.get("entries") or []) if isinstance(payload,dict) else []
            rows=[]
            for r in raw:
                rows.append({"rank":r.get("rank"),"player_id":r.get("puuid") or r.get("summonerId") or "","player_name":r.get("summonerName") or "Player","score":r.get("leaguePoints") or 0,"wins":r.get("wins") or 0,"losses":r.get("losses") or 0,"region":payload.get("name") or "EUROPE"})
        elif ptype=="PANDASCORE":
            # PandaScore is used here for real esports match/tournament discovery; it is not treated as a fake leaderboard.
            rows=[]
        else:
            rows=_pick_list(payload,["entries","leaderboard","players","results"])
    except Exception as exc:
        msg=f"Leaderboard sync failed: {exc}"
        with SessionLocal.begin() as s:
            g=s.get(EsportsGame,game_id); g.last_sync_at=datetime.now(); g.last_sync_status="FAILED"; g.last_sync_error=msg; l=s.get(EsportsSyncLog,log_id); l.status="FAILED"; l.http_status=locals().get("status"); l.message=msg; l.finished_at=datetime.now()
        return {"ok":False,"status":"FAILED","message":msg}
    with SessionLocal.begin() as s:
        if ptype != "PANDASCORE":
            s.execute(delete(EsportsLeaderboardEntry).where(EsportsLeaderboardEntry.game_id==game_id))
        for i,r in enumerate(rows,1):
            rr=str(r.get("rank") or "")
            rank=int(rr) if rr.isdigit() else int(r.get("leaderboard_rank") or i)
            score_value=r.get("score") or r.get("rr") or r.get("points") or 0
            player_name=(f"{r.get('name','Player')}#{r.get('tag')}" if r.get('tag') else str(r.get("player_name") or r.get("name") or r.get("username") or r.get("player") or "Player"))
            s.add(EsportsLeaderboardEntry(game_id=game_id,external_player_id=str(r.get("player_id") or r.get("puuid") or r.get("id") or r.get("external_id") or ""),player_name=player_name,rank=rank,score=Decimal(str(score_value)),wins=int(r.get("wins") or 0),kills=int(r.get("kills") or 0),matches=int(r.get("matches") or 0),region=str(r.get("region") or "EU" if provider.provider_type.upper()=="HENRIKDEV_VALORANT" else r.get("region") or ""),raw_json=json.dumps(r,ensure_ascii=False),synced_at=datetime.now()))
        g=s.get(EsportsGame,game_id); g.last_sync_at=datetime.now(); g.last_sync_status="SUCCESS"; g.last_sync_error=""; l=s.get(EsportsSyncLog,log_id); l.status="SUCCESS"; l.http_status=status; l.message=f"{provider.name}: leaderboard entries {len(rows)}"; l.finished_at=datetime.now()
    if g.tournament_enabled or ptype=="PANDASCORE":
        try:
            if ptype=="PANDASCORE":
                code_map={"counter_strike_2":"csgo","dota_2":"dota2","league_of_legends":"lol","valorant":"valorant"}
                tpath=f"/{code_map.get(g.code,g.code)}/matches/upcoming"
            else:
                tpath=(g.tournament_path or provider.tournament_path_template).format(code=g.code)
            turl=urljoin(base,tpath); r=requests.get(turl,headers=headers,timeout=timeout); r.raise_for_status(); trows=_pick_list(r.json(),["tournaments","events","results","matches"])
            with SessionLocal.begin() as s:
                s.execute(delete(EsportsTournament).where(EsportsTournament.game_id==game_id))
                for x in trows: s.add(EsportsTournament(game_id=game_id,external_id=str(x.get("id") or x.get("external_id") or ""),name=str(x.get("name") or x.get("title") or "Tournament"),status=str(x.get("status") or "UPCOMING"),starts_at=_dt(x.get("starts_at") or x.get("start_time")),ends_at=_dt(x.get("ends_at") or x.get("end_time")),metadata_json=json.dumps(x,ensure_ascii=False),synced_at=datetime.now()))
        except Exception: pass
    return {"ok":True,"status":"SUCCESS","entries":len(rows)}

def client_catalog():
    _ensure_seed()
    with SessionLocal() as s:
        games=s.scalars(select(EsportsGame).where(EsportsGame.enabled.is_(True)).order_by(EsportsGame.name)).all()
        return [{"code":g.code,"name":g.name,"tournament_enabled":bool(g.tournament_enabled),"leaderboard_visible":bool(g.leaderboard_visible)} for g in games]
