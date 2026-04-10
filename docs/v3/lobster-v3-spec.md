# 🦞 Lobster v3.0 — Curiosity-Driven Research Explorer

**升級自 v2.5 社群人格版。核心變化：從「定時搜尋 → 發文」改為「好奇心驅動的探索 → 消化 → 進化循環」。**

---

## 設計哲學

v2.5 是一隻會找東西然後發文的龍蝦。
v3.0 是一隻會思考、會消化、會自己長出新問題的龍蝦。

發文是副產品，不是目的。龍蝦的核心循環是：
```
Reflect → Hypothesize → Forage → Digest → Evolve → (偶爾) Publish
```

## LLM 策略

| Tier | 用途 | 預設模型 | 備註 |
|------|------|----------|------|
| `LOCAL` | Reflect, Hypothesize, Extract, Evolve, Query gen, Hook check, AI 味檢查 | local GPT-OSS-B | 免費，盡量跑 |
| `REMOTE` | Connect (需要 long context + reasoning), 高品質 Write | OpenRouter → Sonnet | 按需，每次 ~$0.05-0.15 |

原則：能 local 就 local。只有「比對已知知識」和「高品質產出」才上 remote。

---

## 核心循環：Curiosity Loop

**不是 cron job。是 event-driven async loop。**

```
┌─────────────────────────────────────────────────┐
│                 Curiosity Loop                   │
│                                                  │
│  ┌──────────┐    ┌─────────────┐                │
│  │ Reflect  │───→│ Hypothesize │                │
│  │ (LOCAL)  │    │ (LOCAL)     │                │
│  └──────────┘    └──────┬──────┘                │
│       ↑                 │                        │
│       │          open_questions[]                │
│       │                 ↓                        │
│       │         ┌──────────────┐                │
│       │         │   Forage     │                │
│       │         │ (multi-src)  │                │
│       │         └──────┬───────┘                │
│       │                │                        │
│       │           raw_finds[]                   │
│       │                ↓                        │
│       │         ┌──────────────┐                │
│       │         │   Digest     │                │
│       │         │ Extract(LOCAL)│                │
│       │         │ Connect(REMOTE)│               │
│       │         │ Synthesize(LOCAL)│             │
│       │         └──────┬───────┘                │
│       │                │                        │
│       │    insights[] + new open_questions[]     │
│       │                ↓                        │
│       │         ┌──────────────┐                │
│       └─────────│   Evolve     │                │
│                 │   (LOCAL)    │                │
│                 └──────────────┘                │
│                                                  │
└─────────────────────────────────────────────────┘
```

### 觸發條件

Loop 在以下任一條件成立時啟動一輪：
- `open_questions[]` 非空（上一輪 digest 產生了新問題）
- 你手動丟了一個 URL / topic / `/explore` 指令
- 定時 seed（每天 06:00 和 18:00 跑一次 Reflect，產生初始問題）

Loop 在以下任一條件成立時暫停：
- `open_questions[]` 空了（好奇心被餵飽）
- 當日 local token budget 用完
- 當月 remote token budget 用完
- 連續 3 輪 digest 沒有產出 connect 率 > 0.3 的 insight（避免空轉）

### 每輪預估成本

| Step | Model | Est. tokens | Est. cost |
|------|-------|-------------|-----------|
| Reflect | LOCAL | ~2k | $0 |
| Hypothesize | LOCAL | ~1k | $0 |
| Forage | API calls | — | $0 (PubMed/bioRxiv 免費) |
| Extract | LOCAL | ~3k × N articles | $0 |
| Connect | REMOTE | ~8k | ~$0.05 |
| Synthesize | LOCAL | ~2k | $0 |
| Evolve | LOCAL | ~1k | $0 |

一輪大約 $0.05 remote cost。一天跑 5 輪 = $0.25。月成本 ~$7.50。

---

## 模組詳細設計

### 1. Reflect (`agent/reflect.py`)

**Input**: knowledge_state.json + recent_digests[] (最近 7 天) + 你最近的互動紀錄
**Model**: LOCAL
**Output**: reflection_memo (自然語言)

Prompt 骨架：
```
你是一隻正在回顧自己最近學到什麼的研究龍蝦。

以下是你的 soul（核心興趣和研究身分）：
{soul_md}

以下是你最近 7 天的 digest 紀錄：
{recent_digests}

以下是主人最近跟你互動時提到的東西：
{recent_interactions}

請回答：
1. 我最近一直在看什麼？有沒有 pattern？
2. 有什麼 gap — 我看了很多 A 但從來沒看過跟 A 有關的 B？
3. 有什麼 surprising connection 我可能還沒注意到？
4. 主人最近在意的 project 是什麼？我有在 serve 它嗎？
```

### 2. Hypothesize (`agent/hypothesize.py`)

**Input**: reflection_memo + soul.md (Active Projects 區) + curiosity.md
**Model**: LOCAL
**Output**: open_questions[] (2-5 個問題)

每個 open_question 的 schema：
```json
{
  "question": "有沒有人用 continuous glucose monitoring 配合 HRV 來研究消防員的 shift work 影響？",
  "soul_anchor": "Firefighter CGM project",
  "expected_source_types": ["pubmed", "biorxiv"],
  "priority": 0.8,
  "parent_insight_id": "ins_20260410_003"  // nullable, 表示哪個 insight 生了這個問題
}
```

### 3. Forage (`explorer/forage.py`)

**Input**: open_questions[]
**Output**: raw_finds[] (articles, posts, threads)

Source routing 邏輯（deterministic, 不需要 LLM）：

```python
def route_question(q: OpenQuestion) -> list[Source]:
    sources = []
    text = q.question.lower()
    expected = q.expected_source_types

    # Explicit expected sources always included
    if "pubmed" in expected:
        sources.append(PubMedSource(q))
    if "biorxiv" in expected:
        sources.append(BioRxivSource(q))
    if "arxiv" in expected:
        sources.append(ArXivSource(q))

    # Keyword-based fallback routing
    if any(kw in text for kw in ["trial", "rct", "cohort", "intervention",
                                   "disease", "treatment", "patient"]):
        sources.append(PubMedSource(q))
    if any(kw in text for kw in ["preprint", "model", "architecture",
                                   "benchmark", "transformer", "agent"]):
        sources.append(ArXivSource(q))
    if any(kw in text for kw in ["trend", "opinion", "take", "thread",
                                   "newsletter", "blog"]):
        sources.append(TavilySource(q))
        sources.append(JinaSource(q))  # for Substack deep reads

    return deduplicate(sources)
```

每個 Source adapter 的 interface：
```python
class Source(ABC):
    @abstractmethod
    async def search(self, question: OpenQuestion) -> list[RawFind]:
        ...

class PubMedSource(Source):
    """Uses PubMed E-utilities. Free, no key needed (with rate limit)."""
    async def search(self, q):
        # esearch → efetch → parse XML
        query = await self.question_to_pubmed_query(q)  # LOCAL LLM
        ...

class BioRxivSource(Source):
    """Uses bioRxiv API. Free."""
    ...

class ArXivSource(Source):
    """Uses arXiv API. Free."""
    ...

class TavilySource(Source):
    """Uses Tavily search. 1000 free/month."""
    ...

class JinaSource(Source):
    """Uses Jina Reader for full-text extraction. Free."""
    ...
```

### 4. Digest (`digester/`)

三個 sub-step，最重要的模組。

#### 4a. Extract (`digester/extract.py`)

**Input**: raw_finds[]
**Model**: LOCAL
**Output**: structured_extracts[]

根據 source type 動態選 schema：

```python
EXTRACT_SCHEMAS = {
    "pubmed": {
        "type": "clinical_research",
        "fields": ["population", "intervention", "comparison", "outcome",
                    "method_quality", "effect_size", "clinical_utility"],
    },
    "biorxiv": {
        "type": "preprint",
        "fields": ["population", "intervention", "comparison", "outcome",
                    "method_quality", "preprint_maturity", "replication_status"],
    },
    "arxiv": {
        "type": "methods_paper",
        "fields": ["novelty_claim", "method_description", "baselines_compared",
                    "limitations_stated", "code_available", "relevance_to_clinical"],
    },
    "blog_substack": {
        "type": "opinion_piece",
        "fields": ["central_claim", "evidence_cited", "author_credibility",
                    "counterarguments_addressed", "actionability"],
    },
    "twitter": {
        "type": "social_signal",
        "fields": ["claim", "source_linked", "engagement_level",
                    "expert_endorsement", "novelty_vs_hype"],
    }
}
```

#### 4b. Connect (`digester/connect.py`)

**Input**: structured_extract + knowledge_state.json
**Model**: REMOTE (Sonnet) — 需要 long context + reasoning
**Output**: connection_result

```json
{
  "extract_id": "ext_20260410_012",
  "connection_type": "extends",  // "confirms" | "contradicts" | "extends" | "novel" | "irrelevant"
  "connected_to": ["ks_hrv_firefighter", "ks_cgm_glucose_variability"],
  "insight": "這篇是第一個把 CGM glycemic variability 跟 HRV 在 shift workers 裡一起看的研究，用的是 24hr time-domain HRV，跟我們計畫的 NeuroKit2 分析方法不同但結果可以比對。",
  "confidence": 0.85,
  "open_questions_spawned": [
    "他們用的 glucose variability metric 是 CV 還是 MAGE？跟我們 Abbott Libre 的 output 能比嗎？"
  ]
}
```

Connect rate = 有 connection 的 extracts / 總 extracts。這個數字餵給 Evolve 做 source quality tracking。

#### 4c. Synthesize (`digester/synthesize.py`)

**Input**: connection_results[]
**Model**: LOCAL
**Output**: insights[] + new open_questions[]

Insight schema：
```json
{
  "id": "ins_20260410_003",
  "type": "research_lead",  // "trend" | "gap" | "connection" | "research_lead" | "tool_discovery"
  "title": "CGM + HRV 在 shift work 研究的新切入點",
  "body": "...",
  "soul_relevance": ["Firefighter CGM project"],
  "publishable": true,  // hook 分數 >= 7 且有 surprising angle
  "hook_score": 8,
  "source_articles": ["ext_20260410_012", "ext_20260410_015"]
}
```

### 5. Evolve (`agent/evolve.py`)

**Input**: weekly digest_logs + connect rates by source + knowledge_state diff
**Model**: LOCAL
**Output**: evolution_proposals[] → Telegram 推送給你 approve/reject

三種 proposal：

```python
@dataclass
class SourceQualityUpdate:
    """「bioRxiv 這週 connect 率 0.82，Tavily 只有 0.28，建議降 Tavily forage 頻率」"""
    source: str
    current_weight: float
    proposed_weight: float
    reason: str

@dataclass
class FrontierProposal:
    """「根據最近的 digest pattern，你可能對 X 感興趣，加入 soul.md exploration frontier？」"""
    topic: str
    evidence: list[str]  # insight IDs that suggest this
    proposed_keywords: list[str]

@dataclass
class DeprecationProposal:
    """「Y keyword 三週沒有 connect 了，建議移除」"""
    keyword: str
    last_connect_date: str
    reason: str
```

所有 proposals 透過 Telegram 推送，格式：
```
🧬 Evolution Proposals (週報)

📈 Source Quality
  bioRxiv: 0.65 → 0.72 (connect rate ↑)
  Tavily: 0.40 → 0.28 (3 週下降，建議降權)
  [Approve] [Reject] [Discuss]

🆕 New Frontier
  "wearable-based digital phenotyping in occupational health"
  Evidence: ins_003, ins_007, ins_012
  [Add to soul.md] [Ignore]

🗑️ Deprecation
  keyword "transformer attention visualization" — 4 週沒 connect
  [Remove] [Keep]
```

---

## soul.md 新結構

```markdown
# 🦞 Soul v3

## Core Identity（你手寫，很少改）

### 研究身分
- PGY-1 resident physician @ TVGH
- PhD candidate in public health @ NYCU
- Expertise: occupational health, causal inference, ML for clinical research, epidemiology

### 認知風格
- 偏好 RCT > observational，但欣賞聰明的自然實驗和工具變數
- 對 effect size 敏感，不被 p-value 唬住
- 喜歡跨領域連結（AI 概念 ↔ 醫學現象）
- Skeptical of AI hype，但對真正的方法論創新感興趣

### 品味紅線（絕對不要推給我的）
- Me-too research
- Effect size 微小的統計顯著
- AI hype 無實質內容
- 「在這個 AI 時代...」開頭的任何東西

## Active Projects（你定期更新，龍蝦也會根據互動推測）

- **LUMEN**: multi-agent SR/MA pipeline → ML4H 2026
- **Dance EEG**: 16-week folk dance intervention, MSE/coherence → PNAS
- **Firefighter CGM**: Garmin vivosmart 5 + Abbott Libre 2, Phase 3 HRV engine
- **NTM-LD**: hypertonic saline paper, GEE piecewise spline
- **Teaching Monster**: automated AP-level edu video pipeline

## Exploration Frontier（龍蝦自主更新，你 approve）

### Active frontiers
- (龍蝦會在這裡提案新方向)

### Watch list — 值得追蹤的 authors/sources
- (龍蝦會在這裡推薦)

### Deprecated — 曾經追蹤但不再有用
- (龍蝦會在這裡記錄)

## Source Weights（龍蝦自動管理）

| Source | Weight | Last updated | Connect rate (7d) |
|--------|--------|-------------|-------------------|
| PubMed | 0.90 | — | — |
| bioRxiv | 0.75 | — | — |
| arXiv | 0.80 | — | — |
| Tavily (web) | 0.50 | — | — |
| Jina (Substack) | 0.45 | — | — |
```

---

## knowledge_state.json

不是 paper 的列表，是按 topic cluster 組織的「龍蝦目前對世界的理解」。

```json
{
  "clusters": {
    "hrv_firefighter": {
      "current_understanding": "HRV 在消防員 shift work 中的研究主要集中在 time-domain metrics，few studies combine with CGM...",
      "last_updated": "2026-04-10",
      "confidence": 0.6,
      "key_sources": ["ext_001", "ext_012"],
      "open_gaps": ["no study combines HRV + CGM in this population"],
      "related_clusters": ["cgm_glucose_variability", "occupational_stress"]
    },
    "cgm_glucose_variability": {
      "current_understanding": "...",
      ...
    }
  },
  "meta": {
    "total_clusters": 15,
    "last_major_update": "2026-04-10",
    "total_extracts_processed": 342
  }
}
```

---

## 保留的 v2.5 功能

### 社群發文（on-demand, 從 insight 觸發）

當 Synthesize 產出一個 `publishable: true` 的 insight：
1. 推送 Telegram 通知：「有一個可以發的 insight，要發嗎？」
2. 你 approve → 進入原本的 skill selection → draft → hook check → AI 味檢查 → 發 X + Threads
3. 你 reject → insight 存入 knowledge_state，不發文

保留的 skills（從 v2.5 不變）：
- research_commentary
- threads_voice
- all 10 skills

保留的 checks（不變）：
- Hook 強度 ≥ 7
- AI 味檢查（禁用詞、emoji 開頭、三點總結...）

### Telegram 互動

保留 v2.5 所有指令，新增：

| 指令 | 功能 |
|------|------|
| `/status` | 看 curiosity loop 狀態（目前 open_questions 數、今日跑了幾輪、token 用量） |
| `/questions` | 看目前的 open_questions 列表 |
| `/inject <question>` | 手動注入一個 open_question |
| `/evolve` | 立即觸發 Evolve，看 proposals |
| `/knowledge <topic>` | 查看 knowledge_state 中某個 cluster 的當前理解 |
| `/digest` | 查看最近一次 digest 的結果 |
| 貼 URL | 立即進入 Forage → Digest（跳過 Reflect/Hypothesize） |

### Mirror 週檢（升級）

Mirror 的 input 從「engagement metrics」擴展為：

```python
mirror_input = {
    "engagement": weekly_engagement_stats,       # 保留
    "digest_logs": weekly_digest_summaries,       # 新增
    "knowledge_diff": knowledge_state_diff_7d,    # 新增：這週學了什麼
    "connect_rates": source_connect_rates_7d,     # 新增
    "loop_stats": {                               # 新增
        "total_loops": 23,
        "avg_loops_per_day": 3.3,
        "empty_loops": 5,        # 沒產出 insight 的
        "questions_generated": 47,
        "questions_resolved": 31,
    },
    "human_interactions": weekly_interactions,     # 你跟龍蝦說了什麼
}
```

Mirror output 除了原本的 style.md 修改提案，加上 Evolve 的三種 proposals。

---

## 排程設計

### 保留 cron（社交行為）

```
09:30  晨間互動 — 抓 X mentions、replies、engagement
15:30  午後互動 — 同上
22:00  夜間沉澱 — 更新 memory.md、Telegram 每日摘要
週日 23:00  Mirror 週檢 + Evolve proposals
```

### 改為 event-driven（探索行為）

```
06:00  Seed — 跑 Reflect → Hypothesize → 產生當日初始 open_questions
18:00  Seed — 第二輪 Reflect（偏人文/跨域方向，保留 v2.5 的設計）

其餘時間：Curiosity Loop 自主運行
  - 有 open_questions → 跑一輪 Forage → Digest → Synthesize
  - 輪與輪之間 sleep 15-30 分鐘（防 rate limit + 像人類一樣有節奏）
  - 一天最多 10 輪（hard cap）
  - 沒有 open_questions → 不跑，等下次 seed 或你手動 inject
```

---

## 檔案結構（v2.5 → v3.0 diff）

```
lobster-v3/
├── identity/
│   ├── soul.md              ← 新結構（Core + Active Projects + Frontier + Weights）
│   ├── style.md             ← 不變
│   ├── curiosity.md         ← 改為 auto-generated from knowledge_state
│   └── memory.md            ← 不變
│
├── brain/                   ← 🆕 核心新模組
│   ├── reflect.py           ← Reflect agent
│   ├── hypothesize.py       ← Hypothesize agent（產生 open_questions）
│   ├── curiosity_loop.py    ← Loop orchestrator（event-driven）
│   └── knowledge_state.py   ← knowledge_state.json CRUD
│
├── digester/                ← 🆕 消化層
│   ├── extract.py           ← Source-aware structured extraction
│   ├── connect.py           ← Knowledge comparison (REMOTE)
│   ├── synthesize.py        ← Insight generation + new questions
│   └── schemas/             ← Extract schemas per source type
│       ├── pubmed.json
│       ├── arxiv.json
│       ├── blog.json
│       └── twitter.json
│
├── agent/                   ← 保留，加 evolve
│   ├── mirror.py            ← 升級版 Mirror
│   ├── evolve.py            ← 🆕 Source quality + frontier proposals
│   └── spawn.py             ← 不變
│
├── explorer/                ← 重構
│   ├── forage.py            ← 🆕 Question-driven multi-source search
│   ├── sources/             ← 🆕 Source adapters
│   │   ├── base.py
│   │   ├── pubmed.py
│   │   ├── biorxiv.py
│   │   ├── arxiv.py
│   │   ├── tavily.py
│   │   └── jina.py
│   └── rss.py               ← 保留（deterministic digest 用）
│
├── skills/                  ← 不變
├── publisher/               ← 不變
├── bot/                     ← 新增指令 handler
├── llm/                     ← 🆕 加 local model client
│   ├── router.py            ← LOCAL vs REMOTE routing
│   ├── local_client.py      ← Local GPT-OSS-B client
│   └── remote_client.py     ← OpenRouter client（原本的）
├── db/                      ← 加 knowledge_state table
├── scheduler/               ← 改為 2 seed + 4 social cron
├── utils/                   ← 不變
├── data/
│   └── knowledge_state.json ← 🆕 龍蝦的腦
└── main.py
```

---

## 環境變數（新增）

```bash
# 新增
LOCAL_LLM_BASE_URL=http://localhost:11434/v1    # 或你的 local API endpoint
LOCAL_LLM_MODEL=gpt-oss-b                        # 模型名稱
LOCAL_LLM_MAX_TOKENS=4096

CURIOSITY_LOOP_MAX_ROUNDS_PER_DAY=10
CURIOSITY_LOOP_SLEEP_BETWEEN_ROUNDS=900          # 15 分鐘
CONNECT_RATE_STALL_THRESHOLD=0.3                  # 連續 3 輪低於此值就暫停
KNOWLEDGE_STATE_PATH=data/knowledge_state.json

# 保留所有 v2.5 的環境變數
```

---

## Migration 計畫

### Phase 1（第 1 週）：建 brain + digester 骨架

1. 建立 `llm/router.py` + `llm/local_client.py`，確認 local GPT-OSS-B 可以通
2. 建立 `data/knowledge_state.json` 空結構
3. 實作 `digester/extract.py`（只做 PubMed schema 先）
4. 測試：手動丟一篇 PubMed article → extract → 看 output

### Phase 2（第 2 週）：Forage + Connect

1. 實作 `explorer/sources/pubmed.py` adapter
2. 實作 `digester/connect.py`（用 REMOTE Sonnet）
3. 實作 `brain/knowledge_state.py` CRUD
4. 測試：手動給一個 open_question → forage → extract → connect → 看 knowledge_state 有沒有更新

### Phase 3（第 3 週）：Reflect + Hypothesize + Loop

1. 實作 `brain/reflect.py` + `brain/hypothesize.py`
2. 實作 `brain/curiosity_loop.py` orchestrator
3. 加入 scheduler 的 06:00 / 18:00 seed trigger
4. 測試：讓 loop 自己跑一天，看 Telegram 通知

### Phase 4（第 4 週）：Evolve + Mirror 升級 + 其他 sources

1. 實作 `agent/evolve.py`
2. 升級 `agent/mirror.py` 的 input
3. 加入 bioRxiv、arXiv、Tavily source adapters
4. 加入 blog/twitter extract schemas
5. 新增 Telegram 指令（/status, /questions, /inject, /knowledge）
6. 全流程測試

### Phase 5（第 5 週+）：觀察 + 調參

- 觀察 connect rate by source，調整 initial weights
- 觀察 open_questions 品質，調整 Hypothesize prompt
- 觀察 loop 頻率是否合理
- 收集你的 approve/reject 資料，開始訓練 Evolve 的判斷力

---

## 預算估計

| 項目 | 月成本 |
|------|--------|
| Local LLM (GPT-OSS-B) | $0（你自己跑） |
| Remote LLM (Sonnet via OpenRouter) | ~$7.50（5 輪/天 × 30 天 × $0.05/輪） |
| Tavily | $0（免費 1000 次/月） |
| PubMed / bioRxiv / arXiv API | $0 |
| Jina Reader | $0 |
| Railway | ~$5 |
| X API | Free tier |
| **Total** | **~$12.50/月** |

比 v2.5 的預估 $30/月 便宜一半以上，但因為有 local LLM 做 heavy lifting，實際產出應該多很多。
