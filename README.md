# CodeForge

CodeForge v0.1.1 是一个轻量级 Coding Agent 编排框架。它不直接调用模型 API，
也不负责生成模型能力；它通过 subprocess 调用现有的 Codex CLI 和 Claude Code
CLI，用明确的角色、文件制品、路由策略和人工确认来完成一个可审计的开发闭环。

## 工作流

```text
task.md
   │
   ▼
Architect (Codex) ──► architecture.md / architecture.json
   │
   ▼
Human approval [y/n]
   │ y
   ▼
Implementer (policy: Claude Code or Codex)
   │
   ▼
Reviewer (Codex) ──► review.md / review.json
   │                    │ changes requested, bounded by max_iterations
   │                    └──────────────────────────────► Implementer
   ▼
Tests + Verifier (Codex) ──► verification.md / verification.json
   │
   ▼
Done / Failed
```

角色和执行器彼此独立：角色描述职责，执行器只描述所使用的 CLI。各阶段不靠
agent 聊天传递上下文，而是读取任务、批准后的架构、相关文件、Git diff、审查与
测试结果等受控输入。

## 安装与使用

要求 Python 3.10+，并至少安装、登录 Codex CLI。低风险任务还需要 Claude Code
CLI；如果不使用 Claude Code，可以把策略中的低风险执行器也设为 `codex`。

```powershell
python -m pip install -e .
codeforge run .\my-task.md
```

也可以不安装入口脚本：

```powershell
python -m CodeForge run .\my-task.md
```

Architect 完成后，终端会展示方案并询问 `Continue? [y/n]`。v0.1.1 不提供自动
跳过选项。每次运行都会在 `tasks/<timestamp>-<task-name>/` 创建独立目录：

```text
task.md
state.json
artifacts/
  architecture.md
  architecture.json
  implementation-1.md
  implementation-1.json
  review-1.md
  review-1.json
  review.md
  review.json
  verification.md
  verification.json
```

`state.json` 持久化阶段、状态、迭代次数、实际路由的执行器，并预留
`git_commit_before` 与 `git_commit_after`。

## 运行时权限确认

v0.1.1 为 Codex CLI 和 Claude Code CLI 注入官方 `PermissionRequest` Hook。当
agent 请求执行超出当前自动授权范围的命令时：

```text
Agent requests permission
          ↓
state.json: status = awaiting_approval
          ↓
独立 Windows 控制台展示 executor、stage、tool、reason 和输入
          ↓
用户输入 y / n
          ↓
Hook 返回 allow / deny，原 CLI 会话继续
          ↓
state.json: status = running，并写入 approval_history
```

这不是重新启动 agent，因此不会丢失当前上下文。拒绝后，agent 可以选择安全的
替代方案；如果最终无法产生有效制品，任务会进入 `failed`。关闭授权窗口、授权
超时或窗口启动失败都按拒绝处理。

Codex 使用 `--dangerously-bypass-hook-trust` 仅信任 CodeForge 动态注入的 Hook；
它不会绕过 Codex 的命令审批或 sandbox。实际动作仍由弹出的确认窗口决定。

## 配置

v0.1.1 的配置位于 `.agentforge/`：

- `config.yaml`：Codex/Claude Code 命令、超时、交互授权与测试命令。
- `workflow.yaml`：阶段说明和 `max_iterations`。
- `policies.yaml`：低/高风险执行器、保守默认值及高风险关键词。
- `roles/*.md`：四个角色的提示词和机器输出协议。

每个 executor 支持以下授权配置：

```json
{
  "interactive_approvals": true,
  "approval_timeout_seconds": 1800
}
```

设为 `false` 会恢复普通非交互执行，不再注入 CodeForge Hook。配置文件采用
JSON-compatible YAML（JSON 本身是合法 YAML），因此运行时不需要
额外 YAML 依赖。例如把所有实现任务路由到 Codex：

```json
{
  "implementation": {
    "low_risk": "codex",
    "high_risk": "codex",
    "default": "codex"
  }
}
```

默认策略优先采纳 Architect 声明的 `low`/`high` 风险；若没有有效声明，则用
关键词规则判断，无法判断时保守地选择 Codex。Reviewer 可将修复标为高风险，
使下一轮修复升级到 Codex。

## 当前限制

- Agent 直接修改当前工作目录，没有 Git worktree 或容器隔离。
- 工作流串行执行，不支持 agent 间自由通信或并行 agent。
- 上下文按角色裁剪，但依赖 Architect 正确列出相关文件。
- 配置只支持 JSON-compatible YAML，不支持 YAML 锚点等扩展语法。
- 交互授权需要桌面 Windows 会话；CI、SSH 或无头环境应关闭该功能并预先配置权限。
- Hook 处理工具权限请求，不处理 CLI 登录、账户验证或外部网页登录流程。
- v0.1.1 没有长期记忆、向量数据库、自动训练或模型 API 客户端。
- CLI 的具体参数可能随 Codex/Claude Code 版本变化，可在 `config.yaml` 调整。

## Roadmap

- Git worktree 隔离与更安全的变更基线
- 并行 agents 和更丰富的工作流阶段
- 更好的任务记忆与上下文预算
- 更多可替换 executors
- 更完善的结构化制品校验和失败恢复

## 开发验证

```powershell
python -m unittest discover -s tests -v
```
