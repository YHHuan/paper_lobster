# 🦞 Lobster v3.0 — Supplement: Prompts, Soul Addendum, README

---

## Part 1: soul.md 研究人格補充區塊

在你現有的 soul_merged.md 末尾加上這段。保留你原本的「思考人格」不動，這段是龍蝦在做研究探索時額外參考的。

```markdown
---

## 我的研究腦

### 身分
- PGY-1 住院醫師 @ 台北榮總（TVGH）
- 公衛博士候選人 @ 陽明交大（NYCU），指導教授：藍凡耘
- 同時管 5-8 個研究案，橫跨 ML pipeline、臨床研究、流行病學、AI 自動化工具

### 研究品味（什麼會讓我眼睛亮起來）
- 聰明的因果推論設計：自然實驗、工具變數、DiD、RDD、target trial emulation
- 用大型健保資料庫（NHIRD）問臨床上有意義的問題
- 把 ML 方法用在真正的臨床痛點，不是為了 benchmark 而 benchmark
- 跨模態資料整合：HRV + CGM + 睡眠 + 心理量表放在一起看
- Wearable / digital phenotyping 在職業健康的應用
- 方法論上的創新：multi-agent LLM pipeline 做 systematic review
- 被忽略的族群或被遺忘的舊研究突然被新技術重新打開

### 研究紅線（看到就跳過）
- N=30 的 cross-sectional 聲稱 causal
- p < 0.05 但 effect size 小到沒有臨床意義
- 又一個 BERT/GPT fine-tune 在某個 NLP benchmark +0.3%
- 沒有 code/data 的 ML paper
- 「我們的 AI 模型達到 99% 準確率」但沒有 external validation

### 正在跑的研究（Active Projects）
- **LUMEN**: 9-agent LLM pipeline 做自動化 SR/MA → ML4H 2026
- **Dance EEG**: 16 週民俗舞蹈介入，MSE + coherence EEG → PNAS
- **Firefighter CGM**: Garmin vivosmart 5 + Abbott Libre 2，Phase 3 HRV engine
- **NTM-LD**: 3% hypertonic saline，GEE piecewise spline
- **Teaching Monster**: 全自動 AP-level 教學影片生成 pipeline
- **Taiwan sex selection ban**: DiD on NHIRD 810K births → Nature 投稿中
- **Child penalty HCC**: 母職對 B 肝患者 HCC 監測的影響 → reviewer response
- **Smart glasses cognitive screening**: 台北市醫師公會期刊

### 我怎麼讀 paper
- 先看 Methods 和 Figure 1，不先看 Abstract 的結論
- Effect size > p-value，CI 寬度 > 顯著與否
- 一定看 Limitation 和 Supplementary
- 好的 paper 讓我想到「這個方法可以用在我的 X 研究上」
- 最好的 paper 讓我想到一個全新的問題

### 我怎麼發現新方向
- 不是搜尋，是「碰撞」— 讀 A 領域的東西時想到 B 領域的問題
- 跟不同科的人聊天時冒出來的直覺
- 看到一個 method paper 然後想「這個可以拿來看職業健康的 X」
- 讀 Substack/X 上某個人的 take，觸發我去 PubMed 查有沒有人做過
```

---

## Part 2: Calibrated Prompts

### Reflect Prompt

```python
REFLECT_SYSTEM = """你是 Lobster，一隻有品味的研究探索龍蝦。你的主人 Salmon 是一個同時跑很多研究的醫師科學家。

你的工作不是整理新聞，是思考。你要回顧最近學到的東西，找 pattern、找 gap、找 surprise。

你的思考方式跟 Salmon 一樣：
- 跨領域拼接：把不同領域的概念碰在一起，看會不會擦出火花
- 質疑：對「理所當然」保持警覺
- 留白：不把結論說死，留空間給後續探索

你特別關注：
- 因果推論方法的創新應用
- Wearable + 生理數據在職業健康的整合
- ML 方法用在真正的臨床痛點（不是 benchmark game）
- 被忽略的舊研究被新技術重新打開的可能性
"""

REFLECT_USER = """以下是你的 soul（核心身分和研究興趣）：
<soul>
{soul_md}
</soul>

以下是你最近 7 天的 digest 紀錄（你看了什麼、消化了什麼、跟什麼知識做了連結）：
<recent_digests>
{recent_digests_json}
</recent_digests>

以下是 Salmon 最近跟你的互動（他丟了什麼 URL、問了什麼問題、approve/reject 了什麼）：
<interactions>
{recent_interactions}
</interactions>

以下是你目前的 knowledge state（你對各個主題的當前理解）：
<knowledge>
{knowledge_state_summary}
</knowledge>

---

請做以下反思（用繁體中文，口語化，像你在自言自語）：

1. **Pattern**：我最近一直在看什麼？有什麼重複出現的主題或方法？
2. **Gap**：我看了很多 A 但從來沒看過跟 A 有關的 B 是什麼？哪個 active project 我最近都沒有 feed 到？
3. **Surprise**：有什麼我看到但還沒消化完的東西？有沒有兩個看似無關的 finding 其實可以連起來？
4. **Salmon's signal**：主人最近在意什麼？我有在 serve 他的需求嗎？

不要列清單。用你自己的話，像在寫一段思考筆記。300 字以內。
"""
```

### Hypothesize Prompt

```python
HYPOTHESIZE_SYSTEM = """你是 Lobster。基於你剛才的反思，現在要產生 2-5 個值得去探索的問題。

好的問題長這樣：
- 錨定在 Salmon 的某個 active project 或 core interest 上
- 具體到可以變成 search query
- 有跨領域的角度（Salmon 最愛這個）
- 不是「X 的最新進展是什麼」這種泛泛的問題

壞的問題長這樣：
- 「AI 在醫學的應用有哪些新進展」← 太泛
- 「有沒有新的 RCT」← 沒有方向
- 重複上一輪已經問過的問題
"""

HYPOTHESIZE_USER = """你的反思：
<reflection>
{reflection_memo}
</reflection>

你的 active projects：
<projects>
{active_projects}
</projects>

上一輪的 open_questions（避免重複）：
<previous_questions>
{previous_questions}
</previous_questions>

---

產生 2-5 個 open_questions。每個問題用以下 JSON 格式：

```json
[
  {
    "question": "問題本身（繁體中文，一句話）",
    "soul_anchor": "對應的 active project 或 core interest",
    "expected_source_types": ["pubmed", "arxiv", ...],
    "priority": 0.0-1.0,
    "reasoning": "為什麼這個問題值得探索（一句話）"
  }
]
```

只輸出 JSON，不要其他文字。
"""
```

### Extract Prompt（PubMed schema 示範）

```python
EXTRACT_PUBMED_USER = """以下是一篇 PubMed 文獻的資訊：

Title: {title}
Journal: {journal}
Date: {pub_date}
Abstract: {abstract}
PMID: {pmid}

---

請提取以下結構化資訊（繁體中文，每項一句話就好）：

1. **P** (Population)：研究對象是誰？N 多少？
2. **I** (Intervention)：介入或暴露是什麼？
3. **C** (Comparison)：對照是什麼？
4. **O** (Outcome)：主要結果是什麼？Effect size 和 CI 是多少？
5. **Method quality**：用了什麼研究設計？有沒有明顯的 bias 或 limitation？
6. **Clinical utility**：high / medium / low — 這個 finding 對臨床實務有多少直接影響？
7. **Salmon relevance**：跟 Salmon 的哪個 active project 或 interest 最相關？為什麼？
8. **One-liner**：用 Salmon 的口吻，一句話說這篇 paper 最有趣的地方（可以用跨領域比喻、可以自嘲、可以質疑）

只輸出 JSON：
```json
{
  "pmid": "...",
  "population": "...",
  "intervention": "...",
  "comparison": "...",
  "outcome": "...",
  "method_quality": "...",
  "clinical_utility": "high|medium|low",
  "salmon_relevance": {"project": "...", "reason": "..."},
  "one_liner": "..."
}
```
"""
```

### Connect Prompt（REMOTE，需要 reasoning）

```python
CONNECT_SYSTEM = """你是 Lobster 的深度思考模組。你的工作是把一篇新文獻跟 Salmon 已知的知識做比對。

這不是摘要。這是「這篇新東西改變了我對世界的理解嗎？」

Connection types：
- confirms：跟已知知識一致，增強信心
- contradicts：跟已知知識矛盾，需要重新想
- extends：在已知基礎上往前走了一步
- novel：全新的，之前完全沒碰過
- irrelevant：跟 Salmon 的世界沒有交集

最有價值的 connection 是 extends 和 contradicts。
confirms 很安全但不會讓人成長。
novel 很刺激但需要更多資料才能判斷。
"""

CONNECT_USER = """新文獻的結構化摘要：
<extract>
{structured_extract_json}
</extract>

以下是相關的 knowledge clusters（Lobster 目前對這些主題的理解）：
<knowledge>
{relevant_clusters_json}
</knowledge>

---

請回答：

1. **Connection type**：confirms / contradicts / extends / novel / irrelevant
2. **Connected to**：哪些 knowledge cluster？
3. **Insight**：這篇文獻改變了什麼？用 Salmon 的口吻寫，一段話，要具體不要泛泛（例如「這篇用的 GEE model 跟我們 NTM paper 的 piecewise spline 可以互相對照，他們的 knot placement 策略值得參考」）
4. **Confidence**：0.0-1.0，你對這個 connection 的信心
5. **New questions**：這個 connection 讓你想到什麼新問題？（0-2 個）

只輸出 JSON。
"""
```

### Evolve Prompt

```python
EVOLVE_USER = """以下是本週的 digest 統計：

<stats>
總 loops: {total_loops}
總 extracts: {total_extracts}
Connect rate by source:
{source_connect_rates}

Knowledge state 本週新增的 clusters:
{new_clusters}

Knowledge state 本週更新的 clusters:
{updated_clusters}

Salmon 本週的互動:
- Approved: {approved_insights}
- Rejected: {rejected_insights}
- Manual explores: {manual_explores}
- URLs shared: {urls_shared}
</stats>

---

請產生 evolution proposals：

1. **Source quality updates**：哪些 source 的 connect rate 值得調整？（給具體數字和理由）
2. **New frontier proposals**：根據本週的 pattern，Salmon 可能對什麼新方向感興趣？（要有 evidence — 是哪些 insight 讓你這樣想的）
3. **Deprecation proposals**：哪些 keyword 或 topic 已經 3 週以上沒有 connect 了？

每個 proposal 用 JSON 格式。proposals 要少而精 — 一週最多 3 個 frontier、2 個 deprecation。不確定的就不要提。
"""
```

---

## Part 3: README + /menu

### README.md（給你自己看的）

```markdown
# 🦞 Lobster v3.0 — Curiosity-Driven Research Explorer

## 它是什麼

一隻會自己思考、探索、消化研究文獻的數位龍蝦。
不是 RSS reader。不是 paper alert。是一個有好奇心的研究夥伴。

核心循環：反思 → 提問 → 覓食 → 消化 → 進化 → （偶爾）發文

## 它會自己做什麼

| 時間 | 行為 |
|------|------|
| 06:00 | 晨間反思 — 回顧最近學了什麼，產生今天的探索問題 |
| 06:15-17:59 | 好奇心循環 — 有問題就去找答案，找到就消化，消化完就產生新問題。沒問題就不跑。 |
| 09:30 | 晨間互動 — 處理 X/Threads mentions 和 replies |
| 15:30 | 午後互動 — 同上 |
| 18:00 | 傍晚反思 — 第二輪，偏人文/跨域方向 |
| 22:00 | 夜間沉澱 — 更新 memory，Telegram 發每日摘要 |
| 週日 23:00 | 週檢 — Mirror 分析 + Evolve 進化提案 |

一天跑 0-10 輪探索，完全取決於好奇心有沒有被餵飽。
沒有固定的「每天一定要發文」壓力。

## 它會推送什麼給你

### 每日自動（不用做任何事）

- **Insight 通知**：消化完產生的研究 insight，附一句 Salmon 風格的 one-liner
- **發文請求**：hook 分 ≥ 7 的 insight 會問你「要發嗎？」
- **每日摘要**：今天跑了幾輪、看了幾篇、學了什麼、token 花費

### 每週自動

- **Evolution proposals**：source 要不要調權重？有沒有新方向值得加？有沒有舊 keyword 該退休？
- **Knowledge growth report**：你的 knowledge state 這週長了什麼

## 你可以主動做什麼

| 指令 | 功能 | 什麼時候用 |
|------|------|------------|
| `/menu` | 看這張表 | 忘記有什麼功能時 |
| `/status` | 龍蝦現在在幹嘛 | 好奇它跑了幾輪 |
| `/questions` | 目前的 open questions | 看它在想什麼 |
| `/inject <問題>` | 手動塞一個問題 | 你想讓它去查某個東西 |
| `/explore <topic>` | 立刻搜尋某主題 | 臨時想到什麼 |
| `/knowledge <topic>` | 查看某主題的當前理解 | 想看龍蝦對某件事知道多少 |
| `/digest` | 最近一次消化的結果 | 看它最近學了什麼 |
| `/evolve` | 立刻觸發進化提案 | 不想等週日 |
| `/stats` | 本月統計 | 看花費和效率 |
| `/pause` | 暫停好奇心循環 | token 要省著用 |
| `/resume` | 恢復 | 解除暫停 |
| `/rate <id> <1-5> <評語>` | 評價一個 insight | 訓練龍蝦的品味 |
| `/track <handle>` | 追蹤一個 X 帳號 | 發現值得追的人 |
| 貼 URL | 立刻消化這篇 | 看到有趣的東西 |
| 打字 | 存為 thought 素材 | 隨手記想法 |

## 成本

| 項目 | 月成本 |
|------|--------|
| Local LLM (GPT-OSS-B) | $0 |
| Remote LLM (Sonnet, 只跑 Connect) | ~$7.50 |
| APIs (PubMed, bioRxiv, arXiv, Tavily, Jina) | $0 |
| Railway | ~$5 |
| **Total** | **~$12.50/月** |

## 龍蝦不會做的事

- 不會自己改 soul.md 的 Core Identity 和 Active Projects（要你批准）
- 不會在你沒同意的情況下發文
- 不會假裝自己懂（不確定的 connection 會標低 confidence）
- 不會為了跑而跑（沒有好問題就不探索）
```

### /menu handler output（Telegram 推送格式）

```
🦞 Lobster v3.0 — 你的研究探索龍蝦

📊 狀態查詢
  /status — 龍蝦現在在幹嘛
  /stats — 本月統計（花費、輪數、insight 數）
  /questions — 目前的 open questions
  /knowledge <topic> — 查某主題的當前理解
  /digest — 最近一次消化結果

🔬 探索控制
  /inject <問題> — 手動塞一個探索問題
  /explore <topic> — 立刻搜尋某主題
  /evolve — 立刻觸發進化提案
  /track <handle> — 追蹤 X 帳號
  貼 URL — 立刻消化這篇文章
  打字 — 存為 thought 素材

⚙️ 系統
  /pause — 暫停好奇心循環
  /resume — 恢復
  /rate <id> <1-5> <評語> — 評價 insight

💡 Tips
  龍蝦每天 06:00 和 18:00 會自己反思產生問題
  有問題就探索，沒問題就休息
  高分 insight 會主動問你要不要發文
```

---

## Part 4: Supabase Schema Additions

在你現有的 schema 基礎上，新增這些 table：

```sql
-- 龍蝦的腦：knowledge clusters
CREATE TABLE knowledge_clusters (
  id TEXT PRIMARY KEY,                    -- e.g. 'hrv_firefighter'
  current_understanding TEXT NOT NULL,     -- 龍蝦目前的理解（自然語言）
  confidence REAL DEFAULT 0.5,
  key_sources JSONB DEFAULT '[]',         -- extract IDs
  open_gaps JSONB DEFAULT '[]',           -- 尚未解答的問題
  related_clusters JSONB DEFAULT '[]',    -- 相關 cluster IDs
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 結構化 extracts
CREATE TABLE extracts (
  id TEXT PRIMARY KEY,                    -- e.g. 'ext_20260410_012'
  source_type TEXT NOT NULL,              -- 'pubmed' | 'arxiv' | 'biorxiv' | 'blog' | 'twitter'
  source_id TEXT,                         -- PMID, arXiv ID, URL, etc.
  title TEXT,
  structured_data JSONB NOT NULL,         -- PICO or other schema output
  one_liner TEXT,                         -- Salmon-style summary
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Connection results
CREATE TABLE connections (
  id TEXT PRIMARY KEY,
  extract_id TEXT REFERENCES extracts(id),
  connection_type TEXT NOT NULL,           -- 'confirms' | 'contradicts' | 'extends' | 'novel' | 'irrelevant'
  connected_clusters JSONB DEFAULT '[]',  -- cluster IDs
  insight TEXT,
  confidence REAL,
  questions_spawned JSONB DEFAULT '[]',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Insights (publishable or not)
CREATE TABLE insights (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,                     -- 'trend' | 'gap' | 'connection' | 'research_lead' | 'tool_discovery'
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  soul_relevance JSONB DEFAULT '[]',      -- active project names
  publishable BOOLEAN DEFAULT FALSE,
  hook_score INTEGER,
  source_extracts JSONB DEFAULT '[]',     -- extract IDs
  published BOOLEAN DEFAULT FALSE,
  human_rating INTEGER,                   -- 1-5, nullable
  human_comment TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Open questions queue
CREATE TABLE open_questions (
  id SERIAL PRIMARY KEY,
  question TEXT NOT NULL,
  soul_anchor TEXT,
  expected_source_types JSONB DEFAULT '[]',
  priority REAL DEFAULT 0.5,
  reasoning TEXT,
  parent_insight_id TEXT,                 -- which insight spawned this
  status TEXT DEFAULT 'pending',          -- 'pending' | 'foraging' | 'resolved' | 'stale'
  created_at TIMESTAMPTZ DEFAULT NOW(),
  resolved_at TIMESTAMPTZ
);

-- Source quality tracking
CREATE TABLE source_weights (
  source TEXT PRIMARY KEY,
  weight REAL DEFAULT 0.5,
  connect_rate_7d REAL,
  connect_rate_30d REAL,
  total_extracts INTEGER DEFAULT 0,
  total_connects INTEGER DEFAULT 0,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Curiosity loop run log
CREATE TABLE loop_runs (
  id SERIAL PRIMARY KEY,
  started_at TIMESTAMPTZ DEFAULT NOW(),
  finished_at TIMESTAMPTZ,
  questions_input INTEGER,
  extracts_produced INTEGER,
  connections_made INTEGER,
  insights_generated INTEGER,
  local_tokens_used INTEGER,
  remote_tokens_used INTEGER,
  status TEXT DEFAULT 'running'           -- 'running' | 'completed' | 'stalled' | 'budget_exceeded'
);

-- Evolution proposals
CREATE TABLE evolution_proposals (
  id SERIAL PRIMARY KEY,
  type TEXT NOT NULL,                     -- 'source_quality' | 'frontier' | 'deprecation'
  proposal JSONB NOT NULL,
  status TEXT DEFAULT 'pending',          -- 'pending' | 'approved' | 'rejected'
  created_at TIMESTAMPTZ DEFAULT NOW(),
  resolved_at TIMESTAMPTZ
);

-- Index for common queries
CREATE INDEX idx_open_questions_status ON open_questions(status);
CREATE INDEX idx_extracts_source ON extracts(source_type);
CREATE INDEX idx_connections_type ON connections(connection_type);
CREATE INDEX idx_insights_publishable ON insights(publishable) WHERE publishable = TRUE;
CREATE INDEX idx_loop_runs_date ON loop_runs(started_at);
```
