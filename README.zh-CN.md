<div align="center">

<img src="assets/wordmark.png" alt="eDEX-Deck" width="640">

**给 [eDEX-UI](https://github.com/GitSquared/edex-ui) 加的一层非侵入式 UI**

重排布局、逐个开关面板、嵌入任意本地 Web UI —— **不改动它的任何一个文件**

[English](README.md) · 简体中文

</div>

---

## 为什么叫"非侵入"

eDEX-UI 已于 2021 年 10 月归档，内核停留在 Electron 12 / Chromium 89。想改它就得重建整个 renderer，而任何 fork 都会继承 GPL-3.0。

eDEX-Deck 反过来做 —— 通过 Chrome DevTools Protocol 驱动**正在运行**的实例：

| | |
|---|---|
| 安装目录里的文件 | **从不改动** |
| `settings.json` | **从不改动** |
| 实际改变的东西 | 启动参数 + 内存中的注入 |
| eDEX 退出之后 | **什么都不留** |

这也让本项目不含 eDEX-UI 的任何代码，因此可以用 MIT 授权。

---

## 截图

| 布局坞 | 模块开关 |
|---|---|
| ![dock](docs/screenshots/dock-peek.png) | ![modules](docs/screenshots/modules-panel.png) |

| `DEFAULT` | `COCKPIT` | `FOCUS` |
|---|---|---|
| ![default](docs/screenshots/layout-default.png) | ![cockpit](docs/screenshots/layout-cockpit.png) | ![focus](docs/screenshots/layout-focus.png) |

把无关的本地 Web UI 嵌进中央窗格：

![embedded](docs/screenshots/embed-demo.png)

---

## 特性

- **布局坞** —— 可拖动、可贴边吸附的悬浮控件
- **三套布局预设** —— `DEFAULT` / `COCKPIT`（面板全部集中左栏）/ `FOCUS`（终端优先）
- **逐模块开关** —— 11 个面板可独立显隐，与预设叠加生效
- **贴边隐藏** —— 吸附到屏幕边缘后收起为 9px 触发条，悬停滑出
- **嵌入任意本地 Web UI** —— 用 `BrowserView` 覆盖中央终端，跑什么由你定
- **自动补丁** —— 自动注入 ES2022 缺失 API，让现代 Web 应用跑在 Chromium 89 上
- **附带主题** —— `deck-teal` 青绿主题，附"从截图提取配色"的工具链

---

## 下载即用

每个 [Release](https://github.com/Docking666/edex-deck/releases) 都附预编译包，**已内置 Python** —— 你唯一需要装的就是 eDEX-UI 本身。

| 平台 | 文件 | 说明 |
|---|---|---|
| Windows | `edex-deck.exe` | 单文件，双击即可 |
| Windows | `edex-deck-portable-*.zip` | 文件夹版，启动更快 |
| macOS | `edex-deck.dmg` | |
| Linux | `edex-deck` | 先 `chmod +x` |

不带参数双击 = 注入布局坞并常驻，直到你关闭 eDEX。把 `edex-deck.json` 放在程序旁边即可使用 profile。

---

## 环境要求（从源码运行）

- 已安装 eDEX-UI **2.2.x**
- Python **3.8+**
- `pip install websocket-client`

---

## 快速开始

```bash
git clone https://github.com/<you>/edex-deck.git
cd edex-deck
pip install websocket-client

# 启动 eDEX 并注入布局坞
python src/inject.py
```

### 嵌入本地 Web UI

**任何能通过 HTTP 访问的界面都能嵌** —— VS Code（`code-server`）、Jupyter、Grafana、自研看板，都可以。仓库自带一个演示页，可以直接试：

```bash
# 起一个本地静态服务
python -m http.server 8898 --directory examples

# 另一个终端里嵌入它
python src/inject.py --url "http://127.0.0.1:8898/demo-ui.html"
```

若目标程序启动时会在 stdout 打印自己的 URL，也可以让注入器帮你拉起并自动抓取：

```bash
python src/inject.py --serve "mytool --serve --port 8898"
```

常驻服务则可以配成 profile（见下文），一条命令切换。

### Windows 一键启动

双击 **`launch.cmd`** —— 它会自动找 Python、缺依赖就装 `websocket-client`，然后带着布局坞启动 eDEX；你关闭 eDEX 时它自己退出。

想要带图标的桌面快捷方式：

```powershell
powershell -ExecutionPolicy Bypass -File tools\install-shortcut.ps1
```

`launch.cmd` 会把多余参数原样转给注入器，所以你可以再建一个专门嵌入某个 Web UI 的快捷方式：

```cmd
launch.cmd --url "http://127.0.0.1:8080"
```

### 常用参数

| 参数 | 作用 |
|---|---|
| `--edex <path>` | 指定 eDEX 可执行文件（否则自动探测） |
| `--keep` | 注入完不关闭 eDEX |
| `--no-layout` | 只嵌入 Web UI，不注入布局坞 |
| `--debug-port <n>` | 改 CDP 端口（默认 `9333`） |
| `--capture-docs` | 依次切换每个布局预设并截图到 `docs/screenshots/` |

---

## 布局坞用法

```
LAYOUT [DEFAULT] [COCKPIT] [FOCUS] | MODULES | PIN
```

- **拖动**到任意位置，位置记在 `localStorage`
- **`MODULES`** 展开模块开关：`PANEL` 组 9 个（`CLOCK` `SYSINFO` `HW` `CPU` `RAM` `PROC` `NETSTAT` `GLOBE` `TRAFFIC`），`DOCK` 组 2 个（`FILES` `KEYBOARD`）
- **每个 `PANEL` 模块后面有个位置徽标** —— `L` 左栏 / `R` 右栏 / `D` 底部条。点徽标就能把模块搬过去，两侧栏位、底部条和终端会跟着重新排布；某栏被搬空后会自动收起，不留一个空标题

也就是说这里不只是"开关"，**底部条是一个真正可用的槽位**，任何模块都能停在那里。当你用一个把屏幕大部分让给终端的布局、又希望保留几个仪表时，这条特别顺手。

举例：`COCKPIT` 把面板全集中到左栏并隐藏键盘，此时你可以把 `NETSTAT`、`TRAFFIC`、`GLOBE`、`CPU` 一起搬到下方，终端会自动收缩让出空间。
- **`PIN`** 开启贴边吸附：拖到屏幕边缘松手即收起，鼠标悬停滑出
- **双击**控件 = 取消吸附 + 回到右下角

**预设管"怎么排"，模块开关管"显示什么"**，两者叠加。例如 `FOCUS` + 只留 `CPU`/`RAM`/`NETSTAT`，就是一个极简监视台。

---

## 主题

`src/themes/deck-teal.json` 是配套主题（青绿 + 纯黑，标签文字降为中性灰，只让数据带颜色）。

```bash
# Windows
copy src\themes\deck-teal.json "%APPDATA%\eDEX-UI\themes\"

# macOS / Linux
cp src/themes/deck-teal.json ~/.config/eDEX-UI/themes/
```

然后把 `settings.json` 里的 `"theme"` 改成 `"deck-teal"`。

> ⚠️ `settings.json` **不一定是 UTF-8**（可能含本地编码的文本）。`tools/apply_theme.py` 全程按二进制 + 正则改字段，**不做 JSON 解析重写**，避免把其他字段弄成乱码。

### 用截图生成自己的主题

```bash
python tools/palette.py shot.png          # 输出主色分布 + 关键采样点
python tools/preview_theme.py mytheme     # 临时切换预览，结束后自动还原
```

`tools/palette.py` **零依赖** —— 纯 `zlib` + 手写反滤波解码 PNG。

---

## 工作原理

```
1. 带 --remote-debugging-port 启动 eDEX
2. GET /json/list           -> 定位 renderer target（ui.html）
3. 轮询等待界面构建完成（eDEX 的主界面全部由 JS 动态生成）
4. Runtime.evaluate：
     - 为嵌入的 Web UI 创建 BrowserView        （可选）
     - 给它装上 polyfill                      （可选）
     - 注入布局坞
5. 截图 / 退出
```

几个踩过的坑与对策：

| 问题 | 对策 |
|---|---|
| shell 里存在 `ELECTRON_RUN_AS_NODE` 时，Electron 二进制会退化成纯 Node，拒绝所有 `--参数` | 启动前清掉相关环境变量 |
| eDEX 的 CSP（`default-src file:`）会拦 `http` iframe | 改用 `BrowserView`（独立 `webContents`，不受宿主 CSP 约束） |
| 现代 Web UI 依赖较新的 Chromium API（`Object.hasOwn` 等） | 在页面脚本执行前用 `Page.addScriptToEvaluateOnNewDocument` 注入 polyfill |
| `#main_shell` 有 `.5s` 尺寸过渡 | 布局切换后延迟 ~620ms 再重新对齐嵌入视图的 bounds |
| 更新检查器离线时抛错并弹窗挡住界面 | 定时守卫持续清理 |

---

## 已知限制

- **Windows**：eDEX 无法追踪终端工作目录，文件浏览器始终停留在游离状态。这是上游限制（界面会显示 `TRACKING FAILED`）。
- **`COCKPIT` 预设会隐藏文件浏览器**：eDEX 的文件网格在容器尺寸变化后就不出内容，与其留一个空框，不如把空间让给终端。
- 布局坞是**运行时注入**的，每次启动 eDEX 都需要重新注入。若希望开机即生效，可把布局 CSS 写进主题的 `injectCSS` 字段（代价是失去交互控件）。
- 仅在 Windows 上的 eDEX-UI 2.2.8 / Electron 12.2.2 验证过。换版本可能需要更新选择器 —— `tools/dump_modules.py` 会打印运行实例中实际存在的模块 ID。

---

## 与官方无关

eDEX-Deck 是一个独立的非官方工具，与 eDEX-UI 项目及其作者无隶属或背书关系。eDEX-UI 本身以 **GPL-3.0** 授权；本项目不含其任何代码，仅在运行时与之交互。

---

## 许可证

[MIT](LICENSE)
