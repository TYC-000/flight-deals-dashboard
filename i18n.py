"""Bilingual UI strings (English + 繁體中文)."""

T = {
    "en": {
        # Page meta
        "page_title": "YC's Flight Deal Dashboard",
        "sidebar_title": "YC's Flight Deal Dashboard",
        "sidebar_caption": "Asia outer-port (KUL/CGK/BKK/ICN) → Middle East → Spain",
        "title": "✈️ YC's Outer-Port Flight Deal Dashboard",
        "subtitle": "**KUL · CGK · BKK · ICN → Middle East → Spain (MAD/BCN)** · All business class",

        # Sidebar
        "lang_label": "🌐 Language",
        "filters_override": "### 🎛️ Filters (override defaults)",
        "max_risk": "Max connection failure risk (%)",
        "max_fatigue": "Max fatigue index",
        "min_savings": "Min savings vs TPE direct (%)",
        "allowed_verdicts": "Allowed Jev verdicts",
        "yc_original_filters": "### ⚙️ YC's original filter rules",
        "evaluated_at": "Evaluated at: {ts}",
        "language_english": "English",
        "language_chinese": "繁體中文",
        "min_aircraft": "Min aircraft comfort (1-10)",
        "min_aircraft_help": "Min comfort score (Jev scores A380/A350/B787 ≈ 9-10; older 777 ≈ 4-6)",
        "max_risk_help": "Max connection failure probability (25% default)",
        "reset_filters_btn": "🚀 Apply YC recommended filters",
        "filters_recommended_caption": "YC's recommended defaults: risk ≤ 25%, fatigue ≤ 7.5, save ≥ 35%, aircraft ≥ 4, prime_deal + acceptable_economy",

        # User preference filters (soft: prefer but don't hard-exclude)
        "user_prefs_header": "### 🎯 Travel companion's preferences",
        "excluded_carriers": "❌ Avoid these carriers (warning, not blocking)",
        "excluded_carriers_help": "Carrier codes to flag (e.g., LH = Lufthansa, BA = British Airways). Will show warning icon on cards.",
        "preferred_aircraft": "✈️ Preferred aircraft types (priority boost)",
        "preferred_aircraft_help": "Aircraft types to boost in ranking (e.g., A380, A350, B787). Top 3 may reorder.",
        "tag_excluded": "⚠ Excluded by you",
        "tag_preferred": "✈ Preferred aircraft",
        "tag_codeshare": "⚠ Codeshare",

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

        # Filter controls
        "reset_filters_btn": "🚀 Apply YC recommended filters",
        "filters_recommended_caption": "YC's recommended defaults: risk ≤ 25%, fatigue ≤ 7.5, save ≥ 35%, aircraft ≥ 4, prime_deal + acceptable_economy",
        "max_risk_help": "Max connection failure probability (25% default)",
        "min_aircraft": "Min aircraft comfort (1-10)",
        "min_aircraft_help": "Min comfort rating (Jev scores A380/A350/B787 ≈ 9-10; older 777 ≈ 4-6)",


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
        "sidebar_caption": "亞洲外站 (KUL/CGK/BKK/ICN) → 中東轉機 → 西班牙",
        "title": "✈️ YC 外站機票比價看板",
        "subtitle": "**KUL · CGK · BKK · ICN → 中東轉機 → 西班牙 (MAD/BCN)** · 全商務艙",

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
        "min_aircraft": "機型舒適度下限 (1-10)",
        "min_aircraft_help": "最低舒適度分數（Jev 評 A380/A350/B787 ≈ 9-10；老款 777 ≈ 4-6）",
        "max_risk_help": "連接失敗概率上限（預設 25%）",
        "reset_filters_btn": "🚀 套用 YC 推薦過濾器",
        "filters_recommended_caption": "YC 推薦預設值：風險 ≤ 25%、疲勞 ≤ 7.5、省幅 ≥ 35%、機型 ≥ 4，允許 prime_deal + acceptable_economy",

        # 用戶偏好 filter（soft：標籤警告，不硬性排除）
        "user_prefs_header": "### 🎯 旅伴偏好",
        "excluded_carriers": "❌ 避開這些航空（警告，不硬性排除）",
        "excluded_carriers_help": "要標記的航空代碼（例如 LH = 漢莎、BA = 英航）。卡片會顯示警告圖示。",
        "preferred_aircraft": "✈️ 偏好機型（排序優先）",
        "preferred_aircraft_help": "要優先排序的機型（例如 A380、A350、B787）。Top 3 可能會重排。",
        "tag_excluded": "⚠ 你想避開",
        "tag_preferred": "✈ 偏好機型",
        "tag_codeshare": "⚠ 代碼共享",

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


# === Seasonal pricing data + best-time-by-destination ===
# Pricing category: "cheap", "moderate", or "peak"
SEASONAL_DATA = {
    "en": [
        ("March",        "cheap",    "Light Easter traffic, snow on Alps", "West/South Europe great"),
        ("April",        "moderate", "Easter shift can spike some weeks", "Avoid Easter week"),
        ("May",          "moderate", "Decent weather, decent prices",     ""),
        ("June",         "moderate", "School breaks begin",                ""),
        ("July",         "peak",     "School summer holiday",              "Mediterranean is 35°C+"),
        ("August",       "peak",     "High season",                        "Avoid Southern Europe heat"),
        ("September",    "cheap",    "Kids back to school, prices drop",   "Great weather in Spain"),
        ("October",      "cheap",    "Mid-Oct to early-Dec best window",   "10 月是歐洲旅遊甜點"),
        ("November",     "cheap",    "Same window as Oct",                 "Christmas markets begin"),
        ("December 15-31","peak",    "Christmas/New Year",                 "Avoid"),
        ("Jan–mid Feb",   "cheap",    "Post-holiday lull",                  "OK to fly"),
        ("Mid-Feb–Mar",   "cheap",    "Same window",                        ""),
    ],
    "zh": [
        ("3 月",         "cheap",    "復活節前、日本賞櫻結束",            "西歐 / 南歐天氣恢復"),
        ("4 月",         "moderate", "復活節所在週可能飆價",              "避開復活節那週"),
        ("5 月",         "moderate", "天氣佳、價格中等",                  ""),
        ("6 月",         "moderate", "暑假開始前夕",                      ""),
        ("7 月",         "peak",     "學生放暑假",                        "南歐地中海 35°C+"),
        ("8 月",         "peak",     "旅遊最高峰",                        "避免南歐高溫"),
        ("9 月",         "cheap",    "學生開學，票價回檔",                "西班牙天氣最佳"),
        ("10 月",        "cheap",    "10月中到12月初 → 最佳購票期",       "歐洲秋景 + 票甜"),
        ("11 月",        "cheap",    "10月中到12月初這段延伸",            "耶誕市集開始"),
        ("12/15-31",     "peak",     "聖誕 + 跨年",                       "避免"),
        ("1 月-2月初",   "cheap",    "節慶後空窗",                        "適合出發"),
        ("2 月中-3 月",  "cheap",    "同上視窗",                          ""),
    ],
}

DESTINATION_BEST_TIME = {
    "en": {
        "MAD": "Madrid — Apr–Jun, Sep–Oct best (sun + 22°C, low humidity)",
        "BCN": "Barcelona — May–Jun, Sep (city breaks ok; Aug too hot)",
        "CDG": "Paris — Apr–Jun, Sep–early Oct",
        "FCO": "Rome — Apr, May, Sep–Oct (skip Aug 35°C+ heat)",
        "AMS": "Amsterdam — Apr–May, Sep (tulips / autumn)",
        "ZRH": "Zurich — Jun–Sep (Swiss Alps year-round but snowy highlands)",
        "FRA": "Frankfurt — May–Jun, Sep (Christmas markets in Dec)",
    },
    "zh": {
        "MAD": "馬德里 — 4-6 月、9-10 月最佳（日照 + 22°C 不潮濕）",
        "BCN": "巴塞隆納 — 5-6 月、9 月；8 月太熱",
        "CDG": "巴黎 — 4-6 月、9 月到 10 月初",
        "FCO": "羅馬 — 4 月、5 月、9-10 月（避開 8 月 35°C+）",
        "AMS": "阿姆斯特丹 — 4-5 月、9 月（鬱金香 / 秋景）",
        "ZRH": "蘇黎世 — 6-9 月（阿爾卑斯全年可去但冬天雪封）",
        "FRA": "法蘭克福 — 5-6 月、9 月；12 月聖誕市集",
    },
}

# Calendar tab translations
I18N_CALENDAR = {
    "en": {
        "tab_calendar": "🗓️ Booking Calendar",
        "cal_title": "Best time to buy Europe flights",
        "cal_caption": "Curated from deal-hunter rules of thumb",
        "cal_season_header": "📅 Month-by-Month Pricing",
        "cal_dest_header": "📍 Best Season by Destination",
        "cal_dest_caption": "Match window to destination for max comfort + low cost",
        "cal_cheap": "Cheap",
        "cal_peak": "Peak (avoid)",
        "cal_moderate": "Moderate",
        "cal_pro_tips_header": "Pro booking tips",
        "cal_pro_tips_body": """- Book **Tue-Thu 00:00-03:00 TPE time** — fare classes often reset
- Web search "Star Alliance cheap business class XYZ-2027" 6-8 weeks before
- Open-jaw (one-way each leg) sometimes cheaper than round-trip
- Positioning flights via ICN (TW) cheapest for KR/JP/Taiwan residents""",
    },
    "zh": {
        "tab_calendar": "🗓️ 購票時機",
        "cal_title": "買歐洲機票的最佳時機",
        "cal_caption": "整理自出國達人建議（你旅伴的智慧）",
        "cal_season_header": "📅 各月票價走勢",
        "cal_dest_header": "📍 各目的地最佳季節",
        "cal_dest_caption": "把窗 + 目的地時間對齊會最舒服、最便宜",
        "cal_cheap": "便宜期",
        "cal_peak": "貴期（避免）",
        "cal_moderate": "中等",
        "cal_pro_tips_header": "搶票小技巧",
        "cal_pro_tips_body": """- 週二到週四 **凌晨 0-3 點（TPE 時間）** 上網搶票，fare class 會重置
- 出發前 6-8 週搜「星盟 2027 4 月商務艙 X」之類的關鍵字
- **Open-jaw**（去回不同機場）有時候比 round-trip 便宜
- 台灣出發走 ICN（虎航）最便宜的 KR/JP/Taiwan 三角接管""",
    },
}

# Merge calendar translations into main T dict
for lang in ["en", "zh"]:
    if lang in T:
        for key, val in I18N_CALENDAR[lang].items():
            T[lang][key] = val


# Layout preference labels (used by layout_detector + flight_dashboard)
LAYOUT_I18N = {
    "en": {
        "layout_label": "📐 Layout",
    },
    "zh": {
        "layout_label": "📐 版面",
    },
}

for lang in ["en", "zh"]:
    if lang in T:
        for key, val in LAYOUT_I18N[lang].items():
            T[lang][key] = val

# Aircraft comfort knowledge base
# comfort_score: 1-5 ★ (5 = modern latest-gen business, 1 = old/codeshare cramped)
# Common types across our airlines:
AIRCRAFT_DATA = {
    "A380":       {"comfort": 5, "notes_zh": "雙層巨無霸 安靜穩，長途首選",            "notes_en": "Double-decker, quiet, stable"},
    "A350-900":   {"comfort": 5, "notes_zh": "最新世代、安靜、氣壓調整舒適",         "notes_en": "Latest gen, quiet, smooth pressure"},
    "A350-1000":  {"comfort": 5, "notes_zh": "最現代遠程機",                       "notes_en": "Modern longest-range"},
    "B787-9":     {"comfort": 5, "notes_zh": "最現代、濕度佳、窗戶電子變色",       "notes_en": "Modern, better humidity, e-dim windows"},
    "B787-10":    {"comfort": 5, "notes_zh": "B787 加大版",                       "notes_en": "B787 stretched"},
    "B777-300ER": {"comfort": 4, "notes_zh": "穩定但舊款座椅",                     "notes_en": "Stable but older seats"},
    "B777-200ER": {"comfort": 3, "notes_zh": "老舊 777-200，商務艙椅距窄",         "notes_en": "Older 777-200, cramped J cabin"},
    "B777-200LR": {"comfort": 3, "notes_zh": "長程版，但常被指定為舊艙等",          "notes_en": "Long-range, often old config"},
    "A330-300":   {"comfort": 4, "notes_zh": "中距離適合、機型尚新",               "notes_en": "Mid-range, decent age"},
    "A330-200":   {"comfort": 3, "notes_zh": "舊款 A330",                         "notes_en": "Older A330"},
    "B737":       {"comfort": 3, "notes_zh": "短程經濟/商務窄體",                  "notes_en": "Short-range narrowbody"},
    "A321neo":    {"comfort": 4, "notes_zh": "中型新世代",                        "notes_en": "Modern mid-size"},
    "A320neo":    {"comfort": 4, "notes_zh": "中型新世代",                        "notes_en": "Modern mid-size"},
    "B737-MAX":   {"comfort": 4, "notes_zh": "B737 改進版",                       "notes_en": "Improved B737"},
}

# Codeshare warnings — flights sold by one carrier but flown by another
# (very common in Asia outer-port; e.g., QR sells but MH operates)
COMMON_CODESHARES = {
    "MH": "Malaysia Airlines",
    "TR": "Scoot (Low-cost subsidiary of SQ)",
    "7C": "Jeju Air (Korean low-cost)",
    "TW": "Tigerair Taiwan",
    "KE": "Korean Air",
    "OZ": "Asiana",
    "JL": "Japan Airlines",
    "NH": "ANA",
    "EK": "Emirates (self)",
    "QR": "Qatar Airways (self)",
    "SQ": "Singapore Airlines (self)",
    "TK": "Turkish Airlines (self)",
    "LH": "Lufthansa (self)",
    "BA": "British Airways",
    "AF": "Air France",
    "KL": "KLM",
}


# Fleet age — typical for the airline (years on average)
# Used when individual segment age is unknown
AIRLINE_AVG_FLEET_AGE = {
    "Emirates": 7.5,         # EK 機隊較新
    "Qatar Airways": 8.0,    # QR
    "Etihad": 9.0,           # EY
    "Turkish Airlines": 9.5, # TK
    "Lufthansa": 13.0,       # LH 機隊偏舊
    "Finnair": 11.0,
    "Singapore Airlines": 7.0,  # SQ 最先進
    "Korean Air": 11.5,
    "Asiana": 12.0,
    "Malaysia Airlines": 13.0,  # MH 機隊偏舊
}


def aircraft_comfort_score(aircraft_type: str) -> int:
    """Look up comfort score (1-5). Falls back to 3 if unknown."""
    if not aircraft_type:
        return 3
    if aircraft_type in AIRCRAFT_DATA:
        return AIRCRAFT_DATA[aircraft_type]["comfort"]
    # Try prefix match (e.g. "A350-900ER" → "A350-900")
    for prefix in sorted(AIRCRAFT_DATA.keys(), key=len, reverse=True):
        if aircraft_type.startswith(prefix):
            return AIRCRAFT_DATA[prefix]["comfort"]
    return 3


def is_codeshare(marketing: str, operating: str) -> bool:
    """True if operating carrier differs from marketing carrier."""
    if not marketing or not operating:
        return False
    return marketing.upper() != operating.upper()

# Aircraft tab translations
AIRCRAFT_I18N = {
    "en": {
        "tab_aircraft": "✈️ Aircraft info",
        "acf_title": "Aircraft comfort & codeshare alerts",
        "acf_caption": "Long-haul business-class seat comfort and operator consistency",
        "acf_codeshare_warning_header": "Codeshare warnings",
        "acf_codeshare_caption": "Flights below have a different operator than the marketing carrier — cabin product may differ",
        "acf_legend_header": "Comfort legend",
        "acf_legend_body": (
            "- ★5 = A380, A350, B787 (latest gen, ideal)\n"
            "- ★4 = B777-300ER (modern)\n"
            "- ★3 = Older 777-200, A330 (mid-age)\n"
            "- ★2 = codeshare with downgrade risk\n"
            "- ★1 = old config / very cramped"
        ),
        "metrics_aircraft_score": "Aircraft comfort (1-10)",
        "metrics_aircraft_breakdown": "Per-segment aircraft details",
    },
    "zh": {
        "tab_aircraft": "✈️ 機型資訊",
        "acf_title": "機型舒適度 & 代碼共享警訊",
        "acf_caption": "長程商務艙座椅舒適度與執飛一致性",
        "acf_codeshare_warning_header": "代碼共享警告",
        "acf_codeshare_caption": "以下航班執飛航空與銷售航空不同 — 艙等與服務可能有差異",
        "acf_legend_header": "舒適度圖例",
        "acf_legend_body": (
            "- ★5 = A380、A350、B787（最新世代，推薦）\n"
            "- ★4 = B777-300ER（現代機型）\n"
            "- ★3 = 老款 777-200、A330（中等年齡）\n"
            "- ★2 = 代碼共享，艙等可能降級\n"
            "- ★1 = 老舊艙 / 非常擁擠"
        ),
        "metrics_aircraft_score": "機型舒適度 (1-10)",
        "metrics_aircraft_breakdown": "每段航班的機型細節",
    },
}

for lang in ["en", "zh"]:
    if lang in T:
        for key, val in AIRCRAFT_I18N[lang].items():
            T[lang][key] = val
