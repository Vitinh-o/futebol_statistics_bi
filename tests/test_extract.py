"""Unit tests for the API-Football ETL transformations and client behavior."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from extract import (  # noqa: E402
    CLUBES_COLUMNS,
    ESTATISTICAS_COLUMNS,
    JOGADORES_COLUMNS,
    PARTIDAS_COLUMNS,
    ApiFootballClient,
    ApiFootballError,
    ExtractionConfig,
    resolve_free_tier_season,
    run_pipeline,
    transform_clubs,
    transform_matches,
    transform_players_and_stats,
)


class TestTransformClubs(unittest.TestCase):
    def test_transforms_and_deduplicates_clubs(self) -> None:
        payload = [
            {
                "team": {
                    "id": 128,
                    "name": " Palmeiras ",
                    "code": "pal",
                    "logo": "https://media.api-sports.io/football/teams/128.png",
                },
                "venue": {"name": "Allianz Parque", "city": "São Paulo"},
            },
            {
                "team": {
                    "id": 127,
                    "name": "Flamengo",
                    "code": None,
                    "logo": "https://media.api-sports.io/football/teams/127.png",
                },
                "venue": {"name": "Maracanã", "city": "Rio de Janeiro"},
            },
        ]

        df = transform_clubs(payload)

        self.assertEqual(list(df.columns), CLUBES_COLUMNS)
        self.assertEqual(len(df), 2)
        self.assertEqual(df["id_clube"].tolist(), [127, 128])
        self.assertEqual(df.loc[df["id_clube"] == 127, "sigla"].item(), "FLA")
        self.assertEqual(df.loc[df["id_clube"] == 128, "sigla"].item(), "PAL")
        self.assertEqual(df.loc[df["id_clube"] == 128, "nome_clube"].item(), "Palmeiras")


class TestTransformMatches(unittest.TestCase):
    def test_splits_finished_and_scheduled_matches_into_two_rows_each(self) -> None:
        payload = [
            {
                "fixture": {
                    "id": 1001,
                    "date": "2026-04-12T00:30:00+00:00",  # 2026-04-11 21:30 BRT
                    "status": {"short": "FT"},
                },
                "league": {"id": 71, "round": "Regular Season - 1"},
                "teams": {"home": {"id": 128}, "away": {"id": 127}},
                "goals": {"home": 2, "away": 1},
            },
            {
                "fixture": {
                    "id": 1002,
                    "date": "2026-04-19T19:00:00+00:00",
                    "status": {"short": "NS"},
                },
                "league": {"id": 71, "round": "Regular Season - 2"},
                "teams": {"home": {"id": 127}, "away": {"id": 128}},
                "goals": {"home": None, "away": None},
            },
        ]

        df = transform_matches(payload)

        self.assertEqual(list(df.columns), PARTIDAS_COLUMNS)
        self.assertEqual(len(df), 4)

        home_ft = df[(df["id_partida"] == 1001) & (df["mando"] == "Mandante")].iloc[0]
        away_ft = df[(df["id_partida"] == 1001) & (df["mando"] == "Visitante")].iloc[0]

        self.assertEqual(home_ft["data_jogo"], "2026-04-11")
        self.assertEqual(home_ft["rodada_num"], 1)
        self.assertEqual(home_ft["pontos"], 3)
        self.assertEqual(home_ft["resultado"], "V")
        self.assertEqual(away_ft["pontos"], 0)
        self.assertEqual(away_ft["resultado"], "D")

        ns_rows = df[df["id_partida"] == 1002]
        self.assertTrue(ns_rows["pontos"].isna().all())
        self.assertTrue(ns_rows["resultado"].isna().all())


class TestTransformPlayersAndStats(unittest.TestCase):
    def test_translates_positions_handles_transfers_and_scales_accuracy(self) -> None:
        payload = [
            {
                "player": {
                    "id": 328,
                    "name": "Hulk",
                    "firstname": "Givanildo",
                    "lastname": "Vieira de Sousa",
                    "age": 39,
                    "nationality": "Brazil",
                    "photo": "https://media.api-sports.io/football/players/328.png",
                },
                "statistics": [
                    {
                        "team": {"id": 131},
                        "league": {"id": 71},
                        "games": {
                            "appearences": 20,
                            "lineups": 19,
                            "minutes": 1700,
                            "position": "Attacker",
                            "rating": "7.456",
                        },
                        "shots": {"total": 80, "on": 35},
                        "goals": {"total": 10, "assists": 6},
                        "passes": {"total": 500, "key": 40, "accuracy": 78},
                        "tackles": {"total": 10, "interceptions": 3},
                        "cards": {"yellow": 4, "yellowred": 1, "red": 1},
                    },
                    {
                        "team": {"id": 128},
                        "league": {"id": 71},
                        "games": {
                            "appearences": 5,
                            "lineups": 4,
                            "minutes": 360,
                            "position": "Midfielder",
                            "rating": None,
                        },
                        "shots": {"total": 12, "on": 5},
                        "goals": {"total": 2, "assists": None},
                        "passes": {"total": 120, "key": 9, "accuracy": None},
                        "tackles": {"total": 4, "interceptions": 1},
                        "cards": {"yellow": 1, "yellowred": 0, "red": 0},
                    },
                    {
                        "team": {"id": 131},
                        "league": {"id": 13},  # Copa Libertadores - must be ignored
                        "games": {"appearences": 10, "minutes": 900, "position": "Attacker"},
                    },
                ],
            }
        ]

        df_players, df_stats = transform_players_and_stats(payload, league_id=71)

        self.assertEqual(list(df_players.columns), JOGADORES_COLUMNS)
        self.assertEqual(list(df_stats.columns), ESTATISTICAS_COLUMNS)

        self.assertEqual(len(df_players), 1)
        self.assertEqual(df_players.loc[0, "nome_completo"], "Givanildo Vieira de Sousa")
        # Uses position from the club with more minutes (1700 > 360)
        self.assertEqual(df_players.loc[0, "posicao"], "Atacante")

        # Transferred player has 1 row per club in Serie A
        self.assertEqual(len(df_stats), 2)
        row_131 = df_stats[df_stats["id_clube"] == 131].iloc[0]
        self.assertAlmostEqual(float(row_131["nota_media"]), 7.46)
        self.assertAlmostEqual(float(row_131["passes_precisao_pct"]), 0.78)
        self.assertEqual(row_131["cartoes_vermelhos"], 2)

        row_128 = df_stats[df_stats["id_clube"] == 128].iloc[0]
        self.assertTrue(pd.isna(row_128["nota_media"]))
        self.assertTrue(pd.isna(row_128["passes_precisao_pct"]))
        self.assertEqual(row_128["assistencias"], 0)


class TestApiFootballClientAndPipeline(unittest.TestCase):
    def test_client_raises_on_api_error_payload(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = {"errors": {"token": "Invalid API key"}}

        with patch("extract.requests.Session.get", return_value=mock_response):
            with ApiFootballClient("bad-key", min_interval_seconds=0.0) as client:
                with self.assertRaises(ApiFootballError):
                    client.fetch_teams(71, 2026)

    def test_run_pipeline_writes_four_expected_csvs(self) -> None:
        responses = [
            {"response": [{"team": {"id": 128, "name": "Palmeiras", "code": "PAL"}, "venue": {}}]},
            {
                "response": [
                    {
                        "fixture": {
                            "id": 1,
                            "date": "2026-04-15T21:00:00+00:00",
                            "status": {"short": "FT"},
                        },
                        "league": {"id": 71, "round": "Regular Season - 1"},
                        "teams": {"home": {"id": 128}, "away": {"id": 127}},
                        "goals": {"home": 1, "away": 1},
                    }
                ]
            },
            {
                "paging": {"current": 1, "total": 1},
                "response": [
                    {
                        "player": {"id": 10, "name": "Dudu", "age": 34, "nationality": "Brazil"},
                        "statistics": [
                            {
                                "team": {"id": 128},
                                "league": {"id": 71},
                                "games": {"appearences": 1, "minutes": 90, "position": "Attacker"},
                                "goals": {"total": 1, "assists": 0},
                                "shots": {"total": 3, "on": 2},
                                "passes": {"total": 30, "key": 2, "accuracy": 85},
                                "tackles": {"total": 1, "interceptions": 0},
                                "cards": {"yellow": 0, "yellowred": 0, "red": 0},
                            }
                        ],
                    }
                ],
            },
        ]

        mock_http_responses = []
        for payload in responses:
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {}
            resp.json.return_value = payload
            mock_http_responses.append(resp)

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir)
            with patch("extract.requests.Session.get", side_effect=mock_http_responses):
                outputs = run_pipeline(
                    ExtractionConfig(
                        api_key="test-key",
                        season=2026,
                        output_dir=out_dir,
                        min_interval_seconds=0.0,
                    )
                )

            for path in outputs.values():
                self.assertTrue(path.exists(), f"Expected CSV {path} to exist")

            self.assertEqual(len(pd.read_csv(outputs["partidas"])), 2)

    def test_resolve_free_tier_season_uses_two_year_offset(self) -> None:
        self.assertEqual(resolve_free_tier_season(2026), 2024)
        self.assertEqual(resolve_free_tier_season(2027), 2025)

    def test_fetch_players_respects_free_tier_max_three_pages(self) -> None:
        page_responses = []
        for page_num in range(1, 5):
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {}
            resp.json.return_value = {
                "paging": {"current": page_num, "total": 35},
                "response": [{"player": {"id": page_num}}],
            }
            page_responses.append(resp)

        with patch("extract.requests.Session.get", side_effect=page_responses) as mock_get:
            with ApiFootballClient("test-key", min_interval_seconds=0.0) as client:
                players = client.fetch_players(71, 2024)

        self.assertEqual(mock_get.call_count, 3)
        self.assertEqual([p["player"]["id"] for p in players], [1, 2, 3])

    def test_fetch_players_by_teams_and_deduplicates_transferred_stats(self) -> None:
        team_128_resp = MagicMock()
        team_128_resp.status_code = 200
        team_128_resp.headers = {}
        team_128_resp.json.return_value = {
            "paging": {"current": 1, "total": 1},
            "response": [
                {
                    "player": {"id": 50, "name": "Atleta X"},
                    "statistics": [
                        {
                            "team": {"id": 128},
                            "league": {"id": 71},
                            "games": {"appearences": 10, "minutes": 800, "position": "Attacker"},
                            "goals": {"total": 4, "assists": 2},
                        },
                        {
                            "team": {"id": 127},
                            "league": {"id": 71},
                            "games": {"appearences": 5, "minutes": 300, "position": "Attacker"},
                            "goals": {"total": 1, "assists": 1},
                        },
                    ],
                }
            ],
        }

        team_127_resp = MagicMock()
        team_127_resp.status_code = 200
        team_127_resp.headers = {}
        team_127_resp.json.return_value = team_128_resp.json.return_value

        with patch(
            "extract.requests.Session.get", side_effect=[team_128_resp, team_127_resp]
        ) as mock_get:
            with ApiFootballClient("test-key", min_interval_seconds=0.0) as client:
                players_raw = client.fetch_players_by_teams(71, 2024, [127, 128])

        self.assertEqual(mock_get.call_count, 2)
        _, df_stats = transform_players_and_stats(players_raw, league_id=71)
        # Must NOT double-count stats returned by both team queries
        self.assertEqual(len(df_stats), 2)
        self.assertEqual(int(df_stats.loc[df_stats["id_clube"] == 128, "gols"].item()), 4)
        self.assertEqual(int(df_stats.loc[df_stats["id_clube"] == 127, "gols"].item()), 1)


if __name__ == "__main__":
    unittest.main()
