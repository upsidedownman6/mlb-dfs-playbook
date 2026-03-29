# ─────────────────────────────────────────────────────────────────────────────
# MLB DFS Playbook — Production Streamlit App
# ─────────────────────────────────────────────────────────────────────────────
# Data:  MLB Stats API (schedule + probables, free, no key)
#        Open-Meteo (weather, free, no key)
# Math:  PuLP linear programming (true salary-cap optimizer)
# Run:   streamlit run app.py
# ─────────────────────────────────────────────────────────────────────────────

import streamlit as st
import pandas as pd
import requests
import io
import random
from datetime import datetime, timedelta
from pulp import (
    LpProblem, LpMaximize, LpVariable, lpSum,
    LpBinary, LpStatus, value, PULP_CBC_CMD
)
import pandas as pd
import streamlit as st
# ... your other imports ...

def leverage_color(val):
    if pd.isna(val):
        return ""
    if val >= 1.4:
        return "background-color:#145A32;color:white;"
    if val >= 1.0:
        return "background-color:#1E8449;color:white;"
    if val >= 0.7:
        return "background-color:#7D6608;color:white;"
    return "background-color:#922B21;color:white;"
try:
    import statsapi
    STATSAPI_OK = True
except ImportError:
    STATSAPI_OK = False

st.set_page_config(
    page_title="MLB DFS Playbook",
    page_icon="⚾",
    layout="wide",
    initial_sidebar_state="collapsed"
)

import logging
logging.getLogger("pulp").setLevel(logging.CRITICAL)

SALARY_CAP   = 50_000
SALARY_FLOOR = 49_000

DOME_PARKS = {"ARI","HOU","MIA","MIL","MIN","SEA","TB","TEX","TOR"}

PARK_FACTORS = {
    "ARI":{"runs":102,"hr":85},  "ATL":{"runs":102,"hr":102},
    "BAL":{"runs":117,"hr":187}, "BOS":{"runs":107,"hr":74},
    "CHC":{"runs":104,"hr":86},  "CWS":{"runs":97,"hr":100},
    "CIN":{"runs":94,"hr":120},  "CLE":{"runs":94,"hr":70},
    "COL":{"runs":131,"hr":112}, "DET":{"runs":93,"hr":58},
    "HOU":{"runs":102,"hr":122}, "KC":{"runs":110,"hr":58},
    "LAA":{"runs":102,"hr":148}, "LAD":{"runs":100,"hr":122},
    "MIA":{"runs":103,"hr":82},  "MIL":{"runs":88,"hr":110},
    "MIN":{"runs":102,"hr":80},  "NYM":{"runs":91,"hr":79},
    "NYY":{"runs":100,"hr":146}, "PHI":{"runs":104,"hr":120},
    "PIT":{"runs":102,"hr":72},  "SD":{"runs":91,"hr":77},
    "SF":{"runs":91,"hr":64},    "SEA":{"runs":82,"hr":118},
    "STL":{"runs":97,"hr":76},   "TB":{"runs":106,"hr":126},
    "TEX":{"runs":103,"hr":130}, "TOR":{"runs":100,"hr":137},
    "WSH":{"runs":104,"hr":104}, "OAK":{"runs":109,"hr":119},
}

STADIUM_COORDS = {
    "ARI":(33.4453,-112.0667), "ATL":(33.8908,-84.4678),
    "BAL":(39.2839,-76.6217),  "BOS":(42.3467,-71.0972),
    "CHC":(41.9484,-87.6553),  "CWS":(41.8300,-87.6339),
    "CIN":(39.0979,-84.5082),  "CLE":(41.4962,-81.6852),
    "COL":(39.7559,-104.9942), "DET":(42.3390,-83.0485),
    "HOU":(29.7573,-95.3555),  "KC":(39.0517,-94.4803),
    "LAA":(33.8003,-117.8827), "LAD":(34.0739,-118.2400),
    "MIA":(25.7781,-80.2197),  "MIL":(43.0280,-87.9712),
    "MIN":(44.9817,-93.2781),  "NYM":(40.7571,-73.8458),
    "NYY":(40.8296,-73.9262),  "PHI":(39.9061,-75.1665),
    "PIT":(40.4469,-80.0057),  "SD":(32.7073,-117.1566),
    "SF":(37.7786,-122.3893),  "SEA":(47.5914,-122.3325),
    "STL":(38.6226,-90.1928),  "TB":(27.7682,-82.6534),
    "TEX":(32.7473,-97.0822),  "TOR":(43.6414,-79.3894),
    "WSH":(38.8730,-77.0074),  "OAK":(38.5853,-121.5008),
}

PARK_NAMES = {
    "ARI":"Chase Field","ATL":"Truist Park","BAL":"Oriole Park at Camden Yards",
    "BOS":"Fenway Park","CHC":"Wrigley Field","CWS":"Rate Field",
    "CIN":"Great American Ball Park","CLE":"Progressive Field","COL":"Coors Field",
    "DET":"Comerica Park","HOU":"Daikin Park","KC":"Kauffman Stadium",
    "LAA":"Angel Stadium","LAD":"Dodger Stadium","MIA":"loanDepot park",
    "MIL":"American Family Field","MIN":"Target Field","NYM":"Citi Field",
    "NYY":"Yankee Stadium","PHI":"Citizens Bank Park","PIT":"PNC Park",
    "SD":"Petco Park","SF":"Oracle Park","SEA":"T-Mobile Park",
    "STL":"Busch Stadium","TB":"Tropicana Field","TEX":"Globe Life Field",
    "TOR":"Rogers Centre","WSH":"Nationals Park","OAK":"Sutter Health Park",
}

DK_TEAM_MAP = {
    "KAN":"KC","KCA":"KC","CHW":"CWS","CHA":"CWS","CHN":"CHC",
    "SLN":"STL","SDN":"SD","SFN":"SF","LAN":"LAD","NYN":"NYM",
    "NYA":"NYY","WAS":"WSH","ATH":"OAK","TBA":"TB","MIA":"MIA",
    "ANA":"LAA","FLA":"MIA",
}

def norm_team(t):
    return DK_TEAM_MAP.get(str(t).upper().strip(), str(t).upper().strip())
# ─────────────────────────────────────────────────────────────────────────────
# SESSION STATE INIT
# ─────────────────────────────────────────────────────────────────────────────
def init_state():
    defaults = {
        "games": [],
        "players": pd.DataFrame(),
        "lineups": [],
        "proj_edits": {},   # {player_id: {base, bvp, form}}
        "locks": set(),
        "excludes": set(),
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()

# ─────────────────────────────────────────────────────────────────────────────
# MLB SCHEDULE + PROBABLES (MLB Stats API)
# ─────────────────────────────────────────────────────────────────────────────
_MLB_ID_MAP = {
    133:"OAK",134:"PIT",135:"SD",136:"SEA",137:"SF",138:"STL",
    139:"TB",140:"TEX",141:"TOR",142:"MIN",143:"PHI",144:"ATL",
    145:"CWS",146:"MIA",147:"NYY",158:"MIL",108:"LAA",109:"ARI",
    110:"BAL",111:"BOS",112:"CHC",113:"CIN",114:"CLE",115:"COL",
    116:"DET",117:"HOU",118:"KC",119:"LAD",120:"WSH",121:"NYM",
}

def _mlb_team_abbr(team_id, name):
    if team_id in _MLB_ID_MAP:
        return _MLB_ID_MAP[team_id]
    nm = (name or "").upper()
    for abbr in PARK_FACTORS:
        if abbr in nm:
            return abbr
    return nm[:3] if name else "UNK"

@st.cache_data(ttl=900, show_spinner=False)
def fetch_mlb_schedule(date_str: str):
    """date_str: MM/DD/YYYY"""
    if not STATSAPI_OK:
        return []
    try:
        sched = statsapi.schedule(date=date_str)
        games = []
        for g in sched:
            if g.get("status") in ("Cancelled", "Postponed"):
                continue
            away = _mlb_team_abbr(g.get("away_id", 0), g.get("away_name", ""))
            home = _mlb_team_abbr(g.get("home_id", 0), g.get("home_name", ""))
            games.append({
                "game_id":   g.get("game_id"),
                "time":      g.get("game_datetime", ""),
                "away":      away,
                "home":      home,
                "away_name": g.get("away_name", away),
                "home_name": g.get("home_name", home),
                "away_pitcher": g.get("away_probable_pitcher", "TBD"),
                "home_pitcher": g.get("home_probable_pitcher", "TBD"),
                "away_confirmed": g.get("away_probable_pitcher","") not in ("","TBD"),
                "home_confirmed": g.get("home_probable_pitcher","") not in ("","TBD"),
                "away_total": 4.25,
                "home_total": 4.25,
                "ou": 8.5,
            })
        return games
    except Exception:
        return []

# ─────────────────────────────────────────────────────────────────────────────
# WEATHER — OPEN-METEO (free, no key)
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=1800, show_spinner=False)
def fetch_weather(lat: float, lon: float, game_time_utc: str):
    """Returns dict: temp_f, wind_mph, wind_deg, humidity, precip_pct, condition"""
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&hourly=temperature_2m,precipitation_probability,windspeed_10m,"
            f"winddirection_10m,relativehumidity_2m,weathercode"
            f"&temperature_unit=fahrenheit&windspeed_unit=mph"
            f"&timezone=auto&forecast_days=2"
        )
        r = requests.get(url, timeout=6)
        r.raise_for_status()
        data = r.json()

        hours = data["hourly"]["time"]
        target = game_time_utc[:16] if game_time_utc else datetime.utcnow().strftime("%Y-%m-%dT%H:%M")
        best_idx = 0
        for i, h in enumerate(hours):
            if h[:16] <= target[:16]:
                best_idx = i

        wcode = data["hourly"]["weathercode"][best_idx]
        condition = _wmo_to_condition(wcode)

        return {
            "temp_f":    round(data["hourly"]["temperature_2m"][best_idx], 1),
            "wind_mph":  round(data["hourly"]["windspeed_10m"][best_idx], 1),
            "wind_deg":  data["hourly"]["winddirection_10m"][best_idx],
            "humidity":  data["hourly"]["relativehumidity_2m"][best_idx],
            "precip_pct":data["hourly"]["precipitation_probability"][best_idx],
            "condition": condition,
            "wcode":     wcode,
        }
    except Exception:
        return {"temp_f":70,"wind_mph":5,"wind_deg":180,"humidity":50,
                "precip_pct":0,"condition":"Unknown","wcode":0}

def _wmo_to_condition(code):
    if code == 0:              return "Clear ☀️"
    if code in (1, 2):         return "Partly Cloudy ⛅"
    if code == 3:              return "Overcast ☁️"
    if code in range(51, 68):  return "Rain 🌧️"
    if code in range(80, 83):  return "Showers 🌦️"
    if code in range(95, 100): return "Thunderstorm ⛈️"
    if code in range(71, 78):  return "Snow ❄️"
    return "Cloudy 🌫️"

def deg_to_label(deg):
    dirs = ["N","NNE","NE","ENE","E","ESE","SE","SSE",
            "S","SSW","SW","WSW","W","WNW","NW","NNW"]
    return dirs[round(deg / 22.5) % 16]
    # ─────────────────────────────────────────────────────────────────────────────
# ENVIRONMENT SCORES (HITTING & PITCHING)
# ─────────────────────────────────────────────────────────────────────────────

def compute_hitting_env_score(park_runs, temp_f, wind_mph, wind_deg, is_dome, precip_pct):
    """Higher = better for hitters. 0 is neutral-ish."""
    if is_dome:
        base = 0.5  # domes are usually slightly hitter neutral to friendly
        park_term = (park_runs - 1.0) * 4.0
        return round(base + park_term, 2)

    score = 0.0
    # Park runs: 0.0 at 1.00, about +/- 3 at extremes like COL / SEA
    score += (park_runs - 1.0) * 4.0

    # Temperature: hot = good for bats
    if temp_f >= 85:
        score += 2.0
    elif temp_f >= 78:
        score += 1.2
    elif temp_f >= 70:
        score += 0.5
    elif temp_f <= 45:
        score -= 2.0
    elif temp_f <= 55:
        score -= 1.0

    # Wind
    norm = wind_deg % 360
    if 315 <= norm or norm <= 45:  # blowing out
        if wind_mph >= 18:
            score += 2.0
        elif wind_mph >= 10:
            score += 1.0
        elif wind_mph >= 6:
            score += 0.4
    elif 135 <= norm <= 225:       # blowing in
        if wind_mph >= 18:
            score -= 1.8
        elif wind_mph >= 10:
            score -= 1.0

    # Rain: heavy rain knocks it down slightly
    if precip_pct >= 60:
        score -= 1.0
    elif precip_pct >= 40:
        score -= 0.4

    return round(score, 2)


def compute_pitcher_env_score(park_runs, temp_f, wind_mph, wind_deg, is_dome, precip_pct, opp_total):
    """Higher = better for pitchers (lower scoring environment + low opp total)."""
    hit_score = compute_hitting_env_score(park_runs, temp_f, wind_mph, wind_deg, is_dome, precip_pct)
    score = -hit_score  # inverse of hitting environment

    # Opponent implied total: biggest driver for SP
    if opp_total <= 3.0:
        score += 3.0
    elif opp_total <= 3.5:
        score += 2.0
    elif opp_total <= 4.0:
        score += 1.0
    elif opp_total >= 5.0:
        score -= 1.0

    return round(score, 2)


def tier_from_score(score, for_pitcher=False):
    """Return (tier, label) given an environment score."""
    if for_pitcher:
        if score >= 4.0:
            return "elite",   "🧊 Elite Pitching Spot"
        if score >= 2.5:
            return "good",    "👍 Solid Pitching Spot"
        if score <= -1.5:
            return "avoid",   "🔥 Risky for SP"
        return "neutral",     "⚖️ Neutral SP Spot"
    else:
        if score >= 4.0:
            return "elite",   "🔥 Elite Hitting Spot"
        if score >= 2.5:
            return "good",    "↑ Good Hitting Spot"
        if score <= -1.5:
            return "cold",    "❄️ Cold for Bats"
        return "neutral",     "⚖️ Neutral Hitting Spot"
# ─────────────────────────────────────────────────────────────────────────────
# IMPLIED TEAM TOTALS FROM MONEYLINES + GAME TOTAL
# ─────────────────────────────────────────────────────────────────────────────

def moneyline_to_prob(ml):
    """Convert American ML to implied win probability (no vig)."""
    ml = float(ml)
    if ml < 0:
        return (-ml) / (-ml + 100.0)
    else:
        return 100.0 / (ml + 100.0)

def implied_totals_from_ml(total_runs, home_ml, away_ml):
    """
    Approximate implied team totals from game total + home/away ML.
    Uses normalized win probabilities to split the total. [web:297][web:299][web:304]
    """
    try:
        total = float(total_runs)
        h_ml = float(home_ml)
        a_ml = float(away_ml)
    except (TypeError, ValueError):
        return None, None

    p_home = moneyline_to_prob(h_ml)
    p_away = moneyline_to_prob(a_ml)

    s = p_home + p_away
    if s <= 0:
        return None, None
    p_home /= s
    p_away /= s

    home_total = total * p_home
    away_total = total * p_away

    return round(away_total, 2), round(home_total, 2)
# ─────────────────────────────────────────────────────────────────────────────
# PROJECTION ENGINE
# ─────────────────────────────────────────────────────────────────────────────
def get_park_factor(team):
    pf = PARK_FACTORS.get(norm_team(team), {"runs":100})
    return pf["runs"] / 100.0

def get_wind_factor(wind_mph, wind_deg, is_dome, is_pitcher):
    if is_dome:
        return 1.0
    norm = wind_deg % 360
    if 315 <= norm or norm <= 45:
        direction = "out"
    elif 135 <= norm <= 225:
        direction = "in"
    else:
        direction = "cross"

    if direction == "out":
        adj = min(wind_mph * 0.004, 0.08)
    elif direction == "in":
        adj = -min(wind_mph * 0.004, 0.07)
    else:
        adj = min(wind_mph * 0.001, 0.02)

    return (1.0 - adj) if is_pitcher else (1.0 + adj)

def get_temp_factor(temp_f, is_pitcher):
    if temp_f < 40:     adj = -0.06
    elif temp_f < 50:   adj = -0.03
    elif temp_f < 60:   adj = -0.01
    elif temp_f < 72:   adj =  0.0
    elif temp_f < 82:   adj =  0.02
    else:               adj =  0.035
    return (1.0 - adj) if is_pitcher else (1.0 + adj)

def get_vegas_factor(team, games_list, is_pitcher):
    team = norm_team(team)
    for g in games_list:
        if g["away"] == team:
            total = g["away_total"]
            opp   = g["home_total"]
        elif g["home"] == team:
            total = g["home_total"]
            opp   = g["away_total"]
        else:
            continue
        avg = 4.5
        if is_pitcher:
            return max(0.75, 0.90 + (1.0 - opp / avg) * 0.25)
        else:
            return max(0.75, 0.85 + (total / avg) * 0.22)
    return 1.0

def build_projections(df, games_list):
    if df.empty:
        return df
    df = df.copy()

    # Weather per home team
    weather_cache = {}
    for _, row in df.iterrows():
        home = row.get("home_team", row["team"])
        if home not in weather_cache:
            is_dome = norm_team(home) in DOME_PARKS
            if is_dome:
                weather_cache[home] = {
                    "temp_f":72,"wind_mph":0,"wind_deg":0,
                    "humidity":50,"precip_pct":0,
                    "condition":"Dome 🏟️","is_dome":True
                }
            else:
                coords = STADIUM_COORDS.get(norm_team(home))
                if coords:
                    game_time = ""
                    for g in games_list:
                        if g["home"] == norm_team(home):
                            game_time = g.get("time","")
                            break
                    w = fetch_weather(coords[0], coords[1], game_time)
                    w["is_dome"] = False
                    weather_cache[home] = w
                else:
                    weather_cache[home] = {
                        "temp_f":70,"wind_mph":5,"wind_deg":180,
                        "humidity":50,"precip_pct":0,
                        "condition":"Unknown","is_dome":False
                    }

    for col in ["temp_f","wind_mph","wind_deg","humidity","precip_pct","condition","is_dome"]:
        df[col] = df["home_team"].map(lambda h: weather_cache.get(h, {}).get(col))

    df["park_f"]  = df.apply(lambda r: get_park_factor(r["home_team"]), axis=1)
    df["wind_f"]  = df.apply(lambda r: get_wind_factor(r["wind_mph"] or 5, r["wind_deg"] or 180,
                                                       r["is_dome"] or False, r["isP"]), axis=1)
    df["temp_f_factor"] = df.apply(lambda r: get_temp_factor(r["temp_f"] or 70, r["isP"]), axis=1)
    df["vegas_f"] = df.apply(lambda r: get_vegas_factor(r["team"], games_list, r["isP"]), axis=1)

    df["base"] = df.apply(lambda r: st.session_state.proj_edits.get(r["id"],{}).get("base", r["avg"]), axis=1)
    df["bvp"]  = df.apply(lambda r: st.session_state.proj_edits.get(r["id"],{}).get("bvp",  0.0), axis=1)
    df["form"] = df.apply(lambda r: st.session_state.proj_edits.get(r["id"],{}).get("form", 0.0), axis=1)

    df["finalProj"] = (df["base"] * df["park_f"] * df["wind_f"] *
                       df["temp_f_factor"] * df["vegas_f"] +
                       df["bvp"] + df["form"]).clip(lower=0).round(2)
    return df

# ─────────────────────────────────────────────────────────────────────────────
# CSV PARSER
# ─────────────────────────────────────────────────────────────────────────────
def parse_dk_csv(file_bytes):
    try:
        df = pd.read_csv(io.BytesIO(file_bytes))
        df.columns = [c.strip() for c in df.columns]
        required = ["Position","Name","ID","Roster Position","Salary","Game Info","TeamAbbrev","AvgPointsPerGame"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            st.error(f"CSV missing columns: {missing}")
            return pd.DataFrame()

        df = df.rename(columns={
            "Position":"pos","Name":"name","ID":"id",
            "Roster Position":"rosterPos","Salary":"sal",
            "Game Info":"gameInfo","TeamAbbrev":"team",
            "AvgPointsPerGame":"avg"
        })
        df["id"]  = df["id"].astype(str).str.strip()
        df["sal"] = pd.to_numeric(df["sal"], errors="coerce").fillna(0).astype(int)
        df["avg"] = pd.to_numeric(df["avg"], errors="coerce").fillna(0.0)
        df["team"] = df["team"].apply(norm_team)
        df["isP"]  = df["rosterPos"].str.strip() == "P"

        import re
        def parse_game(info):
            m = re.match(r"([A-Z]+)@([A-Z]+)", str(info).upper())
            if m:
                return norm_team(m.group(1)), norm_team(m.group(2))
            return "", ""

        df["away_team"] = df["gameInfo"].apply(lambda x: parse_game(x)[0])
        df["home_team"] = df["gameInfo"].apply(lambda x: parse_game(x)[1])
        df["opp"] = df.apply(
            lambda r: r["home_team"] if r["team"]==r["away_team"] else r["away_team"],
            axis=1
        )

        df["locked"]      = False
        df["excluded"]    = False
        df["spConfirmed"] = False

        df = df[df["sal"] > 0].reset_index(drop=True)
        return df
    except Exception as e:
        st.error(f"CSV parse error: {e}")
        return pd.DataFrame()
# ─────────────────────────────────────────────────────────────────────────────
# LP OPTIMIZER
# ─────────────────────────────────────────────────────────────────────────────
SLOT_ELIGIBLE = {
    "P1": ["P"],    "P2": ["P"],
    "C":  ["C","C/1B"],
    "1B": ["1B","C/1B","1B/3B"],
    "2B": ["2B","2B/SS"],
    "3B": ["3B","1B/3B"],
    "SS": ["SS","2B/SS"],
    "OF1":["OF"], "OF2":["OF"], "OF3":["OF"],
}
SLOTS = list(SLOT_ELIGIBLE.keys())

def player_eligible_slots(roster_pos):
    rp = str(roster_pos).strip()
    eligible = []
    for slot, pos_list in SLOT_ELIGIBLE.items():
        if any(p in rp for p in pos_list):
            eligible.append(slot)
    return eligible

def solve_one_lineup(players, salary_cap, salary_floor,
                     stack_size, locked_ids, excluded_ids,
                     prev_lineups, min_unique,
                     noise_sigma=0.0, game_stack=False):
    pool = [p for p in players if p["id"] not in excluded_ids]
    if not pool:
        return None

    if noise_sigma > 0:
        pool = [{**p, "finalProj": p["finalProj"] + random.gauss(0, noise_sigma)} for p in pool]

    locked_in = [p for p in pool if p["id"] in locked_ids]

    elig = {}
    for p in pool:
        slots = player_eligible_slots(p["rosterPos"])
        if slots:
            elig[p["id"]] = slots

    prob = LpProblem("DFS", LpMaximize)

    x = {}
    for p in pool:
        for slot in elig.get(p["id"], []):
            x[(p["id"], slot)] = LpVariable(f"x_{p['id']}_{slot}", cat=LpBinary)

    if not x:
        return None

    pid_map = {p["id"]: p for p in pool}

    # Objective
    prob += lpSum(x[(pid, slot)] * pid_map[pid]["finalProj"]
                  for (pid, slot) in x)

    # Each slot filled exactly once
    for slot in SLOTS:
        prob += lpSum(x[(pid, s)] for (pid, s) in x if s == slot) == 1

    # Each player in at most one slot
    for pid in elig:
        prob += lpSum(x[(pid, s)] for s in elig[pid] if (pid, s) in x) <= 1

    # Salary
    prob += lpSum(x[(pid, slot)] * pid_map[pid]["sal"] for (pid, slot) in x) <= salary_cap
    prob += lpSum(x[(pid, slot)] * pid_map[pid]["sal"] for (pid, slot) in x) >= salary_floor

    # Locked
    for p in locked_in:
        if elig.get(p["id"]):
            prob += lpSum(x[(p["id"], s)] for s in elig[p["id"]] if (p["id"], s) in x) == 1

    # Stack: at least stack_size hitters from one team
    hitter_teams = list({p["team"] for p in pool if not p["isP"]})
    if stack_size >= 2 and hitter_teams:
        team_stack = {t: LpVariable(f"ts_{t}", cat=LpBinary) for t in hitter_teams}
        for t in hitter_teams:
            t_hitters = [p for p in pool if p["team"] == t and not p["isP"]]
            t_count = lpSum(x[(p["id"], s)]
                            for p in t_hitters
                            for s in elig.get(p["id"], [])
                            if (p["id"], s) in x)
            M = min(len(t_hitters), 8)
            prob += t_count >= stack_size * team_stack[t]
            prob += t_count <= M * team_stack[t]
        prob += lpSum(team_stack[t] for t in hitter_teams) >= 1

    # Max 8 from any team
    for t in {p["team"] for p in pool}:
        t_players = [p for p in pool if p["team"] == t]
        prob += lpSum(x[(p["id"], s)]
                      for p in t_players
                      for s in elig.get(p["id"], [])
                      if (p["id"], s) in x) <= 8

    # Diversity vs previous lineups
    for prev in prev_lineups:
        prev_ids = {p["id"] for p in prev["players"]}
        prob += lpSum(x[(pid, slot)]
                      for (pid, slot) in x
                      if pid in prev_ids) <= 10 - min_unique

    prob.solve(PULP_CBC_CMD(msg=0, timeLimit=10))

    if LpStatus[prob.status] != "Optimal":
        return None

    lineup = []
    for (pid, slot), var in x.items():
        if value(var) is not None and round(value(var)) == 1:
            lineup.append({**pid_map[pid], "slot": slot})
    if len(lineup) != 10:
        return None
    return lineup

def _find_stack(lineup, stack_size):
    from collections import Counter
    hitters = [p["team"] for p in lineup if not p["isP"]]
    counts = Counter(hitters)
    best = counts.most_common(1)
    return best[0][0] if best and best[0][1] >= stack_size else "–"

def generate_lineups(players_df, n_lineups, stack_size, min_unique,
                     salary_floor, locked_ids, excluded_ids,
                     noise_sigma=0.5, game_stack=False):
    players = players_df.to_dict("records")
    lineups = []
    failed  = 0
    max_attempts = n_lineups * 25
    progress = st.progress(0, text="Building lineups…")

    for attempt in range(max_attempts):
        if len(lineups) >= n_lineups:
            break
        lu = solve_one_lineup(
            players, SALARY_CAP, salary_floor,
            stack_size, locked_ids, excluded_ids,
            lineups, min_unique,
            noise_sigma=noise_sigma,
            game_stack=game_stack
        )
        if lu is None:
            failed += 1
            if failed > 30 and len(lineups) == 0:
                break
        else:
            total_sal = sum(p["sal"] for p in lu)
            total_proj = sum(p["finalProj"] for p in lu)
            stack_team = _find_stack(lu, stack_size)
            lineups.append({
                "players": lu,
                "sal": total_sal,
                "proj": round(total_proj, 2),
                "stack": stack_team
            })
        pct = min(len(lineups) / n_lineups, 1.0)
        progress.progress(pct, text=f"Built {len(lineups)}/{n_lineups} lineups…")

    progress.empty()
    return lineups

# ─────────────────────────────────────────────────────────────────────────────
# WEATHER IMPACT LABEL
# ─────────────────────────────────────────────────────────────────────────────
def weather_impact(temp_f, wind_mph, wind_deg, precip_pct, is_dome):
    if is_dome:
        return "dome", "🏟️ Dome — weather irrelevant"
    if precip_pct >= 50:
        return "warning", f"⛈️ RAIN RISK ({precip_pct}%) — monitor postponement"
    score = 0
    if temp_f > 80:    score += 2
    elif temp_f > 68:  score += 1
    elif temp_f < 45:  score -= 3
    elif temp_f < 55:  score -= 1

    norm = wind_deg % 360
    if 315 <= norm or norm <= 45:
        direction = "out"
    elif 135 <= norm <= 225:
        direction = "in"
    else:
        direction = "cross"

    if direction == "out":
        score += 2 if wind_mph >= 15 else (1 if wind_mph >= 8 else 0)
    elif direction == "in":
        score -= 2 if wind_mph >= 15 else (1 if wind_mph >= 8 else 0)

    wind_label = deg_to_label(wind_deg)
    if score >= 3:
        return "hitter",  f"🔥 HITTER BOOST — {wind_mph}mph {wind_label}, {temp_f:.0f}°F"
    if score >= 1:
        return "hitter",  f"↑ Slight Hitter Lean — {temp_f:.0f}°F, {wind_mph}mph {wind_label}"
    if score <= -2:
        return "pitcher", f"❄️ PITCHER BOOST — {temp_f:.0f}°F, {wind_mph}mph {wind_label}"
    if score <= -1:
        return "pitcher", f"↓ Slight Pitcher Lean — {temp_f:.0f}°F"
    return "neutral",  f"⚖️ Neutral — {temp_f:.0f}°F, {wind_mph}mph {wind_label}"

# ─────────────────────────────────────────────────────────────────────────────
# HEADER + TABS
# ─────────────────────────────────────────────────────────────────────────────
n_players = len(st.session_state.players) if isinstance(st.session_state.players, pd.DataFrame) else 0
n_lineups = len(st.session_state.lineups)

c1, c2 = st.columns([3, 1])
with c1:
    st.markdown("## ⚾ MLB DFS Playbook")
    st.caption("Auto-loads schedule · weather · probables  |  LP optimizer  |  DK-ready CSV exports")
with c2:
    m1, m2 = st.columns(2)
    m1.metric("Players", n_players)
    m2.metric("Lineups",  n_lineups)
st.divider()

tab_slate, tab_pool, tab_proj, tab_opt, tab_lu = st.tabs([
    "🎮  Today’s Slate",
    "👥  Player Pool",
    "📊  Projections",
    "⚙️  Optimizer",
    "📋  Lineups",
])

# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 — TODAY'S SLATE
# ─────────────────────────────────────────────────────────────────────────────
with tab_slate:
    today_str = datetime.now().strftime("%m/%d/%Y")
    today_display = datetime.now().strftime("%A, %B %-d")
    st.subheader(f"Slate — {today_display}")

    col_load, col_date, _ = st.columns([1, 1, 4])
    with col_load:
        if st.button("🔄  Load Today's Games", type="primary"):
            with st.spinner("Fetching MLB schedule…"):
                loaded = fetch_mlb_schedule(today_str)
            if loaded:
                st.session_state.games = loaded
                st.success(f"Loaded {len(loaded)} games.")
            else:
                st.warning("No games found or MLB StatsAPI unavailable.")

    with col_date:
        override = st.date_input("Or pick a date", value=datetime.now().date(), label_visibility="collapsed")
        if st.button("Load →", key="load_date"):
            ds = override.strftime("%m/%d/%Y")
            with st.spinner("Fetching…"):
                loaded = fetch_mlb_schedule(ds)
            if loaded:
                st.session_state.games = loaded
                st.success(f"Loaded {len(loaded)} games.")

    if not st.session_state.games:
        st.info("Click **Load Today's Games** to auto-populate the slate.")
    else:
        # Build summary metrics for Top Hitting & Pitching spots
        summary_rows_hit = []
        summary_rows_sp  = []

        for g in st.session_state.games:
            home = g.get("home", "HOME")
            away = g.get("away", "AWAY")
            is_dome = norm_team(home) in DOME_PARKS

            coords = STADIUM_COORDS.get(norm_team(home))
            if coords and not is_dome:
                w = fetch_weather(coords[0], coords[1], g.get("time",""))
            elif is_dome:
                w = {
                    "temp_f":72, "wind_mph":0, "wind_deg":0, "humidity":50,
                    "precip_pct":0, "condition":"Dome 🏟️"
                }
            else:
                w = {
                    "temp_f":70, "wind_mph":5, "wind_deg":180, "humidity":50,
                    "precip_pct":0, "condition":"Unknown"
                }

            park_runs = PARK_FACTORS.get(norm_team(home), {"runs":100})["runs"] / 100.0
            hit_score = compute_hitting_env_score(
                park_runs,
                w["temp_f"],
                w["wind_mph"],
                w["wind_deg"],
                is_dome,
                w["precip_pct"],
            )
            hit_tier, hit_label = tier_from_score(hit_score, for_pitcher=False)
            summary_rows_hit.append({
                "Game": f"{away} @ {home}",
                "Park": PARK_NAMES.get(norm_team(home), ""),
                "Score": hit_score,
                "Tag": hit_label,
            })

            # Pitcher env per side
            away_opp_total = g["home_total"]
            home_opp_total = g["away_total"]

            away_p_score = compute_pitcher_env_score(
                park_runs,
                w["temp_f"],
                w["wind_mph"],
                w["wind_deg"],
                is_dome,
                w["precip_pct"],
                away_opp_total,
            )
            home_p_score = compute_pitcher_env_score(
                park_runs,
                w["temp_f"],
                w["wind_mph"],
                w["wind_deg"],
                is_dome,
                w["precip_pct"],
                home_opp_total,
            )
            away_p_tier, away_p_label = tier_from_score(away_p_score, for_pitcher=True)
            home_p_tier, home_p_label = tier_from_score(home_p_score, for_pitcher=True)

            summary_rows_sp.append({
                "Team": away,
                "Opp":  home,
                "Score": away_p_score,
                "Tag":  away_p_label,
            })
            summary_rows_sp.append({
                "Team": home,
                "Opp":  away,
                "Score": home_p_score,
                "Tag":  home_p_label,
            })

        # Sort and display top spots
        if summary_rows_hit:
            hit_df = pd.DataFrame(summary_rows_hit).sort_values("Score", ascending=False).head(5)
            sp_df  = pd.DataFrame(summary_rows_sp).sort_values("Score", ascending=False).head(5)

            hc1, hc2 = st.columns(2)
            with hc1:
                st.markdown("**Top Hitting Spots**")
                st.dataframe(
                    hit_df,
                    hide_index=True,
                    use_container_width=True,
                    height=min(220, 40 + 35*len(hit_df)),
                )
            with hc2:
                st.markdown("**Top Pitching Spots**")
                st.dataframe(
                    sp_df,
                    hide_index=True,
                    use_container_width=True,
                    height=min(220, 40 + 35*len(sp_df)),
                )

        # Now render individual game cards
        n_games = len(st.session_state.games)
        for row_i in range(0, n_games, 2):
            gcols = st.columns(2)
            for col_i, g_idx in enumerate(range(row_i, min(row_i+2, n_games))):
                g = st.session_state.games[g_idx]
                home = g.get("home", "HOME")
                away = g.get("away", "AWAY")
                is_dome = norm_team(home) in DOME_PARKS

                coords = STADIUM_COORDS.get(norm_team(home))
                if coords and not is_dome:
                    w = fetch_weather(coords[0], coords[1], g.get("time",""))
                elif is_dome:
                    w = {
                        "temp_f":72, "wind_mph":0, "wind_deg":0, "humidity":50,
                        "precip_pct":0, "condition":"Dome 🏟️"
                    }
                else:
                    w = {
                        "temp_f":70, "wind_mph":5, "wind_deg":180, "humidity":50,
                        "precip_pct":0, "condition":"Unknown"
                    }

                imp_type, imp_label = weather_impact(
                    w["temp_f"], w["wind_mph"], w["wind_deg"],
                    w["precip_pct"], is_dome
                )
                wind_label = deg_to_label(w["wind_deg"]) if not is_dome else "—"

                park_runs = PARK_FACTORS.get(norm_team(home), {"runs":100})["runs"] / 100.0
                hit_score = compute_hitting_env_score(
                    park_runs,
                    w["temp_f"],
                    w["wind_mph"],
                    w["wind_deg"],
                    is_dome,
                    w["precip_pct"],
                )
                hit_tier, hit_label = tier_from_score(hit_score, for_pitcher=False)

                away_opp_total = g["home_total"]
                home_opp_total = g["away_total"]
                away_p_score = compute_pitcher_env_score(
                    park_runs,
                    w["temp_f"],
                    w["wind_mph"],
                    w["wind_deg"],
                    is_dome,
                    w["precip_pct"],
                    away_opp_total,
                )
                home_p_score = compute_pitcher_env_score(
                    park_runs,
                    w["temp_f"],
                    w["wind_mph"],
                    w["wind_deg"],
                    is_dome,
                    w["precip_pct"],
                    home_opp_total,
                )
                away_p_tier, away_p_label = tier_from_score(away_p_score, for_pitcher=True)
                home_p_tier, home_p_label = tier_from_score(home_p_score, for_pitcher=True)

                with gcols[col_i]:
                    st.markdown(f"### {away} @ {home}")
                    st.caption(PARK_NAMES.get(norm_team(home), ""))

                    st.markdown(
                        f"**{w['temp_f']:.0f}°F**  ·  {w['condition']}  ·  "
                        f"{w['wind_mph']:.0f} mph {wind_label}  ·  "
                        f"{w['humidity']}% RH  ·  {w['precip_pct']}% precip"
                    )
                    st.info(imp_label)

                    st.caption(
                        f"Hitting Env Score: {hit_score} · {hit_label}  |  "
                        f"Away SP: {away_p_score} · {away_p_label}  |  "
                        f"Home SP: {home_p_score} · {home_p_label}"
                    )

                    # Moneylines + Total → Implied Team Totals
                    mlc1, mlc2, mlc3 = st.columns([1,1,1.2])
                    away_ml = mlc1.number_input(
                        f"{away} ML",
                        value=float(g.get("away_ml", 0)),
                        step=10.0,
                        format="%0.0f",
                        key=f"aml_{g_idx}"
                    )
                    home_ml = mlc2.number_input(
                        f"{home} ML",
                        value=float(g.get("home_ml", 0)),
                        step=10.0,
                        format="%0.0f",
                        key=f"hml_{g_idx}"
                    )
                    game_total = mlc3.number_input(
                        "Game Total (O/U)",
                        value=float(g.get("ou", 8.5)),
                        step=0.5,
                        format="%0.1f",
                        key=f"tot_{g_idx}"
                    )

                    st.session_state.games[g_idx]["away_ml"] = away_ml
                    st.session_state.games[g_idx]["home_ml"] = home_ml
                    st.session_state.games[g_idx]["ou"]      = game_total

                    if away_ml != 0 and home_ml != 0 and game_total > 0:
                        itt_away, itt_home = implied_totals_from_ml(game_total, home_ml, away_ml)
                        if itt_away is not None and itt_home is not None:
                            st.session_state.games[g_idx]["away_total"] = itt_away
                            st.session_state.games[g_idx]["home_total"] = itt_home
                            st.caption(
                                f"Implied Totals (from ML & O/U): "
                                f"{away} {itt_away} · {home} {itt_home}"
                            )

                    vc1, vc2, vc3 = st.columns([2,1,2])
                    new_at = vc1.number_input(
                        f"{away} total",
                        min_value=0.0, max_value=15.0,
                        value=float(g["away_total"]), step=0.25, key=f"at_{g_idx}"
                    )
                    vc2.write("")
                    vc2.write(f"**O/U {g['ou']}**")
                    new_ht = vc3.number_input(
                        f"{home} total",
                        min_value=0.0, max_value=15.0,
                        value=float(g["home_total"]), step=0.25, key=f"ht_{g_idx}"
                    )
                    st.session_state.games[g_idx]["away_total"] = new_at
                    st.session_state.games[g_idx]["home_total"] = new_ht
# ─────────────────────────────────────────────────────────────────────────────
# TAB 2 — PLAYER POOL
# ─────────────────────────────────────────────────────────────────────────────
with tab_player_pool:  # <- use whatever you called this tab in st.tabs(...)
    st.header("Player Pool")

    if "player_pool" not in st.session_state or st.session_state.player_pool is None:
        st.info("Upload your DraftKings CSV and build the player pool first.")
    else:
        player_pool = st.session_state.player_pool

        # 1) Ownership upload
        st.subheader("Projected Ownership (optional)")

        own_file = st.file_uploader(
            "Upload projected ownership CSV (RG, LineStar, etc.)",
            type=["csv"],
            key="own_upload",
        )

        if own_file is not None:
            own_df = pd.read_csv(own_file)
            # Normalize common column names from different sites
            own_df = own_df.rename(
                columns={
                    "Name": "player_name",
                    "Player": "player_name",
                    "Team": "team",
                    "Tm": "team",
                    "Pos": "position",
                    "Position": "position",
                    "Own": "proj_own",
                    "ProjOwn": "proj_own",
                    "Projected Ownership": "proj_own",
                }
            )
            own_df = own_df[["player_name", "team", "position", "proj_own"]]
        else:
            own_df = None

        # 2) Attach ownership to your player pool
        df = player_pool.copy()

        # TODO: adjust these 4 names to match your columns
        name_col = "player_name"   # e.g. "Name"
        team_col = "team"          # e.g. "TeamAbbrev"
        pos_col = "position"       # e.g. "Position"
        proj_col = "Proj_final"    # your projection column

        if own_df is not None:
            df = df.merge(
                own_df,
                left_on=[name_col, team_col, pos_col],
                right_on=["player_name", "team", "position"],
                how="left",
            )
            df.drop(
                columns=["player_name_y", "team_y", "position_y"],
                errors="ignore",
                inplace=True,
            )
            df.rename(
                columns={
                    "player_name_x": name_col,
                    "team_x": team_col,
                    "position_x": pos_col,
                },
                inplace=True,
            )
        else:
            df["proj_own"] = pd.NA

        df["proj_own"] = pd.to_numeric(df["proj_own"], errors="coerce")

        # 3) Compute leverage
        if proj_col in df.columns:
            max_proj = df[proj_col].max()

            def calc_leverage(row):
                if (
                    pd.isna(row["proj_own"])
                    or row["proj_own"] <= 0
                    or pd.isna(row[proj_col])
                    or max_proj <= 0
                ):
                    return pd.NA
                return (row[proj_col] / max_proj) / (row["proj_own"] / 100.0)

            df["leverage_score"] = df.apply(calc_leverage, axis=1)
        else:
            df["leverage_score"] = pd.NA

        # 4) Display styled table
        show_cols = [
            col
            for col in [
                name_col,
                team_col,
                pos_col,
                "salary",
                proj_col,
                "proj_own",
                "leverage_score",
            ]
            if col in df.columns
        ]

        styled = (
            df[show_cols]
            .style.format(
                {
                    proj_col: "{:.1f}",
                    "proj_own": "{:.1f}",
                    "leverage_score": "{:.2f}",
                }
            )
            .applymap(leverage_color, subset=["leverage_score"])
        )

        st.dataframe(styled, use_container_width=True)
# ─────────────────────────────────────────────────────────────────────────────
# TAB 3 — PROJECTIONS
# ─────────────────────────────────────────────────────────────────────────────
with tab_proj:
    st.subheader("Projection Model")
    st.caption("Final Proj = Base × Park × Wind × Temp × Vegas + BvP + Form")

    df = st.session_state.players
    if df.empty:
        st.info("Upload a DK CSV on the Player Pool tab first.")
    else:
        if st.session_state.games:
            df = build_projections(df, st.session_state.games)
            st.session_state.players = df

        rc1, rc2, rc3 = st.columns([1,1,3])
        pj_pos  = rc1.selectbox("Filter Position", ["All"] + sorted(df["pos"].dropna().unique().tolist()), key="pj_pos")
        pj_team = rc2.selectbox("Filter Team",     ["All"] + sorted(df["team"].dropna().unique().tolist()), key="pj_team")
        pj_sort = rc3.selectbox("Sort", ["Final Proj","Base","Salary","Value"], key="pj_sort")

        if st.button("↺ Recalculate"):
            if st.session_state.games:
                st.session_state.players = build_projections(df, st.session_state.games)
            st.rerun()

        view = df.copy()
        if pj_pos  != "All": view = view[view["pos"] == pj_pos]
        if pj_team != "All": view = view[view["team"] == pj_team]

        sort_col = {"Final Proj":"finalProj","Base":"base","Salary":"sal","Value":"__val2__"}.get(pj_sort,"finalProj")
        if pj_sort == "Value":
            view["__val2__"] = view["finalProj"] / (view["sal"]/1000).replace(0, float("nan"))
        view = view.sort_values(sort_col, ascending=False)

        proj_rows = []
        for _, p in view.iterrows():
            edits = st.session_state.proj_edits.get(p["id"], {})
            proj_rows.append({
                "ID":      p["id"],
                "Pos":     p["pos"],
                "Name":    p["name"],
                "Team":    p["team"],
                "Salary":  p["sal"],
                "Base":    round(edits.get("base", p["avg"]), 2),
                "Park F":  round(p.get("park_f",1.0), 3),
                "Wind F":  round(p.get("wind_f",1.0), 3),
                "Temp F":  round(p.get("temp_f_factor",1.0), 3),
                "Vegas F": round(p.get("vegas_f",1.0), 3),
                "BvP":     round(edits.get("bvp", 0.0), 2),
                "Form":    round(edits.get("form",0.0), 2),
                "Final ▲": round(p.get("finalProj", p["avg"]), 2),
            })
        proj_df = pd.DataFrame(proj_rows)

        edited_proj = st.data_editor(
            proj_df,
            column_config={
                "Base":    st.column_config.NumberColumn("Base",   format="%.1f"),
                "BvP":     st.column_config.NumberColumn("BvP Δ", format="%.1f"),
                "Form":    st.column_config.NumberColumn("Form Δ",format="%.1f"),
                "Salary":  st.column_config.NumberColumn("Salary", format="$%d"),
                "Park F":  st.column_config.NumberColumn("Park",   format="%.3f"),
                "Wind F":  st.column_config.NumberColumn("Wind",   format="%.3f"),
                "Temp F":  st.column_config.NumberColumn("Temp",   format="%.3f"),
                "Vegas F": st.column_config.NumberColumn("Vegas",  format="%.3f"),
                "Final ▲": st.column_config.NumberColumn("Proj",   format="%.2f"),
            },
            disabled=["ID","Pos","Name","Team","Salary","Park F","Wind F","Temp F","Vegas F","Final ▲"],
            hide_index=True,
            use_container_width=True,
            height=520,
            key="proj_editor"
        )

        if edited_proj is not None:
            changed = False
            for _, row in edited_proj.iterrows():
                pid = row["ID"]
                existing = st.session_state.proj_edits.get(pid, {})
                new_edit = {"base": float(row["Base"]), "bvp": float(row["BvP"]), "form": float(row["Form"])}
                if new_edit != existing:
                    st.session_state.proj_edits[pid] = new_edit
                    changed = True
            if changed:
                st.session_state.players = build_projections(st.session_state.players, st.session_state.games)
                st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# TAB 4 — OPTIMIZER
# ─────────────────────────────────────────────────────────────────────────────
with tab_opt:
    st.subheader("Optimizer Settings")

    df = st.session_state.players
    if df.empty:
        st.info("Upload a DK CSV first.")
    else:
        oc1, oc2, oc3 = st.columns(3)

        with oc1:
            st.markdown("**Lineup Generation**")
            n_lineups    = st.number_input("Number of Lineups", min_value=1, max_value=150, value=20, step=1)
            stack_size   = st.selectbox("Stack Size (hitters)", [4,3,5,2,1], index=0)
            min_unique   = st.number_input("Min Unique Players/Lineup", min_value=0, max_value=9, value=3, step=1)
            salary_floor = st.number_input("Salary Floor ($)", min_value=40000, max_value=50000, value=49000, step=100)

        with oc2:
            st.markdown("**Constraints**")
            game_stack   = st.checkbox("Game Stack (SP + Opp Hitters)", value=False)
            noise_level  = st.select_slider("Projection Noise", options=["None","Low","Medium","High"], value="Low")
            noise_map    = {"None":0.0, "Low":0.4, "Medium":1.2, "High":2.5}
            noise_sigma  = noise_map[noise_level]
            max_exp      = st.slider("Max Player Exposure %", min_value=10, max_value=100, value=100, step=5)

        with oc3:
            st.markdown("**Active Constraints**")
            locked   = list(st.session_state.locks)
            excluded = list(st.session_state.excludes)
            lock_names = df[df["id"].isin(locked)]["name"].tolist() if locked else []
            excl_names = df[df["id"].isin(excluded)]["name"].tolist() if excluded else []
            if lock_names:
                st.success(f"🔒 Locked ({len(lock_names)}): {', '.join(lock_names)}")
            else:
                st.caption("🔒 No locked players")
            if excl_names:
                st.error(f"🚫 Excluded ({len(excl_names)}): {', '.join(excl_names[:10])}{'…' if len(excl_names)>10 else ''}")
            else:
                st.caption("🚫 No excluded players")
            active   = df[~df["excluded"]]
            pitchers = active[active["isP"]]
            hitters  = active[~active["isP"]]
            st.caption(f"Pool: {len(active)} active — {len(pitchers)} P / {len(hitters)} hitters")

        st.divider()
        gen_btn = st.button("⚡  Generate Lineups", type="primary", disabled=df.empty)

        if gen_btn:
            if st.session_state.games:
                df = build_projections(df, st.session_state.games)
                st.session_state.players = df

            active = df[~df["excluded"]].copy()
            if len(active) < 10:
                st.error("Not enough active players (need at least 10).")
            else:
                with st.spinner("Optimizing…"):
                    lineups = generate_lineups(
                        active,
                        n_lineups    = n_lineups,
                        stack_size   = stack_size,
                        min_unique   = min_unique,
                        salary_floor = salary_floor,
                        locked_ids   = st.session_state.locks,
                        excluded_ids = st.session_state.excludes,
                        noise_sigma  = noise_sigma,
                        game_stack   = game_stack
                    )

                if max_exp < 100 and lineups:
                    from collections import Counter
                    exp_count = Counter()
                    filtered = []
                    for lu in lineups:
                        ok = all(
                            (exp_count[p["id"]] + 1) / (len(filtered) + 1) * 100 <= max_exp
                            for p in lu["players"]
                        )
                        if ok:
                            for p in lu["players"]:
                                exp_count[p["id"]] += 1
                            filtered.append(lu)
                    lineups = filtered

                st.session_state.lineups = lineups
                if lineups:
                    avg_sal  = sum(l["sal"]  for l in lineups) / len(lineups)
                    avg_proj = sum(l["proj"] for l in lineups) / len(lineups)
                    r1, r2, r3 = st.columns(3)
                    r1.metric("Lineups Generated", len(lineups))
                    r2.metric("Avg Salary",  f"${avg_sal:,.0f}")
                    r3.metric("Avg Proj",    f"{avg_proj:.1f}")
                    st.success("Done! Go to the 📋 Lineups tab to view and export.")
                else:
                    st.error("No valid lineups found. Try relaxing constraints.")

# ─────────────────────────────────────────────────────────────────────────────
# TAB 5 — LINEUPS
# ─────────────────────────────────────────────────────────────────────────────
with tab_lu:
    st.subheader("Generated Lineups")
    lineups = st.session_state.lineups

    if not lineups:
        st.info("No lineups yet. Configure settings in the ⚙️ Optimizer tab and click Generate.")
    else:
        lc1, lc2, lc3, lc4 = st.columns([1,1,1,3])
        lc1.metric("Total Lineups", len(lineups))
        avg_sal  = sum(l["sal"]  for l in lineups) / len(lineups)
        avg_proj = sum(l["proj"] for l in lineups) / len(lineups)
        lc2.metric("Avg Salary",  f"${avg_sal:,.0f}")
        lc3.metric("Avg Proj",    f"{avg_proj:.1f}")

        ORDER = ["P1","P2","C","1B","2B","3B","SS","OF1","OF2","OF3"]

        def build_readable_csv(lineups):
            rows = []
            for i, lu in enumerate(lineups):
                slot_map = {}
                for p in lu["players"]:
                    slot_map[p["slot"]] = p
                row = {"#": i+1}
                for slot in ORDER:
                    p = slot_map.get(slot)
                    row[slot] = f"{p['name']} ({p['team']})" if p else "–"
                row["Salary"] = lu["sal"]
                row["Proj"]   = round(lu["proj"], 1)
                row["Stack"]  = lu["stack"]
                rows.append(row)
            return pd.DataFrame(rows)

        def build_dk_csv(lineups):
            dk_rows = []
            for lu in lineups:
                slot_map = {}
                for p in lu["players"]:
                    slot_map[p["slot"]] = p
                dk_row = {}
                for i, slot in enumerate(ORDER):
                    col = ["P","P","C","1B","2B","3B","SS","OF","OF","OF"][i]
                    p = slot_map.get(slot)
                    dk_row[col if i < 2 else f"{col}_{i}"] = p["id"] if p else ""
                dk_rows.append(dk_row)
            return pd.DataFrame(dk_rows)

        readable_csv = build_readable_csv(lineups).to_csv(index=False).encode()
        dk_csv       = build_dk_csv(lineups).to_csv(index=False).encode()

        ec1, ec2 = lc4.columns(2)
        ec1.download_button("📥 Export Readable CSV", data=readable_csv,
                             file_name="MLB_DFS_Lineups_Readable.csv", mime="text/csv")
        ec2.download_button("🚀 Export DK Upload CSV", data=dk_csv,
                             file_name="MLB_DFS_DKUpload.csv", mime="text/csv")

        display_rows = []
        for i, lu in enumerate(lineups):
            slot_map = {p["slot"]: p for p in lu["players"]}
            row = {"#": i+1}
            labels = ["SP1","SP2","C","1B","2B","3B","SS","OF1","OF2","OF3"]
            for j, slot in enumerate(ORDER):
                p = slot_map.get(slot)
                row[labels[j]] = f"{p['name']}" if p else "–"
            row["Salary"] = f"${lu['sal']:,}"
            row["Proj"]   = round(lu["proj"],1)
            row["Stack"]  = lu["stack"]
            display_rows.append(row)

        st.dataframe(
            pd.DataFrame(display_rows),
            hide_index=True,
            use_container_width=True,
            height=600
        )
