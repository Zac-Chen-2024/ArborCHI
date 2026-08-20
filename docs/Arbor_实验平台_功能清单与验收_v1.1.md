# Arbor 实验平台 · 功能总清单与验收标准(v1.1)

> 2026-08-19 · 汇总自:实验方案 v2.1 / 日志手册 v1 / 开发手册 v1.2 / 界面 v5 & b-v3
> v1.1:新增 track 双轨(test 全真记录、异地存放、读取侧隔离)与开场交互(BE-19/20、FS-11/12、MOD-07)
> 用法:开发对着做,验收对着勾。每项有编号,验收时引用编号。
> "假实验" = 日志手册 §10 的逐动作脚本,两条件各跑一遍。

---

## 一、后端(BE)

| # | 功能 | 验收方式 |
|---|---|---|
| BE-01 | 建场:`POST /api/study/sessions`(condition / participant_code / lang)→ 生成 session + token(绑定 workspace),返回 join 链接 | 建 C、B 各一场,token 表出现带 `role:participant` 的条目 |
| BE-02 | 鉴权:复用 WorkspaceMiddleware;token 表扩展 `role: participant\|moderator`;无效 token 401;跨 workspace 访问 404 | 用 A 被试 token 请求 B 被试资源 → 404;无 token → 401 |
| BE-03 | 阶段机(服务端仲裁):C = setup→tutorial→practice→organization→generation→verification→confidence→probe→done;B = …practice→work→confidence…;只能经 `advance` 推进;服务端落 `phase_enter/exit` | 假实验全程,events.jsonl 中每阶段 enter/exit 成对 |
| BE-04 | 计时:组织段 deadline 随 state 下发,到 X 落 `phase_softlock`;核验段服务端静默计时,到 Y+10 落 softlock;**核验段 state 响应不含任何剩余时间字段** | 抓包核验段 `/state` 响应,无时间字段;两段各触发一次软锁 |
| BE-05 | 状态轮询:`GET /api/study/state` → {phase, softlock, org_deadline?, lang},2s 轮询可承受 | 断续轮询 5 分钟无错;org 段有 deadline,verify 段无 |
| BE-06 | 日志摄入:`POST /api/study/log/batch`,校验 study 信封(schema_version/seq/ts_wall/ts_mono/phase/practice/cond/build);seq 断号照收并登记 gap;`append_jsonl` + 批次 fsync;返回 acked_seq;**产品线 `/api/logs` 一字不动** | 乱序/断号批次注入 → gap 被登记;对拍产品端点 diff 为零 |
| BE-07 | 材料服务:只读 bundle;manifest 的 material_hash / tree_hash / model / params 注入 `session_start`;**任何响应不含干扰节点标记、探针答案、答案卷** | 抓全部 API 响应 grep 标记字段 → 零命中;session_start 含四个钉死值 |
| BE-08 | 生成(C):逐节点判定 冻结取 `pregen/` / 被改走增量生成(钉死 model/params);逐句 `source: frozen\|live`;拼装后**在被试可编辑之前**落 `draft_snapshot`;返回全文+逐句元数据 | 改 1 个节点生成:该节点句 `live`、其余 `frozen`;snapshot 时间戳早于首个 text_edit |
| BE-09 | 聊天(B):system prompt 从 prompt 注册表读(记 id/version/hash);**首条 bootstrap 由服务端自动发出**;每次响应落 `msg_response`(全文进 snapshots/,引用 trace 行);按预注册规则判定 `frozen_draft_marked` 并落对应 draft_snapshot | 新开 B 场:未发任何消息即有首轮输出;规则命中时两事件齐现 |
| BE-10 | 草稿自动保存:C 信件面板 / B 编辑器,≤10s 周期落盘;崩溃后恢复到最近版本 | 编辑中杀进程重启,内容损失 ≤10s |
| BE-11 | 提交:校验 final_text_hash → 落终稿 snapshot(`snapshot_id:"final"`)→ 锁定;此后一切写操作 409 | 提交后再发 text_edit / chat → 409 |
| BE-12 | 信心:`POST /api/study/confidence`(likert_1_7 + est_problem_count)落 `confidence_submit` | 事件字段齐全 |
| BE-13 | 拷问:`probe/start` 从终稿按分论点分层抽 12–15 句;**confidence 未提交则 409**;逐句作答落 `probe_item`(judgment/rt_ms/source_opened) | 顺序违规 → 409;≤15 句全取,>15 分层抽样可复算 |
| BE-14 | 主试 API:建场 / advance / monitor(最新 seq、心跳年龄、当前阶段)/ 场记 `moderator_note` / 收场触发 integrity | /mod 全流程可操作 |
| BE-15 | 完整性报告:收场生成 `integrity.json`,覆盖日志手册 §8 全部条目(seq 无断号、心跳≥95%、双 snapshot 哈希对上、phase 成对、checkpoint 存在、confidence 先于 probe、事件量 ±3σ、材料/树哈希一致) | 假实验后逐条绿;人为制造一项缺陷 → 对应条目红 |
| BE-16 | 存储与备份:`data/workspaces/{ws}/sessions/{sid}/{events.jsonl, snapshots/, integrity.json}`;backup_data.sh 覆盖该目录 | 目录结构对;跑一次备份含新数据 |
| BE-17 | 安全:CORS 白名单含 study 前端源;`/api/study/*` 异常不回传 `str(exc)`;日志零 PII;收场对 `msg_send.text` 跑 PII 模式扫描,命中脱敏并标 `redacted:true` | 构造异常看响应体;注入假邮箱看脱敏 |
| BE-18 | 练习材料:独立迷你 bundle(另一法条);practice 期事件全部 `practice:true` | 练习期任意事件抽查标志位 |
| BE-19 | 双轨 track:token 表加 `track: formal\|test`(mint 加 `--track`);信封带 track(schema v2);**test 场全真记录**(与正式零分叉:阶段机/seq/心跳/snapshot/integrity 全同),仅落盘至 `data/study_test/{ws}/…`,formal 落正式目录 | 各建一场对拍事件流字段级一致;仅路径与 track 字段不同 |
| BE-20 | 读取侧隔离:分析/导出脚本路径写死正式目录,test 数据物理不可达;`logs_summary.py` 支持 `--track test` 显式查看 | 跑导出 test 零出现;显式参数可查 test |

## 二、前端 · 两条件共享(FS)

| # | 功能 | 验收方式 |
|---|---|---|
| FS-01 | `tokens.css` 唯一样式真源;两条件像素对照 v5 / b-v3(高度节奏 56/44/42/42/48/40) | 截图叠 mockup;改一个 token 两边同步变 |
| FS-02 | `/join?token=` → TokenGate → 条件由服务端 state 决定路由;改 URL 切不了条件 | 手动访问 /c 用 B token → 被路由回 B |
| FS-03 | i18n:默认 en,zh 完整;语言由 session 配置下发;**被试端无切换控件**;ESLint 禁裸字符串;key 覆盖检查过 | 建 zh 场全界面中文;lint 零告警 |
| FS-04 | 日志 SDK(扩展现有 interactionLogger):自动注入 seq/ts_wall/ts_mono/phase/practice/cond/build;5s 或 20 条批发;sendBeacon 兜底;localStorage 镜像恢复;心跳 30s;失败退避重发 | 假实验含拔网线 30s + 关标签页两项,seq 连续无丢行 |
| FS-05 | 共享 EvidenceViewer:exhibit 芯片条、连续翻页渲染、pager(上一页/下一页/位置)、缩放、paper 渲染;`page_change` 区分 `via: click\|scroll\|linkage`;bbox 高亮由 prop 开关 | C 开 B 关同一组件;三种 via 各触发一次 |
| FS-06 | 阶段门:教程页、练习页(**必过关卡**:C=开一次放大镜+定位一次 bbox,B=手动翻到指定页;过关落 `checkpoint_passed`)、软锁遮罩、提交后锁定视图 | 不过关无法进正式任务;事件存在 |
| FS-07 | 倒计时组件:**仅组织段渲染**(读服务端 deadline);核验段任何位置无时钟 | 核验段全 DOM 搜不到计时元素 |
| FS-08 | ConfidenceForm:两问必填,提交前无法进拷问 | 服务端 409 有对应 UI 处理 |
| FS-09 | ProbeRunner:逐句呈现、三选(Supported/Not supported/Unsure)、可查源文、记 rt_ms 与 source_opened | probe_item 字段齐全;抽句与终稿对得上 |
| FS-10 | 版本注入:每事件带 build hash;界面角落显示版本号(主试核对用) | 事件抽查;界面可见 |
| FS-11 | test 场顶栏渲染灰色 `TEST` 徽章;formal 场无任何视觉差异 | 两场各截图对比 |
| FS-12 | 被试端 Start 页:TokenGate 验证后单按钮「开始 Start」;点击落 `session_start` 并进入阶段机;条件/track 由 token 定死,页面无任何选择项 | 假实验首步;DOM 无第二按钮 |

## 三、前端 · 条件 C(C)

| # | 功能 | 验收方式 |
|---|---|---|
| C-01 | 顶栏:阶段签(组织段=倒计时,核验段=「Review & revise · Submit when ready」)、Help 抽屉、Submit final | 两阶段切换文案与控件正确 |
| C-02 | 溯源面包屑:主论点 › 分论点 › exhibit·页;悬停时加 Hover preview 标 | 点击/悬停各验一次 |
| C-03 | 嵌套卡片树:主论点容器 + 分论点卡;状态机 proposed(虚线琥珀)/accepted/edited(实线绿)/removed;采用、全部采用;计数徽章 | 状态跃迁逐一落 `node_state`;计数实时对 |
| C-04 | 节点操作菜单:Rename / Split / Merge with previous / Move under… / Promote / Remove;容器内拖拽排序 + 跨容器拖拽移动 | 每操作落 `tree_op`,语义与 ArgumentsContext 对齐 |
| C-05 | 证据芯片:悬停预览(左栏联动、虚线态)vs 点击提交(实线态)双态;放大镜图标;拖拽指派/取消指派 | hover_start/end、chip_click、assign/unassign 事件齐 |
| C-06 | 未指派证据池:展开、拖出到任意节点(`pool_drag_out`) | 事件 + 树上出现该 snippet |
| C-07 | 实体关系面板:仅事实三元组 + 各边出处 + 「其他出处」行;**无任何警告/评价** | 逐 snippet 渲染对 relations.json;UI 无警告态代码路径 |
| C-08 | 信件面板:引证解析渲染(含多引证括号);点引证 → 四段回溯链(高亮分论点 → 芯片 → bbox 滚动定位 → 面包屑);未生成段骨架 | cite_click 后四处联动齐;via:"linkage" 落日志 |
| C-09 | stale:结构改动后横幅 +「Regenerate this paragraph」;局部重生成走 sentenceDiff 对齐,sent_id 血缘不断 | 改节点→stale 现;重生成后新旧句映射可查 |
| C-10 | 行内文本编辑:信件面板直接改字;`text_edit` debounce 2s 携带 affected_sent_ids;句子分裂/合并留旧 id 链 | 拆一句为两句,血缘链在 |
| C-11 | 3× 放大镜:三档缩放、翻页、Esc/←→、dwell 上报;**CandidateBox 恒空**(相邻候选禁用,注释写明) | lightbox_open/close(dwell_ms)对秒表;代码审该参数 |
| C-12 | 键盘:↑↓ 焦点、Enter 采用、v 放大镜 | 逐键验 |
| C-13 | 组织段/核验段形态:组织段只有树可编辑(信件占位);生成过渡;核验段树仍可编辑(DP4 循环)+ 信件可核可改 | 阶段切换 UI 状态各截图 |
| C-14 | 克制红线:干扰节点无任何特殊样式或 data 属性;无强弱评分;live/frozen 句**视觉无差**(仅数据标) | DOM/样式审计零泄露 |

## 四、前端 · 条件 B(B)

| # | 功能 | 验收方式 |
|---|---|---|
| B-01 | 聊天:服务端 bootstrap 首轮直接呈现;发送、重新生成;「Copy to draft →」追加进编辑器并落 `copy_to_draft` | 新场即见首轮;复制后编辑器内容与事件一致 |
| B-02 | 草稿编辑器:纯 textarea;引证纯文本不可点;句数/引证数统计条;自动保存指示 | 点击引证无任何响应;统计随编辑更新 |
| B-03 | 证据查看器:linkage=false(无 bbox 高亮、无联动跳转);手动翻页/缩放是唯一路径 | 与 C 同组件不同 props;联动代码路径不可达 |
| B-04 | 顶栏:「Write & review · Submit when ready」+ Submit draft;全程无时钟 | 文案、无时钟 |
| B-05 | 与 C 同构的事件流:panel_focus(evidence/chat/draft)、doc_open、page_change、zoom、msg_send/response、text_edit、declare_done、submit | 假实验对照事件字典逐条打勾 |

## 五、主试面板(MOD)

| # | 功能 | 验收方式 |
|---|---|---|
| MOD-01 | moderator token 进门;participant token 进不来 | 交叉验证 |
| MOD-02 | 建场表单(条件/语言/编号)→ 显示 join 链接 + token | 建两场各条件 |
| MOD-03 | 阶段推进按钮 + 当前阶段显示 + 服务端计时(**仅主试可见**) | 被试端核验段无时钟,主试端有 |
| MOD-04 | 实时监控:最新 seq、心跳年龄红绿灯、事件计数 | 拔被试网线 → 30s 内变红 |
| MOD-05 | 场记输入 → `moderator_note` | 事件落盘 |
| MOD-06 | 收场:一键 integrity,红绿清单展示 | 对 BE-15 |
| MOD-07 | /mod 首页双按钮:**Test** 一键 mint(track:test)并新标签直达 join;**Experiment** 弹建场表单(条件/语言/被试编号必填)后生成正式 token;被试端永远见不到这个选择 | 各点一次,查 token track、落盘路径、徽章 |

## 六、离线工具链(OT)

| # | 功能 | 验收方式 |
|---|---|---|
| OT-01 | 树预生成脚本:固定种子出 5 棵全存档;按预注册规则(含雷筛选 → 距答案树中位距离)自动选定;落 tree_hash | 重跑同种子逐字节一致;选择过程有日志 |
| OT-02 | 节点文本预生成:逐句 sent_id / snippet_ids / exhibit_refs / sentence_type / source:"frozen" | 抽 3 节点核对 schema |
| OT-03 | Bundle 校验器:schema、哈希、bbox 约定(÷1000 + 页宽高)、**防泄露检查**(前端可达数据零标记) | 故意埋一个标记 → 校验失败 |
| OT-04 | 自动树独立性检查:选定树 vs 答案树编辑距离显著大于零 | 输出距离值入材料冻结记录 |
| OT-05 | 练习 bundle 独立生成;与正式材料无同构证据 | 人工比对一遍 |

---

## 验收流程(按序)

1. **单元层**:BE 各项配测试进现有 CI 盘子,全绿
2. **假实验 ×2**(C、B 各一场,日志手册 §10 脚本):FS/C/B/MOD 全部编号逐项勾,含拔网线与关标签页两项破坏测试
3. **integrity 全绿** + 人为注伤各红一次(BE-15)
4. **克制审计**(C-07 / C-11 / C-14 / BE-07 / OT-03 五项联查):由不写代码的人对着方案 §红线独立过一遍
5. 全部通过 → 打冻结 tag(M5),此后只修 bug

任何一项没有对应实现或验收不过,不进 pilot。
