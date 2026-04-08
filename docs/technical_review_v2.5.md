# Lobster v2.5 技術全面檢視

> 最後更新：2026-04-07
> 目標讀者：開發者本人（MD/PhD 住院醫師，lobster 主人）

---

## 一、系統總覽

Lobster v2.5 是一隻自主運營的數位龍蝦，每天透過 6 次心跳（探索×2、互動×2、創作×1-2、反思×1）在 X 和 Threads 上發表有品味的內容。週日晚間進行 Mirror 自省。部署在 Railway，資料存 Supabase，LLM 用 OpenRouter (Claude Sonnet 4.5)，Telegram 作為主人控制介面。

### 核心架構圖

```
Scheduler (APScheduler, 6+1 daily)
    │
    ▼
Lobster Agent ──── Explorer ──── Tavily / RSS / Jina / X Listener
    │                              (知識輸入)
    ├── Spawn (深度研究子agent)
    │
    ├── LLM Client (OpenRouter)
    │     └── Identity Loader (soul + style + curiosity + memory + skill)
    │
    ├── Quality Gates ──── Hook Evaluator (LLM 1-10分)
    │                 ──── AI Smell Detector (禁詞/句式)
    │                 ──── Number Validator (數字溯源)
    │
    ├── Publisher ──── X Poster (tweepy OAuth 1.0a)
    │             ──── Threads Poster (Meta Graph API)
    │             ──── Engagement Tracker (3h/24h/72h)
    │
    └── Telegram Bot (通知 + 指令)

Supabase (discoveries, posts, interactions, evolution_log,
          token_usage, rss_sources, tracked_handles, identity_state)
```

---

## 二、各維度優勢與劣勢

### A. 知識輸入 (Input)

| 優勢 | 劣勢 |
|------|------|
| Tavily 搜尋覆蓋廣泛網頁 | 免費額度 1000次/月，實際用量~400/月，但搜尋深度受限 |
| RSS 多來源聚合 | RSS 來源需手動維護，無自動發現機制 |
| Jina Reader 免費無上限 | 截斷 5000 字元，長文/PDF 讀不完整 |
| X Listener 追蹤社群討論 | 免費 tier 90 reads/月，嚴重受限 |
| 主人可透過 Telegram 貼 URL | 被動等待，無法主動深入探索某主題 |
| 搜尋 query 分早晚兩組 | query 是硬編碼的，無法根據近期興趣動態調整 |
| — | **無學術資料庫 API**（PubMed, arXiv, Semantic Scholar） |
| — | **無 PDF 全文解析** |
| — | **無圖片/影片理解能力** |
| — | **無 Google Scholar 引用追蹤** |
| — | 搜尋結果品質取決於 Tavily 排序，無法自訂排序邏輯 |
| — | 無法追蹤特定 topic 的長期演進（只有快照式搜尋） |

### B. 處理/思考 (Process)

| 優勢 | 劣勢 |
|------|------|
| Claude Sonnet 4.5 品質不錯 | 單一模型依賴，無本地 LLM 備援 |
| 10 種 Skill 覆蓋多種內容類型 | Skill 選擇是 LLM 判斷，無歷史表現加權 |
| Spawn 子 agent 做深度研究 | Spawn 很簡單（單次 LLM call），非真正的 multi-step research |
| 品質三道關卡 | 品質閘門是序列執行，失敗就丟棄，無迭代改進策略 |
| Identity Loader 組合完整人格 | 人格 context 每次都全量載入，token 消耗大 |
| — | **無 RAG**：vector search 函數存在但未啟用，無法檢索自己過去內容 |
| — | **無推理鏈（Chain-of-Thought）**：創作是單次 prompt → 輸出 |
| — | **無 tool use / function calling**：LLM 無法主動要求查資料或讀網頁 |
| — | **無多 agent 協作**：只有 lobster + spawn，無辯論/審核/編輯角色 |
| — | 反思只更新 curiosity/memory 文字，不調整行為權重 |
| — | Mirror 提出修改建議但需人工批准，無自主演化 |

### C. 儲存 (Storage)

| 優勢 | 劣勢 |
|------|------|
| Supabase PostgreSQL 功能完整 | 免費 tier 500MB，長期運營會滿 |
| REST API 跨平台相容 | 無直接 SQL 連線（效能較差） |
| JSONB 存 engagement 彈性大 | 缺乏結構化分析的便利性 |
| Vector(1024) 欄位已設計 | **向量搜尋未啟用**，embedding 未產生 |
| identity_state 動態記憶 | 只有 curiosity + memory 兩個 key，資訊密度低 |
| — | **無知識圖譜**：discoveries 之間無關聯 |
| — | **無媒體儲存**（圖片、PDF 原檔） |
| — | **無快取層**：每次 Jina 都重新讀取 |
| — | raw_content 可能被截斷，損失資訊 |
| — | 無版本控制或 diff 追蹤（evolution_log 只記錄提案） |

### D. 輸出 (Output)

| 優勢 | 劣勢 |
|------|------|
| 雙平台雙語（X 英文 + Threads 繁中） | **純文字**，無圖片/圖表/影片 |
| CJK-aware 字數計算 | 字數限制壓縮了深度 |
| Auto thread splitting | Thread splitting 基本，無結構規劃 |
| Twin post 連結機制 | 兩個版本獨立創作，無法確保觀點一致性 |
| 10 種 Skill 語氣變化 | — |
| — | **無長文輸出**（blog、newsletter、學術摘要） |
| — | **無圖文搭配**（資料視覺化、資訊圖表） |
| — | **無音頻/影片**（podcast clip、short video） |
| — | 無排程發文（只在心跳時發） |
| — | 無 A/B testing（同主題不同寫法對比） |

### E. 反饋與演化 (Feedback & Evolution)

| 優勢 | 劣勢 |
|------|------|
| Engagement 3h/24h/72h 追蹤 | **追蹤資料未回饋到內容策略** |
| Owner rating 機制 (1-5分) | Rating 資料未影響 Skill 選擇或 topic 偏好 |
| 每日 Reflect 更新 curiosity/memory | 反思是文字描述，無量化指標 |
| 週日 Mirror 分析 + 演化提案 | 提案需人工批准，bottleneck |
| Personality drift 偵測 (0-10) | 偵測到 drift 後無自動修正機制 |
| — | **無 self-play / self-critique**：只有一個 LLM 角色評審 |
| — | **無歷史表現資料庫**：不知道哪種 hook 歷史上最有效 |
| — | **無受眾分析**：不知道誰在看、他們喜歡什麼 |
| — | **無實驗框架**：無法系統性測試新策略 |
| — | evolution_log 記了但不執行，是死檔案 |
| — | 無外部 feedback loop（讀者意見、同行評審） |

---

## 三、對標分析：Lobster vs「小金」能力

李宏毅老師的「小金」是一個能自主操作電腦、搜尋資料、執行任務的 AI agent。以下對比：

| 能力維度 | 小金 | Lobster v2.5 | 差距 |
|----------|------|-------------|------|
| **自主操作電腦** | Computer Use + 螢幕截圖 | 無 | 🔴 完全缺失 |
| **網路搜尋** | 自主搜尋 + 驗證 | Tavily API (被動) | 🟡 有但被動 |
| **文件讀寫** | 自主讀寫任何檔案 | 只能讀 Jina 網頁 | 🔴 嚴重受限 |
| **程式執行** | 可以寫 code 並執行 | 無 | 🔴 完全缺失 |
| **多步推理** | Tool use + planning | 單次 LLM call | 🔴 嚴重不足 |
| **自我修正** | 觀察結果 → 修正策略 | Quality gate 失敗 → 丟棄 | 🟡 有但粗糙 |
| **記憶系統** | Long-term memory | curiosity + memory (文字) | 🟡 原始 |
| **多工能力** | 多 agent 協作 | 單 agent + 簡單 spawn | 🟡 原始 |
| **演化能力** | 持續學習 | Mirror 提案 (需人工) | 🔴 無自主演化 |

**結論**：Lobster 目前是「content creation bot with quality gates」，距離「autonomous evolving agent」還有 3-4 個大階段。

---

## 四、桌機 vs 雲端分析

### 需求前提
目標是讓龍蝦成為有自主演化能力的系統，需要：
1. 能跑本地 LLM（降低 API 成本、允許更多實驗）
2. 能執行 code（Python、統計分析）
3. 能操作瀏覽器（Computer Use）
4. 24/7 在線
5. 足夠的記憶體和儲存

### 比較

| 面向 | 桌機 (建議規格) | 雲端 (Railway + 擴充) |
|------|-----------------|---------------------|
| **一次性成本** | ~NT$40,000-60,000 (RTX 4060+, 32GB RAM, 1TB SSD) | NT$0 |
| **月費** | ~NT$500 (電費) | NT$1,500-4,000+ (Railway Pro + GPU 按需) |
| **本地 LLM** | ✅ 可跑 7B-13B 模型 (Llama 3, Mistral) | ❌ Railway 無 GPU；需另租 RunPod/Vast.ai |
| **24/7 在線** | 需保持開機，有停電風險 | ✅ 自動 |
| **Computer Use** | ✅ 本地 Docker + VNC | ✅ 但需額外配置 |
| **擴展性** | 硬體限制 | ✅ 隨需擴展 |
| **維護** | 自行維護 | 平台維護 |
| **彈性** | 想做什麼做什麼 | 受平台限制 |
| **適合階段** | 開發+實驗 | 穩定運營 |
| **1年總成本** | ~NT$46,000-66,000 | ~NT$18,000-48,000 |
| **2年總成本** | ~NT$52,000-72,000 | ~NT$36,000-96,000 |

### 建議：混合架構

```
桌機 (開發 + 實驗 + 本地 LLM)          Railway (穩定運營)
┌───────────────────────┐              ┌──────────────────┐
│ Local LLM (7B-13B)    │              │ Lobster 主程式    │
│ Code execution sandbox│◄─── API ────►│ Scheduler         │
│ Computer Use 實驗      │              │ Telegram Bot      │
│ 資料分析 (Stata/Python)│              │ Publisher         │
│ PDF 解析               │              │                  │
└───────────────────────┘              └──────────────────┘
         │                                      │
         └──────────── Supabase ────────────────┘
```

**理由**：
- 桌機跑「實驗性質」的東西（本地 LLM、Computer Use、code execution）
- Railway 跑「穩定運營」（發文排程、Telegram、engagement tracking）
- 兩者共用 Supabase，互不干擾
- 先買桌機做 R&D，成熟後再決定哪些遷移到雲端

---

## 五、現行規則與機制完整清單

### 發文規則
- 每平台每日最多 3 篇
- 最短間隔 4 小時
- 15% 機率當天只探索不發文（擬人化）
- Hook score < 7 重寫一次，仍 < 7 退稿
- AI smell check 失敗重寫一次，仍失敗退稿
- 數字必須在原文中可溯源（警告但不擋）
- X: 英文 140-240 words，超長自動分 thread
- Threads: 繁中 200-400 字，獨立創作非翻譯

### 互動規則
- X 每日最多回覆 5 次
- Threads 每日最多回覆 8 次（目前僅自己貼文）
- 每個對話串最多 3 輪
- 回覆延遲 1-3 小時（避免像 bot）
- 挑釁/釣魚/廣告不回

### 預算規則
- 月 token 預算 $30 USD
- 80% 時警告
- 120% 時節流（停止探索，只反思和互動）
- Token 用量按 heartbeat 類型追蹤

### 排程規則（Asia/Taipei，±45 分鐘隨機偏移）
- 06:00 早探索, 09:30 早互動, 12:00 午創作
- 15:30 午互動, 18:00 晚探索(+50%創作), 22:00 反思
- 週日 23:00 Mirror

### 身份規則
- soul.md, style.md: git 管理，主人編輯
- curiosity.md, memory.md: DB 管理，龍蝦自己更新
- evolution_log: 紀錄演化提案，需主人批准

---

## 六、外部服務依賴與瓶頸

| 服務 | 用途 | 免費額度 | 月消耗估計 | 瓶頸等級 |
|------|------|---------|-----------|---------|
| OpenRouter | LLM (Claude Sonnet 4.5) | 按量付費 | ~$15-25 | 🟡 成本 |
| Supabase | 資料庫 | 500MB, 50K rows | ~100 rows/月 | 🟢 充足 |
| Tavily | 搜尋 | 1000 次/月 | ~400 次 | 🟡 堪用 |
| Jina | 網頁讀取 | 無限 | ~200 次 | 🟢 充足 |
| X API | 發文+讀取 | 450 write, 90 read/月 | ~90 write, ~90 read | 🔴 緊張 |
| Threads API | 發文+讀取 | 高額度 | ~90 | 🟢 充足 |
| Telegram | Bot | 無限 | 無限 | 🟢 |
| Railway | 部署 | $5 credit/月 | ~$5-8 | 🟡 可能超出 |

---

## 七、程式碼品質與技術債

### 優點
- 完全 async，效能好
- 模組分離清楚（agent/explorer/publisher/db/llm/utils）
- 錯誤處理有 try-except + Telegram 通知
- 環境變數管理得當

### 技術債
- `lobster.py` 456 行，過長，應拆分
- prompt 模板硬編碼在 `prompts.py`，缺乏版本管理
- 搜尋 query 硬編碼，無法動態調整
- DB client 是手寫 REST，缺乏 ORM 型別安全
- 無單元測試
- 無 CI/CD pipeline
- 無 logging framework（只有 print + Telegram）
- vector search 函數存在但未使用
- engagement 資料收了但未分析

---

*本文件應隨系統演進持續更新。*
