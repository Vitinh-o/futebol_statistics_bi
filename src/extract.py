"""ETL pipeline for Brasileirão Série A (API-Football v3 -> Star Schema CSVs).

Extracts clubs, matches, player profiles, and season player statistics from
API-Football (`league_id = 71`) while respecting free-tier rate limits, and
outputs normalized CSV files into `/data` matching the Power BI Star Schema
contract defined in `README.md`.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import os
from pathlib import Path
import re
import time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
import requests

LOGGER = logging.getLogger("bi_futebol.extract")

DEFAULT_BASE_URL = "https://v3.football.api-sports.io"
DEFAULT_LEAGUE_ID = 71
DEFAULT_MIN_INTERVAL_SECONDS = 6.5  # Safe for free-tier 10 req/min limit
DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_RETRIES = 4

FINISHED_STATUSES = frozenset({"FT", "AET", "PEN"})

POSITION_TRANSLATIONS: dict[str, str] = {
    "Goalkeeper": "Goleiro",
    "Defender": "Defensor",
    "Midfielder": "Meio-Campo",
    "Attacker": "Atacante",
}

CLUBES_COLUMNS = [
    "id_clube",
    "nome_clube",
    "sigla",
    "escudo_url",
    "estadio",
    "cidade",
]

JOGADORES_COLUMNS = [
    "id_jogador",
    "nome_jogador",
    "nome_completo",
    "idade",
    "nacionalidade",
    "posicao",
    "foto_url",
]

PARTIDAS_COLUMNS = [
    "id_partida",
    "rodada_num",
    "data_jogo",
    "id_clube",
    "id_adversario",
    "mando",
    "status_jogo",
    "gols_pro",
    "gols_contra",
    "pontos",
    "resultado",
]

ESTATISTICAS_COLUMNS = [
    "id_jogador",
    "id_clube",
    "jogos",
    "titularidades",
    "minutos_jogados",
    "nota_media",
    "gols",
    "assistencias",
    "finalizacoes_total",
    "finalizacoes_no_gol",
    "passes_total",
    "passes_precisao_pct",
    "passes_chave",
    "desarmes",
    "interceptacoes",
    "cartoes_amarelos",
    "cartoes_vermelhos",
]

_ROUND_NUMBER_RE = re.compile(r"(\d+)\s*$")

try:
    BRT_TIMEZONE: timezone | ZoneInfo = ZoneInfo("America/Sao_Paulo")
except ZoneInfoNotFoundError:
    # Windows Python environments without the `tzdata` package fall back to UTC-3.
    BRT_TIMEZONE = timezone(timedelta(hours=-3))


class ApiFootballError(RuntimeError):
    """Raised when the API-Football service returns an unrecoverable error."""


@dataclass(frozen=True, slots=True)
class ExtractionConfig:
    """Runtime configuration for the API-Football extraction pipeline."""

    api_key: str
    league_id: int = DEFAULT_LEAGUE_ID
    season: int | None = None
    output_dir: Path = Path(__file__).resolve().parent.parent / "data"
    base_url: str = DEFAULT_BASE_URL
    min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS


class ApiFootballClient:
    """Rate-limit-aware HTTP client for API-Football v3."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not api_key or not api_key.strip():
            raise ValueError("API_FOOTBALL_KEY must be a non-empty string.")

        self._base_url = base_url.rstrip("/")
        self._min_interval = max(0.0, min_interval_seconds)
        self._timeout = timeout_seconds
        self._last_request_ts = 0.0
        self._session = requests.Session()
        self._session.headers.update(
            {
                "x-apisports-key": api_key.strip(),
                "Accept": "application/json",
            }
        )

    def __enter__(self) -> ApiFootballClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self._session.close()

    def _throttle(self) -> None:
        if self._min_interval <= 0:
            return
        elapsed = time.monotonic() - self._last_request_ts
        remaining = self._min_interval - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self._base_url}/{endpoint.lstrip('/')}"

        for attempt in range(1, MAX_RETRIES + 1):
            self._throttle()
            self._last_request_ts = time.monotonic()

            try:
                response = self._session.get(url, params=params, timeout=self._timeout)
            except requests.RequestException as exc:
                if attempt == MAX_RETRIES:
                    raise ApiFootballError(
                        f"Network failure calling {endpoint} after {MAX_RETRIES} attempts: {exc}"
                    ) from exc
                wait_seconds = 2.0**attempt
                LOGGER.warning(
                    "Request error on %s (attempt %d/%d): %s. Retrying in %.1fs.",
                    endpoint,
                    attempt,
                    MAX_RETRIES,
                    exc,
                    wait_seconds,
                )
                time.sleep(wait_seconds)
                continue

            if response.status_code == 429 or response.status_code >= 500:
                if attempt == MAX_RETRIES:
                    raise ApiFootballError(
                        f"HTTP {response.status_code} calling {endpoint}: {response.text}"
                    )
                retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                wait_seconds = retry_after if retry_after is not None else max(15.0, 2.0**attempt)
                LOGGER.warning(
                    "HTTP %d on %s (attempt %d/%d). Waiting %.1fs before retry.",
                    response.status_code,
                    endpoint,
                    attempt,
                    MAX_RETRIES,
                    wait_seconds,
                )
                time.sleep(wait_seconds)
                continue

            if response.status_code >= 400:
                raise ApiFootballError(
                    f"HTTP {response.status_code} calling {endpoint}: {response.text}"
                )

            payload: dict[str, Any] = response.json()
            errors = payload.get("errors")
            if errors:
                if _is_rate_limit_error(errors) and attempt < MAX_RETRIES:
                    wait_seconds = max(60.0, self._min_interval * 2)
                    LOGGER.warning(
                        "API rate limit message on %s (attempt %d/%d): %s. Sleeping %.1fs.",
                        endpoint,
                        attempt,
                        MAX_RETRIES,
                        errors,
                        wait_seconds,
                    )
                    time.sleep(wait_seconds)
                    continue
                raise ApiFootballError(f"API-Football error on {endpoint}: {errors}")

            remaining_day = response.headers.get("x-ratelimit-requests-remaining")
            if remaining_day is not None:
                LOGGER.debug("API daily quota remaining: %s", remaining_day)

            return payload

        raise ApiFootballError(f"Exhausted retries calling {endpoint}.")

    def _get_paginated(self, endpoint: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        all_items: list[dict[str, Any]] = []
        page = 1
        total_pages = 1

        while page <= total_pages:
            page_params = {**params, "page": page}
            payload = self._get(endpoint, params=page_params)
            items = payload.get("response") or []
            all_items.extend(items)

            paging = payload.get("paging") or {}
            total_pages = int(paging.get("total") or 1)
            LOGGER.info(
                "Fetched %s page %d/%d (%d records).",
                endpoint,
                page,
                total_pages,
                len(items),
            )
            page += 1

        return all_items

    def fetch_current_season(self, league_id: int) -> int:
        """Discover the current active season for a given league ID."""
        payload = self._get("leagues", params={"id": league_id, "current": "true"})
        entries = payload.get("response") or []
        for entry in entries:
            for season_info in entry.get("seasons") or []:
                if season_info.get("current") and season_info.get("year") is not None:
                    return int(season_info["year"])

        # Fallback if `current=true` returns season metadata without the current flag set
        if entries:
            seasons = entries[0].get("seasons") or []
            years = [int(s["year"]) for s in seasons if s.get("year") is not None]
            if years:
                return max(years)

        raise ApiFootballError(f"Could not determine active season for league_id={league_id}.")

    def fetch_teams(self, league_id: int, season: int) -> list[dict[str, Any]]:
        """Fetch all teams registered in the league/season."""
        payload = self._get("teams", params={"league": league_id, "season": season})
        items: list[dict[str, Any]] = payload.get("response") or []
        LOGGER.info("Fetched %d teams for league=%d season=%d.", len(items), league_id, season)
        return items

    def fetch_fixtures(self, league_id: int, season: int) -> list[dict[str, Any]]:
        """Fetch all fixtures for the league/season."""
        payload = self._get("fixtures", params={"league": league_id, "season": season})
        items: list[dict[str, Any]] = payload.get("response") or []
        LOGGER.info("Fetched %d fixtures for league=%d season=%d.", len(items), league_id, season)
        return items

    def fetch_players(self, league_id: int, season: int) -> list[dict[str, Any]]:
        """Fetch all paginated player records for the league/season."""
        items = self._get_paginated("players", params={"league": league_id, "season": season})
        LOGGER.info(
            "Fetched %d total player entries for league=%d season=%d.",
            len(items),
            league_id,
            season,
        )
        return items


def _parse_retry_after(header_value: str | None) -> float | None:
    if not header_value:
        return None
    try:
        return max(0.0, float(header_value))
    except ValueError:
        return None


def _is_rate_limit_error(errors: Any) -> bool:
    if isinstance(errors, dict):
        text = " ".join(f"{k} {v}" for k, v in errors.items()).lower()
    elif isinstance(errors, list):
        text = " ".join(str(item) for item in errors).lower()
    else:
        text = str(errors).lower()
    return "ratelimit" in text or "rate limit" in text or "too many requests" in text


def _clean_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _to_int_or_zero(value: Any) -> int:
    if value is None or value == "":
        return 0
    return int(value)


def _to_nullable_int(value: Any) -> int | pd.NA.__class__:
    if value is None or value == "":
        return pd.NA
    return int(value)


def _to_nullable_float(value: Any, *, decimals: int = 2) -> float | pd.NA.__class__:
    if value is None or value == "":
        return pd.NA
    try:
        return round(float(value), decimals)
    except (TypeError, ValueError):
        return pd.NA


def _normalize_pass_accuracy(value: Any) -> float | pd.NA.__class__:
    """Convert API-Football pass accuracy (0-100 scale) into 0.0-1.0 decimal."""
    if value is None or value == "":
        return pd.NA
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return pd.NA
    clamped = min(max(numeric / 100.0, 0.0), 1.0)
    return round(clamped, 4)


def _parse_round_number(round_label: Any) -> int | pd.NA.__class__:
    if not round_label:
        return pd.NA
    match = _ROUND_NUMBER_RE.search(str(round_label).strip())
    return int(match.group(1)) if match else pd.NA


def _parse_brt_date(iso_timestamp: Any) -> str | pd.NA.__class__:
    if not iso_timestamp:
        return pd.NA
    raw = str(iso_timestamp).strip()
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return raw[:10] if len(raw) >= 10 else pd.NA
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BRT_TIMEZONE).date().isoformat()


def _translate_position(raw_position: Any) -> str:
    pos = _clean_str(raw_position)
    if not pos:
        return "Desconhecido"
    return POSITION_TRANSLATIONS.get(pos, pos)


def transform_clubs(teams_payload: list[dict[str, Any]]) -> pd.DataFrame:
    """Transform `/teams` response items into the `dClubes` schema."""
    rows: list[dict[str, Any]] = []
    for item in teams_payload:
        team = item.get("team") or {}
        venue = item.get("venue") or {}
        team_id = team.get("id")
        if team_id is None:
            continue

        name = _clean_str(team.get("name"))
        code = _clean_str(team.get("code")).upper()
        if not code and name:
            code = re.sub(r"[^A-Za-z]", "", name)[:3].upper()

        rows.append(
            {
                "id_clube": int(team_id),
                "nome_clube": name,
                "sigla": code,
                "escudo_url": _clean_str(team.get("logo")),
                "estadio": _clean_str(venue.get("name")),
                "cidade": _clean_str(venue.get("city")),
            }
        )

    if not rows:
        return pd.DataFrame(columns=CLUBES_COLUMNS).astype({"id_clube": "Int64"})

    df = pd.DataFrame(rows, columns=CLUBES_COLUMNS)
    df = df.drop_duplicates(subset=["id_clube"], keep="last")
    df["id_clube"] = df["id_clube"].astype("Int64")
    return df.sort_values("id_clube").reset_index(drop=True)


def transform_matches(fixtures_payload: list[dict[str, Any]]) -> pd.DataFrame:
    """Transform `/fixtures` response into `fPartidas` (2 rows per match)."""
    rows: list[dict[str, Any]] = []

    for item in fixtures_payload:
        fixture = item.get("fixture") or {}
        league = item.get("league") or {}
        teams = item.get("teams") or {}
        goals = item.get("goals") or {}
        status = (fixture.get("status") or {}).get("short")

        fixture_id = fixture.get("id")
        home_team = teams.get("home") or {}
        away_team = teams.get("away") or {}
        home_id = home_team.get("id")
        away_id = away_team.get("id")

        if fixture_id is None or home_id is None or away_id is None:
            continue

        round_num = _parse_round_number(league.get("round"))
        match_date = _parse_brt_date(fixture.get("date"))
        status_code = _clean_str(status) or "NS"
        home_goals = _to_nullable_int(goals.get("home"))
        away_goals = _to_nullable_int(goals.get("away"))

        is_finished = (
            status_code in FINISHED_STATUSES
            and home_goals is not pd.NA
            and away_goals is not pd.NA
        )

        match_sides = (
            ("Mandante", int(home_id), int(away_id), home_goals, away_goals),
            ("Visitante", int(away_id), int(home_id), away_goals, home_goals),
        )

        for mando, club_id, opponent_id, goals_for, goals_against in match_sides:
            if is_finished:
                if goals_for > goals_against:
                    points, result = 3, "V"
                elif goals_for == goals_against:
                    points, result = 1, "E"
                else:
                    points, result = 0, "D"
            else:
                points, result = pd.NA, pd.NA

            rows.append(
                {
                    "id_partida": int(fixture_id),
                    "rodada_num": round_num,
                    "data_jogo": match_date,
                    "id_clube": club_id,
                    "id_adversario": opponent_id,
                    "mando": mando,
                    "status_jogo": status_code,
                    "gols_pro": goals_for,
                    "gols_contra": goals_against,
                    "pontos": points,
                    "resultado": result,
                }
            )

    if not rows:
        return pd.DataFrame(columns=PARTIDAS_COLUMNS).astype(
            {
                "id_partida": "Int64",
                "rodada_num": "Int64",
                "id_clube": "Int64",
                "id_adversario": "Int64",
                "gols_pro": "Int64",
                "gols_contra": "Int64",
                "pontos": "Int64",
            }
        )

    df = pd.DataFrame(rows, columns=PARTIDAS_COLUMNS)
    df = df.drop_duplicates(subset=["id_partida", "id_clube"], keep="last")
    int_cols = [
        "id_partida",
        "rodada_num",
        "id_clube",
        "id_adversario",
        "gols_pro",
        "gols_contra",
        "pontos",
    ]
    for col in int_cols:
        df[col] = df[col].astype("Int64")

    return df.sort_values(["rodada_num", "data_jogo", "id_partida", "mando"]).reset_index(
        drop=True
    )


def transform_players_and_stats(
    players_payload: list[dict[str, Any]],
    *,
    league_id: int = DEFAULT_LEAGUE_ID,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Transform `/players` response into (`dJogadores`, `fEstatisticasJogador`)."""
    player_records: dict[int, dict[str, Any]] = {}
    player_best_minutes: dict[int, int] = {}
    stats_rows: list[dict[str, Any]] = []

    for entry in players_payload:
        player = entry.get("player") or {}
        player_id = player.get("id")
        if player_id is None:
            continue
        pid = int(player_id)

        short_name = _clean_str(player.get("name"))
        first_name = _clean_str(player.get("firstname"))
        last_name = _clean_str(player.get("lastname"))
        full_name = " ".join(part for part in (first_name, last_name) if part) or short_name

        for stat in entry.get("statistics") or []:
            stat_league_id = (stat.get("league") or {}).get("id")
            if stat_league_id is not None and int(stat_league_id) != league_id:
                continue

            team = stat.get("team") or {}
            team_id = team.get("id")
            if team_id is None:
                continue

            games = stat.get("games") or {}
            shots = stat.get("shots") or {}
            goals = stat.get("goals") or {}
            passes = stat.get("passes") or {}
            tackles = stat.get("tackles") or {}
            cards = stat.get("cards") or {}

            minutes = _to_int_or_zero(games.get("minutes"))
            translated_pos = _translate_position(games.get("position"))

            if pid not in player_records or minutes >= player_best_minutes.get(pid, -1):
                player_best_minutes[pid] = minutes
                player_records[pid] = {
                    "id_jogador": pid,
                    "nome_jogador": short_name,
                    "nome_completo": full_name,
                    "idade": _to_nullable_int(player.get("age")),
                    "nacionalidade": _clean_str(player.get("nationality")),
                    "posicao": translated_pos,
                    "foto_url": _clean_str(player.get("photo")),
                }

            red_cards = _to_int_or_zero(cards.get("red")) + _to_int_or_zero(
                cards.get("yellowred")
            )

            stats_rows.append(
                {
                    "id_jogador": pid,
                    "id_clube": int(team_id),
                    "jogos": _to_int_or_zero(games.get("appearences")),
                    "titularidades": _to_int_or_zero(games.get("lineups")),
                    "minutos_jogados": minutes,
                    "nota_media": _to_nullable_float(games.get("rating"), decimals=2),
                    "gols": _to_int_or_zero(goals.get("total")),
                    "assistencias": _to_int_or_zero(goals.get("assists")),
                    "finalizacoes_total": _to_int_or_zero(shots.get("total")),
                    "finalizacoes_no_gol": _to_int_or_zero(shots.get("on")),
                    "passes_total": _to_int_or_zero(passes.get("total")),
                    "passes_precisao_pct": _normalize_pass_accuracy(passes.get("accuracy")),
                    "passes_chave": _to_int_or_zero(passes.get("key")),
                    "desarmes": _to_int_or_zero(tackles.get("total")),
                    "interceptacoes": _to_int_or_zero(tackles.get("interceptions")),
                    "cartoes_amarelos": _to_int_or_zero(cards.get("yellow")),
                    "cartoes_vermelhos": red_cards,
                }
            )

    if not player_records:
        df_players = pd.DataFrame(columns=JOGADORES_COLUMNS).astype(
            {"id_jogador": "Int64", "idade": "Int64"}
        )
    else:
        df_players = pd.DataFrame(list(player_records.values()), columns=JOGADORES_COLUMNS)
        df_players["id_jogador"] = df_players["id_jogador"].astype("Int64")
        df_players["idade"] = df_players["idade"].astype("Int64")
        df_players = df_players.sort_values("id_jogador").reset_index(drop=True)

    stats_int_cols = [
        "id_jogador",
        "id_clube",
        "jogos",
        "titularidades",
        "minutos_jogados",
        "gols",
        "assistencias",
        "finalizacoes_total",
        "finalizacoes_no_gol",
        "passes_total",
        "passes_chave",
        "desarmes",
        "interceptacoes",
        "cartoes_amarelos",
        "cartoes_vermelhos",
    ]

    if not stats_rows:
        df_stats = pd.DataFrame(columns=ESTATISTICAS_COLUMNS).astype(
            {
                **{col: "Int64" for col in stats_int_cols},
                "nota_media": "Float64",
                "passes_precisao_pct": "Float64",
            }
        )
    else:
        df_stats = pd.DataFrame(stats_rows, columns=ESTATISTICAS_COLUMNS)
        # Ensure strict (id_jogador, id_clube) uniqueness per season grain
        if df_stats.duplicated(subset=["id_jogador", "id_clube"]).any():
            sum_cols = [
                col
                for col in stats_int_cols
                if col not in ("id_jogador", "id_clube")
            ]
            agg_spec: dict[str, str] = {col: "sum" for col in sum_cols}
            agg_spec["nota_media"] = "mean"
            agg_spec["passes_precisao_pct"] = "mean"
            df_stats = (
                df_stats.groupby(["id_jogador", "id_clube"], as_index=False)
                .agg(agg_spec)
                .reindex(columns=ESTATISTICAS_COLUMNS)
            )
            df_stats["nota_media"] = df_stats["nota_media"].round(2)
            df_stats["passes_precisao_pct"] = df_stats["passes_precisao_pct"].round(4)

        for col in stats_int_cols:
            df_stats[col] = df_stats[col].astype("Int64")
        df_stats["nota_media"] = df_stats["nota_media"].astype("Float64")
        df_stats["passes_precisao_pct"] = df_stats["passes_precisao_pct"].astype("Float64")
        df_stats = df_stats.sort_values(["id_clube", "id_jogador"]).reset_index(drop=True)

    return df_players, df_stats


def save_csv_atomically(df: pd.DataFrame, target_path: Path) -> None:
    """Write DataFrame as UTF-8 CSV via temporary file rename to avoid partial writes."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target_path.with_suffix(".csv.tmp")
    df.to_csv(tmp_path, index=False, encoding="utf-8")
    tmp_path.replace(target_path)
    LOGGER.info("Saved %s (%d rows).", target_path, len(df))


def run_pipeline(config: ExtractionConfig) -> dict[str, Path]:
    """Execute end-to-end extraction, transformation, and CSV persistence."""
    with ApiFootballClient(
        config.api_key,
        base_url=config.base_url,
        min_interval_seconds=config.min_interval_seconds,
        timeout_seconds=config.timeout_seconds,
    ) as client:
        season = config.season or client.fetch_current_season(config.league_id)
        LOGGER.info("Running extraction for league_id=%d, season=%d.", config.league_id, season)

        teams_raw = client.fetch_teams(config.league_id, season)
        fixtures_raw = client.fetch_fixtures(config.league_id, season)
        players_raw = client.fetch_players(config.league_id, season)

    df_clubes = transform_clubs(teams_raw)
    df_partidas = transform_matches(fixtures_raw)
    df_jogadores, df_estatisticas = transform_players_and_stats(
        players_raw,
        league_id=config.league_id,
    )

    outputs = {
        "clubes": config.output_dir / "clubes.csv",
        "partidas": config.output_dir / "partidas.csv",
        "jogadores": config.output_dir / "jogadores.csv",
        "estatisticas_jogadores": config.output_dir / "estatisticas_jogadores.csv",
    }

    save_csv_atomically(df_clubes, outputs["clubes"])
    save_csv_atomically(df_partidas, outputs["partidas"])
    save_csv_atomically(df_jogadores, outputs["jogadores"])
    save_csv_atomically(df_estatisticas, outputs["estatisticas_jogadores"])

    return outputs


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for local runs and GitHub Actions workflows."""
    parser = argparse.ArgumentParser(
        description="Extract Brasileirão Série A data from API-Football v3 to CSV."
    )
    parser.add_argument(
        "--league-id",
        type=int,
        default=int(os.getenv("LEAGUE_ID", DEFAULT_LEAGUE_ID)),
        help="API-Football league ID (default: 71 - Brasileirão Série A).",
    )
    parser.add_argument(
        "--season",
        type=int,
        default=int(os.environ["SEASON"]) if os.getenv("SEASON") else None,
        help="Target season year (e.g., 2026). Auto-detected if omitted.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "data",
        help="Destination directory for generated CSV files.",
    )
    parser.add_argument(
        "--min-interval",
        type=float,
        default=float(os.getenv("API_MIN_INTERVAL_SECONDS", DEFAULT_MIN_INTERVAL_SECONDS)),
        help="Minimum delay in seconds between API calls (default: 6.5).",
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("LOG_LEVEL", "INFO"),
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity level.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    api_key = os.getenv("API_FOOTBALL_KEY", "").strip()
    if not api_key:
        LOGGER.error(
            "Environment variable API_FOOTBALL_KEY is not set. "
            "Configure it in GitHub Secrets or your local environment before running."
        )
        return 1

    config = ExtractionConfig(
        api_key=api_key,
        league_id=args.league_id,
        season=args.season,
        output_dir=args.output_dir,
        min_interval_seconds=args.min_interval,
    )

    try:
        run_pipeline(config)
    except ApiFootballError as exc:
        LOGGER.error("Extraction aborted: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
