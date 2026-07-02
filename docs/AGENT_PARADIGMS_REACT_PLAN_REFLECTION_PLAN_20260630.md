# DeerFlow Agent 范式解析与改进规划：ReAct / Plan-Execute / Reflection

> 日期：2026-06-30
> 范围：`backend/packages/harness/deerflow/`（lead agent、middlewares、subagents、sql_cross_validation、memory）
> 目的：① 解析三种 Agent 范式的本质；② 对照源码盘点 DeerFlow 现状；③ 给出可落地的改进规划。

---

## 一、三种范式的本质

| 范式 | 核心循环 | 解决的问题 | 典型失效场景 |
|---|---|---|---|
| **ReAct**（Reasoning + Acting） | `思考 → 行动 → 观察` 紧密交织的单一循环。每一步先用自然语言推理，再调用工具，把工具返回的观测喂回下一步推理。 | 让模型边想边查，动态适应环境反馈，避免"闭门造车"。 | 没有全局规划，面对多步骤长任务时容易迷失方向、重复劳动、过早收尾。 |
| **Plan-Execute**（先规划后执行） | `生成计划 → 逐步执行 → （可选）重规划`。规划器先把任务拆成有序子步骤，执行器再依次完成；执行偏离时回到规划器调整。 | 为长程任务提供全局结构，降低"走一步看一步"的发散性，便于并行与进度跟踪。 | 计划僵化、与真实环境脱节；规划/执行分离带来额外延迟与 token 成本。 |
| **Reflection**（自我批判与迭代） | `产出 → 自我批判/验证 → 修正 → 再产出`，直到满足质量门槛或预算耗尽。 | 通过独立复核、交叉验证、错误归因来提升正确性与可靠性。 | 反思可能自我强化错误（同一模型自评偏乐观）；迭代成本高，需要明确停止条件。 |

三者并非互斥：成熟系统往往是 **Plan-Execute 提供骨架、ReAct 填充每个执行步、Reflection 在关键节点做质量闸门**。

---

## 二、DeerFlow 现状盘点（基于源码）

结论先行：

| 范式 | 实现程度 | 关键证据 |
|---|---|---|
| **ReAct** | ✅ 核心循环，完整实现 | lead agent 与每个 subagent 都是 `create_agent` 构建的标准 ReAct 图 |
| **Plan-Execute** | 🟡 部分实现，仅"循环内 TodoList"，无独立 planner | `is_plan_mode` 开关 + `TodoMiddleware`，无规划节点 |
| **Reflection** | 🟡 局部实现，无通用反思回路 | SQL 交叉验证图 + 记忆抽取的"结构化反思"；`reflection/` 目录名是误导（实为动态加载） |

### 2.1 ReAct —— 已是核心循环

DeerFlow 没有手写 agent 循环，而是统一委托给 LangChain 的 `create_agent`（即 LangGraph 预制的 model 节点 ⇄ tools 节点 ReAct 图）。

- Lead agent 工厂：[agent.py:520-540](backend/packages/harness/deerflow/agents/lead_agent/agent.py#L520-L540) —— `create_agent(model=..., tools=final_tools, middleware=..., system_prompt=..., state_schema=ThreadState)`。
- SDK 无配置工厂：[factory.py:139-147](backend/packages/harness/deerflow/agents/factory.py#L139-L147)。
- Subagent 同样是独立的 `create_agent` 实例，reason→act→observe 体现在其 `astream` 循环：[executor.py:551](backend/packages/harness/deerflow/subagents/executor.py#L551)。
- 推理前置由提示词 `<thinking_style>` 强制：[prompt.py:371-378](backend/packages/harness/deerflow/agents/lead_agent/prompt.py#L371-L378)（"Think concisely and strategically BEFORE taking action"）。

**定性：** ReAct 是 DeerFlow 的地基。所有定制都通过 middleware 和 system prompt 注入，而非改写循环本身。

### 2.2 Plan-Execute —— 只有"循环内 TodoList"，无独立规划层

DeerFlow **没有** 规划器节点、没有"先出计划再执行"的两阶段图。"规划"仅以可选的 **TodoList 工具** 形式叠加在同一个 ReAct 循环上。

- 开关：`is_plan_mode`，[agent.py:421](backend/packages/harness/deerflow/agents/lead_agent/agent.py#L421)；关闭时 `_create_todo_list_middleware` 直接返回 `None`（[agent.py:145-257](backend/packages/harness/deerflow/agents/lead_agent/agent.py#L145-L257)）。
- 机制是 `write_todos` 工具（继承 LangChain `TodoListMiddleware`）：[todo_middleware.py:109](backend/packages/harness/deerflow/agents/middlewares/todo_middleware.py#L109)。
  - 提示模型对"≥3 步的复杂目标"才用，简单任务禁用。
  - summarization 后若 todo 滚出上下文会**重新注入**：[todo_middleware.py:120-156](backend/packages/harness/deerflow/agents/middlewares/todo_middleware.py#L120-L156)。
  - **防过早收尾**：模型在 todo 未完成时停下，会被 `after_model` 拉回 model 节点，上限 2 次：[todo_middleware.py:265-309](backend/packages/harness/deerflow/agents/middlewares/todo_middleware.py#L265-L309)。
- 提示词层有 `CLARIFY → PLAN → ACT`（[prompt.py:381](backend/packages/harness/deerflow/agents/lead_agent/prompt.py#L381)）和 subagent 编排的 `COUNT → PLAN BATCHES → EXECUTE → SYNTHESIZE`（[prompt.py:299-306](backend/packages/harness/deerflow/agents/lead_agent/prompt.py#L299-L306)），但这些是"提示模型去思考"，不是结构化执行阶段。

**定性：** 这更接近 Claude Code 的 TodoWrite（循环内动态任务跟踪），而非真正的 Plan-Execute 规划器。计划是"软"的、无强制执行契约、无重规划节点。

### 2.3 Reflection —— 无通用回路，仅两处局部自我批判

**首先澄清：`reflection/` 目录与认知反思无关。** 它是 Python 反射（动态模块/类加载）：`resolve_variable`、`resolve_class`，见 [resolvers.py:25](backend/packages/harness/deerflow/reflection/resolvers.py#L25)、[resolvers.py:73](backend/packages/harness/deerflow/reflection/resolvers.py#L73)。

真正的自我批判/验证只有两处：

1. **SQL 交叉验证图（最接近 Reflection 的特性）** —— [sql_cross_validation/agent.py](backend/packages/harness/deerflow/agents/sql_cross_validation/agent.py)，网关 assistant id `"sql-cross-validation"`。
   - 这是**确定性 LangGraph**（`START → sql_cross_validate → END`），不是 ReAct 循环。
   - `_cross_validate_node`（[agent.py:255-347](backend/packages/harness/deerflow/agents/sql_cross_validation/agent.py#L255-L347)）对**同一问题并行跑两个 SQL subagent**（`asyncio.gather`）：
     - **主查询** = `general-purpose` subagent（独立执行）；
     - **交叉验证** = `mysql-query` subagent，提示词明确"不要假设主查询结论正确"。
   - 第三个 **summarizer LLM** 比对两路输出并给裁决：一致→"已通过交叉验证"；不一致→"交叉验证不一致"并降级置信度；单边/双失败→如实说明。
   - 设计要点：subagent 名称表示**能力域**而非运行角色（近期 commit 明确补充）。
   - **这正是"独立复核 + 交叉验证 + 置信度降级"的反思范式**，但被硬编码为 SQL 专用的独立图，未泛化到 lead agent。

2. **记忆抽取中的"结构化反思"** —— [memory/prompt.py:39-46](backend/packages/harness/deerflow/agents/memory/prompt.py#L39-L46)：抽取记忆前要求模型对会话做错误/重试检测、用户纠正检测，归因后存为 `correction` 类高置信事实。这是**事后**反思（为持久化记忆服务），不是对当前答案的在环修正。技能自进化（[prompt.py:168-181](backend/packages/harness/deerflow/agents/lead_agent/prompt.py#L168-L181)）同理，也是回顾式。

**定性：** 没有针对 lead agent 输出的通用"批判→修正→再产出"回路。

### 2.4 Subagent 委派（横切能力，三范式都依赖它）

- `task` 工具（类比 Claude Code 的 Task）：[task_tool.py:186-228](backend/packages/harness/deerflow/tools/builtins/task_tool.py#L186-L228)，后台异步执行 + 每 5s 轮询 + SSE 事件流。
- 注册表分层解析（builtins → custom_agents → 单 agent override）：[registry.py:50](backend/packages/harness/deerflow/subagents/registry.py#L50)；builtins 为 `general-purpose`、`bash`、`mysql-query`。
- 禁止嵌套：subagent 以 `subagent_enabled=False` 构建。
- 编排提示词把 lead agent 定位为 `DECOMPOSE → DELEGATE → SYNTHESIZE` 的协调者：[prompt.py:236-361](backend/packages/harness/deerflow/agents/lead_agent/prompt.py#L236-L361)。

---

## 三、改进规划

设计原则：**不推翻 ReAct 地基**，以**新增 middleware / 新增图节点 / 新增 subagent profile**的方式增量演进；所有新能力默认可开关，避免无差别增加延迟与 token。

### 阶段 0：基线度量（先量化，再改进）

在动手前建立可观测基线，否则无法判断改进是否有效。

- 复用 `token_usage_middleware` 已有的 per-step token 归因，新增任务级指标：任务成功率、平均工具调用数、过早收尾率（todo 未完成即停）、subagent 失败率。
- 选 20–30 个代表性任务（含 SQL 问数、多步研究、代码任务）建为回归集，落在 `backend/tests/` 下。
- **交付物**：基线报表 + 回归任务集。后续每阶段对照此基线。

### 阶段 1（Plan-Execute）：把"软 TodoList"升级为"显式计划契约"

目标：在不引入笨重 planner 节点的前提下，让计划具备结构与可追踪性。

1. **结构化计划 schema**：将 `write_todos` 的条目从纯文本升级为 `{id, intent, depends_on, status, evidence}`，使步骤具备依赖关系与完成证据。改造点 [todo_middleware.py](backend/packages/harness/deerflow/agents/middlewares/todo_middleware.py)。
2. **可选的 PlanFirst 模式**：新增 `plan_first` 配置开关。开启时，复用 SQL 交叉验证那套"确定性图 + 节点"的写法，在 lead agent 前置一个**规划节点**：先产出计划草案 → 用户/自动确认 → 再进入 ReAct 执行。借鉴现成范式 [sql_cross_validation/agent.py:350-372](backend/packages/harness/deerflow/agents/sql_cross_validation/agent.py#L350-L372) 的图组装方式。默认关闭。
3. **重规划触发**：当连续 N 步无进展或工具反复失败（复用 `loop_detection_middleware` 信号）时，注入 `<system-reminder>` 提示模型重写计划，而非硬编码回到 planner。
- **交付物**：结构化 todo schema + `plan_first` 图节点 + 重规划触发器；阶段 0 回归集验证过早收尾率下降。

### 阶段 2（Reflection）：把 SQL 交叉验证泛化为通用质量闸门

目标：将已验证有效的 SQL 交叉验证模式，抽象为可复用的反思组件。

1. **抽取通用交叉验证库**：把 [sql_cross_validation/agent.py](backend/packages/harness/deerflow/agents/sql_cross_validation/agent.py) 中"并行双 agent + summarizer 裁决 + 置信度降级"的逻辑抽到 `agents/cross_validation/`（与具体领域解耦），SQL 版本成为它的一个 profile。
2. **ReflectionMiddleware（可选、按需触发）**：新增 middleware，仅在满足触发条件时启动反思回路——
   - 触发条件示例：任务被标记为高风险（写操作、对外发布、金额/SQL 计算）、或用户显式要求复核。
   - 回路：对 lead agent 的最终答案，派一个**独立 verifier subagent**（不同 prompt、不假设原结论正确）做批判 → 若发现矛盾则把批判作为观测喂回 ReAct 循环要求修正 → 最多迭代 K 次（明确停止条件，借鉴 `_MAX_COMPLETION_REMINDERS` 的封顶思路）。
   - 关键防自我强化：verifier 用**不同角色提示**且尽量独立取证，避免同模型自评的乐观偏差（沿用 SQL 交叉验证"不要假设主查询正确"的设计）。
3. **置信度透传**：把交叉验证的裁决（已通过 / 不一致 / 未完整验证）作为结构化字段透传到前端，而非仅混在文本里。
- **交付物**：`agents/cross_validation/` 通用库 + 可开关 `ReflectionMiddleware` + 置信度字段；在高风险任务上对照基线衡量正确率提升与成本增量。

### 阶段 3（ReAct 强化）：让核心循环更稳

ReAct 已是地基，强化点在于减少发散与浪费。

1. **观测压缩**：大工具输出经 `tool_output_budget_middleware` 已有预算控制，进一步对失败观测做结构化摘要（错误类型 + 关键栈），降低重复犯错。
2. **反循环增强**：`loop_detection_middleware` 当前检测重复工具调用；扩展为"语义重复"检测（相似而非完全相同的调用），并在触发时引导模型换思路而非简单打断。
3. **思考-行动配比自适应**：根据任务复杂度动态调整 `reasoning_effort`，简单任务降档省成本，复杂任务升档。
- **交付物**：失败观测摘要 + 语义反循环 + 自适应推理档位。

### 阶段 4：三范式协同编排（收口）

把前三阶段拼成一条可配置流水线：

```
PlanFirst(可选) → ReAct 执行循环（含 subagent 委派） → Reflection 质量闸门(可选) → 交付
                         ↑___________ 重规划/修正回路 ___________|
```

- 通过 config 组合开关（`plan_first` / `reflection` / `cross_validation_profile`）适配不同场景：SQL 问数默认开交叉验证；长程研究开 PlanFirst；简单对话三者全关走纯 ReAct。
- **交付物**：统一编排配置 + 文档 + 全量回归对照报告。

---

## 四、风险与取舍

| 风险 | 说明 | 缓解 |
|---|---|---|
| 延迟与 token 成本上升 | Plan/Reflection 都增加 LLM 调用 | 全部做成可开关、按任务风险/复杂度触发，默认走纯 ReAct |
| 反思自我强化错误 | 同模型自评偏乐观 | verifier 用独立角色提示 + 独立取证，沿用 SQL 交叉验证的对抗式设计 |
| 计划僵化脱离环境 | 静态计划与真实反馈脱节 | 计划保持"软契约" + 明确重规划触发器 |
| 改动侵入核心循环 | 破坏现有 ReAct 稳定性 | 一律以 middleware / 独立图节点增量叠加，不改 `create_agent` 主循环 |
| 缺乏停止条件导致死循环 | 反思/重规划无限迭代 | 所有回路硬性封顶（借鉴 `_MAX_COMPLETION_REMINDERS`） |

---

## 五、落地优先级建议

1. **阶段 0（基线度量）** —— 必做前置，1～2 天。
2. **阶段 2（Reflection 泛化）** —— ROI 最高：SQL 交叉验证已验证有效，抽象成本低、对正确性提升明显。
3. **阶段 1（Plan-Execute 升级）** —— 对长程任务价值大，但需注意成本。
4. **阶段 3 / 4** —— 在前述基础上收口与协同。

---

## 附录：关键源码索引

- ReAct 核心：[lead_agent/agent.py:520](backend/packages/harness/deerflow/agents/lead_agent/agent.py#L520)、[subagents/executor.py:551](backend/packages/harness/deerflow/subagents/executor.py#L551)
- Plan（TodoList）：[middlewares/todo_middleware.py](backend/packages/harness/deerflow/agents/middlewares/todo_middleware.py)、[lead_agent/agent.py:421](backend/packages/harness/deerflow/agents/lead_agent/agent.py#L421)
- Reflection（SQL 交叉验证）：[sql_cross_validation/agent.py:255](backend/packages/harness/deerflow/agents/sql_cross_validation/agent.py#L255)
- Reflection（记忆结构化反思）：[memory/prompt.py:39](backend/packages/harness/deerflow/agents/memory/prompt.py#L39)
- Subagent 委派：[tools/builtins/task_tool.py:186](backend/packages/harness/deerflow/tools/builtins/task_tool.py#L186)、[subagents/registry.py:50](backend/packages/harness/deerflow/subagents/registry.py#L50)
- `reflection/` 目录（动态加载，非认知反思）：[reflection/resolvers.py:25](backend/packages/harness/deerflow/reflection/resolvers.py#L25)
