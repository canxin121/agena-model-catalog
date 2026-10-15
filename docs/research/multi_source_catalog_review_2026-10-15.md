# Agena model catalog 多源数据审计与优先级建议

审计日期：2026-10-15。范围：`agena-model-catalog` 自动刷新链路，以及同级 Codex、OpenCode、Gemini CLI 的模型数据实现；补充抽样检查 Hugging Face Hub、OpenRouter 和 LiteLLM 当前公开目录。网络目录统计是该日读取时的快照，不代表永久不变。

## 结论

Agena 当前的**自动下载入口只有 `models.dev/api.json` 一个**。`curation/sources.json` 看起来列出了多个 provider 和 Hugging Face 组织，但它只定义了如何从同一份 models.dev 快照挑选与去重；每条 provider 规则都没有自己的 fetch URL 或 fetcher。人工 patch 与研究说明确实引用过 Codex、Hugging Face、NVIDIA 和厂商文档，因此历史上存在其他证据源，只是它们没有进入可重复的定时抓取与按字段冲突解决流程。

多源是合理方向。合并策略应先区分记录粒度，再对字段组规定优先来源。模型身份、供应商 API 路由、开源权重仓库和某个客户端的模型 preset 是不同记录类型。把它们先按字符串压成同一个模型 ID，会把路由价格、客户可用性或客户端默认值传播到不适用的模型记录。

建议保留 models.dev 作为广覆盖发现源与缺省补充源；增接 HF Hub、OpenRouter、LiteLLM 和厂商官方资料时，为它们限定适用字段和适用对象；把 Codex/Gemini CLI 元数据用于对应客户端的行为核对；把 OpenCode 入口视为 models.dev 镜像。

## 现有链路与数据粒度

仓库 README 将每六小时刷新描述为抓取 models.dev、选择受信 provider/HF 记录、合并字段、应用人工 patch、校验后发布。实际流程与描述一致：

1. `scripts/fetch_modelsdev.sh` 只下载 `https://models.dev/api.json`。
2. `scripts/model_sources.py` 从这一个快照读取 `curation/sources.json` 列出的 provider 与 HF 组织。
3. 对多个源记录归一化到同一个 ID 时，`result.setdefault(...)` 保留规则列表中首先出现的整条记录。它没有对不同字段分别择优。
4. trusted 记录提供的字段覆盖当前值；legacy 精确 ID 记录只补空缺；patch 最后覆盖合并值。
5. 最终 `models.json` 不保留机器可读的逐字段来源、抓取时间和冲突记录。patch 的 `notes` 可以写来源，但没有统一的 provenance 结构。
6. `route_limit_caps` 对某些 route 取较小 context/output 上限，最终只保留一个共享数字；其他 route 差异没有作为 route 记录存储。

这使当前策略可以概括为：**models.dev 提供一个被筛选的整模型基线，patch 提供人工例外，旧快照精确匹配只补空值**。这是一种明确的数据管线，但还不是通用多源合并器。

## 同一时间点的数量核对

| 数据集 | 2026-10-15 读取结果 | 计数口径 |
|---|---:|---|
| models.dev | 230 providers，8,870 provider-model records，4,054 个不同的原始 ID 字符串 | 每条 provider 记录都计数，同一个供应商模型可重复出现 |
| models.dev 经 Agena 当前 ID 归一化 | 约 2,300 个不同 ID | 仅用于理解量级；当前归一化会折叠部分 route alias，不能当成准确的 canonical inventory |
| Agena catalog | 1,928 个 ID | 以 `normalized_catalog_model_id` 规则生成的 catalog 项 |
| Agena 与 models.dev 的 ID 匹配 | 351 trusted，611 legacy exact，966 无匹配 | trusted 记录来自当前 allowlist；legacy exact 为其余快照精确 ID；无匹配项可能来自历史人工导入、Codex/HF/厂商研究或上游已移除的 ID |
| Agena 字段缺口 | 388 项无 pricing，966 项无 knowledge cutoff；context_window_tokens、max_input_tokens、max_output_tokens 各有 28 项缺失 | `scripts/report.py` 当前输出；这些空值不一定都适合用第三方来源补齐 |

8,870 与 1,928 的差异不能直接解释成 Agena 丢了 6,942 个模型。models.dev 计数的是 provider-route 记录，Agena 计数的是去重后的 canonical ID；同时，Agena 只纳入受信身份，保留了部分 models.dev 无匹配项，也会拒绝 gateway alias 和不符合前缀策略的记录。

## 对照项目与独立上游判定

| 来源/项目 | 查到的数据 | 可用于 Agena 的范围 | 判定与风险 |
|---|---|---|---|
| models.dev | 230 providers、8,870 model records；包含 limits、pricing、modalities、features、reasoning options 等归一化字段 | 广覆盖发现；官方 provider 行的通用限额、价格、能力可作为重要 fallback | 当前唯一自动抓取目录。其行是 provider/model 粒度，仍需判断是否确为模型 owner 的 API 路由 |
| OpenCode 的 `models.opencode.ai/api.json` | 与 `models.dev/api.json` 都返回 230 providers、8,870 records；本次响应同为 5,662,854 bytes，ETag 相同，SHA-256 相同 | 可作为镜像或可用性备援 | 本次检查证实响应逐字节相同，不能作为第二份独立证据重复计权。OpenCode 的模型服务默认每小时刷新该 host 的 `/api.json`，允许本地文件/环境变量覆盖 |
| Codex `models-manager/models.json` | 11 个内置 Codex preset；11 个都标记支持 verbosity，10 个默认 `low`、1 个默认 `high`；包含 Codex 特有提示词、工具策略、context 与 picker 信息 | 核对 Codex 产品支持的模型和请求行为；`support_verbosity` 可作为 OpenAI Responses 能力的线索 | 数据属于 Codex 产品配置。Codex 后端还可按认证访问 `/backend-api/codex/models`；它不是 OpenAI 全部产品的公共、匿名模型清单。其 `default_verbosity=low` 表示 Codex preset 默认，不能直接写成 OpenAI API 原生默认 |
| Gemini CLI `DEFAULT_MODEL_CONFIGS` | 源码中的静态 Gemini model aliases/config；包含客户端设置的 `thinkingLevel`、`thinkingBudget`、temperature 等请求选项 | 核对 Gemini CLI 对指定模型的请求参数和客户端默认 | 它是一个客户端配置表，不是多厂商模型数据库。客户端的 HIGH thinking 默认只说明 Gemini CLI 的请求策略，不证明供应商原生默认 |
| Hugging Face Hub API | 按当前 12 个官方组织和 `sources.json` 前缀过滤，API 每组织最多取 1,000 条；本次得到 947 个规范化 repo ID，其中 160 已映射到 Agena catalog，80 也出现在 models.dev 的 HF provider 行 | 权重仓库身份、官方组织归属、仓库创建/更新、license/tag、模型配置与开源权重发现 | 有实质补充空间；本次 947 条里许多会是量化、任务模型、蒸馏、checkpoint、音频/图像仓库。它们需要 repo 类型/`pipeline_tag`/配置检查和显式 alias mapping，不能把 787 个 catalog 未命中项都自动当成新的通用聊天模型 |
| OpenRouter `/api/v1/models` | 462 条 route；每条都有 context、pricing、supported_parameters、top_provider；98 条列出 `verbosity`，332 条列出 `reasoning`；有 19 条带 `alias_target` | OpenRouter 服务路由的价格、context、参数是否经过该 gateway 暴露；route 可用性线索 | 这是独立的活跃 route 数据，可补 route 覆盖。但它描述 OpenRouter 上的服务，不能覆盖同模型的原厂 API 价格/限制。用当前 ID 归一化只作诊断时得到 313 个已有 catalog 候选、149 个新候选、10 个多 route 碰撞；这些尾段匹配不能直接发布为安全 alias |
| LiteLLM `model_prices_and_context_window.json` | 4,120 条；3,276 条有 input/output 价格，3,286 条有 max input，2,890 条有 max output，2,765 条带 `source` URL | 作为供应商/model route 价格与 limits 的交叉核对/低优先级补缺源 | 覆盖很广，但包含 alias 和同名模型 route；简单去掉 provider 前缀后与 Agena ID 归一化会产生 608 个候选碰撞。价格不应失去 provider、套餐、批处理、cache 或时间范围后变成一个模型全局价 |
| 厂商官方 API / 文档 | 每家格式不同；有些 list endpoint 只给 ID/显示名，有些带限制/支持方法；定价常在独立网页 | 对相同供应商、相同产品/endpoint/region 的字段，是最直接的验证依据 | 不能期待一个公共数据库完整覆盖全部字段。可以由专用 fetcher 获取结构化 API 项目，文档类事实继续由有来源 URL 与核验日期的 patch 管理 |

### 为什么“来源数”不能按客户端项目数计算

- OpenCode 直接消费 models.dev 形状的数据；本次两个 API 响应完全相同。
- Codex 的模型目录只描述 Codex 产品自己的 presets 和可访问模型。
- Gemini CLI 配置描述 Google CLI 如何给若干 Gemini ID 设请求参数。
- models.dev 的 `huggingface` provider 行是其中一个集合；当前 Agena 并未直连 HF Hub API。`curation/sources.json` 的 12 个 HF organization 条目是筛选规则，不代表 12 个 HTTP upstream。
- Codex、Gemini CLI 和 OpenCode 是有价值的**客户端侧证据**，但不应被误算成三个独立、覆盖所有厂商的模型数据库。

## 推荐的源优先级：按字段组和记录作用域

来源权重应使用“源 × 字段组 × 目标路由”的矩阵。某来源只在它实际负责的范围内有优先权。

| 字段组 | 首选 | fallback / corroboration | 适用范围与规则 |
|---|---|---|---|
| 模型身份、owner、正式 model ID、别名关系 | 厂商发布页/正式 API；权重模型用官方 HF owner 的 repo/card | models.dev；OpenRouter/LiteLLM 的 canonical/alias 字段作发现线索 | 保留来源原始 ID 与显式 alias edge。只有高置信等价关系才并为 canonical ID；保留 `thinking`、dated snapshot、instruct、region、turbo 等有语义的变体 |
| display name、description、release date | 厂商发布材料或模型 API；权重发布日期用官方 model card/release | models.dev，再用 HF 的 repo 日期作仓库时间 | HF repo 创建时间不是必然的模型发布日期；禁止从 ID 日期格式猜测发布日期 |
| context、input、output limits | 同一产品/endpoint 的官方 API 文档或官方可查询模型信息 | models.dev 的 owner/provider 行；OpenRouter/LiteLLM 只补对应 route | route 限额与模型本体限额分别保留。共享 catalog 若只能给一个安全值，可另算 cap 并记录参与的 routes 与取最小值原因 |
| modalities、tools、structured output、temperature、parallel calls 等接口能力 | 对应 API/adapter 的官方 schema 与文档 | models.dev 明确发布的 capability；route registry 在其 route scope 内提供 corroboration | 能力应以 API route 为对象。没有字段代表“未知/未声明”，显式 `false` 才代表不支持 |
| reasoning effort / thinking 参数与 mode 映射 | 厂商对具体 API 的参数说明 | models.dev `reasoning_options`；OpenRouter 参数清单限于 OpenRouter route | Reasoning、thinking toggle、answer verbosity 分开建模。client preset 仅说明那个客户端会发送什么 |
| `supports_verbosity` | exact adapter/API 文档或该 API 对应的机器可读参数表 | models.dev 将来若显式提供；OpenRouter 的 `supported_parameters` 仅用于 OpenRouter route | 保存 endpoint/adapter 适用范围。Agena 当前的 model-level 字段会混淆不同 adapter 的差异，应逐步提升为 route capability 或明确标注适用 adapter |
| `default_verbosity` | Agena 自己的用户默认应由 Agena 配置决定；供应商 native default 只从明确的官方说明读取 | Codex/Gemini CLI 可作客户端行为核对 | 不从 Codex 的 `low` 或其它应用偏好推断供应商默认。明确保存“provider default”与“client request default”两个语义 |
| pricing | 对应 provider/API、region、账户计划的官方定价 | models.dev 的同 provider 行；OpenRouter/LiteLLM 用于各自 route 的补充和冲突提醒 | 保存币种、单位、缓存/批量/优先级、阶梯和 `as_of`。gateway price 不覆盖模型本体价；遗漏与显式免费/零价分开 |
| open weights、license、artifact facts | 官方 HF repo 文件/card 与模型 owner 发布页 | models.dev / LiteLLM 仅作发现或交叉核对 | repo 必须确认是权重模型，不要把文档、数据集、量化衍生、adapter 或 demo 自动标成基础模型 |
| knowledge cutoff | 厂商技术报告/明确发布的官方模型 card | models.dev 有值时作为 fallback | release date 和 cutoff 不等价；无证据保留空值 |

执行顺序上，经过来源核验的人工 override 可以覆盖自动字段；构建时仍要将它与最新官方/高优先级 observation 比较，冲突时发报告，避免旧 patch 永久掩盖上游更新。自动源优先级平级且值冲突时，不能静默按 JSON 文件顺序取值，应输出带两个来源与值的冲突项，并按高影响字段配置失败或人工复核。

## 数据结构与刷新器建议

1. **分开 model identity、provider route、artifact 和 client preset。** Canonical model 持有模型家族事实；route 记录使用 `(provider, exact_model_id, endpoint/region/product)`；HF artifact 以 repo ID 表示；Codex/Gemini preset 使用 client namespace。显式 alias mapping 连接它们。
2. **增加独立 source registry。** 每个 source 记录 owner、URL/endpoint、schema/version、刷新策略、scope、可提供字段组、priority 和 ID mapping policy。URL 不同且数据独立才记作一个新上游；mirror 另标 `mirror_of`。
3. **保留 raw snapshot 和 provenance sidecar。** 对每个最终字段存 source name、source record ID、raw value、normalized value、retrieved_at/upstream timestamp、priority、适用 route 与核验 URL。发布的 `models.json` 仍可精简；review/report 从 sidecar 解释字段来源。
4. **将缺值和明确值区分到底。** 缺失不参与覆盖；`false`、`0`、空列表（若 schema 定义有效）均保留为明确声明；`null` 必须根据 upstream contract 解释，不自动映射成 false。
5. **把 conflicts、mapping 和质量门禁放在 publish 前。** 对新增身份数量、别名碰撞、单位换算、价格差、limits 差和过期 source 设置报告；官方来源同字段发生不同值时禁止静默 publish。所有源失败时继续使用上个成功 snapshot，但在工作流摘要显示每个源 freshness 和失败状态。

Agena runtime 已有一个 `CatalogDefinitionSourcePriority` sidecar 类型，字段组包括 descriptive、limits、capability、semantics、pricing 和 modes；默认 public source 目前只有 Agena GitHub catalog，所有分值同为 1000。当前 public merge 实际用 `limits_priority` 比较 context/input/output limits；description、capabilities、verbosity/semantics、pricing 与 modes 仍主要采用补空值或合并字段的策略，其它 priority 分值没有形成完整的逐组覆盖行为。因此它是可借鉴的结构起点，还不能替代 catalog 生成阶段的源优先级与 provenance。runtime 无法从已经扁平的 `models.json` 反推出字段来自哪里。

## 分阶段接入顺序

### 第一步：先把现状变成可审计

- 建 source manifest，记录来源类型与 `mirror_of`；将 OpenCode mirror 与 models.dev 合为同一独立来源。
- 当前 trusted source 改为先保留**各来源记录**，再逐字段合并，不在发现阶段选出一条记录丢弃其它 observations。
- 生成 provenance/conflict report，并将历史 patch 的来源 URL、核验日期逐步结构化。

### 第二步：接入真正有增量的上游

- **HF Hub**：先做官方 repo 身份与 artifact discovery 报告；人工/规则明确筛选模型权重、license、task 和基座关系后再添加。初次拉取结果会明显大于当前 models.dev HF 子集，不能全量自动增 catalog。
- **OpenRouter**：建立独立 route 数据；只把 exact OpenRouter route 的 availability、supported parameters、context 和 price 放入 route scope。用 `supported_parameters` 的 98 条 verbosity 信号生成 route 级候选；provider capability 仍需原厂文档确认。
- **LiteLLM**：先用作价格/limits 对账和候选补充，保存其 source URL 与 adapter key；待 exact provider route mapping 有把握后再参与自动合并。
- **厂商 API/文档**：先按 Google、OpenAI、Anthropic 等实际字段能力制定小型 adapter；每种 API 只导入它确实提供的字段。文档核验继续通过带 URL/date 的 patch 接入。

### 第三步：支持下游消费 route 信息

如果希望 Agena 在具体 adapter 上正确显示价格、limits 或 verbosity support，需要 catalog schema 和 runtime 查询接口能返回 route-scoped metadata。现有单条 canonical `pricing`/`supports_verbosity` 无法无损表达同一模型通过不同 route 服务时的差异。路由数据完整接入前，route aggregator 值只用于核对和报告，不写入有全局含义的字段。

## 对 verbosity 字段的直接影响

本次读取的 models.dev 数据 schema 没有 `supports_verbosity` 或 `default_verbosity`。OpenRouter 当前 `supported_parameters` 有 98 条 route 记录包含 `verbosity`，这是此前未进入 Agena 自动流程的独立线索。Codex 内置 preset 的 `support_verbosity/default_verbosity` 也是直接可读的客户端配置，但 default 表示 Codex 的发送默认。正确做法是保留来源与 route/client scope，而不是把 reasoning effort 转成 verbosity，也不是把客户端默认伪装成 provider default。

## 本次使用的可检查证据

- Agena 刷新与筛选：`scripts/fetch_modelsdev.sh`、`scripts/model_sources.py`、`scripts/merge_modelsdev.py`、`scripts/refresh.sh`、`curation/sources.json`。
- 历史来源说明：`curation/README.md` 中 2026-08 initial sweep 的 note；patch `notes` 还含各厂商文档和模型卡引用。
- OpenCode：本机同级 checkout `opencode/packages/core/src/models-dev.ts`、`opencode/packages/opencode/src/provider/provider.ts`；对应公开源码可见 [models-dev.ts](https://github.com/anomalyco/opencode/blob/dev/packages/core/src/models-dev.ts)。
- Codex：本机同级 checkout `codex/codex-rs/models-manager/models.json`、`codex/codex-rs/models-manager/src/lib.rs`、`codex/codex-rs/model-provider/src/models_endpoint.rs`；对应公开文件为 [models.json](https://github.com/openai/codex/blob/main/codex-rs/models-manager/models.json)。
- Gemini CLI：本机同级 checkout `gemini-cli/packages/core/src/config/defaultModelConfigs.ts`、`gemini-cli/packages/core/src/config/models.ts`；对应公开源码为 [defaultModelConfigs.ts](https://github.com/google-gemini/gemini-cli/blob/main/packages/core/src/config/defaultModelConfigs.ts)。
- Agena runtime priority groundwork：同级 checkout `agena/crates/agena-provider/src/catalog_definition.rs`、`agena/crates/agena-runtime/src/model_catalog_source.rs`、`agena/crates/agena-provider/src/catalog_public_merge.rs`。
- Live public endpoints checked on 2026-10-15: [models.dev API](https://models.dev/api.json), [OpenCode model API](https://models.opencode.ai/api.json), [OpenRouter model API](https://openrouter.ai/api/v1/models), [Hugging Face model API](https://huggingface.co/api/models), [LiteLLM price/context dataset](https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json).

本次审计只新增了研究说明，没有更改抓取、合并或发布行为；已有未提交的 verbosity 保留改动不受影响。
