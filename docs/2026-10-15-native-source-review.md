# 云端网模型原厂价格同步方案审阅（2026-10-15）

本次覆盖 34 个启用白名单中的在售模型，并逐项检查全部活跃分组内配置过的 51 个独立模型 ID（含未启用白名单的 17 项）。账号上游任意模型列表不扩充在售目录。读取生产目录和分组设置均使用只读事务，没有修改分组、倍率、调度意图或应用程序。

## 结论与选择

采用 **原厂 provider 白名单 + 原生命名空间 + 完整价卡刷新 + 自动裸名别名**。LiteLLM 是第三方整理源，优先选择模型厂商自身 API 渠道，不能将该选择称为每个费项均实时获官方认证。

| 方案 | 结果 | 决策 |
| --- | --- | --- |
| 保留 additive / update_existing=false | 新型号可补入，已有错误价格和失效费项继续保留 | 不采用 |
| 无渠道约束地覆盖全部同名条目 | 容易把 Gemini Vertex、Azure、OpenRouter 和原厂渠道混在一起 | 不采用 |
| 原厂 provider 与命名空间双重匹配，更新完整条目 | 对应渠道明确，价格变动及删除字段均自动进入，裸名可查询 | 采用 |

定时同步仍使用现有 GitHub Actions；计划每十分钟一次，错开整点高峰到每小时 7/17/27/37/47/57 分，不增加主机服务或定时器。仓库保留历史未匹配条目，但不宣称它们仍有现行官方价格。网络、JSON 解析或空选集失败不发布，单个来源消失则保留上次数据，需结合官方生命周期核查。

原厂选择为 OpenAI/openai、Anthropic/anthropic、Gemini Developer API/gemini、xAI/xai、DeepSeek/deepseek、Z.AI/zai、Kimi/moonshot。国产模型统一使用原厂国际站的美元报价，避免人民币通过固定汇率折成美元。国内站与国际站可能本来就是不同价格，切换口径不能说成原人民币价全都过期。

## 覆盖与费用处理

51 项中，46 项取得精确原厂模型或其命名空间价卡，1 项为官方明确的模型身份映射，3 项为现有明确配置的别名，1 项缺价。34 个在售模型对应 30 个精确原厂模型、1 个官方身份映射、2 个配置别名、1 个缺项。

- 自动为 `gemini/`、`xai/`、`deepseek/`、`zai/`、`moonshot/` 生成裸名，保留完整缓存、长上下文、Batch/Flex/Priority、图片 Token 和来源字段。带前缀来源会随每次同步完整刷新，已有数字和上游删除的字段不再冻结。
- 同步匹配的原厂条目优先于旧 custom_models 和手工别名；无匹配的旧条目继续兼容。取消全局按倍率推导 1h 缓存写价。
- `gemini-3.1-pro` 保持配置到 `gemini-3.1-pro-preview` 的端点别名；`codex-auto-review` 保持本站到 `gpt-5.6-luna` 的别名。另有未启用的 `gpt-5.3-codex-spark` 保持到 `gpt-5.3-codex` 的配置别名。这三项不是各自同名官方模型已获确认。
- 官方价表确认 `deepseek-flash` 即 DeepSeek-V4.1-Flash，因此 `deepseek-v4.1-flash` 映射至 `deepseek/deepseek-flash`，完整复制标准/低谷价格。官方旧名 `deepseek-v4-flash`、`deepseek-v4-flash-vision-exp` 也由 V4.1 Flash 服务，现有原厂条目价格一致；`deepseek-v4-pro` 则独立对应 DeepSeek-V4-Pro-0813。更正初审只看同名键而遗漏官方身份映射的结论。仅裸 `gpt-image-2.5` 继续缺价，不借相邻型号或转售渠道报价。
- Kimi K3 原厂 LiteLLM 缺 5min/1h 写入价，依据当天已校验官方国际站原文补缺 $3/$6 每百万 Token。采用 setdefault，未来原厂条目明确提供的费率（含显式零）优先。此次重新访问该页面返回 403，因此使用 2026-10-15 14:05 成功采集且 SHA-256 已复核的原文，不冒称实时重抓成功。
- Z.AI 的四个在售 GLM 与 DeepSeek Flash/Pro（含规范 Flash 端点和对应别名）的每 Token 缓存写入费未经官方列示，移除 LiteLLM 的合成 0 值；缓存存储“限时免费”不推导成每 Token 缓存写入免费。缺项保持缺项。
- 继续保留此前明确设置的 `gpt-6.1-sol` 全上下文统一价例外，最后删除 272K 加价字段。这是本站覆盖，不宣称官方取消加价。
- 生图分组继续由应用按 1K/2K/4K 每张计价。官方图片 Token 价与分组按张售价单位不同，不能相互覆盖。

关键修正包括 GPT-5.6 Sol 标准输入/输出/命中从 5/30/0.5 改为 4/20/0.4，Sonnet 5.5 缓存读取从 0.2 改为 0.1；Grok 4.7、GLM 5.3 Flash 增加价卡，GLM 和 Kimi 改用原厂国际站 USD 标价，DeepSeek Flash 更新原厂标准价。所有数字单位均为 USD/百万 Token。

## 逐模型比对

下表按输入 / 输出 / 缓存读取列示，`—` 为未提供字段。GPT Image 行这里是文本 Token 费率；图像 Token 单独保留于 JSON，不能把缺失文本输出价填成图片输出价或零。前后 JSON 的全部价格字段变化见[完整字段比较 JSON](https://github.com/wolfydw/model-price-repo/blob/main/docs/2026-10-15-native-source-comparison.json)，未只比较基础三项。

| 模型 | 在售 | 匹配来源 | 原输入 / 输出 / 命中 | 新输入 / 输出 / 命中 |
| --- | --- | --- | --- | --- |
| `claude-fable-5` | 否 | `claude-fable-5` | 10 / 50 / 1 | 10 / 50 / 1 |
| `claude-fable-5-1` | 是 | `claude-fable-5-1` | 10 / 50 / 0.25 | 10 / 50 / 0.25 |
| `claude-haiku-4-5` | 是 | `claude-haiku-4-5` | 1 / 5 / 0.1 | 1 / 5 / 0.1 |
| `claude-haiku-4-5-20251001` | 否 | `claude-haiku-4-5-20251001` | 1 / 5 / 0.1 | 1 / 5 / 0.1 |
| `claude-haiku-5-5` | 是 | `claude-haiku-5-5` | 0.1 / 0.5 / 0.01 | 0.1 / 0.5 / 0.01 |
| `claude-opus-4-5-20251101` | 否 | `claude-opus-4-5-20251101` | 5 / 25 / 0.5 | 5 / 25 / 0.5 |
| `claude-opus-4-6` | 否 | `claude-opus-4-6` | 5 / 25 / 0.5 | 5 / 25 / 0.5 |
| `claude-opus-4-7` | 否 | `claude-opus-4-7` | 5 / 25 / 0.5 | 5 / 25 / 0.5 |
| `claude-opus-4-8` | 否 | `claude-opus-4-8` | 5 / 25 / 0.5 | 5 / 25 / 0.5 |
| `claude-opus-5` | 否 | `claude-opus-5` | 5 / 25 / 0.5 | 5 / 25 / 0.5 |
| `claude-opus-5-5` | 是 | `claude-opus-5-5` | 4 / 20 / 0.2 | 4 / 20 / 0.2 |
| `claude-sonnet-4-5-20250929` | 否 | `claude-sonnet-4-5-20250929` | 3 / 15 / 0.3 | 3 / 15 / 0.3 |
| `claude-sonnet-4-6` | 否 | `claude-sonnet-4-6` | 3 / 15 / 0.3 | 3 / 15 / 0.3 |
| `claude-sonnet-5` | 否 | `claude-sonnet-5` | 2 / 10 / 0.2 | 2 / 10 / 0.2 |
| `claude-sonnet-5-5` | 是 | `claude-sonnet-5-5` | 2 / 10 / 0.2 | 2 / 10 / 0.1 |
| `codex-auto-review` | 是 | `gpt-5.6-luna`（配置别名） | 0.2 / 1.2 / 0.02 | 0.2 / 1.2 / 0.02 |
| `deepseek-v4-flash` | 是 | `deepseek/deepseek-v4-flash` | 0.44 / 1.32 / 0.014 | 0.3 / 1.2 / 0.006 |
| `deepseek-v4-pro` | 是 | `deepseek/deepseek-v4-pro` | 1.32 / 3.96 / 0.044 | 1.32 / 3.96 / 0.044 |
| `deepseek-v4.1-flash` | 是 | `deepseek/deepseek-flash`（官方身份映射） | — / — / — | 0.3 / 1.2 / 0.006 |
| `gemini-3.1-pro` | 是 | `gemini/gemini-3.1-pro-preview`（配置别名） | 2 / 12 / 0.2 | 2 / 12 / 0.2 |
| `gemini-3.6-flash` | 是 | `gemini/gemini-3.6-flash` | 0.75 / 3.75 / 0.075 | 0.75 / 3.75 / 0.075 |
| `gemini-3.7-flash` | 是 | `gemini/gemini-3.7-flash` | 0.75 / 3.75 / 0.075 | 0.75 / 3.75 / 0.075 |
| `gemini-3.8-flash` | 是 | `gemini/gemini-3.8-flash` | 0.75 / 3.75 / 0.075 | 0.75 / 3.75 / 0.075 |
| `gemini-4-argon` | 是 | `gemini/gemini-4-argon` | 2 / 10 / 0.1 | 2 / 10 / 0.1 |
| `glm-5.1` | 是 | `zai/glm-5.1` | 1.4 / 4.4 / 0.28 | 1.4 / 4.4 / 0.26 |
| `glm-5.2` | 是 | `zai/glm-5.2` | 1.1792279 / 4.12729765 / 0.294806975 | 1.4 / 4.4 / 0.26 |
| `glm-5.3` | 是 | `zai/glm-5.3` | 1.4 / 4.4 / 0.26 | 1.4 / 4.4 / 0.26 |
| `glm-5.3-flash` | 是 | `zai/glm-5.3-flash` | — / — / — | 0.15 / 0.5 / 0.03 |
| `gpt-5.2` | 否 | `gpt-5.2` | 1.75 / 14 / 0.175 | 1.75 / 14 / 0.175 |
| `gpt-5.3-codex-spark` | 否 | `gpt-5.3-codex`（配置别名） | 1.75 / 14 / 0.175 | 1.75 / 14 / 0.175 |
| `gpt-5.4` | 否 | `gpt-5.4` | 2.5 / 15 / 0.25 | 2.5 / 15 / 0.25 |
| `gpt-5.4-mini` | 否 | `gpt-5.4-mini` | 0.75 / 4.5 / 0.075 | 0.75 / 4.5 / 0.075 |
| `gpt-5.5` | 是 | `gpt-5.5` | 5 / 30 / 0.5 | 5 / 30 / 0.5 |
| `gpt-5.6` | 否 | `gpt-5.6` | 4 / 20 / 0.4 | 4 / 20 / 0.4 |
| `gpt-5.6-luna` | 是 | `gpt-5.6-luna` | 0.2 / 1.2 / 0.02 | 0.2 / 1.2 / 0.02 |
| `gpt-5.6-sol` | 是 | `gpt-5.6-sol` | 5 / 30 / 0.5 | 4 / 20 / 0.4 |
| `gpt-5.6-terra` | 是 | `gpt-5.6-terra` | 2 / 12 / 0.2 | 2 / 12 / 0.2 |
| `gpt-6-astra` | 是 | `gpt-6-astra` | 10 / 50 / 1 | 10 / 50 / 1 |
| `gpt-6-luna` | 是 | `gpt-6-luna` | 0.1 / 0.5 / 0.01 | 0.1 / 0.5 / 0.01 |
| `gpt-6-sol` | 是 | `gpt-6-sol` | 2 / 10 / 0.2 | 2 / 10 / 0.2 |
| `gpt-6.1-sol` | 是 | `gpt-6.1-sol` | 2 / 10 / 0.1 | 2 / 10 / 0.1 |
| `gpt-image-1` | 否 | `gpt-image-1` | 5 / — / 1.25 | 5 / — / 1.25 |
| `gpt-image-1.5` | 否 | `gpt-image-1.5` | 5 / 10 / 1.25 | 5 / 10 / 1.25 |
| `gpt-image-2` | 是 | `gpt-image-2` | 5 / 10 / 1.25 | 5 / — / 1.25 |
| `gpt-image-2.5` | 是 | 无精确原厂项 | — / — / — | — |
| `gpt-image-2.5-flare` | 是 | `gpt-image-2.5-flare` | 5 / — / 1.25 | 5 / — / 1.25 |
| `gpt-image-2.5-sunburst` | 是 | `gpt-image-2.5-sunburst` | 5 / — / 1.25 | 5 / — / 1.25 |
| `grok-4.5` | 是 | `xai/grok-4.5` | 2 / 6 / 0.3 | 2 / 6 / 0.3 |
| `grok-4.6` | 是 | `xai/grok-4.6` | 2 / 6 / 0.5 | 2 / 6 / 0.5 |
| `grok-4.7` | 是 | `xai/grok-4.7` | — / — / — | 2 / 6 / 0.5 |
| `kimi-k3` | 是 | `moonshot/kimi-k3` | 2.94806975 / 14.7403488 / 0.294806975 | 3 / 15 / 0.3 |

## 来源与实际计费边界

- LiteLLM 价格文件固定 commit：`3fec5075fa3069d4da0bba437ba1e1f2218792ed`，SHA-256 `6fc1f38bce2adaf89463e1bb9436de227dd78e5b2f6befc1b005c3cd88deb2cb`；与本次 main 抓取字节一致。
- [OpenAI 官方价表](https://developers.openai.com/api/docs/pricing.md)：本次抓取成功，GPT-5.6 Sol 现行价及图片 Token 单位已复核。
- [Anthropic 官方价表](https://platform.claude.com/docs/en/about-claude/pricing)：本次重新抓取返回 403，引用当天既有成功归档；Fable/Opus/Sonnet/Haiku 的缓存档位由原厂 LiteLLM 条目同步。
- [Gemini Developer API](https://ai.google.dev/gemini-api/docs/pricing) 与 Vertex 分开；当前优惠日期并未由本站另造定时器，应随上游原厂条目更新并在到期点复核。
- [Z.AI 国际站](https://docs.z.ai/guides/overview/pricing.md)、[DeepSeek 国际站](https://api-docs.deepseek.com/quick_start/pricing/) 本次抓取成功。
- [Kimi 国际站](https://platform.kimi.ai/docs/pricing/chat.md) 当天归档 SHA-256 为 `76361351b3e3f3184cbd89f262f4bd8ed212b4d481dd0d527f34221a35a4d079`；另见既有 model-price-repo-official-comparison 审阅证据。

此任务更新价库及其同步规则，不变更 Sub2API 二进制。既有应用还可能有模型特定策略、渠道/分组覆盖、用户倍率和时间规则；例如已审阅的 DeepSeek Pro 强制转 Flash 及节假日规则属于应用侧问题，不能声称仅更新价库就同时修复了实际扣费。价格仓库完整收录也不等于当前二进制消费了 Batch/Ultrafast 等所有字段。

生成目录由 335 项增加到 541 项（初次发布 540 项，官方身份映射更正新增 1 项），未删除已有模型 ID；新增条目属于价库，不扩充生产在售白名单。发布前后证据与运行缓存验证另存 publication-verification.json。回退可按本次提交恢复前一版配置、脚本和 JSON/哈希，随后由既有十分钟检查拉取。

## DeepSeek 官方身份映射更正

2026-10-15 重新获取官方价格页成功，SHA-256 `210f102275ccf1a6542f08a3bc9e4b4c7c83278cb74b35217bffa112df6363b2`。页面明确列出 Flash/V4.1 和 Pro/0813 的对应关系，也确认旧 Flash 两个名字已退役但仍接受并按 V4.1 Flash 服务。不能只因 LiteLLM 缺少相同版本字符串就判定 V4.1 Flash 没有官方报价。

| 官方模型 | 时段 | 输入 / 输出 / 缓存读取（USD/百万 Token） |
| --- | --- | --- |
| V4.1 Flash | 高峰 | 0.3 / 1.2 / 0.006 |
| V4.1 Flash | 低谷 | 0.15 / 0.6 / 0.003 |
| V4 Pro 0813 | 高峰 | 1.32 / 3.96 / 0.044 |
| V4 Pro 0813 | 低谷 | 0.66 / 1.98 / 0.022 |

同步配置保存官方来源和核验日期；使用既有别名机制随源价卡完整更新，若未来出现精确原厂条目则以该条目优先。补充回归覆盖低谷字段保留、源改价及删字段、重复生成、源消失保留最后价卡、未来精确条目优先、Pro 独立费率。这里只更新价格仓库；应用现存 Pro→Flash 和节假日规则仍须按前述计费边界看待。
