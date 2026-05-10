# PROJECT — paper-lobster

> Salmon-owned ground truth(RESEARCH-PRINCIPLES §5 Step 1). Agent **不**代寫 §1, §2, §3, §8, §9。

```yaml
---
name: paper-lobster
status: active | dormant | stalled | pilot-rebuild | handover | publication-pending
canonical_source: <path or repo URL>
last_updated: YYYY-MM-DD
---
```

## 1. 一句話定位

(Salmon 自填:這個 project 在解決什麼臨床/科研問題)

## 2. 進度狀態

(Salmon 自選 status 上面 frontmatter)
last reviewed: YYYY-MM-DD

## 3. 主要協作者

(name + role)

## 4. Canonical surface

- code: `~/research/<proj>/code/`
- manuscript: `~/research/<proj>/manuscript/` 或 `gdrive:彥勛/...`
- refs: `gdrive:彥勛/papers_library/...` 或本機 symlink
- data: `~/research/<proj>/data/`(public 可進 git)
- data-local: `~/research/<proj>/data-local/`(sensitive,**永不**進 git/Drive)

## 5. Lineage

(舊版本 / 前一段 / 廢棄分支。看 `lineage.md`(若有)— 不重複,只在這裡寫 1 句「為何不 collapse」)

## 6. 重要 deps / runtimes

(see `.tool-versions` + 必要的 `env-spec.md`)

## 7. Sensitive data 處理

- 是否含 PHI / IRB-restricted?
- 是否含 NHIRD release files?
- `.gitignore` 排除哪些?
- (paper-organizer 等 public repo:額外 commit-time 檢查)

## 8. 下一步 Salmon 想做的事

(Salmon 自填,1-3 條)

## 9. Open questions

(blocking project progress 的問題)

---

## Agent rules(本 project 特別覆寫)

(若無 override 此節可空白,落用 `~/research/AGENTS.md`)
