"""Bilingual UI strings (English + 繁體中文)."""

T = {
    "en": {
        # Page meta
        "page_title": "YC's Flight Deal Dashboard",
        "sidebar_title": "YC's Flight Deal Dashboard",
        "sidebar_caption": "Asia outer-port → Middle East → Spain",
        "title": "✈️ YC's Outer-Port Flight Deal Dashboard",
        "subtitle": "**KUL · CGK · BKK → Middle East → Spain (MAD/BCN)** · All business class",

        # Sidebar
        "lang_label": "🌐 Language",
        "filters_override": "### 🎛️ Filters (override)",
        "max_risk": "Max connection risk (%)",
        "max_fatigue": "Max fatigue index",
        "min_savings": "Min savings vs TPE-direct (%)",
        "allowed_verdicts": "Allowed verdicts",
        "yc_original_filters": "### ⚙️ YC's Original Filters",
        "evaluated_at": "Evaluated at: {ts}",
        "language_english": "English",
        "language_chinese": "繁體中文",

        # KPI
        "kpi_top_pick": "🏆 Top pick",
        "kpi_saved_suffix": "saved",
        "kpi_avg_savings": "💰 Average savings",
        "kpi_avg_savings_sub": "vs TPE-direct NT$ {n}",
        "kpi_options_matched": "📋 Options matched",
        "kpi_options_matched_sub": "survivable",
        "kpi_total_savings": "💸 Total potential savings",
        "kpi_total_savings_unit": "K NT$",

        # Tabs
        "tab_overview": "📈 Overview",
        "tab_top3": "🏆 Top 3",
        "tab_compare": "⚖️ Compare",
        "tab_routes": "🗺️ Routes",
        "tab_all": "📋 All options",
        "tab_summary": "📝 Summary",

        # Overview charts
        "scatter_title": "Risk vs Fatigue (size = savings %)",
        "scatter_x": "Connection failure risk",
        "scatter_y": "Fatigue index (1-10)",
        "high_risk_high_fatigue": "HIGH RISK<br>HIGH FATIGUE",
        "low_risk_low_fatigue": "low risk<br>low fatigue",
        "bar_title": "Total cost (TWD) — lower is better",
        "bar_xlabel": "TWD",
        "tpe_baseline_label": "TPE-direct ≈ NT$ {n:,}",
        "savings_title": "Savings % vs TPE-direct — higher is better",
        "savings_xlabel": "Savings %",
        "elapsed_title": "Total elapsed time (hours)",
        "elapsed_xlabel": "Hours",

        # No data
        "no_data_scatter": "No data to plot.",
        "no_options_compare": "No options to compare.",
        "no_options_routes": "No routes to show.",
        "no_data_warning": "⚠️ No options match current filters. Try widening them in the sidebar.",
        "no_candidates_error": "❌ No results found. Run `eval_flight_yc.py` first.",
        "no_candidates_command": "python3 /Users/aib/.hermes/tools/eval_flight_yc.py",

        # Top 3
        "metrics_origin": "Origin",
        "metrics_outer": "Outer port",
        "metrics_hub": "Hub",
        "metrics_carrier": "Carrier",
        "metrics_destination": "Destination",
        "metrics_verdict": "Verdict",
        "metrics_risk": "Connection risk",
        "metrics_fatigue": "Fatigue",
        "metrics_elapsed": "Elapsed",
        "metrics_same_pnr": "Same PNR",
        "metrics_segments": "Segments",
        "metrics_notes": "📝 Notes",
        "metrics_route": "🛫 Full route",
        "metrics_total_cost": "💰 Total cost",
        "metrics_no_notes": "N/A",
        "metrics_n_a": "N/A",
        "top3_title": "🏆 TOP 3 — best deals",
        "top3_intro": "The top 3 strongest candidates by risk-adjusted savings.",
        "top3_savings_pct": "{pct}% saved",
        "top3_metric_label": "{carrier} · {cabin}",

        # Compare
        "compare_pick": "Pick options to compare",
        "compare_select_one": "Select at least one option.",
        "compare_radar_title": "Multi-criteria radar",
        "compare_categories": ["Savings %", "Low risk", "Low fatigue", "Short time", "Same PNR"],

        # Routes
        "routes_intro": "🗺️ All routings (text view)",
        "route_waypoints": "**Route waypoints:**",
        "route_stats": "**Stats:**",

        # All options table
        "table_title": "📋 All evaluated options",
        "table_caption": "{total} total · {matched} currently match your filters",
        "table_col_id": "ID",
        "table_col_label": "Label",
        "table_col_cost": "Cost (TWD)",
        "table_col_save_pct": "Save %",
        "table_col_save_twd": "Save (TWD)",
        "table_col_risk": "Risk",
        "table_col_fatigue": "Fatigue",
        "table_col_survives": "Survives filter",
        "table_col_pnr": "Same PNR",
        "table_filter": "Pick options to compare",
        "download_csv": "⬇️ Download filtered as CSV",

        # Summary
        "summary_title": "📝 Auto-generated summary",
        "raw_json_expander": "🔍 Raw JSON",

        # Footer
        "footer_caption": "🤖 Powered by Jev (TypeSafe SystemOne) · {n} options evaluated · ~NT$ 0.00002 per evaluation",

        # Verdict labels (shown in tag form, bilingual inside parens)
        "verdict_prime_deal": "🟢 prime_deal",
        "verdict_acceptable": "🟡 acceptable_economy",
        "verdict_avoid": "🔴 avoid_exhausting",

        # Long descriptions in Top-3 card
        "top3_section_intro": "The strongest candidates, ranked by verdict → fatigue → risk → price.",
    },

    "zh": {
        # Page meta
        "page_title": "YC 機票比價看板",
        "sidebar_title": "YC 機票比價看板",
        "sidebar_caption": "亞洲外站 → 中東轉機 → 西班牙",
        "title": "✈️ YC 外站機票比價看板",
        "subtitle": "**KUL · CGK · BKK → 中東轉機 → 西班牙 (MAD/BCN)** · 全商務艙",

        # Sidebar
        "lang_label": "🌐 語言",
        "filters_override": "### 🎛️ 過濾條件（自訂）",
        "max_risk": "連接失敗風險上限 (%)",
        "max_fatigue": "疲勞指數上限",
        "min_savings": "對比 TPE 直飛 省幅下限 (%)",
        "allowed_verdicts": "允許的 Jev 標籤",
        "yc_original_filters": "### ⚙️ YC 原始過濾規則",
        "evaluated_at": "評估時間：{ts}",
        "language_english": "English",
        "language_chinese": "繁體中文",

        # KPI
        "kpi_top_pick": "🏆 首選",
        "kpi_saved_suffix": "已省",
        "kpi_avg_savings": "💰 平均省幅",
        "kpi_avg_savings_sub": "對比 TPE 直飛 NT$ {n}",
        "kpi_options_matched": "📋 通過方案數",
        "kpi_options_matched_sub": "通過篩選",
        "kpi_total_savings": "💸 潛在總省幅",
        "kpi_total_savings_unit": "千 NT$",

        # Tabs
        "tab_overview": "📈 總覽",
        "tab_top3": "🏆 Top 3",
        "tab_compare": "⚖️ 比較",
        "tab_routes": "🗺️ 航段",
        "tab_all": "📋 全部方案",
        "tab_summary": "📝 摘要",

        # Overview charts
        "scatter_title": "風險 vs 疲勞（泡泡大小 = 省幅）",
        "scatter_x": "連接失敗風險",
        "scatter_y": "疲勞指數 (1-10)",
        "high_risk_high_fatigue": "高風險<br>高疲勞",
        "low_risk_low_fatigue": "低風險<br>低疲勞",
        "bar_title": "總成本比較 (TWD) — 越低越好",
        "bar_xlabel": "TWD",
        "tpe_baseline_label": "TPE 直飛 ≈ NT$ {n:,}",
        "savings_title": "對比 TPE 直飛省幅 % — 越高越好",
        "savings_xlabel": "省幅 %",
        "elapsed_title": "總旅行時數",
        "elapsed_xlabel": "小時",

        # No data
        "no_data_scatter": "無資料可繪製。",
        "no_options_compare": "沒有可比較的方案。",
        "no_options_routes": "沒有可顯示的航段。",
        "no_data_warning": "⚠️ 沒有方案符合目前過濾條件。試著在側邊欄放寬條件。",
        "no_candidates_error": "❌ 找不到結果。請先執行 `eval_flight_yc.py` 。",
        "no_candidates_command": "python3 /Users/aib/.hermes/tools/eval_flight_yc.py",

        # Top 3
        "metrics_origin": "出發地",
        "metrics_outer": "外站",
        "metrics_hub": "中轉機場",
        "metrics_carrier": "航空公司",
        "metrics_destination": "目的地",
        "metrics_verdict": "Jev 標籤",
        "metrics_risk": "斷鏈風險",
        "metrics_fatigue": "疲勞指數",
        "metrics_elapsed": "總時數",
        "metrics_same_pnr": "同 PNR",
        "metrics_segments": "航段數",
        "metrics_notes": "📝 備註",
        "metrics_route": "🛫 完整航段",
        "metrics_total_cost": "💰 總成本",
        "metrics_no_notes": "無",
        "metrics_n_a": "無",
        "top3_title": "🏆 Top 3 — 性價比最佳",
        "top3_intro": "依 Jev 標籤 → 疲勞 → 風險 → 價格排序的最佳三組。",
        "top3_savings_pct": "已省 {pct}%",
        "top3_metric_label": "{carrier} · {cabin}",

        # Compare
        "compare_pick": "選擇要比較的方案",
        "compare_select_one": "請至少選擇一個方案。",
        "compare_radar_title": "多準則雷達圖",
        "compare_categories": ["省幅 %", "低風險", "低疲勞", "短時數", "同 PNR"],

        # Routes
        "routes_intro": "🗺️ 所有航段（文字版）",
        "route_waypoints": "**航段路徑：**",
        "route_stats": "**統計：**",

        # All options table
        "table_title": "📋 全部評估方案",
        "table_caption": "{total} 個方案 · {matched} 個符合目前過濾條件",
        "table_col_id": "編號",
        "table_col_label": "方案說明",
        "table_col_cost": "成本 (TWD)",
        "table_col_save_pct": "省幅 %",
        "table_col_save_twd": "省下 (TWD)",
        "table_col_risk": "風險",
        "table_col_fatigue": "疲勞",
        "table_col_survives": "通過篩選",
        "table_col_pnr": "同 PNR",
        "table_filter": "選擇要比較的方案",
        "download_csv": "⬇️ 下載篩選結果為 CSV",

        # Summary
        "summary_title": "📝 自動生成的摘要",
        "raw_json_expander": "🔍 原始 JSON",

        # Footer
        "footer_caption": "🤖 Powered by Jev (TypeSafe SystemOne) · {n} 個方案已評估 · 每次約 NT$ 0.00002",

        # Verdict labels
        "verdict_prime_deal": "🟢 prime_deal（最佳）",
        "verdict_acceptable": "🟡 acceptable_economy（可接受）",
        "verdict_avoid": "🔴 avoid_exhausting（避免）",

        # Long descriptions in Top-3 card
        "top3_section_intro": "依標籤 → 疲勞 → 風險 → 價格排序的最佳候選方案。",
    },
}


def get(lang: str, key: str, **fmt) -> str:
    """Look up a string by key, optionally formatting with named args.

    Falls back to English if a key is missing in the requested language.
    """
    s = T.get(lang, T["en"]).get(key, T["en"].get(key, key))
    if fmt:
        try:
            return s.format(**fmt)
        except (KeyError, IndexError):
            return s
    return s
