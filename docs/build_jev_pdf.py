"""Generate a clean PDF explaining Jev's principles, for travel companion."""
from fpdf import FPDF
from pathlib import Path

PDF_OUT = Path("/Users/aib/.hermes/cache/scratch/flight-dashboard/docs/jev_explained_zh.pdf")
FONT_PATH = "/System/Library/Fonts/STHeiti Medium.ttc"


class Doc(FPDF):
    def header(self):
        self.set_y(8)
        self.set_font("Heiti", size=8)
        self.set_text_color(140, 140, 140)
        self.cell(0, 4, "Jev 是什麼？ · 一個故事版說明 · 給李承頤",
                  new_x="LMARGIN", new_y="NEXT", align="L")
        self.set_draw_color(220, 220, 220)
        self.line(self.l_margin, 14, self.w - self.r_margin, 14)
        self.set_y(20)
        self.set_text_color(0, 0, 0)

    def footer(self):
        self.set_y(-12)
        self.set_font("Heiti", size=8)
        self.set_text_color(140, 140, 140)
        self.cell(0, 8, f"第 {self.page_no()} 頁", align="C")

    def h1(self, label):
        self.add_page_break_if_needed(20)
        self.set_font("Heiti", size=15)
        self.set_text_color(30, 64, 175)
        self.cell(0, 9, label, new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(0, 0, 0)
        self.ln(2)

    def h2(self, label):
        self.add_page_break_if_needed(14)
        self.set_font("Heiti", size=12.5)
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

    def callout(self, text):
        # Highlighted box (light blue)
        self.set_font("Heiti", size=11)
        self.set_fill_color(219, 234, 254)
        self.set_text_color(30, 64, 175)
        self.multi_cell(0, 7, text, fill=True)
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
        self.set_font("Heiti", size=9.5)
        self.set_fill_color(243, 244, 246)
        self.set_text_color(55, 65, 81)
        self.multi_cell(0, 5.8, text, fill=True)
        self.set_text_color(0, 0, 0)
        self.ln(2)

    def add_page_break_if_needed(self, needed_height):
        if self.get_y() + needed_height > self.h - self.b_margin:
            self.add_page()


def main():
    pdf = Doc(format="A4")
    pdf.set_auto_page_break(auto=False, margin=15)
    pdf.add_font("Heiti", fname=FONT_PATH)
    pdf.set_font("Heiti", size=11)

    # === Cover ===
    pdf.add_page()
    pdf.ln(40)
    pdf.set_font("Heiti", size=22)
    pdf.set_text_color(30, 64, 175)
    pdf.cell(0, 14, "Jev 是什麼？", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Heiti", size=14)
    pdf.set_text_color(75, 85, 99)
    pdf.cell(0, 9, "一個故事版說明", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(8)
    pdf.set_font("Heiti", size=11)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(0, 7, "— 給李承頤 —", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(35)

    pdf.set_text_color(0, 0, 0)
    pdf.callout(
        "Jev 是一個會看機票方案的 AI 朋友。\n"
        "你跟他描述行程，他用 4 個問題評分，\n"
        "告訴你「訂」、「還行」、「別訂」。"
    )

    pdf.ln(30)
    pdf.set_font("Heiti", size=9)
    pdf.set_text_color(140, 140, 140)
    pdf.cell(0, 6, "文件版本：2026-09-27", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, "為李承頤製作 · by Hermes Agent", align="C", new_x="LMARGIN", new_y="NEXT")

    # === 1. 用一個故事來理解 ===
    pdf.add_page()
    pdf.h1("一、用一個故事來理解")

    pdf.body(
        "假設你的好朋友「阿 J」是個常出國的人。"
        "你問他：「我看到一個機票方案，要不要訂？」"
    )

    pdf.body("阿 J 看一眼，回答你：")

    pdf.quote(
        "風險：「這個轉機 45 分鐘，有點趕，可能會錯過下一班」→ 風險 7/10\n"
        "疲勞：「轉機 2 次太累了，會多花 4 小時」→ 疲勞 7/10\n"
        "飛機：「KE 用 777 還不錯」→ 機型 6/10\n"
        "結論：「不推薦」→ [紅] 別訂"
    )

    pdf.h2("Jev 就是「阿 J」，但有 4 個差別")

    pdf.table(
        ["阿 J（真人）", "Jev（AI）"],
        [
            ["看 5 個方案就累了", "看 22 個瞬間看完"],
            ["憑感覺判斷", "一致的 AI 評分"],
            ["容易漏看細節", "不會漏"],
            ["免費但費時", "兩分錢台幣"],
        ],
        col_widths=[85, 85],
    )

    # === 2. Jev 問的 4 個問題 ===
    pdf.add_page()
    pdf.h1("二、Jev 問的 4 個問題")

    pdf.h2("Q1：連接失敗風險（risk）")
    pdf.quote("意思：這個行程會不會「卡住」？")

    pdf.body("想像你從台灣飛杜拜轉機到馬德里。")
    pdf.body("• 轉機時間只有 45 分鐘 → 飛機 delay 怎麼辦？→ 高風險")
    pdf.body("• 轉機時間 3 小時 → 從容 → 低風險")
    pdf.body("Jev 看的「不只是時間」，還看：")
    pdf.body("• 兩個航班是哪家航空？（不同家航空轉機更累）")
    pdf.body("• 中東機場大不大？（DXB 比 DOH 大，動線簡單）")
    pdf.body("• 季節因素（颱風季、伊斯蘭節日）")
    pdf.body("輸出：0% - 100% 的機率")
    pdf.body("例：「這個方案錯過連程的機率是 13%」")

    pdf.h2("Q2：疲勞指數（fatigue）")
    pdf.quote("意思：到達目的地時會多累？")

    pdf.body("想像你連續玩 3 天沒睡 vs 睡滿 8 小時再玩。")
    pdf.body("Jev 計算：")
    pdf.body("• 飛行總時數（24 小時比 12 小時累）")
    pdf.body("• 中轉次數（直飛 < 1 次中轉 < 2 次中轉）")
    pdf.body("• 時差（飛 12 小時比飛 3 小時累）")
    pdf.body("• 抵達時間（早上抵達比半夜抵達好）")
    pdf.body("輸出：1-10 分")
    pdf.body("• 1 分 = 神清氣爽")
    pdf.body("• 5 分 = 普通累")
    pdf.body("• 10 分 = 累到爆")

    pdf.h2("Q3：機型舒適度（aircraft comfort）")
    pdf.quote("意思：坐的飛機新舊、好不好睡？")

    pdf.table(
        ["飛機", "比喻"],
        [
            ["A380 雙層", "飛機版的高鐵商務艙"],
            ["A350 最新世代", "高鐵商務艙"],
            ["B777-300ER 現代", "高鐵一等座"],
            ["B777-200 老款", "自強號"],
            ["A330 中年齡", "一般客運"],
        ],
        col_widths=[55, 115],
    )
    pdf.body("輸出：1-10 分（10 = 最舒服）")

    pdf.h2("Q4：Jev 標籤（verdict）")
    pdf.quote("意思：一句話結論 — 訂還是不訂？")

    pdf.table(
        ["標籤", "意思"],
        [
            ["[綠] prime_deal", "趕快訂！"],
            ["[黃] acceptable", "可以訂，但有點缺陷"],
            ["[紅] avoid_exhausting", "不要訂，太累了"],
        ],
        col_widths=[60, 110],
    )
    pdf.body("這是 Jev 整合前三題給的最終判決。")

    # === 3. 三個比喻 ===
    pdf.add_page()
    pdf.h1("三、三個比喻幫忙理解")

    pdf.h2("比喻 1：海關")
    pdf.body("你去機場，海關問你 4 個問題：")
    pdf.body("1. 你會不會錯過下一班飛機？（risk）")
    pdf.body("2. 到目的地累不累？（fatigue）")
    pdf.body("3. 飛機新不新？（aircraft）")
    pdf.body("4. 這趟值不值得？（verdict）")
    pdf.body("Jev 就是「會看行程的海關」，但他回答的不是能不能入境，"
             "而是值不值得訂。")

    pdf.h2("比喻 2：美食評論家")
    pdf.body("你去一家新餐廳，問美食評論家：")
    pdf.body("• 會不會等很久？（risk）")
    pdf.body("• 吃完會不會不舒服？（fatigue）")
    pdf.body("• 用餐環境舒不舒服？（aircraft）")
    pdf.body("• 整體值不值得推薦？（verdict）")
    pdf.body("評論家去吃一次，寫 4 個分數。"
             "你看到他的評分，就知道值不值得去。")

    pdf.h2("比喻 3：老司機朋友")
    pdf.body("你問一個常出國的朋友：「這個機票方案怎麼樣？」")
    pdf.body("他看了 5 秒說：")
    pdf.quote(
        "• 風險：「這個中轉時間只有 45 分鐘，有點趕」→ 7/10 機率出包\n"
        "• 疲勞：「轉機 2 次太累了」→ 7.5/10 累\n"
        "• 機型：「KE 用 777 還不錯」→ 6/10 舒服\n"
        "• 結論：「不推」→ avoid_exhausting"
    )
    pdf.body("Jev 就是那個老司機，但他：")
    pdf.body("• 不會忘記")
    pdf.body("• 每次評估都一致")
    pdf.body("• 兩分錢台幣不到")
    pdf.body("• 22 個方案 30 秒內看完")

    # === 4. 實際運作流程 ===
    pdf.add_page()
    pdf.h1("四、實際運作流程")
    pdf.code(
        "你貼 22 個機票方案給 Jev\n"
        "    |\n"
        "    v\n"
        "Jev 對每個方案問 4 題\n"
        "    |\n"
        "    v\n"
        "得到 4 個分數\n"
        "  (例如：風險 13% / 疲勞 6.7 / 機型 8.5 / [綠] prime_deal)\n"
        "    |\n"
        "    v\n"
        "你的 dashboard 用 4 個條件篩選\n"
        "    |\n"
        "    v\n"
        "剩下 12 個進 Top 3"
    )

    # === 5. 跟你一般訂機票的差異 ===
    pdf.h1("五、跟你一般訂機票的差異")
    pdf.table(
        ["自己做", "用 Jev"],
        [
            ["看 5 個方案就累了", "看 22 個瞬間看完"],
            ["憑感覺判斷", "一致的 AI 評分"],
            ["容易漏看細節", "不會漏"],
            ["一致性靠記憶", "永遠一致"],
            ["免費但費時", "兩分錢台幣"],
        ],
        col_widths=[85, 85],
    )

    # === 6. 給你的 30 秒版 ===
    pdf.add_page()
    pdf.h1("六、給你的 30 秒版")
    pdf.callout(
        "Jev 是一個很會看機票的 AI。\n"
        "他看每個方案會回答 4 個問題：\n"
        "1. 會不會錯過下一班？\n"
        "2. 會有多累？\n"
        "3. 飛機好不好坐？\n"
        "4. 整體值不值得？\n\n"
        "回答完，他給一句話結論：\n"
        "「趕快訂」/「還行」/「別訂」。\n\n"
        "然後 dashboard 用 4 個條件篩，\n"
        "只留 Jev 認為值得的。"
    )

    pdf.ln(8)
    pdf.set_draw_color(30, 64, 175)
    pdf.set_line_width(0.5)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(6)
    pdf.set_font("Heiti", size=9)
    pdf.set_text_color(140, 140, 140)
    pdf.cell(0, 6, "文件版本：2026-09-27 · 為李承頤製作", align="C")

    PDF_OUT.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(PDF_OUT))
    print(f"✅ PDF: {PDF_OUT}")
    print(f"   Size: {PDF_OUT.stat().st_size:,} bytes")
    print(f"   Pages: {pdf.page_no()}")


if __name__ == "__main__":
    main()
