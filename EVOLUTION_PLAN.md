# Lobster Evolution Plan — v4 → v5

Honest framing: `evolve.py` / `mirror.py` / `weekly_mirror` 目前產出是 *self-reports*，寫進 `evolution_log` / `evolution_proposals` 但很少真正改動決定行為的 surface（prompts、skill files、critic rubric、source weights 除了 `source_quality` 提案以外）。soul.md / style.md 的人工 approve 流程也卡著。

這份 plan 提四個可以把「感覺在進化」變成「資料上真的在進化」的方向。每一項都盡量符合：
- **一個閉環**（訊號進來 → 行為改變 → 新訊號驗證）
- **可 rollback**（版本化、不 overwrite）
- **可觀察**（Telegram 可以問「這週變了什麼」拿到具體答案）

---

## Locked decisions (2026-04-16)

| # | 決議 |
|---|---|
| P1 diff 模型 | `gpt-oss-120b`（local，free） |
| P1 target 範圍 | writer + editor + critic + hook 四個一起做 |
| P1 A/B | Day-1 只開 2 變體（baseline vs override），validate 通過後再升級 |
| P2 similarity | **沒 embedding**，改用 LLM pairwise judge（詳見下文 Mechanism） |
| P2 merge/split | merge day-1 做、split day-1 做（使用者接受風險）；每次 split 寫 dream_log 隔天審 |
| P3 分類模型 | `gemma4-26b`（local，free） |
| P3 target 範圍 | discovery / post / cluster / skill bias 四種都做 |
| P4 MVP | `/override` 指令 day-1 上線；critic_overrides 累積樣本後自動修正 |

---

## Proposal 1 — Outcome-gated prompt evolution

**目標**：讓 `posts.engagement_*` 這組已經在跑的資料，真的反饋回 Writer/Editor 的 prompt。

### 為什麼這個先做
這是唯一有 ground truth 的地方。其他方向（Critic 自評、reflection 自陳）都容易自我說服；engagement_24h / 72h 來自 X API，騙不了自己。目前 `engagement_samples` 塞進 Mirror 的 weekly_data 後就沒了 — 它會寫個 report，但 Writer 下一週用的還是同一份 soul.md + skill md。
=> 好的必須檢討

### Mechanism
```
posts.engagement_72h  ──►  Evolver weekly job
   (top/bot 10%)            (現有 evolve.py 擴充)
                                    │
                                    ▼
                         diff top vs bottom posts
                         產生 prompt_overrides.v{N}
                                    │
                                    ▼
                         load_identity() 疊加最新 active override
                                    │
                                    ▼
                         下週 post 用新 prompt → 新 engagement
                                    │
                                    └──► 下下週驗證 override 有沒有讓平均 engagement 上升
                                         沒上升 → auto-rollback
```

### Schema changes
```sql
create table prompt_overrides (
  id uuid primary key default gen_random_uuid(),
  version int not null,
  target text not null check (target in ('writer','editor','critic','hook')),
  content text not null,              -- 會被 append 到 skill md 的 delta prompt
  derived_from jsonb not null,        -- {top_post_ids:[], bottom_post_ids:[], diff_rationale:"..."}
  baseline_engagement numeric,        -- 產生這 override 時的 7d 平均 engagement
  validation_engagement numeric,      -- 套用兩週後量到的 7d 平均
  status text default 'active',       -- active / superseded / rolled_back
  created_at timestamptz default now(),
  validated_at timestamptz
);
create index on prompt_overrides (target, status);
```

`load_identity()` 加一步：從 DB 讀 `target=writer, status=active` 最新一筆，append 到 parts。

### Job
- 新增 `Evolver.run_prompt_override()`，跑在 Weekly Mirror 之後（週日 23:30）。
- 產出步驟：
  1. 拉過去 14 天 posts，按 `engagement_72h` 算每篇 likes+replies+reposts 的 z-score。
  2. Top 10% vs bottom 10%（至少各 5 篇才執行，不夠就跳過）。
  3. `chat_local` 呼叫 `gpt-oss-120b` 給出 diff：「高 engagement 那批比低的多 / 少了什麼具體 pattern？給 ≤200 字的 delta prompt。必須引用具體 post_id，禁止抽象化。」
  4. 寫進 `prompt_overrides`，status=active；把上一個 active 標 superseded。
- 新增 **驗證 job**（兩週後跑）：量過去 7 天平均 engagement vs `baseline_engagement`；
  - ≥ +15% → 保留，標 `validated_at`
  - ≤ −15% → 自動 rollback（status=rolled_back），前一代轉回 active
  - 其他 → 保留觀察

### MVP 範圍
- 四個 target 一起做：writer / editor / critic / hook（見 Locked decisions）。
- Day-1 A/B 只開 2 變體（baseline vs override），每個 variant 累積 ≥ 10 篇後才算有效樣本。Validate 第一次通過後再考慮升到 3 變體。
- Diff 步驟用 `gpt-oss-120b`（local，免費）而非 Sonnet。
- Telegram `/overrides` 指令列出目前 active 的 override + 其 baseline/validation 數字。

### 失敗模式
- Engagement metric 雜訊大（14 天樣本 ≤ 20 篇是常態）→ 用 z-score + 最小樣本門檻。
- LLM diff 只是套話（「寫得更有洞見」）→ prompt 強制要求引用具體 post_id 跟具體 pattern。
- 蓋掉 style.md 的個性 → override 存成 delta prompt 而非 replacement，soul/style 永遠是 base。

### 成功訊號
三個月內，至少有一次 override 被 `validated_at` 標記（engagement +15%）且沒被人工推翻。

---

## Proposal 2 — Auto-dream (offline cluster consolidation)

**目標**：把你提到的「auto dream」落成每晚跑一次的 `knowledge_clusters` 再壓縮。

### 為什麼需要
現在 `knowledge_clusters` 只在 curiosity loop 中 `connect` 步驟被動更新（一個 extract 進來、找最近 cluster、merge）。沒有「退一步看全局」的步驟。結果：
- Cluster 內容是 append-only 堆疊，不會 re-organize。
- 兩個重複的 cluster 不會自動合併（你早上遇到的 `vlm_i_medical_image` 找不到，可能就是 cluster 命名 / topic 偏移）。
- Confidence 分數沒人負責 bump / decay。

### Mechanism（no-embedding 版）
```
nightly 03:00
  ├─ pull 過去 7 天 extracts（未被 connect 到任何 cluster 的優先，上限 50 筆）
  ├─ pull 全部 active clusters (id + 名 + current_understanding 摘要)
  │
  ├─ Step A — 未分類 extracts 歸類：
  │     batch (每 10 筆 extract + 全部 cluster 清單) 餵 gpt-oss-120b
  │     要它為每筆 extract 選「最像的 cluster id」或回 "new_candidate:<proposed_topic>"
  │     → 選到現有 cluster → 更新 connections 表
  │     → new_candidate → 寫進 pending_clusters
  │
  ├─ Step B — Merge 偵測（只對本週有動的 cluster 做）：
  │     找出 updated_at 過去 7 天內的 cluster pair
  │     每對餵 gpt-oss-120b："這兩個 cluster 是同一主題嗎？{yes, no, subset}"
  │     yes → 合併（把較低 confidence 併入較高的）
  │     subset → 記錄 parent-child 關係（不破壞任一方）
  │
  ├─ Step C — Split 偵測：
  │     對每個 cluster 餵 gpt-oss-120b 其底下最新 15 筆 extract
  │     問它"這些 extract 應不應該拆成 ≥2 個子主題？"
  │     若 yes → 執行 split，每個 split 都寫 dream_log 隔天給人工審
  │
  ├─ Step D — Re-understanding + confidence decay（對每個 active cluster）：
  │     LLM 讀最新 10 筆 extract + 舊 understanding → 產生新 understanding
  │     confidence: 有新 supporting extract +0.05，7 天沒新資料 −0.02
  │     寫回 knowledge_clusters (current_understanding, confidence, updated_at, last_dream_at)
  │
  └─ 寫 dream_log 一條 summary 推 Telegram （簡短，"今晚合併 2 個、split 1 個、新增 3 個 candidate"）
```

**放棄的東西：**
- `/knowledge <topic>` 的 semantic 搜尋 — 沒 embedding 就沒模糊匹配，只剩 substring + fuzzy ratio。今早 `vlm_i_medical_image` 這類 case 短期無解。未來若 local endpoint 加了 embedding 模型，補一個 dream 前的 re-embed 步驟就能開啟。

**預期成本：**
- 純 local LLM tokens（你 host，免費）。
- 預估每晚 job 耗時 10–15 分鐘（50 extracts × LLM call + N(N-1)/2 對 merge judge + N 次 re-understanding）。比有 embedding 版慢 5–10 倍但跑在你睡覺時間。

### Schema changes
```sql
-- 擴充現有 knowledge_clusters：
alter table knowledge_clusters add column if not exists last_dream_at timestamptz;
alter table knowledge_clusters add column if not exists parent_cluster_id text; -- for subset relations
alter table knowledge_clusters add column if not exists interest_score float default 0.5; -- 給 P3 用

-- 新表
create table dream_log (
  id uuid primary key default gen_random_uuid(),
  ran_at timestamptz default now(),
  clusters_before int,
  clusters_after int,
  merges jsonb,            -- [{from:[id1,id2], into:id1}, ...]
  splits jsonb,            -- [{from:id1, into:[id_new1, id_new2], rationale:"..."}, ...]
  new_candidates jsonb,    -- [{proposed_topic, extract_ids}]
  narrative text,          -- LLM 寫給使用者看的一段話
  llm_tokens_used int      -- 監控
);

create table pending_clusters (
  id uuid primary key default gen_random_uuid(),
  proposed_topic text,
  extract_ids uuid[],
  seen_count int default 1,    -- 連續幾晚出現才 promote
  first_seen timestamptz default now(),
  last_seen timestamptz default now()
);
```

### Job
- 新 heartbeat `nightly_dream`：cron hour=3, minute=0，jitter 20 min。
- 檔案：`lobster/brain/dream.py`。
- 依賴：只有 local LLM（無 sklearn / 無 embedding / 無外部 API）。

### MVP 範圍
- 四個 Step 都 day-1 做（user 接受風險）。
- Split 每次一定要寫進 `dream_log.splits`，隔天早上推播讓你可以手動 revert。
- pending_clusters 需要連續 3 晚出現才 promote 成 cluster（避免 noise）。
- Telegram 早上推送：「🌙 昨晚合併 X 個、split Y 個、新增 Z 個 candidate」。

### 失敗模式
- LLM 判斷不一致（同一 cluster pair 隔天給不同答案）→ pairwise judge 採「連續 2 晚都說 merge」才真正合併。
- LLM 自己寫 understanding 越寫越空泛 → prompt 強制「引用具體 extract_id，不能抽象化」，每次把「前一版 understanding」當輸入要求 ≥30% 內容保留（避免無來由重寫）。
- 3 點跑的時候跟 morning_seed 6 點錯開，不會撞 LLM。
- Split 錯了 → 每個 split 提供一個 `dream_log.id` → `/revert_split <dream_log_id>` 指令一鍵還原。

### 成功訊號
- Cluster 數量一個月後不會爆炸（pending_clusters 有守門）。
- `confidence` 分布從「全是 0.5」變成 0.2–0.9 spread（代表真的在區分高/低信度）。
- 手動審 dream_log 的 merge/split 決定，同意率 ≥ 70%。

---

## Proposal 3 — Interaction signals as dials

**目標**：把 `interactions` 表裡已經在累積的互動訊號，變成 `source_weights` / cluster `interest_score` 的輸入。

### 現況
`interactions` 表有：`type`、`judged_as`、`thread_id` 等。但看 code 只有 `insert_interaction` 跟 count 類 query，沒有「讀使用者 signal → 調權重」的 path。你對某篇 discovery 說「無聊」跟「再寫長一點」現在沒地方存，也沒地方回饋。

### Mechanism
```
你的 Telegram reply
  ├─ 若 reply 到某篇 discovery → 存 discovery_feedback
  ├─ 若 reply 到某篇 post draft → 存 post_feedback
  └─ Lobster 用 chat_local 分類成一個 enum: {boring, nice, too_short, too_long, wrong_tone, love_it, more_like_this, less_like_this}

daily 23:55 aggregator
  ├─ 讀過去 24h feedback
  ├─ 按 feedback.source / feedback.cluster / feedback.skill 聚合
  └─ 更新：
       - source_weights.weight        （boring → -0.05, love_it → +0.05）
       - knowledge_clusters.interest_score（目前沒這欄，要加）
       - skills 使用率 bias（下次選 skill 時的 prior）
```

### Schema changes
```sql
create table feedback (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz default now(),
  user_text text not null,
  classified_as text,                 -- 上面的 enum
  target_type text,                   -- discovery / post / cluster / skill
  target_id uuid,
  applied boolean default false,
  applied_at timestamptz
);

alter table knowledge_clusters add column if not exists interest_score float default 0.5;
alter table skills_usage add column if not exists human_bias float default 0.0;
-- （skills_usage 若沒有就要先建）
```

### Job
- 修改 Telegram bot 的 `handle_message`：任何非 command 的純文字訊息若 *reply to* 了某則 bot 的訊息，歸類成 feedback 並 insert。
- `lobster/brain/feedback_aggregator.py`，跑在 nightly 23:55（mirror 前）。
- 聚合後更新對應 weight 欄位；寫一條 `evolution_log` 紀錄。

### MVP 範圍
- 做 target：discovery、post、cluster、skill bias（目前是 Strategist 的事）。
- 單一 feedback 影響 cap 在 ±0.05，避免一句話把某個 source 打死。
- 分類用 local LLM（gemma4-26b），不用 remote 省預算。

### 失敗模式
- 分類不準 → 在 Telegram 加 reaction buttons（👍 👎 🥱 📏）當可選結構化輸入；純文字保留為 fallback。
- 你心情不好把什麼都打負分 → 加 rolling window smoothing（7 天移動平均而不是當天直接套用）。

### 成功訊號
- 一個月後，不同 source 的 weight 拉開（現在 RSS 各 source weight 應該都還是 0.5 附近）。
- `source_weights.connect_rate_7d` 跟 user satisfaction 開始 correlate。

---

## Proposal 4 — Self-tuning Critic

**目標**：Critic 的 rubric 不是靜態 prompt，而是會根據「被 Critic 殺掉但事後發現值得發」的案例，每週修正自己。

### 為什麼擺最後
這個最容易退化成「Critic 越變越寬鬆最後什麼都 publish」或「越變越嚴最後什麼都 kill」。需要有 grounded ground truth 才不會 drift，而那個 ground truth 就是 #1 跟 #3 的輸出（engagement + human signal）。所以要在 1+3 跑穩之後才啟動。

### Mechanism
```
critic killed → 留在 posts（status='killed_by_critic'）
    │
    ├─ 你可以用 /override <post_id> 撈回某個被 kill 的 draft 手動發
    │  → 標記 human_override=true
    │
    └─ weekly analysis:
        ├─ killed + human_override + engagement 高 → "critic 抓錯了"
        ├─ killed + human_override + engagement 低 → "critic 抓對了"
        ├─ published + engagement 低             → "critic 漏抓"
        └─ published + engagement 高             → "critic 抓對了"
    │
    ▼
  產生 critic_overrides（同 Proposal 1 的 prompt_overrides 機制，只是 target='critic'）
```

### Schema changes
- 重用 Proposal 1 的 `prompt_overrides` 表，`target='critic'`。
- `posts` 加欄位：`status`（draft / killed_by_critic / published / human_override）；`human_override_at`。
- `killed_drafts` 另存或 posts 裡多留一份 `draft_text` + `kill_reason`（後者 `run_critic` 已經有 issues 欄可用）。

### Job
- Weekly，跑在 Evolver 之後。
- 只有當 confusion matrix 四象限都 ≥ 3 樣本才跑（樣本不夠就跳週，避免過擬合單一案例）。

### MVP 範圍
- `/override <post_id>` 指令 day-1 上線（讓你手動救被 kill 的 draft 發文，累積 human_override 樣本）。
- 樣本累積 ≥ 3 個/象限後自動啟動 critic_overrides（重用 Proposal 1 的 prompt_overrides 表，target='critic'）。

### 失敗模式
- 你懶得用 `/override` → 樣本永遠不夠 → 這個 proposal 就是不啟動（自動 degrade 到 no-op，這是好事不是 bug）。
- Critic 被調成一直 publish → 保留底線：hook_score < 6 / ai_smell 失敗這種硬規則不受 override 影響。

### 成功訊號
- 三個月後回看：human_override=true 且 engagement 高 的比例下降（因為 Critic 變聰明，不再錯殺）。

---

## 整體時程建議

| 週 | 做什麼 |
|---|---|
| W1 | Schema migration 下 Supabase；P1 stub + dry-run（不套 override）；`/override` 指令（P4 需要） |
| W2 | P1 切 active=true（A/B: baseline vs override 兩變體）；P2 dream.py 上線（Step A+D：歸類 + re-understanding + decay） |
| W3 | P2 Step B+C：merge + split；P3 feedback 表 + Telegram reply capture |
| W4 | P1 驗證 job；P3 aggregator；整合 `/evolution` 指令統一顯示 |
| W5–W8 | 觀察 + 調參；累積 P4 樣本 |
| W9+ | P4 critic_overrides 自動啟動（若四象限樣本都 ≥ 3） |

## 共通原則（不論做哪個）

- **每個 proposal 都要有 rollback path**。override 系統不覆寫 base（soul.md / skill md 不動）。
- **每週 Telegram 推一句話的「這週變了什麼」**：不是 mirror 那種 3000 字報告，就一行：「writer override v3 上線，baseline=42，驗證中」。
- **加一個 `/evolution` 指令**列出所有 active 的 override / 最新 dream_log / 最近 feedback summary。透明才敢信。

---

## 已確認的決策

見開頭「Locked decisions (2026-04-16)」表格。所有決策已鎖定，可以開始 schema + coding。