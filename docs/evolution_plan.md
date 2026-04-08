# Lobster 演化計畫書：從 Content Bot → Autonomous Evolving Agent

> 最後更新：2026-04-07
> 目標：讓龍蝦成為能自主探索、學習、演化的系統（對標小金級能力）
> 原則：成本效率優先、漸進式實作、每階段可獨立驗收

---

## 你給的建議 vs 我們的現狀

| 建議 | 現狀 | 評估 |
|------|------|------|
| Headless Browser (Playwright) | ❌ 無 | ✅ 高價值，應優先 |
| Docker 虛擬桌面 (noVNC) | ❌ 無 | 🟡 中期，先做 headless |
| Computer Use API | ❌ 無 | 🟡 中期，依賴桌機 |
| Docker 容器化隔離 | ❌ 單一 process | ✅ 高價值但不急 |
| n8n / LangFlow | ❌ 用 APScheduler | 🔴 不建議，現有架構夠用 |
| CrewAI / PydanticAI | ❌ 無 agent framework | ✅ 高價值，Phase 2 |
| Tavily / Serper API | ✅ 已有 Tavily | 🟡 可加 Serper 備援 |
| Google Drive / S3 | ❌ 無 | 🟡 Phase 2 |
| FFmpeg 剪影片 | ❌ 無 | 🔴 非核心，暫不做 |
| MoviePy | ❌ 無 | 🔴 非核心 |
| 沙盒化 (Docker sandbox) | ❌ 無 | ✅ 有 code execution 時必要 |
| 環境變數隔離 | ✅ 已做 | 維持 |
| 預算上限 (max_iterations) | ✅ 有 token budget | 🟡 需加 per-task 上限 |

**結論**：你的建議大部分方向正確。我們已有基礎（Tavily、env 隔離、budget），缺的是**主動探索能力**（headless browser）、**多步推理**（agent framework）、**自主演化**（feedback loop）。影片剪輯和 n8n 不是核心路徑。

---

## Phase 0：基礎強化（1-2 週，零成本）

> 目標：讓現有系統的資訊輸入品質和利用率大幅提升

### 0.1 啟用向量搜尋 + 自我記憶

**問題**：vector search 函數已寫好但沒用，龍蝦不記得自己說過什麼。

**做法**：
```python
# 在 explore 時產生 embedding，存入 discoveries.embedding
# 在 create_post 前，用向量搜尋檢查是否已發過類似內容
# 在反思時，用向量搜尋找到相關歷史 discovery 做對比

# 用 OpenRouter 的 embedding API 或免費的 Jina Embedding
# Jina: https://api.jina.ai/v1/embeddings (免費 1M tokens/月)
```

**成本**：$0（Jina Embedding 免費）
**價值**：避免重複內容 + 建立長期記憶基礎

### 0.2 動態搜尋 query 生成

**問題**：搜尋 query 是硬編碼的，永遠搜一樣的東西。

**做法**：
```python
# 每次 explore 前，讀取 curiosity.md
# 讓 LLM 根據近期興趣 + 過去搜尋結果 + 表現好的主題
# 生成 3-5 個新 query
# 保留 1-2 個固定 query 確保基本覆蓋
```

**成本**：每次多一個 LLM call (~$0.01)
**價值**：搜尋結果從「google 一樣無聊」→「跟著興趣演進」

### 0.3 Engagement 反饋迴路

**問題**：追蹤了 engagement 但資料躺在那裡。

**做法**：
```python
# 在 create_post 的 skill 選擇階段，加入歷史表現數據：
# "過去 30 天，research_commentary 平均 engagement X，
#  cross_domain 平均 Y，hot_take 平均 Z"
# 讓 LLM 不只選「最適合」的 skill，也參考「歷史上最有效」的

# 在 reflect 階段，計算各 skill 的 engagement 趨勢
# 寫入 memory.md
```

**成本**：$0（只是多一個 DB query）
**價值**：龍蝦開始「學」什麼有效

### 0.4 學術資料來源

**問題**：只靠 Tavily，找不到最新論文。

**做法**：
```python
# 加入免費 API：
# 1. arXiv API (完全免費，無需 key)
#    endpoint: http://export.arxiv.org/api/query
# 2. Semantic Scholar API (免費 100 req/5min)
#    endpoint: https://api.semanticscholar.org/graph/v1/paper/search
# 3. PubMed E-utilities (完全免費)
#    endpoint: https://eutils.ncbi.nlm.nih.gov/entrez/eutils/

# 在 explorer/ 下新增 academic.py
# morning explore 加入學術搜尋
```

**成本**：$0（全部免費 API）
**價值**：**巨大**——直接解決「跟 google 一樣無聊」的核心問題

---

## Phase 1：主動探索能力（2-4 週，低成本）

> 目標：龍蝦能主動深入探索，不只看搜尋結果的摘要

### 1.1 Playwright 無頭瀏覽器

**問題**：Jina 只能讀純文字，很多網頁需要 JS render。

**做法**：
```python
# requirements.txt 新增 playwright
# explorer/ 新增 browser.py

class HeadlessBrowser:
    async def read_page(self, url: str) -> str:
        """完整渲染網頁後取文字，支援 JS render"""
    
    async def screenshot(self, url: str) -> str:
        """截圖回傳路徑，供未來多模態 LLM 理解"""
    
    async def extract_links(self, url: str) -> list:
        """提取頁面所有連結，支援深度探索"""

# 在 Railway Dockerfile 中安裝 chromium
# Procfile: 加入 playwright install chromium
```

**成本**：Railway 記憶體需求增加 ~200MB
**價值**：能讀 JS-heavy 網頁、截圖、為 Computer Use 打基礎

### 1.2 深度探索鏈（Multi-step Research）

**問題**：Spawn 只做一次 LLM call，不是真正的研究。

**做法**：
```python
# agent/deep_research.py

async def deep_research(discovery, db, llm, browser):
    """
    多步研究流程：
    1. 讀取 discovery 原文（Jina 或 Playwright）
    2. LLM 產生 3 個 follow-up 問題
    3. 對每個問題做 Tavily 搜尋
    4. 讀取最相關的 2 個結果
    5. LLM 綜合所有資料，產生研究報告
    6. 存入 discoveries.raw_content（豐富版）
    """
    # interest_score >= 8 時觸發
    # 有 max_steps=5 防止無限迴圈
    # 有 per-research token budget
```

**成本**：每次深度研究 ~$0.10-0.20（3-5 個 LLM call）
**價值**：從「看到標題評分」升級為「真正理解內容後評分」

### 1.3 PDF 全文解析

**問題**：學術論文多為 PDF，目前無法讀取。

**做法**：
```python
# explorer/pdf_reader.py
# 選項 A: pymupdf4llm (免費，本地解析)
# 選項 B: Jina Reader 支援 PDF URL
# 選項 C: 如有桌機，用 marker 或 nougat 做 OCR

# 在 explore 流程中：
# if url.endswith('.pdf'):
#     content = await pdf_reader.extract(url)
```

**成本**：$0（pymupdf4llm 免費）
**價值**：能讀論文全文，學術探索能力質變

---

## Phase 2：多 Agent 協作 + 自主演化（4-8 週，中等成本）

> 目標：龍蝦從「一隻」變成「一群」，開始自主演化

### 2.1 Agent 角色分化

**做法**：
```python
# 不用 CrewAI（太重），用輕量自建：

class AgentRole:
    EXPLORER = "explorer"      # 負責找素材
    CRITIC = "critic"          # 負責挑毛病
    WRITER = "writer"          # 負責寫稿
    EDITOR = "editor"          # 負責潤稿
    STRATEGIST = "strategist"  # 負責選題和 skill

# create_post 流程變成：
# 1. Strategist 看所有 discoveries + 歷史表現 → 選題 + 選 skill
# 2. Writer 寫初稿
# 3. Critic 挑毛病（取代 hook evaluator 的硬規則）
# 4. Editor 根據 Critic 意見改稿
# 5. 最終品質檢查（AI smell + number validator 保留）
```

**成本**：每篇文章從 1-2 個 LLM call → 4-5 個，成本 ×2-3
**價值**：品質大幅提升 + 能自我辯論

### 2.2 自主演化機制

**問題**：Mirror 提出建議但需人工批准，演化太慢。

**做法**：
```python
# 分級自主權：

AUTONOMY_LEVELS = {
    "low_risk": {
        # 自動執行，Telegram 通知
        "examples": [
            "調整搜尋 query 權重",
            "更新 curiosity.md",
            "調整 skill 選擇偏好",
            "新增 RSS 來源",
        ]
    },
    "medium_risk": {
        # 先通知，24小時無否決自動執行
        "examples": [
            "修改 style.md 的語氣描述",
            "新增一個 skill",
            "調整發文頻率",
        ]
    },
    "high_risk": {
        # 必須人工批准
        "examples": [
            "修改 soul.md 核心價值",
            "更換 LLM 模型",
            "修改預算",
            "開啟 proactive engagement",
        ]
    }
}

# Mirror 執行 low_risk 改變後直接生效
# medium_risk 用 Telegram inline button：[批准] [否決]
# high_risk 必須 /approve
```

**成本**：$0（邏輯改動）
**價值**：**核心演化能力的基礎**

### 2.3 實驗框架

**做法**：
```python
# db 新增 experiments 表

# experiments: {
#   id, hypothesis, variant_a, variant_b, metric,
#   start_date, end_date, results, conclusion
# }

# 例：
# hypothesis: "hot_take skill 在週五表現比週一好"
# variant_a: 週一發 hot_take
# variant_b: 週五發 hot_take
# metric: engagement_24h.likes + engagement_24h.retweets
# duration: 4 weeks
# 由 Strategist agent 自動設計和評估實驗
```

**成本**：$0（邏輯改動）
**價值**：從「憑感覺」到「有數據」的演化

---

## Phase 3：桌機 + Computer Use（8-12 週，需硬體投資）

> 目標：龍蝦能操作電腦，具備小金等級的能力
> 前提：已購入桌機

### 3.1 本地 LLM 部署

**做法**：
```bash
# 桌機安裝 ollama
# 模型選擇：
# - Llama 3.1 8B (一般任務，快速)
# - Qwen 2.5 14B (中文任務，品質好)
# - Mistral 7B (英文任務)

# 用途：
# 1. 批量處理（embedding、初步篩選）→ 省 API 費
# 2. 實驗性質的 agent 對話 → 不怕燒錢
# 3. 本地隱私敏感任務
# 4. API 備援

# 暴露 API：ollama serve → http://桌機IP:11434
# Railway 龍蝦可以透過 tailscale 隧道呼叫桌機 LLM
```

**成本**：NT$40,000-60,000（一次性）+ NT$500/月電費
**價值**：解鎖無限實驗 + 降低 API 成本

### 3.2 Code Execution Sandbox

**做法**：
```python
# 桌機用 Docker 跑 code sandbox

# agent/code_executor.py
class CodeExecutor:
    async def execute_python(self, code: str) -> str:
        """在 Docker sandbox 中執行 Python 程式碼"""
        # 使用 docker SDK
        # 限制：無網路、無檔案系統、10秒 timeout
        # 回傳 stdout + stderr
    
    async def execute_r(self, code: str) -> str:
        """在 Docker sandbox 中執行 R 程式碼（統計分析）"""

# 用途：
# 1. 龍蝦可以自己算統計（驗證論文數據）
# 2. 產生資料視覺化圖片
# 3. 做簡單的 meta-analysis
```

**成本**：$0（Docker 免費）
**價值**：龍蝦能「算」不只能「讀」

### 3.3 Computer Use（進階）

**做法**：
```python
# 桌機 Docker 跑 noVNC 容器
# Anthropic Computer Use Beta 或自建

# 初期用例（保守）：
# 1. 自動登入 Google Scholar 追蹤引用
# 2. 自動下載 PDF 論文
# 3. 截圖特定網頁的圖表

# 不做（風險太高）：
# 1. 自動操作銀行/帳號
# 2. 自動發送 email
# 3. 任何需要密碼的操作
```

**成本**：Docker 容器 RAM ~1-2GB
**價值**：解鎖無法用 API 完成的任務

---

## Phase 4：長期願景（12+ 週）

### 4.1 知識圖譜
- discoveries 之間建立關聯（引用、相似、衝突、延伸）
- 龍蝦能說「這跟我三個月前發現的 X 有關」
- 使用 Neo4j 或 Supabase + JSONB 關聯

### 4.2 多模態輸出
- 用 matplotlib/plotly 自動生成資料圖
- 用 Pillow 做簡單的資訊圖
- 附圖發文（X + Threads 都支援）

### 4.3 Newsletter / 長文
- 週報自動生成（本週最佳 discoveries + 龍蝦觀點）
- 用 Substack API 或自建 blog

### 4.4 社群互動升級
- 追蹤特定領域 KOL 的討論
- 主動參與 Thread 討論串（不只回覆自己的）
- 跨平台內容聯動

---

## 成本估算總覽

| Phase | 時間 | 額外月費 | 一次性成本 | 核心價值 |
|-------|------|---------|-----------|---------|
| **0: 基礎強化** | 1-2 週 | +$0 | $0 | 搜尋品質↑, 自我記憶, 反饋迴路 |
| **1: 主動探索** | 2-4 週 | +$2-5 | $0 | 深度研究, PDF, 瀏覽器 |
| **2: 多 Agent + 演化** | 4-8 週 | +$5-10 | $0 | 自主演化, 實驗框架 |
| **3: 桌機 + Computer Use** | 8-12 週 | +$500 電費 | NT$50,000 | 本地 LLM, Code execution |
| **4: 長期願景** | 12+ 週 | 視規模 | 視規模 | 知識圖譜, 多模態 |

**建議路徑**：0 → 1 → 2 → 決定是否買桌機 → 3 → 4

Phase 0-2 完全不需要額外硬體投資，只需要寫程式碼。等到 Phase 2 做完，你會更清楚桌機帶來的邊際價值是否值得投資。

---

## 立即可執行的改進（本次 Push）

根據「explore 查出來的東西跟 google 一樣無聊」這個痛點，以下是最高 ROI 的改進：

### 改進 1：動態 query 生成
- 檔案：`explorer/search.py`
- 改動：explore 前先讀 curiosity.md，LLM 生成搜尋 query
- 預期效果：搜尋結果跟著龍蝦的興趣走

### 改進 2：加入 arXiv + Semantic Scholar
- 新檔案：`explorer/academic.py`
- 改動：morning explore 加入學術 API 搜尋
- 預期效果：直接找到最新論文，不再依賴 Tavily 的泛搜尋

### 改進 3：啟用向量去重
- 檔案：`agent/lobster.py`, `db/client.py`
- 改動：explore 時生成 embedding，create_post 前向量搜尋去重
- 預期效果：不再重複發類似內容

### 改進 4：Engagement feedback → Skill 選擇
- 檔案：`agent/lobster.py`, `agent/prompts.py`
- 改動：create_post 時加入歷史 engagement 數據
- 預期效果：龍蝦學會什麼有效

---

*本計畫書為活文件，隨執行進度持續更新。*
