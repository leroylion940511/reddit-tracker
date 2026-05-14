# v4 Schema — Reddit Tracker

> 對應 SCHEDULE.md M2.1。12 張表，分四群：探索 / 評分推送 / 收藏追蹤 / LLM 與問答。
> 與 v3 schema 大架構相同，差別在 Reddit 化的欄位名與 `related_posts.relation_type` 多了 `crosspost`。

---

## 表分群

| 群組 | 表 | 用途 |
|------|----|----|
| 探索 | `candidate_posts`、`subreddit_sources`、`keyword_seeds` | M2 |
| 評分推送 | `scoring_records`、`daily_pushes`、`feedback` | M3 + M4 |
| 收藏追蹤 | `tracked_posts`、`post_snapshots`、`related_posts` | M5 |
| LLM 與問答 | `llm_records`、`qa_sessions`、`qa_messages` | M3 + M6 |

---

## ER 圖（mermaid）

```mermaid
erDiagram
    candidate_posts ||--o{ scoring_records : "has scores"
    candidate_posts ||--o{ daily_pushes : "pushed as"
    candidate_posts ||--o{ feedback : "user reaction"
    candidate_posts ||--o| tracked_posts : "promoted to"

    tracked_posts ||--o{ post_snapshots : "time-series"
    tracked_posts ||--o{ related_posts : "follow-ups"
    tracked_posts ||--o{ qa_sessions : "/ask context"

    qa_sessions ||--o{ qa_messages : "multi-turn"

    candidate_posts {
        bigint id PK
        string reddit_post_id UK "PRAW submission.id"
        string subreddit
        string title
        text selftext
        string permalink
        string author_username
        int author_karma
        datetime author_created_utc
        datetime posted_at
        datetime discovered_at
        string discovery_source "subreddit:<name> / keyword:<seed>"
        int initial_score
        int initial_num_comments
        float upvote_ratio
        string lang "zh-Hant / en / ..."
        json metadata "raw PRAW payload"
    }

    scoring_records {
        bigint id PK
        bigint candidate_post_id FK
        string stage "rules / haiku / final"
        bool passed
        float score
        json details
        datetime scored_at
        decimal cost_usd
    }

    daily_pushes {
        bigint id PK
        date push_date
        bigint candidate_post_id FK
        string push_type "already_hot / early_bet / breaking"
        int rank
        datetime pushed_at
    }

    feedback {
        bigint id PK
        bigint user_id
        bigint candidate_post_id FK
        string action "collect / dislike / mute_author"
        datetime acted_at
    }

    tracked_posts {
        bigint id PK
        bigint candidate_post_id FK
        bigint user_id
        datetime promoted_at
        string polling_tier "hot / warm / cold"
        datetime last_polled_at
        string status "active / paused / archived"
        text initial_summary
    }

    post_snapshots {
        bigint id PK
        bigint tracked_post_id FK
        datetime captured_at
        int score
        int num_comments
        float upvote_ratio
        json new_comments "delta since last snapshot"
    }

    related_posts {
        bigint id PK
        bigint tracked_post_id FK
        string reddit_post_id "t1_xxx for comment / t3_xxx for submission"
        string relation_type "author_followup / author_reply / hot_reply / crosspost"
        float relevance_score
        bool is_milestone
        text content
        datetime posted_at
        datetime discovered_at
    }

    subreddit_sources {
        int id PK
        string name UK
        string lang_hint "zh / en / mixed"
        bool enabled
        datetime last_polled_at
        int total_candidates_yielded
        int total_promoted
        int total_collected
    }

    keyword_seeds {
        int id PK
        string keyword UK
        string category
        string lang "zh / en"
        bool enabled
        datetime last_polled_at
        int total_candidates_yielded
        int total_promoted
        int total_collected
    }

    llm_records {
        bigint id PK
        string provider "anthropic / minimax"
        string model
        string purpose "scoring / summarization / qa"
        int input_tokens
        int output_tokens
        int cached_tokens
        decimal cost_usd
        datetime called_at
        json context_ref "polymorphic FK"
    }

    qa_sessions {
        bigint id PK
        bigint user_id
        bigint tracked_post_id FK
        datetime started_at
        datetime ended_at
        string state "active / closed / timed_out"
    }

    qa_messages {
        bigint id PK
        bigint qa_session_id FK
        string role "user / assistant"
        text content
        int input_tokens
        int output_tokens
        decimal cost_usd
        datetime sent_at
    }
```

---

## 設計筆記

### 沿用 v3 的決定（PROGRESS.md gotcha 第 99–108 行）

- **BigInt PK 在 SQLite 不會 auto-increment** → 統一用 `BigInteger().with_variant(Integer(), "sqlite")`
- **JSON 欄位**：直接用 SQLAlchemy `JSON` type，Postgres 自動 JSONB、SQLite 自動 TEXT。
  v3 的自訂 `JSONField` + alembic mako import 那個坑直接避開。
- **timestamps**：全部 `DateTime(timezone=True)`，存 UTC tz-aware。
- **LLMSummary**：v3 把 evolution JSON 塞 `content` 字串裡。v4 沿用，所以 schema 不開 `evolution_summaries` 表，
  在 `llm_records` 內用 `purpose='summarization'` + `context_ref` 反查。

### v4 新增 / 改名

- `candidate_posts`：`thread_id` → `reddit_post_id`、新增 `subreddit` / `author_karma` / `upvote_ratio` / `lang`
- `related_posts.relation_type`：新增 `crosspost`（v3 沒有，是 Reddit `submission.duplicates()` 的產物）
- `subreddit_sources`：v3 沒這張表（Threads 時期 keyword 是唯一 source）

### 索引（M2.3 migration 中建立）

| 表 | 索引 | 理由 |
|----|------|------|
| `candidate_posts` | `(reddit_post_id)` UNIQUE | 去重 |
| `candidate_posts` | `(discovered_at)` | discovery job 排序 |
| `candidate_posts` | `(subreddit, posted_at)` | per-sub 統計 |
| `scoring_records` | `(candidate_post_id, stage)` | 取最新 verdict |
| `daily_pushes` | `(push_date, rank)` | 每日 Top 5 查詢 |
| `tracked_posts` | `(polling_tier, last_polled_at)` | 分級輪詢調度 |
| `related_posts` | `(tracked_post_id, relation_type)` | 後續事件查詢 |
| `subreddit_sources` | `(name)` UNIQUE | seeds loader idempotent |
| `keyword_seeds` | `(keyword)` UNIQUE | seeds loader idempotent |
