"""Idempotent PBIR layout, styling, SVG background, and visual builder script.

Applies the Brasileirão Série A 2024 Design System (1280x720 canvas, 180px dark
SVG sidebar + native Page Navigator, Pitch Emerald #059669 / Royal Cobalt #2563EB)
to `powerbi/estatisticas_de_futebol.Report`.

Preserves existing visual IDs and user-configured bindings while populating
empty visuals (Pages 3 & 4), adding missing slicers, headers, and navigation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPORT_DIR = Path(__file__).resolve().parent.parent / "powerbi" / "estatisticas_de_futebol.Report"
DEF_DIR = REPORT_DIR / "definition"
PAGES_DIR = DEF_DIR / "pages"
REPORT_JSON = DEF_DIR / "report.json"

THEME_FILE = "brasileirao_theme.json"
BG_SVG_FILE = "brasileirao_bg_1280x720.svg"

VISUAL_SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/item/report/"
    "definition/visualContainer/2.15.0/schema.json"
)
PAGE_SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/item/report/"
    "definition/page/2.1.0/schema.json"
)

# Existing Page IDs
P1_ID = "e9568cd067775bb6d437"
P2_ID = "8aedbb50b3e1fe4653e3"
P3_ID = "4a9274aecd373fcb645c"
P4_ID = "6d397177228ad86fa091"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def lit(val: str) -> dict[str, Any]:
    return {"expr": {"Literal": {"Value": val}}}


def solid(hex_color: str) -> dict[str, Any]:
    return {"solid": {"color": lit(f"'{hex_color}'")}}


def col_field(entity: str, prop: str) -> dict[str, Any]:
    return {
        "Column": {
            "Expression": {"SourceRef": {"Entity": entity}},
            "Property": prop,
        }
    }


def meas_field(entity: str, prop: str) -> dict[str, Any]:
    return {
        "Measure": {
            "Expression": {"SourceRef": {"Entity": entity}},
            "Property": prop,
        }
    }


def col_proj(entity: str, prop: str, *, active: bool = False) -> dict[str, Any]:
    proj: dict[str, Any] = {
        "field": col_field(entity, prop),
        "queryRef": f"{entity}.{prop}",
        "nativeQueryRef": prop,
    }
    if active:
        proj["active"] = True
    return proj


def meas_proj(entity: str, prop: str) -> dict[str, Any]:
    return {
        "field": meas_field(entity, prop),
        "queryRef": f"{entity}.{prop}",
        "nativeQueryRef": prop,
    }


def make_position(
    x: float,
    y: float,
    width: float,
    height: float,
    z: int,
    tab_order: int | None = None,
) -> dict[str, Any]:
    return {
        "x": x,
        "y": y,
        "z": z,
        "height": height,
        "width": width,
        "tabOrder": tab_order if tab_order is not None else z,
    }


def set_container_title(
    visual_data: dict[str, Any],
    title: str,
    subtitle: str | None = None,
) -> None:
    vco = visual_data["visual"].setdefault("visualContainerObjects", {})
    vco["title"] = [
        {
            "properties": {
                "show": lit("true"),
                "text": lit(f"'{title}'"),
                "fontFamily": lit("'Segoe UI'"),
                "fontSize": lit("10.5D"),
                "bold": lit("true"),
                "fontColor": solid("#0F172A"),
            }
        }
    ]
    if subtitle:
        vco["subTitle"] = [
            {
                "properties": {
                    "show": lit("true"),
                    "text": lit(f"'{subtitle}'"),
                    "fontFamily": lit("'Segoe UI'"),
                    "fontSize": lit("8.5D"),
                    "fontColor": solid("#64748B"),
                }
            }
        ]


def make_categorical_filter(
    name: str, entity: str, prop: str, values: list[str]
) -> dict[str, Any]:
    alias = entity[0].lower()
    return {
        "name": name,
        "field": col_field(entity, prop),
        "type": "Categorical",
        "filter": {
            "Version": 2,
            "From": [{"Name": alias, "Entity": entity, "Type": 0}],
            "Where": [
                {
                    "Condition": {
                        "In": {
                            "Expressions": [
                                {
                                    "Column": {
                                        "Expression": {"SourceRef": {"Source": alias}},
                                        "Property": prop,
                                    }
                                }
                            ],
                            "Values": [[{"Literal": {"Value": f"'{v}'"}}] for v in values],
                        }
                    }
                }
            ],
        },
    }


def make_topn_filter(
    name: str,
    entity: str,
    prop: str,
    measure_entity: str,
    measure_prop: str,
    top_n: int,
) -> dict[str, Any]:
    return {
        "name": name,
        "field": col_field(entity, prop),
        "type": "TopN",
        "filter": {
            "Version": 2,
            "From": [
                {
                    "Name": "subquery",
                    "Expression": {
                        "Subquery": {
                            "Query": {
                                "Version": 2,
                                "From": [
                                    {"Name": "d1", "Entity": entity, "Type": 0},
                                    {"Name": "_", "Entity": measure_entity, "Type": 0},
                                ],
                                "Select": [
                                    {
                                        "Column": {
                                            "Expression": {"SourceRef": {"Source": "d1"}},
                                            "Property": prop,
                                        },
                                        "Name": "field",
                                    }
                                ],
                                "OrderBy": [
                                    {
                                        "Direction": 2,
                                        "Expression": {
                                            "Measure": {
                                                "Expression": {"SourceRef": {"Source": "_"}},
                                                "Property": measure_prop,
                                            }
                                        },
                                    }
                                ],
                                "Top": top_n,
                            }
                        }
                    },
                    "Type": 2,
                },
                {"Name": "d1", "Entity": entity, "Type": 0},
            ],
            "Where": [
                {
                    "Condition": {
                        "In": {
                            "Expressions": [
                                {
                                    "Column": {
                                        "Expression": {"SourceRef": {"Source": "d1"}},
                                        "Property": prop,
                                    }
                                }
                            ],
                            "Table": {"SourceRef": {"Source": "subquery"}},
                        }
                    }
                }
            ],
        },
    }


def build_page_navigator(visual_id: str) -> dict[str, Any]:
    return {
        "$schema": VISUAL_SCHEMA,
        "name": visual_id,
        "position": make_position(12, 114, 156, 212, z=5000, tab_order=5000),
        "visual": {
            "visualType": "pageNavigator",
            "objects": {
                "layout": [
                    {
                        "properties": {
                            "orientation": lit("1L"),
                            "cellPadding": lit("8L"),
                        }
                    }
                ]
            },
            "drillFilterOtherVisuals": True,
        },
    }


def build_header_textbox(
    visual_id: str,
    title: str,
    subtitle: str,
    width: float = 560,
) -> dict[str, Any]:
    return {
        "$schema": VISUAL_SCHEMA,
        "name": visual_id,
        "position": make_position(200, 12, width, 64, z=100, tab_order=100),
        "visual": {
            "visualType": "textbox",
            "objects": {
                "general": [
                    {
                        "properties": {
                            "paragraphs": [
                                {
                                    "textRuns": [
                                        {
                                            "value": title,
                                            "textStyle": {
                                                "fontFamily": "Segoe UI",
                                                "fontSize": "18pt",
                                                "fontWeight": "bold",
                                                "color": "#0F172A",
                                            },
                                        }
                                    ]
                                },
                                {
                                    "textRuns": [
                                        {
                                            "value": subtitle,
                                            "textStyle": {
                                                "fontFamily": "Segoe UI",
                                                "fontSize": "9pt",
                                                "color": "#64748B",
                                            },
                                        }
                                    ]
                                },
                            ]
                        }
                    }
                ]
            },
            "drillFilterOtherVisuals": True,
        },
    }


def build_slicer(
    visual_id: str,
    entity: str,
    prop: str,
    header_label: str,
    x: float,
    y: float,
    w: float,
    h: float,
    z: int,
    *,
    mode: str = "Dropdown",
    single_select: bool = False,
    accent_color: str | None = None,
) -> dict[str, Any]:
    objects: dict[str, Any] = {
        "data": [{"properties": {"mode": lit(f"'{mode}'")}}],
        "header": [
            {
                "properties": {
                    "show": lit("true"),
                    "text": lit(f"'{header_label}'"),
                    "fontColor": solid(accent_color or "#64748B"),
                }
            }
        ],
    }
    if single_select:
        objects["selection"] = [
            {
                "properties": {
                    "singleSelect": lit("true"),
                    "strictSingleSelect": lit("false"),
                }
            }
        ]
    vco: dict[str, Any] = {}
    if accent_color:
        vco["border"] = [
            {
                "properties": {
                    "show": lit("true"),
                    "color": solid(accent_color),
                    "width": lit("1.5D"),
                    "radius": lit("6D"),
                }
            }
        ]

    visual: dict[str, Any] = {
        "visualType": "slicer",
        "query": {
            "queryState": {
                "Values": {"projections": [col_proj(entity, prop, active=True)]}
            }
        },
        "objects": objects,
        "drillFilterOtherVisuals": True,
    }
    if vco:
        visual["visualContainerObjects"] = vco

    return {
        "$schema": VISUAL_SCHEMA,
        "name": visual_id,
        "position": make_position(x, y, w, h, z=z),
        "visual": visual,
    }


def build_card_visual(
    visual_id: str,
    measures: list[tuple[str, str]],
    x: float,
    y: float,
    w: float,
    h: float,
    z: int,
    *,
    accent_color: str | None = None,
) -> dict[str, Any]:
    objects: dict[str, Any] = {
        "layout": [
            {
                "properties": {
                    "cellPadding": lit("10L"),
                    "maxTiles": lit(f"{max(len(measures), 3)}L"),
                }
            }
        ]
    }
    if accent_color:
        objects["accentBar"] = [
            {
                "properties": {
                    "show": lit("true"),
                    "position": lit("'Left'"),
                    "weight": lit("4L"),
                    "color": solid(accent_color),
                },
                "selector": {"id": "default"},
            }
        ]

    return {
        "$schema": VISUAL_SCHEMA,
        "name": visual_id,
        "position": make_position(x, y, w, h, z=z),
        "visual": {
            "visualType": "cardVisual",
            "query": {
                "queryState": {
                    "Data": {
                        "projections": [meas_proj(ent, prop) for ent, prop in measures]
                    }
                }
            },
            "objects": objects,
            "drillFilterOtherVisuals": True,
        },
    }


def update_report_json() -> None:
    report = load_json(REPORT_JSON)
    base_version = report.get("themeCollection", {}).get("baseTheme", {}).get(
        "reportVersionAtImport",
        {"visual": "2.15.0", "report": "3.4.0", "page": "2.3.1"},
    )
    report.setdefault("themeCollection", {})["customTheme"] = {
        "name": THEME_FILE,
        "reportVersionAtImport": base_version,
        "type": "RegisteredResources",
    }

    packages = report.setdefault("resourcePackages", [])
    reg_pkg = next(
        (p for p in packages if p.get("name") == "RegisteredResources"),
        None,
    )
    if reg_pkg is None:
        reg_pkg = {
            "name": "RegisteredResources",
            "type": "RegisteredResources",
            "items": [],
        }
        packages.append(reg_pkg)

    items = reg_pkg.setdefault("items", [])
    desired_items = [
        {"name": THEME_FILE, "path": THEME_FILE, "type": "CustomTheme"},
        {"name": BG_SVG_FILE, "path": BG_SVG_FILE, "type": "Image"},
    ]
    existing_names = {item["name"] for item in items}
    for item in desired_items:
        if item["name"] not in existing_names:
            items.append(item)

    save_json(REPORT_JSON, report)


def update_page_json(page_id: str, display_name: str) -> None:
    page_path = PAGES_DIR / page_id / "page.json"
    page = load_json(page_path)
    page["$schema"] = PAGE_SCHEMA
    page["displayName"] = display_name
    page["displayOption"] = "FitToPage"
    page["width"] = 1280
    page["height"] = 720
    page["objects"] = {
        "background": [
            {
                "properties": {
                    "transparency": lit("0D"),
                    "image": {
                        "image": {
                            "name": lit(f"'{BG_SVG_FILE}'"),
                            "url": {
                                "expr": {
                                    "ResourcePackageItem": {
                                        "PackageName": "RegisteredResources",
                                        "PackageType": 1,
                                        "ItemName": BG_SVG_FILE,
                                    }
                                }
                            },
                            "scaling": lit("'Fit'"),
                        }
                    },
                }
            }
        ],
        "outspace": [
            {
                "properties": {
                    "color": solid("#E2E8F0"),
                    "transparency": lit("0D"),
                }
            }
        ],
    }
    save_json(page_path, page)


def save_visual(page_id: str, visual_data: dict[str, Any]) -> None:
    vid = visual_data["name"]
    save_json(PAGES_DIR / page_id / "visuals" / vid / "visual.json", visual_data)


def load_visual(page_id: str, visual_id: str) -> dict[str, Any]:
    return load_json(PAGES_DIR / page_id / "visuals" / visual_id / "visual.json")


def ensure_projection_first(
    visual_data: dict[str, Any],
    role: str,
    projection: dict[str, Any],
    *,
    insert_index: int = 0,
) -> None:
    projs = visual_data["visual"]["query"]["queryState"][role]["projections"]
    if not any(p.get("queryRef") == projection["queryRef"] for p in projs):
        projs.insert(insert_index, projection)


def configure_page_1() -> None:
    update_page_json(P1_ID, "01. Visão Geral")

    # Sidebar Page Navigator
    save_visual(P1_ID, build_page_navigator("nav_sidebar_p1"))

    # Header Title & Slicers
    save_visual(
        P1_ID,
        build_header_textbox(
            "p1_header_title",
            "Visão Geral do Campeonato",
            "Classificação, evolução de pontos e desempenho por mando • Brasileirão Série A 2024",
            width=560,
        ),
    )
    save_visual(
        P1_ID,
        build_slicer(
            "p1_slicer_turno",
            "dRodadas",
            "turno",
            "TURNO",
            x=780,
            y=16,
            w=230,
            h=58,
            z=200,
            mode="Dropdown",
        ),
    )
    save_visual(
        P1_ID,
        build_slicer(
            "p1_slicer_mando",
            "fPartidas",
            "mando",
            "MANDO DE CAMPO",
            x=1026,
            y=16,
            w=234,
            h=58,
            z=201,
            mode="Dropdown",
        ),
    )

    # KPI Strip (4 New Cards)
    kpi = load_visual(P1_ID, "1471d986f1aafa66e456")
    kpi["position"] = make_position(200, 92, 1060, 92, z=300)
    # Upgrade league KPIs to match mockup (Líder, Aprov. Líder %, Média Gols/Partida, Melhor Ataque)
    kpi["visual"]["query"]["queryState"]["Data"]["projections"] = [
        meas_proj("_Medidas", "Líder (Card)"),
        meas_proj("_Medidas", "Aproveitamento Líder %"),
        meas_proj("_Medidas", "Média Gols por Partida"),
        meas_proj("_Medidas", "Melhor Ataque (Card)"),
    ]
    kpi["visual"].setdefault("objects", {})["layout"] = [
        {"properties": {"cellPadding": lit("14L"), "maxTiles": lit("4L")}}
    ]
    save_visual(P1_ID, kpi)

    # Left Table: Classificação Geral
    tbl = load_visual(P1_ID, "c50ef0bb9211916d866d")
    tbl["position"] = make_position(200, 200, 580, 500, z=400)
    ensure_projection_first(tbl, "Values", col_proj("dClubes", "escudo_url"), insert_index=1)
    set_container_title(tbl, "Classificação Geral — Série A 2024")
    save_visual(P1_ID, tbl)

    # Right Top: Line Chart (Evolução de Pontos)
    line = load_visual(P1_ID, "c5ec75571b6197000f07")
    line["position"] = make_position(796, 200, 464, 242, z=500)
    set_container_title(line, "Evolução de Pontos por Rodada (Top 4)")
    save_visual(P1_ID, line)

    # Right Bottom: Clustered Bar (Mandante vs Visitante)
    bar = load_visual(P1_ID, "3da4a8e7541610312399")
    bar["position"] = make_position(796, 458, 464, 242, z=600)
    set_container_title(bar, "Aproveitamento %: Mandante vs. Visitante")
    save_visual(P1_ID, bar)


def configure_page_2() -> None:
    update_page_json(P2_ID, "02. Scouting")

    # Sidebar Page Navigator
    save_visual(P2_ID, build_page_navigator("nav_sidebar_p2"))

    # Header Title & Slicers
    save_visual(
        P2_ID,
        build_header_textbox(
            "p2_header_title",
            "Scouting & Eficiência de Jogadores",
            "Produção ofensiva, conversão de finalizações e volume por 90 minutos",
            width=440,
        ),
    )
    save_visual(
        P2_ID,
        build_slicer(
            "p2_slicer_clube",
            "dClubes",
            "nome_clube",
            "CLUBE",
            x=656,
            y=16,
            w=190,
            h=58,
            z=200,
            mode="Dropdown",
        ),
    )
    save_visual(
        P2_ID,
        build_slicer(
            "p2_slicer_pos",
            "dJogadores",
            "posicao",
            "POSIÇÃO",
            x=862,
            y=16,
            w=186,
            h=58,
            z=201,
            mode="Dropdown",
        ),
    )
    save_visual(
        P2_ID,
        build_slicer(
            "p2_slicer_min",
            "fEstatisticasJogador",
            "minutos_jogados",
            "MINUTOS MÍNIMOS",
            x=1064,
            y=16,
            w=196,
            h=58,
            z=202,
            mode="GreaterThanOrEqual",
        ),
    )

    # KPI Strip (5 New Cards)
    kpi = load_visual(P2_ID, "42d3f97c6b801f90ab21")
    kpi["position"] = make_position(200, 92, 1060, 92, z=300)
    kpi["visual"].setdefault("objects", {})["layout"] = [
        {"properties": {"cellPadding": lit("12L"), "maxTiles": lit("5L")}}
    ]
    save_visual(P2_ID, kpi)

    # Middle Left: Scatter Chart
    scatter = load_visual(P2_ID, "10da87829dcccebc6ced")
    scatter["position"] = make_position(200, 200, 522, 252, z=400)
    scatter["visual"]["query"]["queryState"].setdefault(
        "Size", {"projections": [meas_proj("_Medidas", "Minutos Jogados")]}
    )
    set_container_title(scatter, "Eficiência: Finalizações Totais vs. Gols (Tam: Minutos)")
    save_visual(P2_ID, scatter)

    # Middle Right: Stacked Bar (Top 10 G+A)
    bar = load_visual(P2_ID, "c3864020caac9bd0a0ef")
    bar["position"] = make_position(738, 200, 522, 252, z=500)
    set_container_title(bar, "Top 10 Participações em Gol (Gols + Assistências)")
    if "filterConfig" not in bar:
        bar["filterConfig"] = {
            "filters": [
                make_topn_filter(
                    "top10_ga_players",
                    "dJogadores",
                    "nome_jogador",
                    "_Medidas",
                    "Participações em Gol (G+A)",
                    10,
                )
            ]
        }
    save_visual(P2_ID, bar)

    # Bottom: Matriz Analítica de Scouting
    tbl = load_visual(P2_ID, "094d7c5a2329acb9186b")
    tbl["position"] = make_position(200, 468, 1060, 232, z=600)
    ensure_projection_first(tbl, "Values", col_proj("dJogadores", "foto_url"), insert_index=0)
    set_container_title(tbl, "Matriz Analítica de Scouting")
    save_visual(P2_ID, tbl)


def configure_page_3() -> None:
    update_page_json(P3_ID, "03. Raio-X Clube")

    # Sidebar Page Navigator
    save_visual(P3_ID, build_page_navigator("nav_sidebar_p3"))

    # Header Title & Slicers
    save_visual(
        P3_ID,
        build_header_textbox(
            "p3_header_title",
            "Raio-X do Clube",
            "Diagnóstico completo de campanha, mando e produtividade individual do elenco",
            width=560,
        ),
    )
    save_visual(
        P3_ID,
        build_slicer(
            "p3_slicer_clube",
            "dClubes",
            "nome_clube",
            "CLUBE SELECIONADO",
            x=780,
            y=16,
            w=246,
            h=58,
            z=200,
            mode="Dropdown",
            single_select=True,
            accent_color="#059669",
        ),
    )

    # Existing Turno Slicer repositioned cleanly in Header
    slicer_turno = load_visual(P3_ID, "b7792fae29327c5343d5")
    slicer_turno["position"] = make_position(1042, 16, 218, 58, z=201)
    slicer_turno["visual"]["objects"] = {
        "data": [{"properties": {"mode": lit("'Dropdown'")}}],
        "header": [{"properties": {"show": lit("true"), "text": lit("'TURNO'")}}],
    }
    save_visual(P3_ID, slicer_turno)

    # Left Top Identity Banner (existing empty cardVisual f2a4d969ba4c7b5020e1)
    banner = load_visual(P3_ID, "f2a4d969ba4c7b5020e1")
    banner["position"] = make_position(200, 92, 348, 92, z=300)
    banner["visual"]["query"] = {
        "queryState": {
            "Data": {
                "projections": [
                    meas_proj("_Medidas", "Banner Clube"),
                    meas_proj("_Medidas", "Banner Estádio"),
                ]
            }
        }
    }
    banner["visual"]["objects"] = {
        "layout": [{"properties": {"cellPadding": lit("8L"), "maxTiles": lit("2L")}}],
        "accentBar": [
            {
                "properties": {
                    "show": lit("true"),
                    "position": lit("'Left'"),
                    "weight": lit("4L"),
                    "color": solid("#059669"),
                },
                "selector": {"id": "default"},
            }
        ],
    }
    save_visual(P3_ID, banner)

    # Right Top 5 KPIs (existing 3e50e1e6313b0d8139eb)
    kpi = load_visual(P3_ID, "3e50e1e6313b0d8139eb")
    kpi["position"] = make_position(564, 92, 696, 92, z=301)
    kpi["visual"].setdefault("objects", {})["layout"] = [
        {"properties": {"cellPadding": lit("10L"), "maxTiles": lit("5L")}}
    ]
    save_visual(P3_ID, kpi)

    # Left Middle: Gols Pró vs Gols Contra por Rodada
    col_chart = load_visual(P3_ID, "b102438eb66f59b3459b")
    col_chart["position"] = make_position(200, 200, 470, 242, z=400)
    set_container_title(col_chart, "Gols Pró vs. Gols Contra por Rodada")
    save_visual(P3_ID, col_chart)

    # Left Bottom: Pontos & Aproveitamento por Turno (populate empty 886e5dea874bc15e7417)
    combo = load_visual(P3_ID, "886e5dea874bc15e7417")
    combo["position"] = make_position(200, 458, 470, 242, z=500)
    combo["visual"]["visualType"] = "lineClusteredColumnComboChart"
    combo["visual"]["query"] = {
        "queryState": {
            "Category": {"projections": [col_proj("dRodadas", "turno", active=True)]},
            "Y": {"projections": [meas_proj("_Medidas", "Pontos Totais")]},
            "Y2": {"projections": [meas_proj("_Medidas", "Aproveitamento %")]},
        }
    }
    set_container_title(combo, "Pontos & Aproveitamento % por Turno")
    save_visual(P3_ID, combo)

    # Right Full Height: Elenco do Clube
    tbl = load_visual(P3_ID, "edd989a05f10096c7ee9")
    tbl["position"] = make_position(686, 200, 574, 500, z=600)
    ensure_projection_first(tbl, "Values", col_proj("dJogadores", "foto_url"), insert_index=0)
    tbl["visual"]["query"]["sortDefinition"] = {
        "sort": [
            {
                "field": meas_field("_Medidas", "Minutos Jogados"),
                "direction": "Descending",
            }
        ]
    }
    set_container_title(tbl, "Elenco do Clube (Ordenado por Minutos Jogados)")
    save_visual(P3_ID, tbl)


def configure_page_4() -> None:
    update_page_json(P4_ID, "04. Head-to-Head")

    # Sidebar Page Navigator
    save_visual(P4_ID, build_page_navigator("nav_sidebar_p4"))

    # Header Title & Slicers (Jogador A vs Jogador B)
    save_visual(
        P4_ID,
        build_header_textbox(
            "p4_header_title",
            "Comparativo Head-to-Head",
            "Duelo direto de atributos técnicos e eficiência por 90 min (Medidas DAX TREATAS)",
            width=560,
        ),
    )
    save_visual(
        P4_ID,
        build_slicer(
            "p4_slicer_a",
            "dJogador_A",
            "nome_jogador",
            "JOGADOR A (EMERALD)",
            x=780,
            y=16,
            w=230,
            h=58,
            z=200,
            mode="Dropdown",
            single_select=True,
            accent_color="#059669",
        ),
    )
    save_visual(
        P4_ID,
        build_slicer(
            "p4_slicer_b",
            "dJogador_B",
            "nome_jogador",
            "JOGADOR B (COBALT)",
            x=1026,
            y=16,
            w=234,
            h=58,
            z=201,
            mode="Dropdown",
            single_select=True,
            accent_color="#2563EB",
        ),
    )

    # Profile Cards + VS Badge
    save_visual(
        P4_ID,
        build_card_visual(
            "p4_profile_a",
            [
                ("_Medidas", "Perfil Nome (A)"),
                ("_Medidas", "Perfil Resumo (A)"),
                ("_Medidas", "Nota Média (A)"),
            ],
            x=200,
            y=92,
            w=496,
            h=92,
            z=300,
            accent_color="#059669",
        ),
    )
    save_visual(
        P4_ID,
        {
            "$schema": VISUAL_SCHEMA,
            "name": "p4_vs_badge",
            "position": make_position(704, 114, 52, 48, z=305),
            "visual": {
                "visualType": "textbox",
                "objects": {
                    "general": [
                        {
                            "properties": {
                                "paragraphs": [
                                    {
                                        "horizontalTextAlignment": "center",
                                        "textRuns": [
                                            {
                                                "value": "VS",
                                                "textStyle": {
                                                    "fontFamily": "Segoe UI",
                                                    "fontSize": "14pt",
                                                    "fontWeight": "bold",
                                                    "color": "#FFFFFF",
                                                },
                                            }
                                        ],
                                    }
                                ]
                            }
                        }
                    ]
                },
                "visualContainerObjects": {
                    "background": [
                        {
                            "properties": {
                                "show": lit("true"),
                                "color": solid("#0F172A"),
                                "transparency": lit("0D"),
                            }
                        }
                    ],
                    "border": [
                        {
                            "properties": {
                                "show": lit("true"),
                                "radius": lit("24D"),
                                "color": solid("#0F172A"),
                            }
                        }
                    ],
                    "padding": [
                        {
                            "properties": {
                                "top": lit("10L"),
                                "bottom": lit("4L"),
                                "left": lit("2L"),
                                "right": lit("2L"),
                            }
                        }
                    ],
                },
                "drillFilterOtherVisuals": True,
            },
        },
    )
    save_visual(
        P4_ID,
        build_card_visual(
            "p4_profile_b",
            [
                ("_Medidas", "Perfil Nome (B)"),
                ("_Medidas", "Perfil Resumo (B)"),
                ("_Medidas", "Nota Média (B)"),
            ],
            x=764,
            y=92,
            w=496,
            h=92,
            z=301,
            accent_color="#2563EB",
        ),
    )

    # Middle Left: Clustered Bar (Eficiência por 90 Minutos A vs B)
    bar = load_visual(P4_ID, "b09514566ab4d4556899")
    bar["position"] = make_position(200, 200, 522, 248, z=400)
    bar["visual"]["visualType"] = "clusteredBarChart"
    bar["visual"]["query"] = {
        "queryState": {
            "Category": {"projections": [col_proj("dMetricas_H2H", "Metrica", active=True)]},
            "Y": {
                "projections": [
                    meas_proj("_Medidas", "H2H Valor (A)"),
                    meas_proj("_Medidas", "H2H Valor (B)"),
                ]
            },
        }
    }
    bar["filterConfig"] = {
        "filters": [
            make_categorical_filter(
                "h2h_grp_eficiencia",
                "dMetricas_H2H",
                "Grupo",
                ["Eficiência / 90min"],
            )
        ]
    }
    set_container_title(bar, "Eficiência por 90 Minutos (A vs. B)")
    save_visual(P4_ID, bar)

    # Middle Right: Clustered Column (Volume & Consistência A vs B)
    col = load_visual(P4_ID, "07abc35931ac04192e52")
    col["position"] = make_position(738, 200, 522, 248, z=500)
    col["visual"]["visualType"] = "clusteredColumnChart"
    col["visual"]["query"] = {
        "queryState": {
            "Category": {"projections": [col_proj("dMetricas_H2H", "Metrica", active=True)]},
            "Y": {
                "projections": [
                    meas_proj("_Medidas", "H2H Valor (A)"),
                    meas_proj("_Medidas", "H2H Valor (B)"),
                ]
            },
        }
    }
    col["filterConfig"] = {
        "filters": [
            make_categorical_filter(
                "h2h_grp_volume",
                "dMetricas_H2H",
                "Grupo",
                ["Volume"],
            )
        ]
    }
    set_container_title(col, "Volume & Consistência na Temporada (A vs. B)")
    save_visual(P4_ID, col)

    # Bottom: Scorecard Comparativo Table
    tbl = load_visual(P4_ID, "84f7a239020454775345")
    tbl["position"] = make_position(200, 464, 1060, 236, z=600)
    tbl["visual"]["query"] = {
        "queryState": {
            "Values": {
                "projections": [
                    col_proj("dMetricas_H2H", "Metrica"),
                    meas_proj("_Medidas", "H2H Valor Formatado (A)"),
                    meas_proj("_Medidas", "H2H Diferença Formatada (A - B)"),
                    meas_proj("_Medidas", "H2H Valor Formatado (B)"),
                    meas_proj("_Medidas", "H2H Vantagem"),
                ]
            }
        }
    }
    tbl["filterConfig"] = {
        "filters": [
            make_categorical_filter(
                "h2h_grp_scorecard",
                "dMetricas_H2H",
                "Grupo",
                ["Scorecard"],
            )
        ]
    }
    set_container_title(tbl, "Scorecard Comparativo (Jogador A vs. Jogador B)")
    save_visual(P4_ID, tbl)


def validate_all_json() -> int:
    json_files = list(REPORT_DIR.rglob("*.json"))
    for path in json_files:
        json.loads(path.read_text(encoding="utf-8"))
    return len(json_files)


def main() -> None:
    update_report_json()
    configure_page_1()
    configure_page_2()
    configure_page_3()
    configure_page_4()
    total_valid = validate_all_json()
    print(f"Design system applied successfully. Validated {total_valid} JSON files.")


if __name__ == "__main__":
    main()
