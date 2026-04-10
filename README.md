# SuperWeb2PDF (s2p)

将全页网页截图转换为**智能分页** PDF —— 自动在空白区域分页，避免切断文字和图片。

## 为什么需要它？

普通的「截图转 PDF」工具要么把整张长图塞进一页，要么按固定高度硬切，经常把段落、表格拦腰斩断。`s2p` 会分析截图中的空白/背景带，在最佳位置分页，输出阅读体验接近原始网页的 PDF。

## 快速开始

```bash
# 克隆并安装（开发模式）
git clone https://github.com/<your-org>/SuperWeb2PDF.git
cd SuperWeb2PDF
pip install -e .

# 最简用法：一张长截图 → PDF
s2p --image screenshot.png

# 多张截图自动拼接 → PDF
s2p --images "captures/*.png" -o output.pdf

# macOS：直接抓取 Chrome 当前标签页
s2p --current-tab -o page.pdf --open
```

## 安装

### 基础安装

```bash
pip install -e .
```

依赖：**Pillow** ≥ 12.0、**reportlab** ≥ 4.0。Python ≥ 3.11。

### 可选依赖

```bash
# 未来 --url 无头浏览器模式
pip install -e ".[capture]"    # playwright

# 未来 --watch 文件夹监控模式
pip install -e ".[watch]"      # watchdog

# 全部可选依赖
pip install -e ".[all]"
```

## 使用示例

### 单张截图转 PDF

```bash
s2p --image full-page.png
# → full-page.pdf（自动命名）

s2p --image full-page.png -o report.pdf --paper letter
# → report.pdf，Letter 纸张尺寸
```

### 多张截图拼接

```bash
s2p --images "screenshots/page-*.png" -o combined.pdf
# 自然排序（page-2.png 排在 page-10.png 之前），拼接后分页
```

### 抓取 Chrome 当前标签页（macOS）

```bash
s2p --current-tab -o capture.pdf -v
# 自动滚动触发懒加载 → 逐屏截图 → 拼接 → 智能分页 → PDF
```

### 自动尺寸模式

```bash
s2p --image screenshot.png --auto-size
# 每页尺寸与内容完全匹配，不使用固定纸张
```

### 控制宽度与页高

```bash
s2p --image wide-page.png --max-width 1200 --max-height 2000
```

### 自定义纸张

```bash
s2p --image screenshot.png --paper 200x300
# 200mm × 300mm 自定义纸张
```

### 生成后自动打开（macOS）

```bash
s2p --image screenshot.png --open
```

### 无头浏览器抓取 URL

```bash
# 公开页面 — 自动启动 Chromium，滚动触发懒加载，全页截图
s2p --url https://example.com/article -o article.pdf

# 需要先安装浏览器：playwright install chromium
```

### CDP 模式 — 连接已运行的 Chrome

```bash
# 先启动带调试端口的 Chrome
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222

# 抓取指定 URL（使用已有 Chrome 的 cookie 和登录状态）
s2p --url https://private-page.com --cdp 9222 -o page.pdf

# 抓取当前页面（不指定 URL）
s2p --cdp 9222 -o current.pdf
```

### 文件夹监控模式

```bash
# 监控 inbox 文件夹，新图片自动转 PDF
s2p --watch ~/Screenshots/inbox -o ~/Screenshots/output

# 配合 Chrome 扩展使用：扩展保存截图到 inbox，s2p 自动处理
```

### Chrome 扩展（手动截图）

加载 `extension/` 目录为 Chrome 未打包扩展：

1. 打开 `chrome://extensions`
2. 启用「开发者模式」
3. 点击「加载已解压的扩展程序」→ 选择 `extension/` 文件夹
4. 点击扩展图标 → "Capture Full Page"
5. 截图保存到 Downloads，再用 `s2p --image` 处理

## CLI 参数参考

### 输入源（互斥，必选其一）

| 参数 | 说明 |
|------|------|
| `--image FILE` | 输入单张长截图 |
| `--images PATTERN` | 输入多张截图（glob 模式，如 `"*.png"`） |
| `--current-tab` | 抓取 Chrome 当前标签页（macOS，需配置权限） |
| `--url URL` | 无头浏览器抓取 URL（需 Playwright） |
| `--url URL --cdp PORT` | 通过 CDP 连接已有 Chrome 抓取 URL |
| `--cdp PORT` | 抓取 CDP Chrome 当前页面 |
| `--watch DIR` | 监控文件夹，自动转换新截图（需 watchdog） |

### 处理选项

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--paper SIZE` | `a4` | 纸张尺寸：`a4`、`a3`、`letter`、`legal` 或 `宽x高`（mm） |
| `--dpi N` | `150` | 输出 PDF 的 DPI |
| `--split MODE` | `smart` | 分页模式：`smart`（智能）、`fixed`（固定高度）、`none`（不分页） |
| `--blank-threshold N` | `10` | 空白检测颜色容差（0 = 完全匹配） |
| `--min-blank-band N` | `5` | 最小空白带高度（像素） |
| `--max-width PX` | — | 限制最大宽度（像素），等比缩放 |
| `--max-height PX` | — | 限制最大页高（像素） |
| `--scroll-delay MS` | `800` | 抓取模式的滚动延迟（毫秒） |
| `--auto-size` | — | 自动尺寸模式，每页匹配内容尺寸 |

### 输出选项

| 参数 | 说明 |
|------|------|
| `-o, --output FILE` | 输出 PDF 路径（不指定则自动命名） |
| `--open` | 生成后自动打开 PDF（macOS） |
| `-v, --verbose` | 显示详细处理进度 |

## 智能分页算法

`s2p` 的核心是 **smart split** 算法，流程如下：

1. **扫描空白带** — 逐行分析截图像素，找出连续的纯色/背景行（容差可调）。每隔 4 像素采样一次以提升性能。
2. **放置理想切割线** — 按 `max_page_height` 的整数倍放置理想分割点。
3. **搜索窗口** — 在每个理想点的 ±20%（`search_ratio`）范围内搜索候选空白带。
4. **评分** — 对窗口内每个空白带计算得分：`空白带高度 × 接近度权重`，接近度从理想点的 1.0 线性衰减到窗口边缘的 0.0。
5. **选取最优** — 取得分最高的空白带中心作为分割点；若窗口内无空白带，则在理想位置硬切（hard cut）。

这确保了分页尽可能落在段落间距、节标题上方等自然间隙处。

## 项目架构

```
superweb2pdf/
├── cli.py                  # CLI 入口与参数解析
├── capture/                # 截图采集层
│   ├── applescript.py      #   macOS Chrome 抓取（AppleScript + Quartz）
│   ├── file_input.py       #   本地文件/glob 输入
│   ├── headless.py         #   Playwright 无头 Chromium 抓取
│   ├── cdp.py              #   CDP 连接已有 Chrome
│   └── watcher.py          #   文件夹监控
└── core/                   # 处理核心
    ├── splitter.py         #   智能分页引擎
    ├── image_utils.py      #   图片加载、拼接、裁剪、缩放
    └── pdf_builder.py      #   PDF 生成（reportlab）

extension/                  # Chrome 截图扩展（MV3）
├── manifest.json
├── popup.html
└── popup.js
```

**数据流：**

```
输入源 → capture 层（加载/抓取） → PIL Image
     → 缩放（可选）→ splitter 分析分割点
     → image_utils 裁剪分页 → pdf_builder 生成 PDF
```

## `--current-tab` 模式前提条件

此模式仅限 **macOS**，需要以下配置：

1. **安装 Google Chrome** 并保持打开状态
2. **启用 AppleScript JS 执行**：Chrome → 视图 → 开发者 → 勾选「允许 Apple 事件中的 JavaScript」
3. **授予屏幕录制权限**：系统设置 → 隐私与安全性 → 屏幕录制 → 允许你的终端应用（Terminal / iTerm / VS Code 等）
4. **Chrome 窗口不能最小化**（Quartz 需要窗口可见）

工作原理：AppleScript 控制 Chrome 滚动页面 → Quartz `CGWindowListCreateImage` 逐屏截图 → 裁剪浏览器工具栏 → 拼接为完整长图。

## 开发

```bash
# 安装开发环境
git clone https://github.com/<your-org>/SuperWeb2PDF.git
cd SuperWeb2PDF
pip install -e ".[all]"

# 运行测试
python -m pytest tests/ -v

# 项目结构
# superweb2pdf/     — 主代码
# tests/            — 测试
# extension/        — 浏览器扩展（实验性）
# local/            — 本地参考资料
```

### 贡献指南

1. Fork 本仓库
2. 创建功能分支：`git checkout -b feature/your-feature`
3. 提交更改并推送
4. 发起 Pull Request

## 许可证

MIT License — 详见 [LICENSE](LICENSE) 文件。
