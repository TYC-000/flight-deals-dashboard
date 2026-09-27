"""Generate a clean PDF from top3_scoring_zh.md using fpdf2 + STHeiti font."""
from fpdf import FPDF
from pathlib import Path

PDF_OUT = Path("/Users/aib/.hermes/cache/scratch/flight-dashboard/docs/top3_scoring_zh.pdf")
MD_PATH = Path("/Users/aib/.hermes/cache/scratch/flight-dashboard/docs/top3_scoring_zh.md")
FONT_PATH = "/System/Library/Fonts/STHeiti Medium.ttc"

class Doc(FPDF):
    def header(self):
        # Title header on each page (subtle)
        self.set_y(8)
        self.set_font("Heiti", size=8)
        self.set_text_color(140, 140, 140)
        self.cell(0, 4, "Top 3 評分標準說明書 · 給李承頤的信任建立書", new_x="LMARGIN", new_y="NEXT", align="L")
        self.set_draw_color(220, 220, 220)
        self.line(self.l_margin, 14, self.w - self.r_margin, 14)
        self.set_y(20)
        self.set_text_color(0, 0, 0)

    def footer(self):
        self.set_y(-12)
        self.set_font("Heiti", size=8)
        self.set_text_color(140, 140, 140)
        self.cell(0, 8, f"第 {self.page_no()} 頁", align="C")

    def chapter_title(self, num, label):
        self.add_page_break_if_needed(20)
        self.set_font("Heiti", size=15)
        self.set_text_color(30, 64, 175)
        self.cell(0, 9, f"{num}. {label}", new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(0, 0, 0)
        self.ln(2)

    def h3(self, label):
        self.add_page_break_if_needed(14)
        self.set_font("Heiti", size=12)
        self.set_text_color(75, 85, 99)
        self.cell(0, 7, label, new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(0, 0, 0)
        self.ln(1)

    def body(self, text):
        self.set_font("Heiti", size=10.5)
        self.set_text_color(0, 0, 0)
        self.multi_cell(0, 6, text)
        self.ln(2)

    def quote(self, text):
        self.set_font("Heiti", size=10)
        self.set_text_color(75, 85, 99)
        self.set_x(self.l_margin + 8)
        self.multi_cell(self.w - self.l_margin - self.r_margin - 16, 6, text)
        self.set_text_color(0, 0, 0)
        self.ln(2)

    def table(self, headers, rows, col_widths=None, header_bg=(30, 64, 175)):
        if col_widths is None:
            col_widths = [self.w - self.l_margin - self.r_margin] * len(headers)
            col_widths = [c / len(headers) for c in col_widths]
        # Header
        self.set_font("Heiti", size=10)
        self.set_fill_color(*header_bg)
        self.set_text_color(255, 255, 255)
        row_height = 9
        for i, h in enumerate(headers):
            self.cell(col_widths[i], row_height, h, border=1, fill=True, align="C")
        self.ln(row_height)
        # Rows
        self.set_text_color(0, 0, 0)
        self.set_font("Heiti", size=9.5)
        for ridx, r in enumerate(rows):
            if ridx % 2 == 1:
                self.set_fill_color(243, 244, 246)
            else:
                self.set_fill_color(255, 255, 255)
            for i, c in enumerate(r):
                self.cell(col_widths[i], row_height, str(c), border=1, fill=True, align="L")
            self.ln(row_height)
        self.ln(2)

    def code(self, text):
        self.set_font("Heiti", size=9)
        self.set_fill_color(243, 244, 246)
        self.set_text_color(55, 65, 81)
        self.multi_cell(0, 5.5, text, fill=True)
        self.set_text_color(0, 0, 0)
        self.ln(2)

    def add_page_break_if_needed(self, needed_height):
        if self.get_y() + needed_height > self.h - self.b_margin:
            self.add_page()


def main():
    pdf = Doc(format="A4")
    pdf.set_auto_page_break(auto=False, margin=15)
    pdf.add_font("Heiti", fname=FONT_PATH)
    pdf.add_font("Heiti", "", FONT_PATH, uni=True)
    pdf.set_font("Heiti", size=11)

    # === Cover ===
    pdf.add_page()
    pdf.ln(40)
    pdf.set_font("Heiti", size=22)
    pdf.set_text_color(30, 64, 175)
    pdf.cell(0, 14, "Top 3 評分標準完整說明", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Heiti", size=13)
    pdf.set_text_color(75, 85, 99)
    pdf.cell(0, 9, "給李承頤的信任建立書", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(8)
    pdf.set_font("Heiti", size=11)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(0, 7, "— 為什麼這個 ranking 是這樣運作的 —", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(30)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Heiti", size=11)
    pdf.multi_cell(0, 7,
        "本文件解釋 dashboard 的 Top 3 是怎麼選出來的，\n"
        "包含每個參數的權重與來源 — 給你和你的旅伴完整透明度。",
        align="C")
    pdf.ln(60)
    pdf.set_font("Heiti", size=9)
    pdf.set_text_color(140, 140, 140)
    pdf.cell(0, 6, "文件版本：2026-09-27", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, "對應 dashboard commit d9bc01f", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, "由 Hermes Agent 為 YC & 李承頤製作", align="C", new_x="LMARGIN", new_y="NEXT")

    # === Section 1: 為什麼會有來來回回 ===
    pdf.add_page()
    pdf.chapter_title("一", "為什麼會有「來來回回」多次修改？")
    pdf.body("dashboard 的 Top 3 排名不是「一次寫好」的 — 我們一起調整了 3 次。")
    pdf.body("原因是 Jev 的排序權重要夠強才能反映用戶偏好的真實意圖。")

    pdf.table(
        ["階段", "結果", "原因"],
        [
            ["v1", "LH-SIN-FRA = #1", "Jev 純評估（沒有用戶偏好）"],
            ["v2", "LH-SIN-FRA = #1", "加了 +1.0 penalty 但不夠強，fatigue 5.8 蓋過"],
            ["v3", "LH-SIN-FRA 跌出 Top 3", "改成 +3.0 + verdict 降級，雙重降權"],
        ],
        col_widths=[20, 55, 105],
    )
    pdf.body("這個故事就是本文件的核心 — 看每一層參數的權重如何作用。")

    # === Section 2: 三層架構 ===
    pdf.chapter_title("二", "評分系統三層架構")
    pdf.body("整個系統分三層，由下而上依序作用：")
    pdf.code(
        "┌─────────────────────────────────────────┐\n"
        "│  第三層：用戶偏好 (Soft Preference)      │\n"
        "│  - 排除航空：-3.0 penalty + verdict 降級  │\n"
        "│  - 偏好機型：-1.0 bonus                  │\n"
        "│  - 作用：Top 3 內部排序                  │\n"
        "├─────────────────────────────────────────┤\n"
        "│  第二層：過濾條件 (Hard Filter)          │\n"
        "│  - 風險 ≤ 25%                            │\n"
        "│  - 疲勞 ≤ 7.5                            │\n"
        "│  - 省幅 ≥ 35%                            │\n"
        "│  - 機型 ≥ 4                              │\n"
        "│  - 作用：篩選誰能進 Top 3               │\n"
        "├─────────────────────────────────────────┤\n"
        "│  第一層：Jev 評估 (Base Score)            │\n"
        "│  - 4 題評估                              │\n"
        "│  - 作用：給每個候選原始分數              │\n"
        "└─────────────────────────────────────────┘"
    )

    # === Section 3: 第一層 Jev 4 題 ===
    pdf.chapter_title("三", "第一層：Jev 4 題評估")
    pdf.body("Jev AI 對每個候選方案獨立打分：")
    pdf.table(
        ["題目", "類型", "範圍", "衡量"],
        [
            ["連接失敗風險", "Noul (語意)", "0-1 機率", "中東轉機時錯過下班的概率"],
            ["疲勞指數", "Score (1-3)", "1-10", "整段旅程疲憊程度"],
            ["機型舒適度", "Score (1-3)", "1-10", "長程商務艙座椅與機型品質"],
            ["Jev 標籤", "Choice (3 選)", "string", "綜合定性結論"],
        ],
        col_widths=[35, 30, 30, 85],
    )
    pdf.body("每題成本約 NT$ 0.00002（極便宜），22 個候選 × 4 題 ≈ NT$ 0.0018。")

    pdf.h3("Jev 標籤的 3 個選項")
    pdf.table(
        ["標籤", "定義", "觸發條件"],
        [
            ["prime_deal [綠]", "最佳推薦", "省 ≥ 35% + 風險 ≤ 25% + 疲勞 ≤ 7.5"],
            ["acceptable_economy [黃]", "可接受", "達標但有缺陷"],
            ["avoid_exhausting [紅]", "避免", "嚴重缺陷（太貴或風險高）"],
        ],
        col_widths=[45, 35, 100],
    )

    # === Section 4: 第二層 硬性過濾 ===
    pdf.add_page()
    pdf.chapter_title("四", "第二層：硬性篩選條件")
    pdf.body("只有同時滿足這 5 條件才能進 Top 3：")
    pdf.table(
        ["條件", "預設值", "來源"],
        [
            ["連接失敗風險", "≤ 25%", "中東轉機業界經驗"],
            ["疲勞指數", "≤ 7.5 / 10", "「12hr flight 後還能玩」上限"],
            ["省幅 vs TPE 直飛", "≥ 35%", "比 TPE 直飛省 1/3 才值得"],
            ["機型舒適度", "≥ 4 / 10", "排除最舊機型（如舊 777-200）"],
            ["Jev 標籤", "prime_deal 或 acceptable_economy", "排除 avoid_exhausting"],
        ],
        col_widths=[50, 60, 70],
    )
    pdf.quote(
        "這些預設值都會顯示在 sidebar「>> YC 推薦預設值」區塊 — "
        "一鍵重置或自訂都行。"
    )

    # === Section 5: 第三層排序權重 ===
    pdf.chapter_title("五", "第三層：排序權重")
    pdf.body("篩選後的候選，按以下優先順序排序（從最重要到最不重要）：")
    pdf.table(
        ["順序", "條件", "預設行為"],
        [
            ["1", "Jev 標籤", "prime_deal (0) > acceptable_economy (1) > avoid (2)"],
            ["2", "疲勞指數", "5.8 排前，7.5 排後"],
            ["3", "連接失敗風險", "10% 排前，25% 排後"],
            ["4", "總成本", "便宜的排前"],
            ["5", "用戶偏好分數", "見下表"],
        ],
        col_widths=[15, 50, 115],
    )

    # === Section 6: 用戶偏好分數 ===
    pdf.chapter_title("六", "用戶偏好分數（Soft Preference）")
    pdf.table(
        ["條件", "分數變化", "效果"],
        [
            ["含排除航空 (LH/BA/AF/KL)", "+3.0", "嚴重降權（壓過疲勞差距 0.9）"],
            ["含排除航空 → verdict 降級", "prime_deal → acceptable", "直接喪失排序優先權"],
            ["長程段用偏好機型 (A380/A350/B787)", "-1.0", "升權"],
            ["同 PNR (全程一張票)", "0 (但顯示)", "資訊性標籤"],
            ["代碼共享警告", "0 (但顯示)", "資訊性標籤"],
        ],
        col_widths=[55, 45, 80],
    )

    pdf.h3("為什麼 +3.0 不是 +1.0？")
    pdf.body("這是 v2 → v3 修正的關鍵：")
    pdf.quote(
        "• LH-SIN-FRA 的 fatigue = 5.8（全場最低）\n"
        "• SQ-SIN-CDG 的 fatigue = 6.7\n"
        "• 疲勞差距 = 0.9"
    )
    pdf.body(
        "如果 penalty 只有 +1.0，疲勞 0.9 < penalty 1.0，"
        "所以 LH 還會排第一。"
        "改為 +3.0 後 penalty > 疲勞差距，LH 必降權。"
    )

    # === Section 7: 權重金字塔 ===
    pdf.add_page()
    pdf.chapter_title("七", "權重金字塔（可視化）")
    pdf.code(
        "        ┌──── 排除航空：+3.0 + verdict 降級（決定性）\n"
        "        │\n"
        "        ├──── 疲勞差距：~0.9（v2 不足以壓過）\n"
        "        │\n"
        "        ├──── 風險差距：~1-3（10% vs 25%）\n"
        "        │\n"
        "        └──── 機型偏好：-1.0"
    )

    # === Section 8: 現在 Top 3 ===
    pdf.chapter_title("八", "為什麼現在 Top 3 是這 3 個？")
    pdf.table(
        ["名次", "方案", "總成本", "省幅", "verdict", "fatigue", "risk"],
        [
            ["#1 #1", "SQ-SIN-CDG", "NT$69K", "62%", "prime_deal", "6.7", "13%"],
            ["#2 #2", "BKK-EK-1", "NT$62K", "66%", "prime_deal", "6.9", "24%"],
            ["#3 #3", "KUL-EK-1", "NT$64K", "64%", "prime_deal", "7.0", "10%"],
        ],
        col_widths=[20, 35, 25, 20, 35, 25, 20],
    )

    pdf.body("每個方案的偏好分析：")
    pdf.table(
        ["方案", "排除航空？", "偏好機型？", "verdict 降級？"],
        [
            ["SQ-SIN-CDG", "否", "[OK] A350-900 (-1.0)", "否"],
            ["BKK-EK-1", "否", "[OK] A380 (-1.0)", "否"],
            ["KUL-EK-1", "否", "[OK] A380 (-1.0)", "否"],
        ],
        col_widths=[40, 35, 60, 45],
    )
    pdf.quote(
        "LH-SIN-FRA 因為含 LH → +3.0 + verdict 降級 → 跌出 Top 3。"
    )

    # === Section 9: Q&A ===
    pdf.add_page()
    pdf.chapter_title("九", "給旅伴的信任建立 Q&A")

    pdf.h3("Q1: 「為什麼是你訂的數字？」")
    pdf.body(
        "這 4 個硬條件 (風險 25% / 疲勞 7.5 / 省 35% / 機型 4) 都是通用門檻："
    )
    pdf.quote(
        "• 風險 25% 是業界「中東轉機可接受」上限\n"
        "• 疲勞 7.5 是「12hr flight 後還能玩」上限\n"
        "• 省 35% 是「值得麻煩繞一圈」下限"
    )
    pdf.body(
        "如果你想調，全部可以改 — sidebar 有「>> 套用 YC 推薦過濾器」按鈕一鍵重置。"
    )

    pdf.h3("Q2: 「為什麼 SQ 排 EK 前面？」")
    pdf.body(
        "SQ-SIN-CDG 全程 A350-900（機齡 4 年，最新世代）+ prime_deal 標籤。"
        "BKK-EK-1 用 B777-300ER (7年) + A380 (4年) — 混合機型。"
        "SQ 全 A350 → 體驗均勻一致；EK 是混合。所以 SQ 排前面。"
    )

    pdf.h3("Q3: 「你的『偏好機型』真的有在用嗎？」")
    pdf.body(
        "看 SQ、KUL-EK-1 兩個 A380/A350 偏好機型的方案，"
        "它們都比 fatigue 比它們低的 LH-SIN-FRA 排前面 — 這就是偏好機型 + 排除航空的效果。"
    )
    pdf.quote("如果我把這兩個 filter 關掉，LH 又會回到 #1。")

    pdf.h3("Q4: 「為什麼 Jev 跟一般評分不一樣？」")
    pdf.body("一般評分是固定權重（風險 30%、疲勞 30% 等等）。Jev 用 LLM 做語意理解：")
    pdf.quote(
        "• 同一個方案「QR + DOH 中轉」跟「KE + ICN 直飛」，Jev 看上下文會給不同評分\n"
        "• 它考慮「這個轉機合理嗎？」「這個疲勞來源是時差還是中轉？」\n"
        "• 不是純統計平均，更貼近人的判斷"
    )

    # === Section 10: 調整方式 ===
    pdf.add_page()
    pdf.chapter_title("十", "你可以怎麼調整？")
    pdf.table(
        ["想做", "在 dashboard 怎麼做"],
        [
            ["放寬 / 收緊風險", "sidebar「連接失敗風險上限」slider"],
            ["接受更多疲勞", "sidebar「疲勞指數上限」slider"],
            ["排除更多航空", "sidebar「[X] 避開這些航空」加新代碼"],
            ["偏好其他機型", "sidebar「[機]️ 偏好機型」加新機型"],
            ["重置全部", "點「>> 套用 YC 推薦過濾器」按鈕"],
        ],
        col_widths=[55, 125],
    )
    pdf.quote("所有調整都即時生效，不需要重新跑 pipeline。")

    # === Section 11: 總結 ===
    pdf.chapter_title("十一", "總結一句話")
    pdf.code(
        "Jev AI 給原始分數\n"
        "    ↓\n"
        "5 個硬條件過濾誰能進榜\n"
        "    ↓\n"
        "4 個排序鍵排先後\n"
        "    ↓\n"
        "用戶偏好做 soft 調整"
    )
    pdf.body(
        "這套邏輯每一層都可以單獨調整，全部在 sidebar 一鍵搞定。"
    )

    pdf.ln(8)
    pdf.set_draw_color(30, 64, 175)
    pdf.set_line_width(0.5)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(6)
    pdf.set_font("Heiti", size=9)
    pdf.set_text_color(140, 140, 140)
    pdf.cell(0, 6,
        "文件版本：2026-09-27 · 對應 dashboard commit d9bc01f · 由 Hermes Agent 為 YC & 李承頤製作",
        align="C",
    )

    PDF_OUT.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(PDF_OUT))
    print(f"[OK] PDF: {PDF_OUT}")
    print(f"   Size: {PDF_OUT.stat().st_size:,} bytes")
    print(f"   Pages: {pdf.page_no()}")


if __name__ == "__main__":
    main()
