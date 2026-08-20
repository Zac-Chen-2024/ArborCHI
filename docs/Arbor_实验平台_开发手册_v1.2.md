# Arbor 实验平台 · 前后端开发手册(v1.2)

> 2026-08-19 · 依据:实验方案 v2.1 + 日志手册 v1 + **PetitionLetter2.0 @ `468d5dd`(origin/main,已逐文件核实)**
> 前端视觉规格 = `arbor-write-mode-v5.html`(条件 C)+ `baseline-shell-b-v3.html`(条件 B),像素级照抄。
> **界面双语,默认英语。** 所有面向被试的字符串走 i18n,禁止硬编码。
> v1 → v1.1 → v1.2:前端逐文件核实,新增 §7.5 复用清单;修正 logger 与 bbox 两处判断。原 v1.1 说明:仓库为 public,已 clone 并逐项核对;v1 中所有 `[验证]` 标记已消除,§0.5 与 §2 按实锤重写。

---

## 0.5 现状核对结论(commit `468d5dd`,production-hardening 已合并)

**这个 PR 做的比阶段 0 计划多得多——阶段 0 全部七项 + 阶段 1 的三项全部落地:**

| 已在仓库里的 | 位置 | 对实验的意义 |
|---|---|---|
| workspace 隔离(0.2) | `backend/app/core/workspace.py` + `WorkspaceMiddleware`(main.py 已挂)+ `backend/scripts/mint_token.py` | 一 token = 一工作区 = 一被试,**直接可用**;资源 URL 支持 `?token=` |
| 交互日志(0.3) | `backend/app/routers/logs.py` → `data/workspaces/{ws}/logs/{session_id}.jsonl` | 端点存在,但 schema 是产品版(见 §4.2 的处置) |
| 原子写入(0.1) | `backend/app/core/atomic_io.py`,**含 `append_jsonl`** | 日志落盘原语现成 |
| prompt 外置(1.1) | `backend/app/core/prompt_loader.py`;`legal_argument_organizer.py` 已减 1200+ 行 | B 组策略 prompt 走同一注册表,版本+哈希免费获得 |
| llm 层(1.2) | `llm_client.py`:tenacity 重试 + JSONL tracing(`data/traces/`)+ 内容寻址缓存(`data/llm_cache/`)+ `llm_providers.py` | 生成可复现性的地基现成;`msg_response` 可引用 trace 行 |
| 任务队列(1.3) | `core/jobs.py` + `routers/jobs.py`(排队/轮询/取消) | 实验用不上(§2),但在那儿 |
| 测试 + CI(0.6) | `backend/tests/` 13 个文件 + `.github/workflows/ci.yml` | study 代码照这个盘子加测试 |
| 死代码清理(0.5)+ 目录拍平(0.7) | 服务层 30+ → 16 文件;`frontend/frontend` → `frontend/src`;debug_output 出库 | 手册里所有前端路径按 `frontend/src` 算 |
| CORS/异常(0.4) | `settings.cors_origin_list`;errors.py 重写 | 覆盖到 `/api/study/*` 即可 |

**三个要知道的变化:**

1. **writing 只剩 v3**(`/api/write/v3`),v1/v2 已删;全路由挂了 `validate_path_params`。
2. **一批离线管线服务被删了**:`provenance_engine`、`deepseek_ocr`、`evidence_checker`、`snippet_extractor/linker`、`entity_resolver` 等。运行时 bbox 数据现在由 `snippet_registry.py` 携带(quotes 内含 `{page, bbox}`)。**对实验的含义:材料包制作(§3)是离线工序,可能要从历史 commit 里捞这些工具或独立写脚本——这是 v1.1 里唯一剩下的 `[验证]` 项。**
3. **bbox 归一化约定已存在**:`DocumentViewer` 按 1000×1000 归一化空间换算(坐标 ÷1000)。材料包沿用该约定即可,manifest 另记每页宽高兜底(红线 #8 视为已满足,前提是逐 exhibit 抽查一遍约定一致)。

**前端可白拿的三样**:`TokenGate.tsx`(token 进门,study-app 照抄思路)、`i18n/locales/{en,zh}.json` + `LanguageSwitcher`(i18n 底座已存在,study-app 复用配置方式但按 §6 规则去掉被试端切换)、`BBoxLightbox.tsx` / `Magnifier.tsx` / `DocumentViewer.tsx`(共享 `EvidenceViewer` 的参考实现,搬逻辑不搬样式)。前端 `services/interactionLogger.ts` 已实现批量 flush、sendBeacon 兜底、失败恢复与按 key 节流——**它就是日志 SDK 的 80%,扩展不重写**(补 seq / ts_mono / phase / practice / study 信封与新端点,见 §7.5)。

---
## 0. 一句话目标

在现有仓库里长出一个**实验专用子系统**:两个条件前端(C=Arbor、B=DraftDesk)+ 一个共享后端(会话/阶段机、日志、快照、冻结生成),被试全程走它,产品线原封不动。

---

## 1. 总体架构决策(先定死,不然后面全乱)

### D1 · 实验前端是新建 app,不改造现有前端

```
PetitionLetter2.0/
├── backend/            # 现有 FastAPI,增量加 /api/study 命名空间
├── frontend/           # 现有产品前端 —— 实验期间冻结,一行不动
└── study-app/          # 新建:Vite + React + TS,两条件共用一个 app
```

理由:①两个 mockup 的信息架构(嵌套卡片树)和现有 `ArgumentGraph.tsx`(2656 行手写 canvas)是两套东西,改造比新写贵;②实验代码要在 pilot 后**功能冻结**,和产品线共用一个 app 就冻不住;③`WritingContext`(1124 行)`[验证]` 不进实验——study-app 用一个薄 store,状态形状按日志手册的事件反推。

**连带决定:原计划阶段 2.2 的 react-flow 迁移,对实验线正式取消。**

### D2 · 一个 app,两条路由,条件由服务端定

```
/join?token=…   → 服务端返回 {condition, lang, phase} → 渲染 /c 或 /b
/c              → Arbor 条件(v5 布局)
/b              → DraftDesk 条件(v3 布局)
/mod            → 主试面板(moderator token 才进)
```

条件**不由 URL 决定**,由 token 对应的 session 配置决定——被试改 URL 也切不了条件。

### D3 · 共享层物理共享,不是复制

两个 mockup 里那段相同的 token/组件 CSS,在 study-app 里必须是**同一个文件**:

```
study-app/src/
├── tokens.css                  # 从 mockup 提取,唯一真源(高度/颜色/圆角/阴影)
├── i18n/{en.json, zh.json}
├── lib/
│   ├── logger.ts               # 日志 SDK(§5)
│   ├── api.ts                  # fetch 封装,自动带 Bearer token
│   └── session.ts              # 阶段状态轮询 + 软锁
├── components/shared/          # 两条件物理共用
│   ├── TopBar.tsx              # 56px;阶段签;组织段才渲染倒计时
│   ├── EvidenceViewer/         # phead + ctxstrip + exstrip + 页面区 + pager
│   │   ├── ExhibitStrip.tsx
│   │   ├── PageView.tsx        # OCR 页渲染;bbox 高亮由 prop 开关(C 开 B 关)
│   │   └── PagerBar.tsx
│   ├── Lightbox.tsx            # 3× 放大镜(仅 C 挂载)
│   └── PaperPage.tsx
└── conditions/
    ├── c/  TreePanel · ArgumentCard · SubArgCard · SnippetChip
    │       LetterPanel · RelationsPanel · CrumbStrip
    ├── b/  ChatPanel · DraftEditor
    └── common/  ConfidenceForm · ProbeRunner · SubmitLock · TutorialGate
```

`EvidenceViewer` 是"访问对等、只差链接"的物理保证:**同一个组件**,C 比 B 多传 `linkage` 相关 props(bbox 高亮、由 cite/chip 触发的跳转)。

---

## 2. 后端复用表(实锤版)

| 模块(真实路径) | 实验角色 | 动作 |
|---|---|---|
| `core/workspace.py` + `scripts/mint_token.py` | 被试/主试鉴权 | 复用;token 表加 `role: participant\|moderator` 字段(mint_token 加 `--role` 参数,middleware 读出放 request.state) |
| `routers/logs.py` | 产品线日志,**不动它** | study 新开 `/api/study/log/batch`(§4.2):信封含 seq/ts_mono/phase/practice/cond/build,事件字典按日志手册;落盘复用 `atomic_io.append_jsonl`;产品端点与白名单保持原样,两线互不污染 |
| `core/atomic_io.py` | 快照 + JSONL | 原样复用 |
| `core/prompt_loader.py` | B 组 system prompt / bootstrap prompt 注册 | 复用;manifest 记 prompt id + version + hash |
| `llm_client.py` + `llm_providers.py` | B 聊天与 C 增量生成 | 复用;model/params 从材料包 manifest 钉死;tracing 行号回填进 `msg_response`;llm_cache 作为冻结生成之外的第二道可复现保险(pregen 文件仍是第一真源) |
| `core/jobs.py` | — | **不用**:生成 = 读 pregen + 少量增量,同步 30s 超时足够;留作万一增量生成过慢的逃生门 |
| `snippet_registry.py` | bbox 与 snippet 元数据的现役来源 | 材料包制作时从它导出;像素 bbox → 归一化(带页宽高) |
| `petition_writer_v3.py` + `writing_strategies.py` + `subargument_generator.py` | 离线:预生成 5 棵树与逐节点文本 | 加 `--seed` 透传即可,不重构 |
| `unified_extractor.py` + `standards_registry.py` | 离线材料制作 | 视需要;OCR 与 provenance 旧工具已删,材料包工序可能需从历史 commit 捞或另写脚本 `[验证]` |
| `tests/` + CI | 质量盘子 | study 后端每个新模块配测试,进同一 CI |

## 3. 材料包(Material Bundle)

实验运行时**只读**这个目录,与产品数据完全隔离:

```
backend/study_materials/case_v1/
├── manifest.json        # material_hash, tree_hash, model, model_params, seed,
│                        #   frozen_at, schema_version —— session_start 事件的数据源
├── exhibits/{A3,B1,…}/
│   ├── pages/p{n}.png
│   └── ocr.json         # 每页文本 + bbox(归一化 0–1 坐标,不存像素!)
├── snippets.json        # snippet_id → {exhibit, page, bbox, text, summary, entities[]}
├── relations.json       # snippet_id → 事实三元组(实体关系面板数据;只陈述,无评价字段)
├── tree.frozen.json     # 按预注册规则选定的那棵;含干扰节点标记(仅后端可见,前端不下发标记)
├── pregen/{node_id}.json# 逐句 {sent_id, text, snippet_ids, exhibit_refs, sentence_type, source:"frozen"}
├── prompt_b.txt         # B 组 system prompt(粒度对齐自动树)+ 哈希
├── bootstrap_b.txt      # B 组界面自动发出的首条 prompt + 哈希
└── practice/            # 练习迷你材料(另一法条),结构同上
```

**红线:`tree.frozen.json` 里的干扰节点标记、答案卷、探针 ground truth 一律不进任何发给前端的响应。**前端拿到的树和普通节点无任何区别——判断必须留给人。

---

## 4. 后端开发(`/api/study` 命名空间)

### 4.1 会话与阶段机

```
POST /api/study/sessions            [mod] 建场:{condition, participant_code, lang:"en"|"zh"}
                                          → {session_id, join_token}
GET  /api/study/state               [ptc] 轮询(2s):{phase, softlock, org_deadline_mono_ms?, lang}
POST /api/study/advance             [mod] 阶段推进;服务端写 phase_enter/exit
POST /api/study/submit              [ptc] 提交 → 校验 final_text_hash → 落终稿 snapshot → 锁定
```

阶段机按日志手册 §3:`setup → tutorial → practice → organization → generation → verification → confidence → probe → done`(B 组为 `…practice → work → confidence…`)。

计时全在服务端:组织段 deadline 随 `state` 下发(前端只渲染倒计时);核验段服务端静默计时,到 Y+10 置 `softlock:true`——**核验段的 state 响应里没有任何剩余时间字段**,前端想显示也没数据。

### 4.2 日志端点(升级 0.3)

```
POST /api/study/log/batch     体:{events:[…]}  信封按日志手册 §2
```

服务端职责:校验 token → 校验 `seq` 连续(断号照收,登记 gap)→ `append_jsonl` 到
`data/workspaces/{ws}/sessions/{sid}/events.jsonl` → 返回 `{acked_seq}`。
`draft_snapshot` 类事件:events 里存摘要+哈希,全文写 `snapshots/`。

### 4.3 生成(仅 C)

```
POST /api/study/generate      体:{node_states:{node_id: NodeState}}
```

逻辑:逐节点判断——与冻结树一致(未动/仅采用)→ 读 `pregen/{node_id}.json`;被改名/改挂/新建 → 用 `llm_client` 现场生成(manifest 里的 model/seed),产出句子打 `source:"live"`。拼装全文 → 立即落 **`draft_snapshot`**(被试做任何编辑之前)→ 返回全文+逐句元数据。

**这是全项目唯一过期不可补的功能,里程碑 M1 就要通,不许排到后面。**

### 4.4 聊天(仅 B)

```
POST /api/study/chat          体:{messages:[…]}
```

服务端注入 `prompt_b.txt` 为 system;session 首次调用由**服务端**自动前置 `bootstrap_b.txt`(前端不发第一条);每次响应落 `msg_response` 事件(全文进 snapshots/)。服务端按预注册规则(首条覆盖两主论点且含引证的完整输出)判定并落 `frozen_draft_marked` + 对应 `draft_snapshot`。

### 4.5 拷问与信心

```
POST /api/study/probe/start   → 服务端从终稿 snapshot 按分层规则抽 12–15 句,返回 items
POST /api/study/confidence    体:{likert_1_7, est_problem_count} → 落 confidence_submit
```

`probe/start` 必须校验 `confidence_submit` 已存在,否则 409——顺序红线由服务端把守,不信任前端。

### 4.6 主试面板 API

`GET /api/study/monitor/{sid}`(最新 seq、心跳时间、当前阶段)· `POST /api/study/note`(场记)· 收场触发 `integrity.json` 生成(日志手册 §8 清单)。

---

## 5. 前端日志 SDK(`lib/logger.ts`)

单例。职责照日志手册 §1 实现,要点:

```ts
log(event: string, payload?: object)   // 自动补信封:seq++ / ts_wall / ts_mono / phase / practice
```

- 内存队列,5s 或 20 条触发 batch;失败指数退避;队列镜像 localStorage(崩溃恢复)
- `visibilitychange→hidden` 与 `pagehide`:`navigator.sendBeacon` 冲刷
- `phase` 与 `practice` 从 `session.ts` 读,调用方不传
- 心跳 30s 自驱
- **埋点即 hook**:`SnippetChip` 的 hover/click、`Lightbox` 的 open/close(自算 dwell_ms)、`TreePanel` 的 tree_op/node_state、编辑器 `text_edit`(debounce 2s、带 affected_sent_ids)——对照日志手册 §4 事件字典逐条落,字典里没有的不发明,指标要的不遗漏

---

## 6. i18n(双语,默认英语)

- 库:`react-i18next`;`lang` 由 session 配置下发(建场时主试选),被试端**无切换开关**——一场实验一种语言,混语言的场次数据不可合并
- 规则:任何 JSX 里出现裸中文/英文 UI 字符串 = review 打回;上 ESLint 规则(`i18next/no-literal-string`)
- 材料内容(exhibit、生成文本)本身是英文,不走 i18n;i18n 只管界面 chrome
- mockup 里是中文,**开发以下表英文为准**,中文键值照 mockup 抄:

| key | en(默认) | zh |
|---|---|---|
| `evidence.title.c` | Source Evidence | 证据原文 |
| `evidence.title.b` | Evidence Library | 证据库 |
| `evidence.meta` | {n} exhibits · OCR-processed | {n} 个 exhibit · 已 OCR |
| `crumb.label` | Now viewing | 当前查看 |
| `crumb.preview` | Hover preview | 悬停预览 |
| `doc.current` | Current document | 当前文档 |
| `pager.prev` / `pager.next` | Prev / Next | 上一页 / 下一页 |
| `pager.pos` | {ex} · Page {i} / {n} | {ex} · 第 {i} / {n} 页 |
| `tree.title` | Argument Structure | 论证结构 |
| `tree.stats` | {a} arguments · {s} sub-arguments · {e} evidence items | {a} 个主论点 · {s} 个分论点 · {e} 条证据 |
| `tree.pending` | {n} to review | {n} 待确认 |
| `tree.accepted` | {n} accepted | {n} 已确认 |
| `tree.acceptAll` | Accept all | 全部采用 |
| `node.aiPill` | AI suggested | AI 建议 |
| `node.accept` | Accept | 采用 |
| `node.renamed` | Renamed | 已改名 |
| `node.addSub` | + Add sub-argument | ＋ 添加分论点 |
| `node.menu.rename/split/mergeUp/moveTo/promote/remove` | Rename / Split into two / Merge with previous / Move under… / Promote to argument / Remove | 重命名 / 拆分为两个 / 与上一个合并 / 移到…之下 / 升为主论点 / 移除 |
| `pool.title` | Unused evidence · {n} | 未使用的证据 · {n} |
| `relations.title` | Who this evidence is about | 这条证据说的是谁 |
| `relations.src` | Relations extracted from documents | 关系抽取自文档 |
| `relations.mentions` | Other mentions of "{name}" in this case | 「{name}」在本案中的其他出处 |
| `letter.title` | Petition Letter · {criterion} | 申请信 · {criterion} |
| `letter.stale` | Structure changed — {n} paragraph(s) out of sync | 结构已修改,{n} 段落尚未同步 |
| `letter.regen` | Regenerate this paragraph | 重新生成该段 |
| `phase.verify` | Review & revise · Submit when ready | 核验与修改 · 完成后即可提交 |
| `phase.work` | Write & review · Submit when ready | 写作与核对 · 完成后即可提交 |
| `topbar.help` | Help | 说明 |
| `topbar.submitFinal` | Submit final | 提交定稿 |
| `topbar.submitDraft` | Submit draft | 提交草稿 |
| `chat.title` | Writing Assistant | 写作助手 |
| `chat.badge` | Writing guide loaded · Evidence files attached | 写作指引已加载 · 证据文件已挂载 |
| `chat.copy` | Copy to draft → | 复制到草稿 → |
| `chat.regen` | Regenerate | 重新生成 |
| `chat.placeholder` | Ask for changes, or ask about any piece of evidence… | 向助手提出修改要求,或让它解释某条证据…… |
| `draft.title` | My Draft | 我的草稿 |
| `draft.hint` | This is the version you will submit · Edit freely | 这是你将提交的版本 · 可自由编辑 |
| `draft.stats` | {s} sentences · {c} citations | {s} 句 · {c} 条引证 |
| `draft.saved` | Autosaved · just now | 自动保存 · 刚刚 |
| `lightbox.nav` | Exhibit {ex} · Page {i} of {n} | Exhibit {ex} · 第 {i} 页 / 共 {n} 页 |
| `lightbox.hint` | Esc to close · ←/→ pages | Esc 关闭 · ←/→ 翻页 |
| `probe.q` | Does the cited evidence support this sentence? | 被引证据是否支撑这句话? |
| `probe.opts` | Supported / Not supported / Unsure | 撑得住 / 撑不住 / 不确定 |
| `conf.likert` | I am confident every sentence is supported by evidence | 我确信每句都有证据支持 |
| `conf.count` | How many sentences do you think have citation problems? | 你估计有几句的引证是有问题的? |

(表未尽的键,照同一命名法补,提交前跑一次 key 覆盖检查。)

---

## 7. 条件 C 前端要点(对照 v5)

- **布局**:照 mockup 的 grid 与 token 高度,不许目测调数值——一切高度改动只发生在 `tokens.css`
- **状态**:一个 zustand(或 useReducer)store,形状 = `{nodes: {id: {state, title, parent, snippetIds}}, focus: {subId, chipId, committed|preview}, phase}`——**能从事件流重放出来的状态才是对的状态**
- **交互还原清单**(v4/v5 已实现的语义,逐条搬):hover 预览 vs 点击提交两态 · 面包屑联动 · bbox 滚动定位 · 放大镜三档 · cite 点击回溯 · 采用/全部采用 · 键盘 ↑↓/Enter/v · 关系面板渲染
- **新增**:exhibit 芯片条与 pager 的手动导航(发 `page_change{via:"click"}`,与联动跳转的 `via:"linkage"` 区分)· 信件面板行内编辑(contentEditable 或逐句 textarea,编辑落 `text_edit`,句子分裂/合并按日志手册 §5 维护 sent_id 血缘)· 提交锁定视图
- **克制红线(实现层)**:干扰节点无任何特殊样式或 data 属性;关系面板无警告态;放大镜不渲染相邻候选框;核验段无时钟

## 8. 条件 B 前端要点(对照 v3)

- `EvidenceViewer` 直接复用,`linkage=false`(无 bbox 高亮、无外部跳转指令)
- 聊天:首条由服务端 bootstrap,前端只渲染;"复制到草稿"把消息文本 append 进编辑器并落 `copy_to_draft`
- 草稿编辑器:纯 textarea;引证是纯文本;`text_edit` 同规则落日志
- 提交按钮文案用 `topbar.submitDraft`

## 9. 主试面板(`/mod`,做最小的)

建场(选条件/语言/participant_code)→ 显示 join 链接与 token → 阶段推进按钮 → 实时 seq/心跳灯 → 场记输入 → 收场跑 integrity 并显示红绿清单。**样式不讲究,功能齐就行——它不面向被试。**

---


## 7.5 前端复用清单(逐文件核实,v1.2 新增)

样式以 v5 / b-v3 为唯一真源;下表说的是**逻辑层**的搬运。原则:换壳不换心。

| 现有模块 | 复用内容 | 处置 |
|---|---|---|
| `services/interactionLogger.ts` | 批量 flush、sendBeacon、restoreBatch、节流 | **扩展**:+seq、+ts_mono、+phase/practice 注入、study 信封、指向 `/api/study/log/batch` |
| `components/DocumentViewer.tsx` (749) | bbox 换算(÷1000)、连续翻页窗口、scroll-to-snippet 定位数学、bbox_hover 节流埋点 | 共享 `EvidenceViewer` 的心脏,壳换 v5 的 phead/exstrip/pager |
| `components/LetterPanel.tsx` (991) | 引证正则(含多引证括号)、逐句 provenance 渲染、`onExhibitClick` 全参回溯链、stale 标记与滚动 | 提取引证渲染器 + stale;SectionNav 不搬(单节) |
| `components/BBoxLightbox.tsx` (258) + `Magnifier.tsx` (129) | pdf.js 渲染、`computeCropRect` 纯函数 | 近原样;**`CandidateBox` 恒传空数组**——相邻候选提示是实验克制项,代码注释写明是刻意为之 |
| `utils/sentenceDiff.ts` (159) | (subargument_id, sentence_type) 锚点 + Dice 双字组对齐,阈值 0.92/0.35 | 前端维护 sent_id 血缘;**分析管线复用同一算法与阈值,写进预注册** |
| `components/EvidenceCardPool.tsx` (935) | 未指派池、拖拽、归属查询 | 逻辑提取 |
| `context/ArgumentsContext.tsx` (705) | 树操作语义与 API 调用 | TreePanel 操作层直接接;`tree_op` 埋点挂同一处 |
| `TokenGate` / i18n(en/zh)/ `LanguageSwitcher` | — | 照抄;被试端无切换(§6) |
| **不搬** | `ArgumentGraph` (2918)、`FlowCanvas` (588)、`ConnectionLines` (193)、`WritingContext` 整体(只挑 stale 指纹与局部重生成编排) | 画布范式与跨面板连线不进实验 |

对里程碑的影响:M2 工作量约砍半,新写集中在嵌套卡片树渲染、分段计时 UI、Confidence/Probe 环节页。

## 10. 里程碑与验收

| 里程碑 | 内容 | 验收 |
|---|---|---|
| **M0 脚手架** | study-app 建立;tokens.css 提取;i18n 骨架;/join→条件路由;后端 /api/study 空壳 + 阶段机 | 两条件页面按 mockup 渲染(静态数据),en/zh 可切 |
| **M1 日志与快照** | logger SDK 全量事件;log/batch 升级;**generate + draft_snapshot**;submit + 终稿 snapshot | 日志手册 §10 假实验清单里日志相关行全绿,含拔网线与关标签页两项 |
| **M2 条件 C 完整** | 树交互、联动、放大镜、行内编辑、pager、关系面板、锁定 | C 组假实验整场跑通,§10 清单 C 相关全绿 |
| **M3 条件 B 完整** | 聊天 + bootstrap + frozen_draft_marked + 草稿编辑 | B 组假实验整场跑通 |
| **M4 环节与面板** | ConfidenceForm、ProbeRunner(含 409 顺序守卫)、/mod、integrity 生成 | 完整 85 分钟流程双条件各走一遍,integrity 全绿 |
| **M5 冻结** | 材料包接入正式 case_v1;build hash 注入;打冻结 tag | pilot 开跑;此后只修 bug,schema 与功能不动 |

依赖顺序:M1 先于 M2/M3(埋点是组件的一部分,不是事后补);M2 与 M3 可并行;**M3 允许滑到 C 组正式场次开始之后**(B 排期本来就在 C 满员后)。

---

## 11. 红线汇总(贴在显示器上的那种)

1. `draft_snapshot` 在被试第一次编辑**之前**落盘——M1 验收项,不过不往下走
2. `sent_id` 血缘不断——编辑分裂/合并留旧 id 链
3. `source: frozen|live` 逐句必带
4. 核验段:服务端不下发剩余时间,前端无时钟
5. 干扰节点/探针/答案卷:任何标记不出后端
6. 顺序守卫在服务端:confidence 先于 probe,submit 先于两者
7. 一切 UI 字符串走 i18n,默认 en;一场一语言
8. bbox 用归一化坐标
9. tokens.css 是两条件唯一的样式真源
10. M5 之后:schema 只增不改,功能只减 bug 不加东西
