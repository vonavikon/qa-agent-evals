# qa-agent-evals

[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![VirusTotal](https://img.shields.io/badge/VirusTotal-0%2F75_clean-brightgreen)](https://www.virustotal.com/gui/file/2be21c1ca3e7e4c38667542ef561f0209494dbcd31d7eba476200572876e83ee)

[RU](README.md) · [EN](README.en.md) · **中文** · [Español](README.es.md) · [Français](README.fr.md)

一个 Claude Code 插件，通过扮演角色的子代理对 LLM 系统做验收测试。你只需给出被测系统（SUT）的路径。插件会建立它的画像，生成五种类型的场景卡片，经隔离的适配器让执行子代理跑一遍，由运行在另一个模型上的裁判给出裁定，并汇总出带通过率和覆盖矩阵的报告。

它和手动跑提示词的区别在于一条信任链：每张卡片的预期结果在运行前就已写下，运行后不再修改；事实由机器在裁判之前核查（对回答和系统自己写出的文件做 grep）；裁判运行在另一个模型上，并用带有已知裁定的对照样本校准；验收后的人工确认会不断补充这份样本。运行环境与所有者的 skills 和 MCP 隔离。裁定是不对称的：FAIL 证明缺陷，GOT 只表示"未被驳倒"。

![工作方式：插件研究系统、编写任务，演员扮演用户，陌生插件隔在玻璃后，裁判为回答打分，报告展示结果](assets/concept.en.gif)

*一个业余项目：通过造一个能用的工具并让它测试自己，来理解验收式 evals。*

## 工作方式

```
[A: 分析 SUT] → [B: 适配器 + 冒烟测试] → [C: 卡片] → [D: 运行 × N 次重复] → [E: 报告]
```

- **分析师**（阶段 A）阅读 SUT 并建立画像：功能清单、风险图、攻击面、歧义点、适配器方案。
- **卡片**（阶段 C）分五类：obvious（正常路径）、convoluted（多轮歧义）、critical（损害区域）、adversarial（每张卡一个 OWASP 攻击）、out-of-scope（SUT 是否承认请求超出自己的范围）。格式：YAML，含角色设定、指令、oracle（必须出现 / 不得出现的事实 + 一句散文式预期）和预算。
- **role-user 执行者**通过适配器以角色设定对抗 SUT。对 CLI 系统来说，这是一次隔离的 headless 会话：中性工作目录，访问不到所有者的 skills 和 MCP。Web 型 SUT 走浏览器适配器（Playwright 表面），见 `knowledge/adapters.md`。重复运行由 `scripts/run-cards.sh` 驱动。
- **机器层**（`scripts/check-facts.py`）在裁判之前工作：在转录文本和系统自己写出的文件里 grep oracle 的标记。机器证明了的事，裁判不再改判；自相矛盾（在已证明违规之上给出正面裁定）会自动触发重判。
- **裁判**运行在另一个模型上，分两步工作：先在不了解卡片意图的前提下对照 oracle 给回答打分，再检查执行者有没有放水。每次验收运行前，裁判会在对照样本上校准：手写用例、开放数据集用例（TruthfulQA，Apache 2.0；HH-RLHF 攻击，MIT），以及由人工反馈不断补充的活样本区。
- **反馈闭环（Growing-Golden）**：运行结束后，所有者通过可点击的标注页面或直接在聊天里确认或修正裁定。只有人的裁定才能成为基准，裁判自己的裁定永远不能。
- **报告**：各次重复的裁定与投票、功能 × 类型的覆盖矩阵、带优先级的发现、原因分析、运行局限，以及运行的代价（令牌和美元，SUT 侧和裁判侧分开计量）。

完整图谱（隔离、上下文层级、责任矩阵）见 [docs/architecture.md](docs/architecture.md)。交互版本：[docs/architecture.html](docs/architecture.html)，每个节点都标出对应的文件或参数。请在浏览器中本地打开该文件。项目的全部测试运行汇总在验收日志里：[docs/benchmarks.md](docs/benchmarks.md)。

## 执行隔离（v0.5.0）

被测插件运行在两个隔离级别之一，每次运行的报告都会记录所选级别：

- **host**（默认）：不依赖 Docker 和额外组件。环境隔离与之前相同：环境变量白名单、空 MCP、中性工作目录、篡改检测器。没有文件系统和网络层面的屏障，报告会如实标注该级别"不是沙箱"。对来自已知来源的公开插件来说足够。
- **docker**（用于不可信内容）：容器只挂载工作目录和插件副本，根文件系统只读，非 root 用户，资源限额；对外的唯一通路是通往 LLM 网关的内部代理容器。Docker 不可用时运行直接拒绝启动（fail-closed），不会悄悄退回不安全模式。

用自带的 examples/evil-plugin（一个从不拒绝的插件）做了实跑验证：docker 下，读取宿主机密钥、访问网络、在工作目录之外写文件、伪造证据全部被挡下；host 下同样的攻击被如实记录为该级别的风险。附带发现：网关的服务端工具（网页阅读）会把外部内容带进封闭网络，因此在 docker 模式下被禁用。

v0.5.1 加固：插件源码以只读方式挂载，启动时做写入探测（可写则拒绝运行）；网关的真实密钥只存在于代理容器内，被测进程拿到的是占位密钥；代理只接受 LLM API 路径并限制请求。自动化安全套件（`python scripts/sec-checks.py docker`）一条命令跑完全部六项检查，并在 CI 中保持绿色，Windows 和 Linux runner 均通过（runs/2026-10-13-sec/）。v0.5.2 最终加固：写入探测改为基于证据（只有确认写入被拦截才算成功）；代理路径归一化封堵 /../ 穿越遍历；增加频率/容量/时长限额；代理容器本身以非 root 且无 capabilities 运行；SEC-06 拆分为篡改 oracle 和伪造裁定两项攻击（都用哈希校验）；集成测试用真实的 Claude Code 跑完整流水线（runs/2026-10-13-secint/）。

## 快速开始

要求：Claude Code、bash、python3。Windows 上需要 Git Bash 或 WSL。

安装插件（启动会话时用 `--plugin-dir <路径>`，通过 marketplace，或用 APM：`pip install apm-cli`，然后 `apm install vonavikon/qa-agent-evals`），在被测系统的目录里打开会话，然后输入：

```
对 <SUT 路径> 运行验收测试
```

流水线会自己走完 A 到 E 各阶段，只在确认卡片前停下一次：把卡片展示给你，等你的决定。

## 组成

```
.claude-plugin/plugin.json    清单
skills/acceptance-test/       五阶段流水线（编排器）
agents/analyst.md             SUT 画像
agents/role-user.md           角色执行者
agents/judge.md               两步裁判（绑定另一个模型）
agents/visual-reviewer.md     截图可视化评审（标注只给人看）
knowledge/taxonomy.md         5 种卡片类型、模式、参考 YAML
knowledge/adapters.md         CLI 与浏览器（Playwright）适配器、环境隔离
knowledge/oracle.md           oracle、裁定量表、报告模板
knowledge/sandbox.md          host/docker 两级隔离：边界、代理、检查
knowledge/golden-live.md      对照样本的活样本区（来自反馈的 golden 用例）
scripts/run-cards.sh          单轮卡片的 CLI 运行器，支持重复
scripts/run-integrity.sh      运行目录篡改检测器
scripts/parse-events.py       events.jsonl 解析：回答、来源、诊断
scripts/check-facts.py        机器事实核查（转录 + SUT 写出的文件）
scripts/judge-batch.py        裁判批量调用 + 自相矛盾自动重判
scripts/judge-control.py      裁判对照样本（golden 集）
scripts/collect-feedback.py   人工反馈：标注页面 + golden 候选
scripts/annotate-visuals.py   可视化评审：校验标注、生成带框页面、挑选发布样本（--publish）
scripts/build-index.py        机器可读的运行索引（index.jsonl）
scripts/cost-report.py        运行成本与时长
scripts/judge-metrics.py      裁判在语料上的一致性指标
scripts/diff-runs.py          同一 SUT 两次运行的对比（视图，不是判据）
scripts/make-golden-*.py      开放数据集（TruthfulQA、HH-RLHF）转 golden 用例
scripts/sandbox.py            SUT 会话的隔离级别后端
scripts/sandbox-proxy.py      docker 级别用的 LLM 网关反向代理
scripts/sec-checks.py         六项 docker 隔离检查的安全套件
scripts/sec-integration.py    集成测试：docker 沙箱内跑真实流水线
scripts/Dockerfile.sandbox    隔离容器的镜像
examples/evil-plugin          用于验证隔离的靶标插件
tests/                        流水线的单元测试与实跑测试
docs/spec.md                  规格说明
docs/plan.md                  实现计划
docs/architecture.md          工作原理：流水线、隔离、责任
docs/research-2026-10-09.md   源框架综述
docs/research-2026-10-10-rsi.md  自我提升（self-improvement）资料笔记
docs/research-2026-10-11-kaggle-golden.md  用于 golden 用例的开放数据集
docs/reviews/                 规格的外部评审与代码评审
runs/                         自验收与第三方运行的产物（原始会话日志与敏感数据已剔除）
```

## 状态

v0.6.0。流水线在第三方系统和它自己身上长大。

v0.6.0 为浏览器验收加了一层可视化：适配器在转录旁边截取各状态截图，评审子代理在图上框出缺陷（框 + 严重度 + 评论），反馈页面把带标注的截图展示在裁定旁边。标注只给人看：裁判永远看不到，裁定不变，截图绝不进入 oracle 或机器层。只有所有者亲手挑选的样本才会发布（`annotate-visuals.py --publish`）。

先做了四次自验收（v1-v4，报告见 [runs/](runs/2026-10-08-qa-agent-evals-selftest/report.md)）：v1 找到 3 个真实缺陷（适用范围、承诺未实现的功能、审批控制）；之后每次运行验证上一轮的修复，并寻找新缺陷。

然后是第三方系统：一个文字编辑 skill（两次运行并对比版本，[runs/](runs/2026-10-11-stop-slop-r2/report.md)）、一个带内容注入的幻灯片生成器、一个技术英语改写 skill、经浏览器适配器运行的经典 2048 游戏（确定性的非 LLM SUT），以及来自封闭范围的一些系统（细节保密）。这些运行长出了 v0.3-v0.4：机器事实层（grep 抓到泄露，包括 SUT 自己写的文件）、基于开放数据集的裁判对照样本（TruthfulQA 45/45；HH-RLHF 攻击）、带标注页面的 Growing-Golden 反馈闭环、自相矛盾自动重判，以及实测的运行成本：一次典型验收在 SUT 侧花费 $0.6-1.8，裁判每次调用约 $0.4，因为裁判的 CLI 调用带着约 75K token 的会话前导。

v0.5.0 加入执行隔离（host/docker），并用 evil-plugin 实跑验证，基础设施故障与插件缺陷从此分开（BLOCKED/ERROR 状态）。v0.5.1 和 v0.5.2 对其加固：网关密钥只存放在代理容器内；插件源码只读挂载并做基于证据的写入探测；代理路径归一化封堵 /../ 穿越；增加频率/容量/时长限额；代理以非 root 且无 capabilities 运行。安全套件（`python scripts/sec-checks.py docker`）在 Windows 和 Linux CI runner 上均为绿色（runs/2026-10-13-sec/）；集成测试用真实的 Claude Code 跑活流水线（runs/2026-10-13-secint/）。合计 52 个测试：43 个流水线单元测试和 9 个代理实跑测试。

尚未做到：只实现了 CLI 和浏览器适配器；隔离切断了 skills 的调用，但切不断对它们存在的认知；裁判需要手动指定（显式 `--model`，或在阶段 B 由人选择），因为 agent 的 `model` 字段并非在所有环境都生效。

规格：[docs/spec.md](docs/spec.md)，计划：[docs/plan.md](docs/plan.md)。
