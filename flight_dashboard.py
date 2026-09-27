"""
✈️ YC's Flight Deal Dashboard — Asia Outer-Port → Spain (MAD/BCN)

A Streamlit dashboard for evaluating flight deals using Jev's three-criteria
verdict (connection failure risk, fatigue index, routing verdict).
"""
import json
from pathlib import Path
from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# i18n helper
sys_path = Path(__file__).parent
import sys
sys.path.insert(0, str(sys_path))
from i18n import get as t, SEASONAL_DATA, DESTINATION_BEST_TIME

# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
DATA_DIR = Path(__file__).parent / "data"
RESULTS_PATH = DATA_DIR / "flight_results.json"
SUMMARY_PATH = DATA_DIR / "flight_summary.md"
CANDIDATES_PATH = DATA_DIR / "flight_candidates.json"

TPE_BASELINE_TWD = 180_000  # baseline TPE-direct business class
PAGE_ICON = "✈️"


# ----------------------------------------------------------------------
# Data loaders (with caching)
# ----------------------------------------------------------------------
@st.cache_data(ttl=60)
def load_results() -> dict | None:
    if not RESULTS_PATH.exists():
        return None
    with RESULTS_PATH.open() as f:
        return json.load(f)


@st.cache_data(ttl=60)
def load_summary() -> str:
    if not SUMMARY_PATH.exists():
        return "_No summary available — run `python3 /Users/aib/.hermes/tools/eval_flight_yc.py` first_"
    return SUMMARY_PATH.read_text(encoding="utf-8")


def results_to_dataframe(results: list[dict]) -> pd.DataFrame:
    rows = []
    for r in results:
        ev = r.get("evaluation", {})
        rows.append({
            "id": r.get("id"),
            "label": r.get("label"),
            "origin": r.get("positioning", {}).get("from"),
            "outer_port": r.get("long_haul", {}).get("from"),
            "via_hub": r.get("long_haul", {}).get("via"),
            "carrier": r.get("long_haul", {}).get("carrier"),
            "destination": r.get("long_haul", {}).get("to"),
            "total_cost_twd": r.get("total_cost", 0),
            "savings_pct": r.get("savings_pct", 0),
            "savings_twd": TPE_BASELINE_TWD - r.get("total_cost", 0),
            "routing_verdict": ev.get("routing_verdict", "n/a"),
            "risk": ev.get("connection_failure_risk", 0),
            "fatigue": ev.get("fatigue_index", 0),
            "total_elapsed_h": round(r.get("total_elapsed_min", 0) / 60, 1),
            "same_pnr": bool(r.get("same_pnr", False)),
            "n_segments": len(r.get("segments", [])),
            "notes": str(r.get("notes", "") or ""),
        })
    df = pd.DataFrame(rows)
    # Ensure pyarrow-compatible dtypes: cast all object→string
    for col in df.select_dtypes(include=["object"]).columns:
        df[col] = df[col].astype(str)
    return df


def segments_for_route(option: dict) -> list[dict]:
    """Flatten segments for visualisation."""
    segs = option.get("segments", [])
    return [
        {
            "from": s.get("from"),
            "to": s.get("to"),
            "carrier": s.get("carrier"),
            "flight": s.get("flight"),
            "cabin": s.get("cabin"),
            "duration_min": s.get("duration_min"),
        }
        for s in segs
    ]


# ----------------------------------------------------------------------
# Page config
# ----------------------------------------------------------------------
# Default to English at config time; language picker below overrides via st.rerun
st.set_page_config(
    page_title="YC's Flight Deal Dashboard",
    page_icon=PAGE_ICON,
    layout="wide",
    initial_sidebar_state="expanded",
)


# ----------------------------------------------------------------------
# Language picker — must come BEFORE any UI text so we can pick strings
# ----------------------------------------------------------------------
# Init default — overwrite possible values in priority order below
#
# Priority (highest first):
#   1. URL query string  ?lang=zh  (shareable — receives override)
#   2. Browser localStorage pref (sticky per-browser)
#   3. Hard fallback = "zh" (so first impression matches your main use case)
#
# localStorage note: streamlit only exposes Py→JS via components.html (iframe),
# which we already use elsewhere. For now we read URL query + persistent fallback.
DEFAULT_LANG = "zh"  # change to "en" if you want English-first

if "_lang" not in st.session_state:
    st.session_state["_lang"] = DEFAULT_LANG

# Priority 1: URL query override  (?lang=en or ?lang=zh)
_qp = st.query_params.get("lang")
if isinstance(_qp, list):
    _qp = _qp[0] if _qp else None
if _qp in ("en", "zh"):
    st.session_state["_lang"] = _qp
    try:
        st.query_params["lang"] = _qp  # make sticky in URL after first load
    except Exception:
        pass

# Reserve a placeholder for the sidebar's language radio
_LANG_PLACEHOLDER = st.sidebar.empty()


# ----------------------------------------------------------------------
# Sidebar
# ----------------------------------------------------------------------
with st.sidebar:
    # Language picker — first thing the user sees
    lang_choice = _LANG_PLACEHOLDER.radio(
        t("en", "lang_label"),
        options=["en", "zh"],
        format_func=lambda v: t(v, "lang_label").split(" ", 1)[1] if v == "zh" else "English",
        index=0 if st.session_state["_lang"] == "en" else 1,
        horizontal=True,
        key="_lang_radio",
    )
    if lang_choice != st.session_state["_lang"]:
        st.session_state["_lang"] = lang_choice
        st.rerun()
    L = st.session_state["_lang"]

    st.title(f"{PAGE_ICON} {t(L, 'sidebar_title')}")
    st.caption(t(L, "sidebar_caption"))

    results = load_results()

    if results is None:
        st.error(t(L, "no_candidates_error"))
        st.code(t(L, "no_candidates_command"), language="bash")
        st.stop()

    filters = results.get("filters", {})
    st.markdown(t(L, "filters_override"))

    max_risk = st.slider(
        t(L, "max_risk"),
        min_value=0, max_value=100, value=47,
    )
    max_fatigue = st.slider(
        t(L, "max_fatigue"),
        min_value=0.0, max_value=10.0,
        value=float(filters.get("max_fatigue_index", 7.5)),
        step=0.5,
    )
    min_savings = st.slider(
        t(L, "min_savings"),
        min_value=0, max_value=100,
        value=int(filters.get("min_savings_pct_vs_tpe", 35)),
    )
    verdict_filter = st.multiselect(
        t(L, "allowed_verdicts"),
        options=["prime_deal", "acceptable_economy", "avoid_exhausting"],
        default=["prime_deal", "acceptable_economy"],
    )

    st.markdown("---")
    st.markdown(t(L, "yc_original_filters"))
    st.json(filters)

    st.markdown("---")
    st.caption(t(L, "evaluated_at", ts=results.get("evaluated_at", "n/a")))


# ----------------------------------------------------------------------
# Apply filters
# ----------------------------------------------------------------------
all_evaluated = results.get("all_evaluated", [])
df_all = results_to_dataframe(all_evaluated)

df_survived = df_all.copy()
df_survived = df_survived[
    (df_survived["risk"] <= max_risk / 100) &
    (df_survived["fatigue"] <= max_fatigue) &
    (df_survived["savings_pct"] >= min_savings) &
    (df_survived["routing_verdict"].isin(verdict_filter))
]

# Sort by verdict priority then fatigue then risk then price
verdict_priority = {"prime_deal": 0, "acceptable_economy": 1, "avoid_exhausting": 2}
df_survived = df_survived.sort_values(
    by=["routing_verdict", "fatigue", "risk", "total_cost_twd"],
    key=lambda col: col.map(lambda v: verdict_priority.get(v, 9)) if col.name == "routing_verdict" else col,
)


# ----------------------------------------------------------------------
# KPI row
# ----------------------------------------------------------------------
st.title(t(L, "title"))

# Dynamic subtitle built from current data (so adding ICN updates automatically)
# Identify unique outer ports in the data; sort for a stable label
ports = sorted(set(df_all["outer_port"].dropna())) if not df_all.empty else ["KUL", "CGK", "BKK"]
ports_label = " · ".join(ports)

route_arrow_en = "→"
route_arrow_zh = "→"
if L == "zh":
    st.markdown(f"**{ports_label} {route_arrow_zh} 中東轉機 {route_arrow_zh} 西班牙 (MAD/BCN)** · 全商務艙")
else:
    st.markdown(f"**{ports_label} {route_arrow_en} Middle East {route_arrow_en} Spain (MAD/BCN)** · All business class")

if df_survived.empty:
    st.warning(t(L, "no_data_warning"))
else:
    top_pick = df_survived.iloc[0]
    total_savings = int(df_survived["savings_twd"].sum())
    avg_savings_pct = round(df_survived["savings_pct"].mean(), 1)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric(
            t(L, "kpi_top_pick"),
            f"NT$ {int(top_pick['total_cost_twd']):,}",
            f"{top_pick['savings_pct']}% {t(L, 'kpi_saved_suffix')}",
            delta_color="inverse",
        )
    with c2:
        st.metric(
            t(L, "kpi_avg_savings"),
            f"{avg_savings_pct}%",
            t(L, "kpi_avg_savings_sub", n=f"{TPE_BASELINE_TWD:,}"),
        )
    with c3:
        st.metric(
            t(L, "kpi_options_matched"),
            f"{len(df_survived)} / {len(df_all)}",
            f"{len(df_survived)} {t(L, 'kpi_options_matched_sub')}",
        )
    with c4:
        st.metric(
            t(L, "kpi_total_savings"),
            f"NT$ {total_savings:,}",
            f"{int(total_savings/1000)} {t(L, 'kpi_total_savings_unit')}" if total_savings > 1000 else None,
        )


# ----------------------------------------------------------------------
# Tabs
# ----------------------------------------------------------------------
tab_kpi, tab_top3, tab_compare, tab_map, tab_table, tab_cal, tab_summary = st.tabs([
    t(L, "tab_overview"),
    t(L, "tab_top3"),
    t(L, "tab_compare"),
    t(L, "tab_routes"),
    t(L, "tab_all"),
    t(L, "tab_calendar"),
    t(L, "tab_summary"),
])


# === TAB 1: Overview charts ===
with tab_kpi:
    if df_survived.empty:
        st.info(t(L, "no_data_scatter"))
    else:
        col_a, col_b = st.columns(2)

        # --- Scatter: risk vs fatigue ---
        with col_a:
            fig_scatter = px.scatter(
                df_survived,
                x="risk", y="fatigue",
                size="savings_pct", color="routing_verdict",
                hover_name="label",
                hover_data={
                    "id": True,
                    "origin": True,
                    "outer_port": True,
                    "via_hub": True,
                    "carrier": True,
                    "destination": True,
                    "total_cost_twd": ":,",
                    "savings_pct": True,
                    "risk": ":.0%",
                    "fatigue": ":.1f",
                    "total_elapsed_h": ":.1f",
                },
                size_max=60,
                color_discrete_map={
                    "prime_deal": "#16a34a",
                    "acceptable_economy": "#f59e0b",
                    "avoid_exhausting": "#dc2626",
                },
                title=t(L, "scatter_title"),
                labels={"risk": t(L, "scatter_x"), "fatigue": t(L, "scatter_y")},
            )
            fig_scatter.update_layout(height=450)
            fig_scatter.add_vline(x=0.25, line_dash="dash", line_color="red", opacity=0.5)
            fig_scatter.add_hline(y=7.5, line_dash="dash", line_color="red", opacity=0.5)
            fig_scatter.add_annotation(x=0.05, y=8.5,
                text=t(L, "high_risk_high_fatigue"), showarrow=False,
                font=dict(color="red", size=10), opacity=0.5)
            fig_scatter.add_annotation(x=0.05, y=1.5,
                text=t(L, "low_risk_low_fatigue"), showarrow=False,
                font=dict(color="green", size=10), opacity=0.5)
            st.plotly_chart(fig_scatter, use_container_width=True)

        # --- Bar: price comparison ---
        with col_b:
            df_plot = df_survived.sort_values("total_cost_twd", ascending=True)
            fig_bar = px.bar(
                df_plot,
                x="total_cost_twd", y="label",
                color="routing_verdict",
                orientation="h",
                hover_data=["savings_pct", "risk", "fatigue"],
                color_discrete_map={
                    "prime_deal": "#16a34a",
                    "acceptable_economy": "#f59e0b",
                    "avoid_exhausting": "#dc2626",
                },
                title=t(L, "bar_title"),
                labels={"total_cost_twd": t(L, "bar_xlabel"), "label": ""},
            )
            fig_bar.add_vline(x=TPE_BASELINE_TWD, line_dash="dash", line_color="red",
                annotation_text=t(L, "tpe_baseline_label", n=TPE_BASELINE_TWD),
                annotation_position="top right")
            fig_bar.update_layout(height=450, yaxis={"automargin": True})
            st.plotly_chart(fig_bar, use_container_width=True)

        # --- Savings + elapsed ---
        col_c, col_d = st.columns(2)
        with col_c:
            df_savings = df_survived.sort_values("savings_pct", ascending=False).head(10)
            fig_sav = px.bar(
                df_savings,
                x="savings_pct", y="label",
                orientation="h",
                color="routing_verdict",
                color_discrete_map={
                    "prime_deal": "#16a34a",
                    "acceptable_economy": "#f59e0b",
                    "avoid_exhausting": "#dc2626",
                },
                title=t(L, "savings_title"),
                labels={"savings_pct": t(L, "savings_xlabel")},
            )
            fig_sav.update_layout(height=400, yaxis={"automargin": True})
            st.plotly_chart(fig_sav, use_container_width=True)

        with col_d:
            df_ela = df_survived.sort_values("total_elapsed_h")
            fig_ela = px.bar(
                df_ela,
                x="total_elapsed_h", y="label",
                orientation="h",
                color="fatigue",
                color_continuous_scale="RdYlGn_r",
                title=t(L, "elapsed_title"),
                labels={"total_elapsed_h": t(L, "elapsed_xlabel")},
            )
            fig_ela.update_layout(height=400, yaxis={"automargin": True})
            st.plotly_chart(fig_ela, use_container_width=True)


# === TAB 2: Top 3 cards ===
with tab_top3:
    if df_survived.empty:
        st.info(t(L, "no_options_compare"))
    else:
        st.markdown(f"### {t(L, 'top3_title')}")
        st.caption(t(L, "top3_intro"))
        top3 = df_survived.head(3)
        opt_by_id = {o["id"]: o for o in all_evaluated}
        cols = st.columns(len(top3))
        medals = ["🥇", "🥈", "🥉"]
        for col, (_, row), medal in zip(cols, top3.iterrows(), medals):
            with col:
                verdict_color = {
                    "prime_deal": "🟢",
                    "acceptable_economy": "🟡",
                    "avoid_exhausting": "🔴",
                }.get(row["routing_verdict"], "⚪")

                st.markdown(f"### {medal} {verdict_color} {row['id']}")
                st.caption(row["label"])

                st.metric(
                    t(L, "metrics_total_cost"),
                    f"NT$ {int(row['total_cost_twd']):,}",
                    t(L, "top3_savings_pct", pct=row['savings_pct']),
                )

                st.markdown(f"""
- **{t(L, 'metrics_origin')}**: {row['origin']}
- **{t(L, 'metrics_outer')}**: {row['outer_port']}
- **{t(L, 'metrics_hub')}**: {row['via_hub']}
- **{t(L, 'metrics_carrier')}**: {row['carrier']}
- **{t(L, 'metrics_destination')}**: {row['destination']}
- **{t(L, 'metrics_verdict')}**: {row['routing_verdict']}
- **{t(L, 'metrics_risk')}**: {row['risk']:.0%}
- **{t(L, 'metrics_fatigue')}**: {row['fatigue']:.1f} / 10
- **{t(L, 'metrics_elapsed')}**: {row['total_elapsed_h']}h
- **{t(L, 'metrics_same_pnr')}**: {row['same_pnr']}
- **{t(L, 'metrics_segments')}**: {row['n_segments']}
""")

                with st.expander(t(L, "metrics_notes"), expanded=False):
                    st.write(opt_by_id.get(row["id"], {}).get("notes", t(L, "metrics_no_notes")))

                with st.expander(t(L, "metrics_route"), expanded=False):
                    for seg in segments_for_route(opt_by_id.get(row["id"], {})):
                        st.write(f"  - **{seg['carrier']} {seg['flight']}**: "
                                  f"{seg['from']} → {seg['to']}  "
                                  f"({seg['duration_min']} min, {seg['cabin']})")


# === TAB 3: Side-by-side comparison ===
with tab_compare:
    if df_survived.empty:
        st.info(t(L, "no_options_compare"))
    else:
        st.markdown(f"### {t(L, 'compare_pick')}")
        compare_ids = st.multiselect(
            t(L, "compare_pick"),
            options=df_survived["id"].tolist(),
            default=df_survived.head(3)["id"].tolist(),
            max_selections=4,
        )
        if not compare_ids:
            st.info(t(L, "compare_select_one"))
        else:
            compare_df = df_survived[df_survived["id"].isin(compare_ids)].T
            compare_df.columns = compare_df.iloc[0]
            compare_df = compare_df[1:]

            st.dataframe(
                compare_df,
                use_container_width=True,
                column_config={
                    "total_cost_twd": st.column_config.ProgressColumn(
                        "Total cost (TWD)", format="NT$ %d", min_value=0, max_value=200000,
                    ),
                    "risk": st.column_config.ProgressColumn(
                        "Risk", format="%.0f%%", min_value=0, max_value=100,
                    ),
                    "fatigue": st.column_config.ProgressColumn(
                        "Fatigue", format="%.1f", min_value=0, max_value=10,
                    ),
                    "savings_pct": st.column_config.ProgressColumn(
                        "Savings %", format="%d%%", min_value=0, max_value=100,
                    ),
                },
            )

            opt_by_id = {o["id"]: o for o in all_evaluated}
            categories = t(L, "compare_categories")

            fig_radar = go.Figure()
            for cid in compare_ids:
                row = df_survived[df_survived["id"] == cid].iloc[0]
                opt = opt_by_id.get(cid, {})
                s_pct = row["savings_pct"] / 100
                low_risk = 1 - row["risk"]
                low_fatigue = 1 - (row["fatigue"] / 10)
                short_time = max(0, 1 - (row["total_elapsed_h"] / 30))
                same_pnr = 1.0 if opt.get("same_pnr") else 0.0

                fig_radar.add_trace(go.Scatterpolar(
                    r=[s_pct, low_risk, low_fatigue, short_time, same_pnr],
                    theta=categories,
                    fill="toself",
                    name=cid,
                ))
            fig_radar.update_layout(
                polar=dict(radialaxis=dict(visible=True, range=[0, 1])),
                showlegend=True,
                height=500,
                title=t(L, "compare_radar_title"),
            )
            st.plotly_chart(fig_radar, use_container_width=True)


# === TAB 4: Route map ===
with tab_map:
    if df_survived.empty:
        st.info(t(L, "no_options_routes"))
    else:
        st.markdown(f"### {t(L, 'routes_intro')}")
        opt_by_id = {o["id"]: o for o in all_evaluated}
        for _, row in df_survived.iterrows():
            opt = opt_by_id.get(row["id"], {})
            with st.expander(f"**{row['id']}** — {row['label']}  ({row['total_cost_twd']:,} TWD)"):
                cols = st.columns([0.6, 0.4])
                with cols[0]:
                    st.markdown(t(L, "route_waypoints"))
                    for seg in segments_for_route(opt):
                        st.markdown(
                            f"- 🛫 **{seg['from']}** → 🛬 **{seg['to']}**  "
                            f"(`{seg['carrier']} {seg['flight']}`, "
                            f"{seg['duration_min']}min, {seg['cabin']})"
                        )
                with cols[1]:
                    st.markdown(f"""
**Stats:**
- Risk: {row['risk']:.0%}
- Fatigue: {row['fatigue']:.1f}/10
- Elapsed: {row['total_elapsed_h']}h
- Same PNR: {row['same_pnr']}
""")


# === TAB 5: Full table ===
with tab_table:
    st.markdown(f"### {t(L, 'table_title')}")
    st.caption(t(L, "table_caption", total=len(df_all), matched=len(df_survived)))

    df_display = df_all.copy()
    df_display["survives"] = df_display["id"].isin(df_survived["id"])

    st.dataframe(
        df_display.sort_values(["survives", "total_cost_twd"], ascending=[False, True]),
        use_container_width=True,
        hide_index=True,
        column_config={
            "id": st.column_config.TextColumn(t(L, "table_col_id"), width="small"),
            "label": st.column_config.TextColumn(t(L, "table_col_label"), width="large"),
            "total_cost_twd": st.column_config.NumberColumn(
                t(L, "table_col_cost"), format="NT$ %d",
            ),
            "savings_pct": st.column_config.ProgressColumn(
                t(L, "table_col_save_pct"), format="%d%%", min_value=0, max_value=100,
            ),
            "savings_twd": st.column_config.NumberColumn(
                t(L, "table_col_save_twd"), format="NT$ %d",
            ),
            "risk": st.column_config.ProgressColumn(
                t(L, "table_col_risk"), format="%.0f%%", min_value=0, max_value=100,
            ),
            "fatigue": st.column_config.ProgressColumn(
                t(L, "table_col_fatigue"), format="%.1f", min_value=0, max_value=10,
            ),
            "survives": st.column_config.CheckboxColumn(t(L, "table_col_survives")),
            "same_pnr": st.column_config.CheckboxColumn(t(L, "table_col_pnr")),
        },
    )

    st.download_button(
        t(L, "download_csv"),
        df_survived.to_csv(index=False).encode("utf-8"),
        file_name=f"flight_deals_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
        key="dl_csv",
    )


# === TAB: Best booking calendar ===
with tab_cal:
    st.markdown(f"### 🗓️ {t(L, 'cal_title')}")
    st.caption(t(L, "cal_caption"))

    col_season, col_destination = st.columns(2)

    with col_season:
        st.markdown(f"#### 🌡️ {t(L, 'cal_season_header')}")
        for month, price, weather, dest_note in SEASONAL_DATA[L]:
            emoji = "🟢" if price == "cheap" else ("🔴" if price == "peak" else "🟡")
            label = t(L, "cal_cheap" if price == "cheap" else (
                      "cal_peak" if price == "peak" else "cal_moderate"))
            st.markdown(f"**{month}** {emoji} **{label}**  \n{weather}  \n{('→ ' + dest_note) if dest_note else ''}")

    with col_destination:
        st.markdown(f"#### 📍 {t(L, 'cal_dest_header')}")
        st.caption(t(L, "cal_dest_caption"))
        for dest, season_note in DESTINATION_BEST_TIME[L].items():
            st.markdown(f"- **{dest}** — {season_note}")

    st.markdown("---")
    st.markdown(f"### 💡 {t(L, 'cal_pro_tips_header')}")
    st.markdown(t(L, "cal_pro_tips_body"))


# === TAB 6: Markdown summary ===
with tab_summary:
    st.markdown(f"### {t(L, 'summary_title')}")
    st.markdown(load_summary())

    with open(RESULTS_PATH) as f:
        raw_data = json.load(f)
    with st.expander(t(L, "raw_json_expander"), expanded=False):
        st.json(raw_data)

st.markdown("---")
st.caption(t(L, "footer_caption", n=len(all_evaluated)))
