<p align="center">
  <img src="clawome.png" alt="Clawome" width="200" />
</p>

<h1 align="center">Clawome</h1>

<p align="center">
  <strong>一次 API 调用，搞定任何网页任务。</strong><br/>
  给你的 AI 智能体一个自然语言目标 — Clawome 自动规划、浏览并返回结构化结果。
</p>

<p align="center">
  <a href="#任务智能体-api">任务智能体 API</a> &bull;
  <a href="#快速开始">快速开始</a> &bull;
  <a href="#dom-压缩">DOM 压缩</a> &bull;
  <a href="#性能基准">性能基准</a> &bull;
  <a href="#路线图">路线图</a>
</p>

---

## 任务智能体 API

一个 POST 请求，Clawome 处理剩下的一切 — 规划子任务、控制浏览器、读取页面并返回结果。

```bash
curl -X POST http://localhost:5001/api/agent/start \
  -H "Content-Type: application/json" \
  -d '{"description": "查找纽约大学 Tandon 工程学院的 AI 相关研究生项目"}'
```

轮询进度：

```bash
curl http://localhost:5001/api/agent/status
```

```json
{
  "status": "completed",
  "final_result": "NYU Tandon 提供以下 AI 相关项目：...",
  "subtasks": [
    {"step": 1, "goal": "访问 NYU Tandon 网站", "status": "completed"},
    {"step": 2, "goal": "提取项目列表", "status": "completed"}
  ],
  "llm_usage": {"calls": 12, "input_tokens": 25000, "total_tokens": 28000}
}
```

需要时可取消：

```bash
curl -X POST http://localhost:5001/api/agent/stop
```

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/agent/start` | 提交任务（自然语言） |
| GET | `/api/agent/status` | 轮询进度、子任务和结果 |
| POST | `/api/agent/stop` | 取消正在运行的任务 |

**启动参数：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `task` | string | 任务描述（必填） |
| `max_steps` | number | 覆盖此任务的步数上限（默认：15） |

**状态值：** `idle` → `starting` → `running` → `completed` / `failed` / `cancelled`

### 任务编写技巧

```
差：  "打开深圳大学网站看看有什么内容"
好：  "打开 https://www.szu.edu.cn 首页，提取导航栏、最新3条新闻和通知公告"
```

- **给出 URL** — 避免让智能体猜测要去哪里
- **指定提取内容** — "最新5条新闻" 比 "所有新闻" 更好
- **复杂任务？增加步数** — `"max_steps": 30` 适用于多页面任务
- **或者拆分为小任务** — 每个任务聚焦一个页面或一个目标

### 工作原理

```
你的 API 调用 → 任务智能体 → 规划子任务 → 执行浏览器操作 → 返回结果
                                  ↑                                  |
                                  └── 评估并按需重新规划 ─────────────┘
```

智能体内部使用 LangGraph 状态机：感知页面 → 规划下一步 → 执行操作 → 感知结果 → 循环直到完成。

### 特性
- **自然语言任务** — 用自然语言描述你想要的
- **多步规划** — 自动将复杂任务分解为子任务
- **智能执行** — 感知 → 规划 → 行动 → 感知循环，支持重试和异常检测
- **Markdown 结果** — 最终结果以 Markdown 格式输出，包含结构化数据
- **12+ LLM 供应商** — OpenAI、Anthropic、Google、DeepSeek、通义千问、Moonshot、智谱、Mistral、Groq、xAI 等
- **安全约束** — 仅限浏览器操作，硬性步数限制

---

## DOM 压缩

在底层，任务智能体通过 Clawome 的 DOM 压缩器来感知网页 — 将 30 万 token 的原始 HTML 压缩到约 3000 token 的简洁结构化树。

**你也可以直接使用它**，作为独立 API 为你自己的智能体服务：

```bash
# 打开页面
curl -X POST http://localhost:5001/api/browser/open \
  -d '{"url": "https://www.google.com"}'

# 读取压缩后的 DOM
curl http://localhost:5001/api/browser/dom
```

```
[1] form(role="search")
  [1.1] textarea(name="q", placeholder="Search")
  [1.2] button: Google Search
  [1.3] button: I'm Feeling Lucky
[2] a(href): About
[3] a(href): Gmail
```

- **100:1 压缩比** — 适用于典型网页
- 保留可见文本、交互元素和语义结构
- 层级节点 ID（如 `1.2.3`）用于精确元素定位
- 针对 Google、Wikipedia、Stack Overflow、YouTube 等网站的专用优化器
- Lite 模式可进一步节省 token

### 控制面板
- **浏览器实验场** — 交互式 DOM 查看器和浏览器控制
- **智能体界面** — 任务输入、实时进度追踪、可折叠的步骤详情
- **设置** — LLM 供应商配置、浏览器选项、压缩设置
- **API 文档** — 内置文档，支持中英双语

## 快速开始

**前置条件：** Python 3.10+ / Node.js 18+

```bash
git clone https://github.com/CodingLucasLi/Clawome.git
cd Clawome
cp .env.example .env       # 填入你的 LLM API 密钥
./start.sh                 # 搞定！
```

首次运行会自动创建虚拟环境、安装依赖并下载 Chromium。后续运行跳过安装，即时启动。

```
控制面板：http://localhost:5173
API：     http://localhost:5001
```

> 如果你只使用 DOM 压缩 API，`.env` 是可选的。

### CLI 工具

安装 CLI 后可直接在终端运行任务：

```bash
pip install -e .           # 从项目根目录安装

clawome "去Hacker News找最新AI新闻"          # 提交任务并自动轮询
clawome status                               # 查看进度
clawome stop                                 # 取消任务
clawome "complex task" --max-steps 30        # 覆盖步数上限
```

<details>
<summary><strong>单独启动后端或前端</strong></summary>

```bash
./start-backend.sh         # 仅 API 服务 → http://localhost:5001
./start-frontend.sh        # 仅控制面板  → http://localhost:5173
```

</details>

<details>
<summary><strong>手动安装</strong></summary>

```bash
# 后端
cd backend
python -m venv venv
source venv/bin/activate    # Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
python app.py               # http://localhost:5001

# 前端（在另一个终端）
cd frontend
npm install
npm run dev                 # http://localhost:5173
```

</details>

## 完整 API 参考

<details>
<summary><strong>浏览器 API</strong> — 导航、DOM、交互（任务智能体内部使用，也可独立调用）</summary>

### 导航

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/browser/open` | 打开 URL（如需要会启动浏览器） |
| POST | `/api/browser/back` | 后退 |
| POST | `/api/browser/forward` | 前进 |
| POST | `/api/browser/refresh` | 刷新页面 |

### DOM

| 方法 | 端点 | 说明 |
|------|------|------|
| GET/POST | `/api/browser/dom` | 获取压缩后的 DOM 树 |
| POST | `/api/browser/dom/detail` | 获取元素详情（位置、属性） |
| POST | `/api/browser/text` | 获取节点的纯文本内容 |
| GET | `/api/browser/source` | 获取原始页面 HTML |

### 交互

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/browser/click` | 点击元素 |
| POST | `/api/browser/type` | 输入文本（键盘事件） |
| POST | `/api/browser/fill` | 填充输入框 |
| POST | `/api/browser/select` | 选择下拉选项 |
| POST | `/api/browser/check` | 切换复选框 |
| POST | `/api/browser/hover` | 悬停元素 |
| POST | `/api/browser/scroll/down` | 向下滚动 |
| POST | `/api/browser/scroll/up` | 向上滚动 |
| POST | `/api/browser/keypress` | 按键 |
| POST | `/api/browser/hotkey` | 组合键 |

### Token 优化

所有操作端点支持可选参数以减少响应体积：

- `refresh_dom: false` — 操作后跳过 DOM 刷新（节省 token）
- `fields: ["dom", "stats"]` — 仅返回选定字段

</details>

## 性能基准

| 页面 | 原始 HTML | 压缩后 | 节省 | 完整度 |
|------|----------:|-------:|-----:|:------:|
| Google 首页 | 51K | 238 | 99.5% | 100% |
| Google 搜索 | 298K | 2,866 | 99.0% | 100% |
| Wikipedia 文章 | 225K | 40K | 82.1% | 99.7% |
| 百度首页 | 192K | 457 | 99.8% | 100% |
| 百度搜索 | 390K | 4,960 | 98.7% | 100% |

> **完整度** = 压缩树中保留的可见文本百分比。

## 支持的 LLM 供应商

| 供应商 | 模型示例 |
|--------|----------|
| 通义千问 (DashScope) | qwen-plus, qwen-max, qwen3.5-plus |
| OpenAI | gpt-4o, gpt-4o-mini |
| Anthropic | claude-sonnet-4-20250514, claude-haiku |
| Google | gemini-2.0-flash, gemini-pro |
| DeepSeek | deepseek-chat, deepseek-reasoner |
| Mistral | mistral-large-latest |
| Groq | llama-3.1-70b |
| xAI | grok-2 |
| Moonshot | moonshot-v1-8k |
| 智谱 AI | glm-4 |
| 自定义 | 任何 OpenAI 兼容端点 |

## 路线图

- [x] DOM 压缩 API，支持可插拔的站点专用脚本
- [x] 任务智能体，支持多步规划和自主浏览
- [x] 多供应商 LLM 支持（12+ 供应商）
- [x] 中英双语控制面板
- [ ] MCP（模型上下文协议）服务器集成
- [ ] 视觉定位 — 基于截图的元素定位
- [ ] 多智能体协作

## 第三方库

| 库 | 许可证 | 用途 |
|----|--------|------|
| [Playwright](https://github.com/microsoft/playwright) | Apache 2.0 | 浏览器自动化 |
| [Flask](https://github.com/pallets/flask) | BSD 3-Clause | REST API 服务器 |
| [React](https://github.com/facebook/react) | MIT | 前端界面 |
| [LangGraph](https://github.com/langchain-ai/langgraph) | MIT | 智能体工作流引擎 |
| [LiteLLM](https://github.com/BerriAI/litellm) | MIT | 多供应商 LLM 路由 |
| [Pydantic](https://github.com/pydantic/pydantic) | MIT | 数据校验 |

## 许可证

Apache License 2.0 - 详见 [LICENSE](LICENSE)。
