# Comic Downloader Integrated

这是一个整合了两个漫画下载工具的项目：
1. Comic-DL - 从多个漫画网站下载漫画
2. GetComics Downloader - 从 getcomics.org 下载漫画

## 功能特性

- **GetComics 下载器**：从 getcomics.org 搜索和下载漫画
- **Comic-DL 下载器**：从多个漫画网站下载漫画，支持以下网站：
  - readallcomics.com
  - readcomiconline.li
  - readcomicsonline.ru
  - xoxocomic.com
  - batcave.biz
- **统一的菜单界面**：方便用户选择使用哪个下载器
- **支持 aria2c 下载**：提供更快的下载速度
- **缓存功能**：提高搜索和下载效率

## 快速开始

### 1. 环境准备 (仅需一次)

如果你是第一次在电脑上使用，或者刚把项目拷贝到新电脑，请双击运行：

`install.bat`

该脚本会自动完成以下操作：
- 检查并配置 Python 环境。
- 创建虚拟环境 (`venv`) 以保持系统整洁。
- 安装所有必需的依赖库（包括 `aiohttp`, `playwright`, `requests-toolbelt` 等）。
- 下载并安装 Playwright 浏览器内核 (Chromium)。

**注意**：脚本已优化为支持 UTF-8 编码，确保在中文 Windows 环境下稳定运行。

### 2. 启动程序

- **GUI 图形界面版 (推荐)**：双击 `run-gui.bat`
- **命令行版**：双击 `run.bat`

---

## 安装依赖 (手动方式)

如果你不想使用 `install.bat`，也可以手动配置：

1. 确保安装了 Python 3.10 或更高版本。
2. 安装所需的依赖包：
   ```bash
   pip install -r requirements.txt
   ```
3. 安装浏览器内核：
   ```bash
   playwright install chromium
   ```

## 跨电脑迁移指南

本项目支持“文件夹级”的无缝迁移。只需将整个项目文件夹拷贝到新电脑，然后运行 `install.bat` 即可快速恢复运行环境。

## 使用指南

1. 启动程序后，会显示主菜单，选择要使用的下载器：
   - 1: GetComics Downloader - 从 getcomics.org 下载漫画
   - 2: Comic-DL Downloader - 从多个网站下载漫画
   - 3: 退出程序

2. **GetComics Downloader 使用**：
   - 输入搜索关键词
   - 选择要下载的漫画
   - 等待下载完成

3. **Comic-DL Downloader 使用**：
   - 输入漫画的 URL
   - 选择保存目录
   - 等待下载完成

## 配置选项

在使用 GetComics Downloader 时，可以通过选项菜单设置：
- 下载目录
- 结果数量
- 是否使用 aria2c 下载
- 其他选项

## 注意事项

- 确保网络连接正常
- 对于某些网站，可能需要安装 Playwright 浏览器驱动：
  ```bash
  playwright install
  ```
- aria2c 下载需要 aria2c 可执行文件，可从官方网站下载并放在项目根目录

## 项目结构

```
comic-downloader-integrated/
├── core/
│   ├── main.py          # 主程序入口
│   ├── comic_downloader.py  # Comic-DL 下载器
│   ├── browser_manager.py   # 浏览器管理器
│   ├── getinfo.py        # GetComics 信息获取
│   ├── download.py       # 下载功能
│   ├── menu.py           # 菜单界面
│   ├── logger.py         # 日志功能
│   └── cache.py          # 缓存功能
├── sites/
│   ├── registry.py       # 站点注册表
│   ├── batcave.py        # BatCave 站点模块
│   ├── readallcomics.py  # ReadAllComics 站点模块
│   ├── readcomiconline_li.py  # ReadComicOnline.li 站点模块
│   ├── readcomicsonline_ru.py  # ReadComicsOnline.ru 站点模块
│   └── xoxocomic.py      # XoxoComic 站点模块
├── parsers/
│   ├── __init__.py
│   ├── base_parser.py    # 解析器基类
│   ├── batcave_biz_parser.py  # batcave.biz 解析器
│   ├── readallcomics_parser.py  # readallcomics.com 解析器
│   ├── readcomiconline_li_parser.py  # readcomiconline.li 解析器
│   ├── readcomicsonline_ru_parser.py  # readcomicsonline.ru 解析器
│   └── xoxocomic_parser.py  # xoxocomic.com 解析器
├── run.bat              # 运行脚本
└── README.md            # 说明文档
```

## 许可证

本项目基于原始的 Comic-DL 和 GetComics Downloader 项目，保留其各自的许可证。
