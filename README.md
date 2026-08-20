# ArborCHI · Arbor 实验平台(CHI 2027)

两个条件前端(**C = Arbor** / **B = DraftDesk**)+ 一个共享后端(会话/阶段机、日志、快照、冻结生成)。
被试全程走这套系统;产品线 PetitionLetter2.0 实验期间**冻结,一行不动**。

> **推送目标:本仓 `Zac-Chen-2024/ArborCHI`。**
> `Zac-Chen-2024/PetitionLetter2.0` 只作只读参考,不接收本项目任何提交。

---

## 目录

```
ArborCHI/
├── backend/                  # FastAPI —— 复制自 PetitionLetter2.0 @ 468d5dd
│   ├── app/core/             # workspace / atomic_io / prompt_loader / jobs(原样复用)
│   ├── app/routers/          # 产品路由保留;实验加 /api/study 命名空间
│   ├── prompts/              # prompt 注册表(版本 + 哈希)
│   ├── scripts/mint_token.py # token 签发(待加 --role / --track)
│   └── tests/                # 13 个测试文件,study 新模块照这个盘子加
├── study-app/                # 实验前端(Vite + React + TS),两条件共用一个 app
│   └── src/tokens.css        # ★ 两条件唯一样式真源(红线 #9)
├── mockups/                  # ★ 视觉唯一真源,像素级照抄
│   ├── arbor-write-mode-v5.html    # 条件 C
│   └── baseline-shell-b-v3.html    # 条件 B
├── docs/
│   ├── Arbor_实验平台_开发手册_v1.2.md
│   └── Arbor_实验平台_功能清单与验收_v1.1.md
└── .github/workflows/ci.yml
```

## 两条真源,别搞混

| | 真源 | 规则 |
|---|---|---|
| **样式** | `mockups/*.html` | 像素级照抄;一切高度/颜色改动只发生在 `study-app/src/tokens.css` |
| **逻辑** | PetitionLetter2.0 @ `468d5dd` | 换壳不换心,按开发手册 §7.5 复用清单逐文件搬 |

老仓在本地 clone 于 `../PetitionLetter2.0`,只读。

## 路由

```
/join?token=…   → 服务端返回 {condition, lang, phase} → 路由到 /c 或 /b
/c              → Arbor 条件(v5 布局)
/b              → DraftDesk 条件(v3 布局)
/mod            → 主试面板(moderator token 才进)
```

条件**不由 URL 决定**,由 token 对应的 session 配置决定 —— 被试改 URL 也切不了条件。

## 阶段机

- **C**:`setup → tutorial → practice → organization → generation → verification → confidence → probe → done`
- **B**:`setup → tutorial → practice → work → confidence → probe → done`

计时全在服务端。组织段 deadline 随 `/state` 下发;**核验段的 state 响应里没有任何剩余时间字段**——前端想显示也没数据。

## 红线(十条,贴显示器上那种)

1. `draft_snapshot` 在被试第一次编辑**之前**落盘 —— M1 验收项,不过不往下走
2. `sent_id` 血缘不断 —— 编辑分裂/合并留旧 id 链
3. `source: frozen|live` 逐句必带
4. 核验段:服务端不下发剩余时间,前端无时钟
5. 干扰节点 / 探针答案 / 答案卷:任何标记不出后端
6. 顺序守卫在服务端:confidence 先于 probe,submit 先于两者
7. 一切 UI 字符串走 i18n,默认 **en**;一场一语言
8. bbox 用归一化坐标(÷1000,manifest 另记页宽高兜底)
9. `tokens.css` 是两条件唯一的样式真源
10. M5 之后:schema 只增不改,功能只减 bug 不加东西

## 里程碑

| | 内容 | 状态 |
|---|---|---|
| **M0** | 脚手架:study-app、tokens.css、i18n 骨架、/join 条件路由、/api/study 空壳 + 阶段机 | 进行中 |
| **M1** | 日志 SDK 全量事件、log/batch、**generate + draft_snapshot**、submit + 终稿 snapshot | |
| **M2** | 条件 C 完整(树交互、联动、放大镜、行内编辑、pager、关系面板、锁定) | |
| **M3** | 条件 B 完整(聊天 + bootstrap + frozen_draft_marked + 草稿编辑) | |
| **M4** | ConfidenceForm、ProbeRunner(409 顺序守卫)、/mod、integrity 生成 | |
| **M5** | 材料包接入 case_v1、build hash 注入、打冻结 tag | |

M1 先于 M2/M3(埋点是组件的一部分,不是事后补);M2 与 M3 可并行。

验收对着 `docs/Arbor_实验平台_功能清单与验收_v1.1.md` 逐编号勾(BE-/FS-/C-/B-/MOD-/OT-),任何一项不过不进 pilot。
