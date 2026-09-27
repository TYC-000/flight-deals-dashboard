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

# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
DATA_DIR = Path(__file__).parent / "data"
RESULTS_PATH = DATA_DIR / "flight_results.json"
SUMMARY_PATH = DATA_DIR / "flight_summary.md"
CANDIDATES_PATH = DATA_DIR / "flight_candidates.json"

TPE_BASELINE_TWD = 180_000  # baseline TPE-direct business class
PAGE_ICON = "✈️"
PAGE_TITLE = "YC's Flight Deal Dashboard"


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
st.set_page_config(
    page_title=PAGE_TITLE,
    page_icon=PAGE_ICON,
    layout="wide",
    initial_sidebar_state="expanded",
)


# ----------------------------------------------------------------------
# Sidebar
# ----------------------------------------------------------------------
with st.sidebar:
    st.title(f"{PAGE_ICON} {PAGE_TITLE}")
    st.caption("Asia outer-port → Middle East → Spain")

    results = load_results()

    if results is None:
        st.error("❌ No results found. Run `eval_flight_yc.py` first.")
        st.code("python3 /Users/aib/.hermes/tools/eval_flight_yc.py /tmp/flight_es_candidates.json -o data/flight_results.json", language="bash")
        st.stop()

    filters = results.get("filters", {})
    st.markdown("### 🎛️ Filters (override)")

    max_risk = st.slider("Max connection risk (%)",
                          min_value=0, max_value=100, value=47)
    max_fatigue = st.slider("Max fatigue index",
                            min_value=0.0, max_value=10.0,
                            value=float(filters.get("max_fatigue_index", 7.5)),
                            step=0.5)
    min_savings = st.slider("Min savings vs TPE-direct (%)",
                            min_value=0, max_value=100,
                            value=int(filters.get("min_savings_pct_vs_tpe", 35)))
    verdict_filter = st.multiselect(
        "Allowed verdicts",
        options=["prime_deal", "acceptable_economy", "avoid_exhausting"],
        default=["prime_deal", "acceptable_economy"],
    )

    st.markdown("---")
    st.markdown("### ⚙️ YC's Original Filters")
    st.json(filters)

    st.markdown("---")
    st.caption(f"Evaluated at: {results.get('evaluated_at', 'n/a')}")


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
st.title(f"{PAGE_ICON} YC's Outer-Port Flight Deal Dashboard")
st.markdown("**KUL · CGK · BKK → 中東 hub → Spain (MAD/BCN)** · 全部商務艙")

if df_survived.empty:
    st.warning(f"⚠️ No options match current filters. Try widening them in the sidebar.")
else:
    top_pick = df_survived.iloc[0]
    total_savings = int(df_survived["savings_twd"].sum())
    avg_savings_pct = round(df_survived["savings_pct"].mean(), 1)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric(
            "🏆 Top pick",
            f"NT$ {int(top_pick['total_cost_twd']):,}",
            f"{top_pick['savings_pct']}% saved",
            delta_color="inverse",
        )
    with c2:
        st.metric(
            "💰 Average savings",
            f"{avg_savings_pct}%",
            f"vs TPE-direct NT$ {TPE_BASELINE_TWD:,}",
        )
    with c3:
        st.metric(
            "📋 Options matched",
            f"{len(df_survived)} / {len(df_all)}",
            f"{len(df_survived)} survivable",
        )
    with c4:
        st.metric(
            "💸 Total potential savings",
            f"NT$ {total_savings:,}",
            f"{int(total_savings/1000)}K NT$" if total_savings > 1000 else None,
        )


# ----------------------------------------------------------------------
# Tabs
# ----------------------------------------------------------------------
tab_kpi, tab_top3, tab_compare, tab_map, tab_table, tab_summary = st.tabs([
    "📈 Overview",
    "🏆 Top 3",
    "⚖️ Compare",
    "🗺️ Routes",
    "📋 All options",
    "📝 Summary",
])


# === TAB 1: Overview charts ===
with tab_kpi:
    if df_survived.empty:
        st.info("No data to plot.")
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
                title="Risk vs Fatigue (size = savings %)",
                labels={"risk": "Connection failure risk", "fatigue": "Fatigue index (1-10)"},
            )
            fig_scatter.update_layout(height=450)
            # Add quadrant lines
            fig_scatter.add_vline(x=0.25, line_dash="dash", line_color="red", opacity=0.5)
            fig_scatter.add_hline(y=7.5, line_dash="dash", line_color="red", opacity=0.5)
            # Annotate quadrants
            fig_scatter.add_annotation(x=0.05, y=8.5, text="HIGH RISK<br>HIGH FATIGUE", showarrow=False,
                                        font=dict(color="red", size=10), opacity=0.5)
            fig_scatter.add_annotation(x=0.05, y=1.5, text="low risk<br>low fatigue", showarrow=False,
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
                title="Total cost (TWD) — lower is better",
                labels={"total_cost_twd": "TWD", "label": "Option"},
            )
            # Reference line for TPE baseline
            fig_bar.add_vline(x=TPE_BASELINE_TWD, line_dash="dash", line_color="red",
                               annotation_text=f"TPE-direct ≈ NT$ {TPE_BASELINE_TWD:,}",
                               annotation_position="top right")
            fig_bar.update_layout(height=450, yaxis={"automargin": True})
            st.plotly_chart(fig_bar, use_container_width=True)

        # --- Savings comparison ---
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
                title="Savings % vs TPE-direct — higher is better",
                labels={"savings_pct": "Savings %"},
            )
            fig_sav.update_layout(height=400, yaxis={"automargin": True})
            st.plotly_chart(fig_sav, use_container_width=True)

        with col_d:
            # Elapsed time
            df_ela = df_survived.sort_values("total_elapsed_h")
            fig_ela = px.bar(
                df_ela,
                x="total_elapsed_h", y="label",
                orientation="h",
                color="fatigue",
                color_continuous_scale="RdYlGn_r",
                title="Total elapsed time (hours)",
                labels={"total_elapsed_h": "Hours"},
            )
            fig_ela.update_layout(height=400, yaxis={"automargin": True})
            st.plotly_chart(fig_ela, use_container_width=True)


# === TAB 2: Top 3 cards ===
with tab_top3:
    if df_survived.empty:
        st.info("No options survive filters.")
    else:
        top3 = df_survived.head(3)
        # Build option dicts from json
        opt_by_id = {o["id"]: o for o in all_evaluated}
        cols = st.columns(len(top3))
        medals = ["🥇", "🥈", "🥉"]
        for col, (_, row), medal in zip(cols, top3.iterrows(), medals):
            with col:
                # Card
                verdict_color = {
                    "prime_deal": "🟢",
                    "acceptable_economy": "🟡",
                    "avoid_exhausting": "🔴",
                }.get(row["routing_verdict"], "⚪")

                st.markdown(f"### {medal} {verdict_color} {row['id']}")
                st.caption(row["label"])

                st.metric("💰 Total cost", f"NT$ {int(row['total_cost_twd']):,}",
                          f"-{row['savings_pct']}%")

                st.markdown(f"""
                - **Origin**: {row['origin']}
                - **Outer port**: {row['outer_port']}
                - **Hub**: {row['via_hub']}
                - **Carrier**: {row['carrier']}
                - **Destination**: {row['destination']}
                - **Verdict**: {row['routing_verdict']}
                - **Connection risk**: {row['risk']:.0%}
                - **Fatigue**: {row['fatigue']:.1f} / 10
                - **Elapsed**: {row['total_elapsed_h']}h
                - **Same PNR**: {row['same_pnr']}
                - **Segments**: {row['n_segments']}
                """)

                with st.expander("📝 Notes", expanded=False):
                    st.write(opt_by_id.get(row["id"], {}).get("notes", "N/A"))

                with st.expander("🛫 Full route", expanded=False):
                    for seg in segments_for_route(opt_by_id.get(row["id"], {})):
                        st.write(f"  - **{seg['carrier']} {seg['flight']}**: "
                                  f"{seg['from']} → {seg['to']}  "
                                  f"({seg['duration_min']} min, {seg['cabin']})")


# === TAB 3: Side-by-side comparison ===
with tab_compare:
    if df_survived.empty:
        st.info("No options to compare.")
    else:
        st.markdown("### ⚖️ Compare up to 4 options")
        compare_ids = st.multiselect(
            "Pick options to compare",
            options=df_survived["id"].tolist(),
            default=df_survived.head(3)["id"].tolist(),
            max_selections=4,
        )
        if not compare_ids:
            st.info("Select at least one option.")
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

            # Radar chart
            opt_by_id = {o["id"]: o for o in all_evaluated}
            categories = ["Savings %", "Low risk", "Low fatigue", "Short time", "Same PNR"]

            fig_radar = go.Figure()
            for cid in compare_ids:
                row = df_survived[df_survived["id"] == cid].iloc[0]
                opt = opt_by_id.get(cid, {})
                # Normalise each metric to 0-1 (1 = best)
                s_pct = row["savings_pct"] / 100
                low_risk = 1 - row["risk"]
                low_fatigue = 1 - (row["fatigue"] / 10)
                short_time = max(0, 1 - (row["total_elapsed_h"] / 30))  # 30h = 0
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
                title="Multi-criteria radar",
            )
            st.plotly_chart(fig_radar, use_container_width=True)


# === TAB 4: Route map ===
with tab_map:
    if df_survived.empty:
        st.info("No routes to show.")
    else:
        st.markdown("### 🗺️ All routings (text view)")
        opt_by_id = {o["id"]: o for o in all_evaluated}
        for _, row in df_survived.iterrows():
            opt = opt_by_id.get(row["id"], {})
            with st.expander(f"**{row['id']}** — {row['label']}  ({row['total_cost_twd']:,} TWD)"):
                cols = st.columns([0.6, 0.4])
                with cols[0]:
                    st.markdown("**Route waypoints:**")
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
    st.markdown("### 📋 All evaluated options")
    st.caption(f"{len(df_all)} total · {len(df_survived)} currently match your filters")

    # Highlight survivability
    df_display = df_all.copy()
    df_display["survives"] = df_display["id"].isin(df_survived["id"])

    st.dataframe(
        df_display.sort_values(["survives", "total_cost_twd"], ascending=[False, True]),
        use_container_width=True,
        hide_index=True,
        column_config={
            "id": st.column_config.TextColumn("ID", width="small"),
            "label": st.column_config.TextColumn("Label", width="large"),
            "total_cost_twd": st.column_config.NumberColumn(
                "Cost (TWD)", format="NT$ %d",
            ),
            "savings_pct": st.column_config.ProgressColumn(
                "Save %", format="%d%%", min_value=0, max_value=100,
            ),
            "savings_twd": st.column_config.NumberColumn(
                "Save (TWD)", format="NT$ %d",
            ),
            "risk": st.column_config.ProgressColumn(
                "Risk", format="%.0f%%", min_value=0, max_value=100,
            ),
            "fatigue": st.column_config.ProgressColumn(
                "Fatigue", format="%.1f", min_value=0, max_value=10,
            ),
            "survives": st.column_config.CheckboxColumn("Survives filter"),
            "same_pnr": st.column_config.CheckboxColumn("Same PNR"),
        },
    )

    st.download_button(
        "⬇️ Download filtered as CSV",
        df_survived.to_csv(index=False).encode("utf-8"),
        file_name=f"flight_deals_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
        key="dl_csv",
    )


# === TAB 6: Markdown summary ===
with tab_summary:
    st.markdown("### 📝 Auto-generated summary")
    st.markdown(load_summary())

    with open(RESULTS_PATH) as f:
        raw_data = json.load(f)
    with st.expander("🔍 Raw JSON", expanded=False):
        st.json(raw_data)

st.markdown("---")
st.caption(
    f"🤖 Powered by Jev (TypeSafe SystemOne) · {len(all_evaluated)} options evaluated · "
    f"~NT$ 0.00002 per evaluation"
)
