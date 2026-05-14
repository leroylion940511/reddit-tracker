# Global AGENTS Draft

## Project State

- Always read `PROGRESS.md` at session start — it is the single source of truth for what's done, what's in progress, the immediate next step, and gotchas. Update it whenever the state actually changes (not every commit).

## Working Style

- Prefer concise, actionable answers. State the conclusion first, then add only the necessary explanation.
- When multiple reasonable options exist, choose the most practical default instead of presenting every option.
- For low-risk actions, proceed directly. For high-risk or destructive actions, warn clearly before proceeding.
- Do not guess when local context can be checked. Inspect the machine, project files, and environment first.
- Favor concrete execution over abstract discussion. Give commands, edits, and next steps that can be used immediately.

## Task Execution

- Break larger tasks into smaller executable steps and keep momentum toward completion.
- Help narrow scope and reduce unnecessary branching. Prefer finishing the current path over opening new work.
- If the current approach is inefficient or clearly off-track, say so directly and propose a better path.
- End substantial work with a clear next step or priority recommendation.

## Local Environment Defaults

- Primary local root: `/Users/leroy/local`
- Developer workspace root: `/Users/leroy/local/Developer`
- Documents root: `/Users/leroy/local/Developer/Docs`
- Preferred editor: VS Code

## Language And Tooling Defaults

### Python

- For small scripts, use `python3`.
- For new or serious projects, use `uv` with a local `.venv`.
- Prefer `uv init`, `uv venv`, `uv add`, `uv sync`, and `uv run`.
- Avoid global `pip3 install` and avoid ad-hoc `venv` workflows unless the project already depends on them.

### Node.js

- Use Homebrew-managed `node` and `npm`.
- Global CLI tools should live under `~/.npm-global`.
- Do not introduce `fnm`, `volta`, or `asdf` unless the project already requires them.
- `pnpm` is acceptable when the project already uses it, but the default baseline is Homebrew `node` and `npm`.

### Java

- Default JDK is 17.
- Use JDK 21 only when a project explicitly requires it.
- Keep JDK 8 limited to legacy projects.

### Rust

- Default to the Homebrew Rust toolchain.
- Only introduce `rustup` or multi-toolchain management when the project actually needs it.

### Ruby

- Do not use system Ruby for real project work.
- If Ruby project work is needed, prefer setting up an isolated version manager workflow.

### .NET

- New repositories should include `global.json`.

### Docker

- Docker Desktop is the default container runtime.
- When container behavior changes, verify the current Docker context.

## Collaboration Preferences

- Prioritize coding help, AI agent implementation, local machine operations, automation work, and project organization.
- Provide explicit priorities when there are too many possible directions.
- For long or messy tasks, split work into small finishable chunks.
- Prefer guidance that helps close loops and finish work instead of expanding the task list.

## Decision Rules

- Align technical suggestions with the existing macOS setup, installed tools, and established filesystem layout.
- Prefer project-local dependencies over global installs.
- Keep one main toolchain path per language unless there is a strong reason not to.
- Before changing shell configuration or environment defaults, be conservative and verify impact.
