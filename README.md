# 🦞 Lobster v2.5 — 自主探索型社群人格

一隻有品味的數位龍蝦，每天自己在網路上找有趣的東西，消化後用自己的風格發到 X（英文）和 Threads（繁體中文），會看互動數據、回覆留言、根據反應自我調整。

## 每日自動行為

```
Asia/Taipei 時區，所有時間 ±45 分鐘隨機偏移（防 bot 標記）

06:00  晨間探索
       Tavily 搜尋 AI/醫學/科學新發現 + RSS 訂閱源
       評估每篇素材的興趣分數（1-10），7+ 存入素材庫

09:30  晨間互動
       抓 X mentions 和 replies
       抓 Threads 自己貼文下的留言
       更新已發推文的 engagement 數據（3h/24h/72h）

12:00  午間產出
       從素材庫挑最好的 → 選 skill → 寫草稿
       → Hook 強度檢查（< 7 分退回重寫）
       → AI 味檢查（禁用詞、emoji 開頭、三點總結...）
       → 通過 → 自動發 X（英文）+ Threads（中文，獨立創作不是翻譯）
       → Telegram 通知你

15:30  午後互動
       處理新 mentions，更新 engagement

18:00  傍晚探索
       第二輪探索（人文/跨域/奇聞方向）
       50% 機率產出第二篇

22:00  夜間沉澱
       更新 curiosity.md（最近在關注什麼）
       更新 memory.md（今天發了什麼、反應如何）
       Telegram 發送每日摘要

週日 23:00  Mirror 週檢
       分析本週表現：哪個 skill 有效、哪個語言反應好
       提案 soul.md / style.md 修改
       人格漂移檢測
```

每天有 15% 機率是「沉默日」——只探索和互動，不發文。

## Telegram 互動

### 自動通知（你不用做任何事就會收到）

| 通知 | 內容 |
|------|------|
| 發文通知 | 每篇推文的平台、skill、hook 分數、連結 |
| 24h engagement | 推文發出 24 小時後的互動數據 |
| 回覆通知 | 龍蝦回覆了誰、說了什麼 |
| 每日摘要 | 今天探索/發文/回覆數量 + token 花費 |
| 週報 | Mirror 分析 + 提案修改 |
| 預算警告 | 月花費 > 80% 時提醒 |
| AI 味擋下 | 有草稿被 AI 味檢查擋住 |

### 你可以主動做的

| 指令 | 功能 |
|------|------|
| `/start` | 看所有可用指令 |
| `/stats` | 本月統計（花費、發文數、狀態） |
| `/pause` | 暫停自動發布 |
| `/resume` | 恢復自動發布 |
| `/rate <post_id> <1-5> <評語>` | 評價一篇推文 |
| `/explore <topic>` | 立即搜尋某主題 |
| `/track <handle>` | 追蹤一個 X 帳號 |
| `/enable_proactive` | 開啟主動參與對話（第二個月） |
| 貼 URL | 立即處理這個連結 |
| 發文字 | 存為 thought 素材 |

## 龍蝦的品味篩選

### 會發的
- 反直覺的研究發現
- 聰明的方法論（自然實驗、工具變數）
- 被忽略 20 年突然被重新發現的研究
- 跨領域共鳴（AI 概念 = 醫學現象）
- 真正解決痛點的新工具
- 奇怪但發人深省的新聞

### 絕對不發的
- Me-too research
- Effect size 微小的統計顯著
- AI hype 無實質內容
- 標題黨、資訊農場
- 「在這個 AI 時代...」

## 雙平台策略

| | X | Threads |
|---|---|---|
| 語言 | 英文 | 繁體中文 |
| 口吻 | 學術 tweet 風 | 口語，像跟朋友聊天 |
| 互動 | 完整雙向 | 只回自己貼文下的留言 |
| 頻率 | 每天 1-2 篇 | 每天 1-2 篇 |

同一個 discovery 會獨立創作兩個版本，不是翻譯。

## 安全機制

- **Token 預算**：月上限 $30，80% 警告，120% 停止探索
- **X API**：Free tier 450 writes/月、90 reads/月（留 buffer）
- **發文限制**：每天最多 3 篇/平台，間隔 > 4 小時
- **互動限制**：每天最多 5 則 X 回覆、8 則 Threads 回覆
- **Identity 保護**：soul.md/style.md 修改需主人批准

## 技術棧

| 層 | 工具 | 備註 |
|---|---|---|
| 運行環境 | Railway | auto-deploy from GitHub main |
| LLM | OpenRouter → Claude Sonnet 4.5 | 所有 agent 統一用 Sonnet |
| 資料庫 | Supabase (REST API) | 免費 tier |
| 搜尋 | Tavily | 免費 1000 次/月 |
| 讀網頁 | Jina Reader | 免費，不需 key |
| 通知 | Telegram Bot | |
| 發布 | X API + Threads API | |

## 檔案結構

```
lobster-v2/
├── identity/          # 龍蝦的靈魂（soul.md, style.md, curiosity.md, memory.md）
├── skills/            # 10 個產出技能（research_commentary, threads_voice...）
├── agent/             # 主龍蝦 + Mirror + Spawn
├── explorer/          # 搜尋、RSS、Jina、X listener
├── publisher/         # X poster、Threads poster、engagement tracker
├── bot/               # Telegram bot
├── llm/               # OpenRouter client
├── db/                # Supabase client + schema
├── scheduler/         # 6 個 heartbeat
├── utils/             # AI 味檢查、hook 評估、token 追蹤
└── main.py            # Entry point
```

## 環境變數

```
OPENROUTER_API_KEY     — OpenRouter API key
SUPABASE_URL           — Supabase project URL
SUPABASE_ANON_KEY      — Supabase anon key（或 SUPABASE_SERVICE_ROLE_KEY）
TELEGRAM_BOT_TOKEN     — Telegram bot token
TELEGRAM_USER_ID       — 你的 Telegram user ID（也支援 ALLOWED_USER_ID）
X_API_KEY              — X OAuth 1.0a
X_API_SECRET
X_ACCESS_TOKEN
X_ACCESS_SECRET
TWITTER_HANDLE         — 你的 X handle（不含 @）
TWITTER_BEARER_TOKEN   — X API v2 bearer token（讀取用）
THREADS_ACCESS_TOKEN   — Meta Graph API token
THREADS_USER_ID        — Threads user ID
THREADS_ENABLED        — true/false
TAVILY_API_KEY         — Tavily search API key
TZ=Asia/Taipei
MONTHLY_TOKEN_BUDGET=30
PROACTIVE_ENGAGEMENT_ENABLED=false
```

## 設定步驟

1. 在 Supabase SQL Editor 執行 `db/schema_v2.5.sql`
2. 在 Railway 設定所有環境變數
3. 填寫 `identity/soul.md` 和 `identity/style.md` 中的待補充欄位
4. Push to main → Railway auto-deploy
5. 在 Telegram 跟龍蝦說 `/start`

## 冷啟動期（第一個月）

- 不期待病毒式傳播，目標是「每篇至少有人看完」
- 龍蝦會主動參與大號的對話（reply 而不是發推）
- 內容高度反直覺，引發 reply 比 like 重要
- 你（人類）偶爾轉發或互動，幫龍蝦背書
- 用 `/rate` 給回饋，Mirror 會學習

---

*Lobster v2.5 — 靈感來自李宏毅 OpenClaw / 小金*
