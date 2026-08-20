# Arbor 实验平台 · 日志手册 v1（草案，待 review 冻结）

> **状态:草案。** 本文档由实现反向整理而成 —— 代码先写、文档后补,因此
> **文档与实现天然一致**,不存在"两份规范对不上"的风险。
> 待补漏、review、冻结。冻结后 **schema 只增不改**。
>
> 实现位置:
> - 事件字典与信封校验 `backend/app/core/study_log.py`
> - 服务端事件 `backend/app/core/study_events.py`
> - 前端 SDK `study-app/src/lib/logger.ts`
> - 句子谱系 `study-app/src/lib/textEdit.ts` + `backend/app/core/sentences.py`

---

## 0. 三条总规则

**R1 · 命名一律 snake_case。**
分析管线是 Python,混入 camelCase 会导致两套命名在同一张表里。事件名、payload
字段名、枚举值,全部 snake_case。前端 TS 侧的变量名可以是 camelCase,但**写进
payload 的键必须是 snake_case**。

**R2 · 只记原始事件,不记派生量。**
典型反例:核验深度阶梯 L0–L4。它的停留阈值要 pilot 之后才定,如果现在记
`level: "L3"`,阈值一变就重算不出来了。
所以记的是:进入/离开的时刻、放大镜开关、滚动位置、缩放倍数 —— **级别在分析时算**。

同理不记:`total_dwell_ms`、`edit_count`、`verification_rate` 这类聚合量。
`dwell_ms` 是个例外,因为它由同一对 enter/exit 事件的 `ts_mono` 直接相减得到,
**两个原始时刻都在**,冗余但不丢信息。

**R3 · 拿不准就多记。**
多一个字段的成本约等于零;少一个字段,冻结后不可逆。特别是**人能读的标题**:
`node_id: "s4"` 六周后没人看得懂,`node_title: "决策与资源权限"` 是一句话。
事后抽样问答要按真实操作出题,日志必须自己说得出那句话。

---

## 1. 不可补类 · 逐条对照实现

以下四类一旦漏记,事后**无法从任何其他数据重建**。逐条列出当前实现状态。

| # | 要求 | 实现 | 状态 |
|---|---|---|---|
| 1 | **hover 的 enter/exit 双事件**（只有单事件算不出停留时长） | `hover_start` + `hover_end`,后者带 `dwell_ms`;两者各自带 `ts_mono` | ✅ 已实现 |
| 2 | **放大镜开关** | `lightbox_open` + `lightbox_close`(带 `dwell_ms`);单一入口 `openLightbox()` 保证成对 | ✅ 已实现 |
| 2b | **放大镜内的滚动** | — | ❌ **未实现**,见 §7 待办 |
| 3 | **初稿快照**:生成完成那一刻的全文 + 每句的 `sent_id`/`snippet_ids`/`exhibit_refs`/`subargument_id`/`planted_id`/位置 | `study_snapshots.write_snapshot(..., sentences=[...])` 已支持 sentences 数组 | ⚠️ **容器就位,generate 尚未实现**,见 §7 |
| 4 | **组织段每一次节点操作的前后状态** | `node_state` 带 `from`/`to`;`tree_op` 字典中已定义 | ⚠️ **`node_state` 已实现;`tree_op` 待树编辑 UI(M2)** |

---

## 2. 信封（schema v3）

每条事件,无论客户端还是服务端产生,都带这一层。

| 字段 | 类型 | 由谁填 | 说明 |
|---|---|---|---|
| `schema_version` | int | 服务端 | 当前 **3**。冻结后只增不改 |
| `seq` | int\|null | 客户端 | 每场次单调递增。服务端事件为 `null` |
| `srv_seq` | int\|null | 服务端 | 服务端事件的序号,与客户端 `seq` **不共用计数空间** |
| `ts_wall` | str | **服务端** | ISO-8601 UTC,到达时盖章 |
| `ts_client_wall` | str | 客户端 | 客户端自称的墙钟,仅供对照 |
| `ts_mono` | int\|null | 客户端 | `performance.now()` 起点差,毫秒。**场次内排序用它**,不用墙钟 —— 免受 NTP 校正与休眠唤醒影响 |
| `phase` | str | **服务端** | 服务端当时的阶段。客户端说的另存 `phase_client` |
| `phase_client` | str | 客户端 | 客户端自认的阶段。与上者不一致说明客户端落后一个轮询,分歧留痕 |
| `practice` | bool | 服务端 | `phase == "practice"` |
| `cond` | str | 服务端 | `c` \| `b` |
| `track` | str | 服务端 | `formal` \| `test` |
| `build` | str | 客户端 | 前端构建哈希 |
| `config_hash` | str | 服务端 | `study_config.json` 的语义哈希,建场时钉死 |
| `material_manifest_hash` | str | 服务端 | 材料包 manifest 哈希 |
| `tree_variant_id` | str | 服务端 | 5 棵候选树中选定的那棵的 id |
| `source` | str | 服务端 | `client` \| `server` |
| `session_id` | str | 服务端 | |
| `event` | str | — | 见 §3 |
| `payload` | obj | — | 见 §4 |
| `truncated` | bool | 服务端 | payload 超 64KB 时出现 |

**为什么要后三个哈希**:没有它们,日志说得清"发生了什么",说不清"发生在什么上面" ——
哪套参数、哪份冻结材料、五棵树里的哪一棵。而这恰恰是分析问的第一个问题:
**这场和那场可比吗。**

---

## 3. 事件字典（29 个 + 服务端 9 个）

字典是**封闭**的。不在表内的事件名直接拒收,不落入通用桶 —— 一个静默变成数据的
拼写错误,比一个被拒的批次更糟,因为分析永远不会知道它缺了。

### 3.1 服务端产生（客户端不得伪造）

| 事件 | 时机 |
|---|---|
| `session_created` | 主试建场 |
| `session_start` | 被试点「开始」 |
| `phase_enter` / `phase_exit` | 阶段推进,成对 |
| `phase_softlock` | 组织段超时（核验段永不产生,见 PR-6） |
| `submit_declared` | **被试声明完成的时刻。核验段没有锁也没有铃,这个时间戳就是"他选择核验多久"的因变量** |
| `submit` | 终稿落盘 |
| `draft_snapshot` | 快照落盘 |
| `msg_response` | B 组助手回复（B 已后置） |
| `frozen_draft_marked` | B 组判定（**已暂停,见 §8**） |
| `moderator_note` | 场记 |

### 3.2 两条件共有（客户端）

| 事件 | payload 关键字段 |
|---|---|
| `heartbeat` | — （30 秒自驱） |
| `panel_focus` | `panel`: evidence \| tree \| letter \| chat \| draft \| topbar |
| `doc_open` | `exhibit`, `from_exhibit`, `via` |
| `page_change` | `exhibit`, `page`, `from_page`, `via`: click \| scroll \| linkage, `surface` |
| `zoom` | `panel`, `from`, `to` |
| `checkpoint_passed` | `gate` （练习关卡） |
| `text_edit` | 见 §5 |
| `declare_done` | `condition` |
| `confidence_submit` | `likert_1_7`, `est_problem_count` |
| `probe_item` | `sent_id`, `judgment`, `rt_ms`, `source_opened`, `planted_id` |

### 3.3 条件 C 专有

| 事件 | payload 关键字段 |
|---|---|
| `hover_start` | `snippet_id`, `exhibit`, `page`, `label`, `node_id` |
| `hover_end` | 同上 + `dwell_ms` |
| `chip_click` | `snippet_id`, `exhibit`, `page`, `label`, `node_id`, `via` |
| `cite_click` | 同上（`via: "linkage"`） |
| `bbox_hover` | `snippet_id`, `exhibit`, `page` |
| `lightbox_open` | `snippet_id`, `exhibit`, `page`, `cited_page`, `label`, `via` |
| `lightbox_close` | `snippet_id`, `exhibit`, `page`, `dwell_ms` |
| `tree_op` | `op`, `node_id`, `node_title`, **`before`/`after` 全量状态** |
| `node_state` | `node_id`, `node_title`, `from`, `to`, `via` |
| `assign` / `unassign` | `snippet_id`, `exhibit`, `page`, `node_id`, `node_title` |
| `pool_drag_out` | `snippet_id`, `node_id` |
| `generate_trigger` | `scope` |

**`hover_*` 与 `chip_click` 严格分开是刻意的**:前者是"看了一眼",后者是"选定"。
分析要问的是"被试看了多少条证据却没有采纳",两者合并这个问题就问不出来了。

### 3.4 条件 B 专有（已后置）

`msg_send`（带全文）、`copy_to_draft`（带 `char_count` + `preview`）。

---

## 4. payload 通则

- **一律带人能读的标题**,不只带 id：`node_title`、`label`、`text`
- 位置类事件带**来源与去向**：`from_page` / `page`、`from_exhibit` / `exhibit`
- `via` 区分**被试自己导航**（`click`）与**系统联动跳转**（`linkage`）——
  这是 C 组特有行为的核心测量
- 上限 64KB;超出整体替换为 `{_truncated: true, _bytes: N}` 并在信封标 `truncated`
- 真正大的东西（草稿全文）进 `snapshots/`,事件里只留哈希与摘要

`study_log.summarise()` 把「带标题」这条承诺兑现成一行人话,例如:

```
moved "Decision and resource authority" under "The petitioner performs a leading role"
hovered evidence B1 p.4 for 1800ms without selecting it
read C1 p.1 magnified for 12400ms
```

---

## 5. 句子血缘规则（§5，实现版）

编辑防抖 **2 秒**。每次落 `text_edit`：

| 字段 | 说明 |
|---|---|
| `surface` | `letter` \| `draft` |
| `affected_sent_ids` | 本次改动波及的句子 id |
| `lineage` | `{旧 id: [新 id...]}`。拆句 → 一对多;被删/合并 → 空数组 |
| `splits` / `merges` | 计数 |
| `sentence_count` / `char_count` | |
| `kinds` | `{same, edited, rewritten, new}` 各自计数 |
| `changed_text` | 改动句的**原文**（最多 20 句），带 `sent_id` 与 `kind` |

对齐算法：**Dice 系数**（字符双字组），阈值

| 相似度 | 判定 |
|---|---|
| `= 1.0` | `same` |
| `≥ 0.92` | `edited`（同句改措辞） |
| `≥ 0.35` | `rewritten`（同位置实质重写） |
| `< 0.35` | `new` |

**两档阈值分别有意义**：`edited` 是校对，`rewritten` 是重想，合并会抹掉这个区别。

一句拆成两句时**两半都保留祖先链**；无人认领的旧 id 记空链而非消失。

**断句**：`sentences.py` / `sentences.ts`，两份实现由
`backend/tests/fixtures/sentences.json`（14 用例）锁死为逐案一致。
朴素的 `[.!?]\s` 切法会把 `Dr.` `Inc.` `U.S.` `et al.` `p.5` 全切开 —— 而句数直接
决定拷问抽哪 12–15 句。

---

## 6. 落盘与可靠性

```
data/workspaces/{ws}/sessions/{sid}/     # formal
data/study_test/{ws}/sessions/{sid}/     # test
├── events.jsonl      追加写,一批一次 fsync
├── snapshots/{id}.json
├── session.json
└── integrity.json    （M4）
```

| 故障 | 兜底 |
|---|---|
| 断网 30 秒 | 队列保留 + 指数退避;`seq` 断号服务端**登记不拒收** |
| 关标签页 | `pagehide` → `sendBeacon`（服务端裸读 body,因为 beacon 只能发 text/plain） |
| 浏览器崩溃 | localStorage 镜像,下次启动重放 |
| 服务端只收了一半 | 按 `acked_seq` 排水,剩下的重发 |

---

## 7. 待办（实现尚未覆盖）

1. **放大镜内的滚动位置** —— §1 第 2b 项。需要在 Lightbox 里记 `scroll_top` 变化
   （节流），M2 随 OCR 页一起做
2. **`page_change{via:"scroll"}`** —— 目前**故意不记**。曾用 `mouseEnter` 冒充滚动，
   那会往日志灌被试从没做过的导航；真正的 IntersectionObserver 检测随 M2 做。
   **宁可没有信号，不能有假信号**
3. **`tree_op` 的 before/after 全量状态** —— 树编辑 UI 在 M2
4. **初稿快照的逐句元数据** —— `sentences` 容器已就位，`generate` 未实现
5. **`planted_id`** —— 植入注册表随材料包一起冻结（见 §9）
6. **`bbox_hover`** —— 字典已定义，埋点待 M2

---

## 8. 条件 B：已后置

C 组先跑满 24 场；仅当招募超预期才加跑 6–8 人。相关的 prompt 注册表（BE-09）、
`frozen_draft_marked` 判定规则、B 组假实验验收，**全部后置**。
字典里保留 B 的事件定义，不删 —— 删了将来要改 schema。

---

## 9. 植入错误（新增，§0-2）

初稿快照每句多一个字段：

| 字段 | 说明 |
|---|---|
| `planted_id` | 植入注册表里的 id；**自然产生的句子为 `null`** |

植入注册表与材料包一起冻结，进 `manifest` 哈希。

拷问抽句时（PR-2）：**存活到成稿的植入句强制入选**，且植入句占比 ≤60%。

⚠️ **红线**：`planted_id` **只出现在服务端的快照文件里**，任何发给前端的响应都不含它。
这与干扰节点标记同级 —— 判断必须留给人。

---

## 10. 假实验脚本（待写）

按 §10 要求，我先写实现版本，你按我的版本核。待 M4 完成后补。
必测两项破坏测试：**拔网线 30 秒**、**关标签页**。

---

## 变更记录

| 日期 | 变更 |
|---|---|
| 2026-08-20 | 由实现反向整理成草案；schema v3（信封加 config/material/tree 三元） |
