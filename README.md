# Comic Downloader Integrated

整合了两个漫画下载工作流：

1. `Comic-DL`：从多个在线漫画站点抓取章节并下载图片。
2. `GetComics Downloader`：从 `getcomics.org` 搜索条目并批量下载。

## 主要功能

- 支持 GUI 和命令行两种启动方式。
- Windows 下优先使用项目内 `venv`，避免把依赖装到系统 Python。
- `Comic-DL` 当前支持这些站点：
  - `readallcomics.com`
  - `readcomiconline.li`
  - `readcomicsonline.lol`
  - `readcomicsonline.ru`
  - `xoxocomic.com`
  - `batcave.biz`
- `GetComics Downloader` 支持：
  - 关键词搜索
  - 日期筛选
  - 结果数量切换
  - 上一页、下一页、跳页
  - 最近搜索记录
  - 自动恢复上次搜索条件和缓存结果
  - 结果详情页打开
  - 批量复制结果链接
  - 右键结果菜单
  - 收藏夹持久化
  - 收藏导入 / 导出 JSON
  - 下载队列持久化
  - 从队列批量下载
- 新增本地 `漫画阅读器`：
  - 扫描漫画目录
  - 查看 CBZ / ZIP / 图片文件夹
  - 显示页数、大小、修改时间、路径
  - 直接在 GUI 中翻页阅读
  - 记住上次目录、选中的漫画和阅读页码
  - 打开原文件和所在目录
- 支持 `aria2c` 加速下载。
- 支持 Playwright/Chromium 依赖自动安装。

## 快速开始

### 1. 安装依赖

首次使用，或把项目复制到新电脑后，请先运行：

```bat
install.bat
```

它会自动完成这些操作：

- 检查 Python 环境
- 创建或修复项目内虚拟环境 `venv`
- 安装 `requirements.txt` 中的依赖
- 安装 Playwright 所需的 Chromium

### 2. 启动程序

推荐直接运行：

```bat
run-gui.bat
```

如果想使用命令行版本：

```bat
run.bat
```

这两个脚本都会优先调用项目内 `venv\Scripts\python.exe`。

## 手动安装

如果你不想使用批处理脚本，也可以手动执行：

```bash
python -m venv venv
venv\Scripts\python.exe -m pip install -U pip
venv\Scripts\python.exe -m pip install -r requirements.txt
venv\Scripts\python.exe -m playwright install chromium
```

## GetComics 使用说明

1. 打开 `GetComics Downloader` 页面。
2. 输入搜索关键词，可选填写日期筛选。
3. 选择每页结果数量后开始搜索。
4. 通过 `上一页`、`下一页` 或 `跳转` 浏览结果。
5. 可对搜索结果执行这些操作：
   - 双击打开详情页
   - 批量复制链接
   - 加入收藏
   - 移出收藏
   - 加入队列
   - 移出队列
6. `查看收藏` 可以切换到收藏视图，收藏会写入 `.gui_state.json`。
7. `查看队列` 可以切换到下载队列视图，队列也会持久化保存。
8. `下载队列` 会按当前队列内容批量下载。

## Comic-DL 使用说明

1. 打开 `Comic-DL Downloader` 页面。
2. 输入漫画主页或章节链接。
3. 选择保存目录。
4. 获取章节信息。
5. 选择要下载的章节后开始下载。

## 漫画阅读器使用说明

1. 打开 `漫画阅读器` 页面。
2. 选择漫画根目录，或者直接选择单个 `CBZ` / `ZIP` 文件。
3. 点击 `刷新列表` 扫描本地漫画。
4. 在左侧列表选择条目后，可以先查看文件信息。
5. 点击 `开始阅读` 后可使用 `首页`、`上一页`、`下一页`、`末页` 和页码跳转阅读。
6. 支持 `Left` / `Right`、`PageUp` / `PageDown`、`Home` / `End` 快捷翻页。
7. `打开文件` 可用系统默认程序查看原文件，`打开所在目录` 可直接跳到本地位置。
8. 关闭后重新打开 GUI，会尽量恢复到上次阅读的位置。

## 未完成任务

- 阅读器图片缩放和“适应宽度 / 适应窗口”模式还没有加入。
- 双页阅读、连续滚动阅读模式还没有实现。
- 目前只记住当前一次阅读状态，还没有做到“按每本漫画分别保存进度”。
- 本地阅读器暂时只支持图片文件夹、`CBZ`、`ZIP`，`PDF`、`RAR`、`7z` 还未支持。
- 阅读器列表还没有搜索、筛选、排序切换等更完整的库管理功能。

## 目录结构

```text
comic-downloader-integrated-optimized/
├─ core/
│  ├─ browser_manager.py
│  ├─ cache.py
│  ├─ comic_downloader.py
│  ├─ comic_reader.py
│  ├─ download.py
│  ├─ getcomics_gui_helpers.py
│  ├─ getinfo.py
│  ├─ gui.py
│  ├─ gui_state.py
│  ├─ logger.py
│  ├─ main.py
│  ├─ menu.py
│  └─ series_downloader.py
├─ parsers/
│  ├─ batcave_biz_parser.py
│  ├─ readallcomics_parser.py
│  ├─ readcomiconline_li_parser.py
│  ├─ readcomicsonline_lol_parser.py
│  ├─ readcomicsonline_ru_parser.py
│  └─ xoxocomic_parser.py
├─ sites/
│  ├─ base.py
│  ├─ batcave.py
│  ├─ readallcomics.py
│  ├─ readcomiconline_li.py
│  ├─ readcomicsonline_lol.py
│  ├─ readcomicsonline_ru.py
│  ├─ registry.py
│  └─ xoxocomic.py
├─ tests/
├─ install.bat
├─ run-gui.bat
├─ run.bat
└─ README.md
```

## 常见问题

### GUI 提示缺少依赖

先重新运行：

```bat
install.bat
```

如果你之前是直接用系统 Python 安装依赖，建议删除旧的 `venv` 后重新安装一次。

### Playwright 无法启动

重新执行：

```bash
venv\Scripts\python.exe -m playwright install chromium
```

### aria2c 未生效

请确认 `aria2c.exe` 可用，并且已经放到系统 `PATH` 或项目可访问的位置。

## 测试

运行全部单元测试：

```bash
venv\Scripts\python.exe -m unittest discover -s tests
```

检查关键文件语法：

```bash
venv\Scripts\python.exe -m py_compile core\gui.py core\gui_state.py
```

## 说明

本项目基于原始的 Comic-DL 和 GetComics Downloader 思路整合而成，请仅在遵守目标站点条款和当地法律的前提下使用。
