import os
import sys
import zipfile
import concurrent.futures
import logging
import json

# Add the parent directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sites.registry import SITE_MODULES, get_site_module

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ComicDownloader:
    def __init__(self):
        # 基础保存目录
        self.base_dir = os.path.join(os.path.expanduser("~"), "Documents", "Comics")
        # 确保保存目录存在
        os.makedirs(self.base_dir, exist_ok=True)
        self.project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.site_overrides_path = os.path.join(self.project_dir, ".site_overrides.json")
        
        # 网站下载模块注册表
        self.site_modules = list(SITE_MODULES)
        self.parsers = {site.key: site.create_parser() for site in self.site_modules}
        self.site_overrides = self.load_site_overrides()

    @staticmethod
    def _coerce_positive_int(value, default):
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _coerce_non_negative_float(value, default):
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _normalize_chapter_failure_policy(value, default="continue"):
        normalized = str(value or "").strip().lower()
        if normalized in {"continue", "stop"}:
            return normalized
        return default
    
    def set_base_dir(self, base_dir):
        """设置基础保存目录"""
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)
    
    def get_parser(self, url):
        """根据 URL 获取对应的解析器"""
        site_module = self.get_site_module(url)
        if site_module:
            return self.parsers.get(site_module.key)

        for domain, parser in self.parsers.items():
            if domain in (url or ""):
                return parser
        return None

    def get_site_module(self, url):
        site_module = get_site_module(url)
        if site_module:
            return site_module

        if not hasattr(self, "parsers"):
            return None

        for domain in self.parsers.keys():
            if domain in (url or ""):
                return type(
                    "FallbackSiteModule",
                    (),
                    {
                        "key": domain,
                        "resolve_chapter_url": staticmethod(lambda base_url, chapter_url: chapter_url),
                    },
                )()

        return None

    def get_site_module_by_key(self, key):
        if not key:
            return None

        for site in getattr(self, "site_modules", ()):
            if getattr(site, "key", None) == key:
                return site
        return None

    def _build_site_description(self, site_module):
        if not site_module:
            return None

        display_name = getattr(site_module, "display_name", None) or getattr(site_module, "key", "Unknown Site")
        key = getattr(site_module, "key", display_name)
        domains = tuple(getattr(site_module, "domains", ()) or ())
        default_max_workers = self._coerce_positive_int(getattr(site_module, "default_max_workers", 6), 6)
        default_max_retries = self._coerce_positive_int(getattr(site_module, "default_max_retries", 3), 3)
        default_download_delay = self._coerce_non_negative_float(getattr(site_module, "default_download_delay", 0.1), 0.1)
        default_request_timeout = self._coerce_non_negative_float(getattr(site_module, "default_request_timeout", 30.0), 30.0)
        default_chapter_failure_policy = self._normalize_chapter_failure_policy(
            getattr(site_module, "default_chapter_failure_policy", "continue"),
            "continue",
        )
        override_max_workers = self.get_site_override_max_workers(key)
        override_max_retries = self.get_site_override_max_retries(key)
        override_download_delay = self.get_site_override_download_delay(key)
        override_request_timeout = self.get_site_override_request_timeout(key)
        override_chapter_failure_policy = self.get_site_override_chapter_failure_policy(key)
        effective_max_workers = override_max_workers if override_max_workers is not None else default_max_workers
        effective_max_retries = override_max_retries if override_max_retries is not None else default_max_retries
        effective_download_delay = (
            override_download_delay if override_download_delay is not None else default_download_delay
        )
        effective_request_timeout = (
            override_request_timeout if override_request_timeout is not None else default_request_timeout
        )
        effective_chapter_failure_policy = (
            override_chapter_failure_policy
            if override_chapter_failure_policy is not None
            else default_chapter_failure_policy
        )
        return {
            "key": key,
            "display_name": display_name,
            "domains": domains,
            "default_max_workers": default_max_workers,
            "default_max_retries": default_max_retries,
            "default_download_delay": default_download_delay,
            "default_request_timeout": default_request_timeout,
            "default_chapter_failure_policy": default_chapter_failure_policy,
            "override_max_workers": override_max_workers,
            "override_max_retries": override_max_retries,
            "override_download_delay": override_download_delay,
            "override_request_timeout": override_request_timeout,
            "override_chapter_failure_policy": override_chapter_failure_policy,
            "max_workers": effective_max_workers,
            "max_retries": effective_max_retries,
            "download_delay": effective_download_delay,
            "request_timeout": effective_request_timeout,
            "chapter_failure_policy": effective_chapter_failure_policy,
            "has_override": any(
                value is not None
                for value in (
                    override_max_workers,
                    override_max_retries,
                    override_download_delay,
                    override_request_timeout,
                    override_chapter_failure_policy,
                )
            ),
            "requires_browser": bool(getattr(site_module, "requires_browser", False)),
            "notes": getattr(site_module, "notes", "") or "",
        }

    def get_supported_sites(self):
        return tuple(self.site_modules)

    def describe_site(self, url):
        site_module = self.get_site_module(url)
        return self._build_site_description(site_module)

    def describe_site_by_key(self, key):
        return self._build_site_description(self.get_site_module_by_key(key))

    def get_supported_sites_summary(self):
        parts = []
        for site in self.get_supported_sites():
            site_info = self._build_site_description(site)
            domains = ", ".join(site_info["domains"]) or site_info["key"]
            worker_text = f"当前并发 {site_info['max_workers']}"
            if site_info["has_override"]:
                worker_text += f"（覆盖默认 {site_info['default_max_workers']}）"
            else:
                worker_text = f"默认并发 {site_info['default_max_workers']}"
            browser_tag = "，浏览器辅助" if site_info["requires_browser"] else ""
            parts.append(f"{site_info['display_name']} ({domains}，{worker_text}{browser_tag})")
        return "\n".join(parts)

    def get_default_max_workers(self, url):
        site_info = self.describe_site(url)
        if not site_info:
            return 6
        return max(1, int(site_info["max_workers"]))

    def get_default_max_retries(self, url):
        site_info = self.describe_site(url)
        if not site_info:
            return 3
        return max(1, int(site_info["max_retries"]))

    def get_default_download_delay(self, url):
        site_info = self.describe_site(url)
        if not site_info:
            return 0.1
        return max(0.0, float(site_info["download_delay"]))

    def get_default_request_timeout(self, url):
        site_info = self.describe_site(url)
        if not site_info:
            return 30.0
        return max(0.0, float(site_info["request_timeout"]))

    def get_default_chapter_failure_policy(self, url):
        site_info = self.describe_site(url)
        if not site_info:
            return "continue"
        return self._normalize_chapter_failure_policy(site_info["chapter_failure_policy"], "continue")

    def load_site_overrides(self):
        overrides = {}
        path = getattr(self, "site_overrides_path", None)
        if not path or not os.path.exists(path):
            return overrides

        try:
            with open(path, "r", encoding="utf-8") as file_handle:
                payload = json.load(file_handle)
        except Exception as exc:
            logger.warning("Failed to load site overrides: %s", exc)
            return overrides

        site_payload = payload.get("sites", payload) if isinstance(payload, dict) else {}
        if not isinstance(site_payload, dict):
            return overrides

        for key, config in site_payload.items():
            if not self.get_site_module_by_key(key) or not isinstance(config, dict):
                continue
            normalized = {}

            max_workers = config.get("max_workers")
            if max_workers is not None:
                try:
                    normalized["max_workers"] = max(1, int(max_workers))
                except (TypeError, ValueError):
                    logger.warning("Ignoring invalid max_workers override for %s", key)

            max_retries = config.get("max_retries")
            if max_retries is not None:
                try:
                    normalized["max_retries"] = max(1, int(max_retries))
                except (TypeError, ValueError):
                    logger.warning("Ignoring invalid max_retries override for %s", key)

            download_delay = config.get("download_delay")
            if download_delay is not None:
                try:
                    normalized["download_delay"] = max(0.0, float(download_delay))
                except (TypeError, ValueError):
                    logger.warning("Ignoring invalid download_delay override for %s", key)

            request_timeout = config.get("request_timeout")
            if request_timeout is not None:
                try:
                    normalized["request_timeout"] = max(0.0, float(request_timeout))
                except (TypeError, ValueError):
                    logger.warning("Ignoring invalid request_timeout override for %s", key)

            chapter_failure_policy = config.get("chapter_failure_policy")
            if chapter_failure_policy is not None:
                normalized_policy = self._normalize_chapter_failure_policy(chapter_failure_policy, "")
                if normalized_policy:
                    normalized["chapter_failure_policy"] = normalized_policy
                else:
                    logger.warning("Ignoring invalid chapter_failure_policy override for %s", key)

            if normalized:
                overrides[key] = normalized

        return overrides

    def save_site_overrides(self):
        path = getattr(self, "site_overrides_path", None)
        if not path:
            return False

        payload = {"sites": getattr(self, "site_overrides", {})}
        try:
            with open(path, "w", encoding="utf-8") as file_handle:
                json.dump(payload, file_handle, indent=2, ensure_ascii=False)
            return True
        except Exception as exc:
            logger.error("Failed to save site overrides: %s", exc)
            return False

    def get_site_override(self, key):
        overrides = getattr(self, "site_overrides", {}) or {}
        value = overrides.get(key)
        return dict(value) if isinstance(value, dict) else None

    def get_site_override_max_workers(self, key):
        override = self.get_site_override(key)
        if not override:
            return None
        max_workers = override.get("max_workers")
        if max_workers is None:
            return None
        try:
            return max(1, int(max_workers))
        except (TypeError, ValueError):
            return None

    def get_site_override_max_retries(self, key):
        override = self.get_site_override(key)
        if not override:
            return None
        max_retries = override.get("max_retries")
        if max_retries is None:
            return None
        try:
            return max(1, int(max_retries))
        except (TypeError, ValueError):
            return None

    def get_site_override_download_delay(self, key):
        override = self.get_site_override(key)
        if not override:
            return None
        download_delay = override.get("download_delay")
        if download_delay is None:
            return None
        try:
            return max(0.0, float(download_delay))
        except (TypeError, ValueError):
            return None

    def get_site_override_request_timeout(self, key):
        override = self.get_site_override(key)
        if not override:
            return None
        request_timeout = override.get("request_timeout")
        if request_timeout is None:
            return None
        try:
            return max(0.0, float(request_timeout))
        except (TypeError, ValueError):
            return None

    def get_site_override_chapter_failure_policy(self, key):
        override = self.get_site_override(key)
        if not override:
            return None
        chapter_failure_policy = override.get("chapter_failure_policy")
        if chapter_failure_policy is None:
            return None
        normalized = self._normalize_chapter_failure_policy(chapter_failure_policy, "")
        return normalized or None

    def set_site_override(
        self,
        key,
        max_workers=None,
        max_retries=None,
        download_delay=None,
        request_timeout=None,
        chapter_failure_policy=None,
    ):
        if not self.get_site_module_by_key(key):
            raise ValueError(f"Unknown site key: {key}")

        payload = {}
        if max_workers is not None:
            payload["max_workers"] = max(1, int(max_workers))
        if max_retries is not None:
            payload["max_retries"] = max(1, int(max_retries))
        if download_delay is not None:
            payload["download_delay"] = max(0.0, float(download_delay))
        if request_timeout is not None:
            payload["request_timeout"] = max(0.0, float(request_timeout))
        if chapter_failure_policy is not None:
            normalized_policy = self._normalize_chapter_failure_policy(chapter_failure_policy, "")
            if not normalized_policy:
                raise ValueError(f"Unsupported chapter failure policy: {chapter_failure_policy}")
            payload["chapter_failure_policy"] = normalized_policy
        if not payload:
            raise ValueError("No site override values were provided")

        overrides = dict(getattr(self, "site_overrides", {}) or {})
        existing = dict(overrides.get(key, {}) or {})
        existing.update(payload)
        overrides[key] = existing
        self.site_overrides = overrides
        if not self.save_site_overrides():
            raise RuntimeError("Failed to save site overrides")
        return self.describe_site_by_key(key)

    def reset_site_override(self, key):
        overrides = dict(getattr(self, "site_overrides", {}) or {})
        if key in overrides:
            overrides.pop(key, None)
            self.site_overrides = overrides
            if not self.save_site_overrides():
                raise RuntimeError("Failed to save site overrides")
        return self.describe_site_by_key(key)

    def resolve_chapter_url(self, base_url, chapter_url):
        site_module = self.get_site_module(base_url) or self.get_site_module(chapter_url)
        if not site_module:
            return chapter_url
        return site_module.resolve_chapter_url(base_url, chapter_url)

    def close_parsers(self):
        """Close any parser-managed resources such as browsers."""
        for parser in self.parsers.values():
            close_method = getattr(parser, "close_all", None) or getattr(parser, "close", None)
            if callable(close_method):
                try:
                    close_method()
                except Exception as e:
                    logger.debug(f"Failed to close parser resources: {e}")
    
    def download_image(
        self,
        image_url,
        save_path,
        max_retries=3,
        parser=None,
        referer=None,
        delay_seconds=0.1,
        request_timeout=30.0,
    ):
        """下载单个图片，带有重试机制 and 内容校验"""
        for retry in range(max_retries):
            try:
                # 准备请求头，增加 Referer 模拟来源
                headers = {}
                if referer:
                    headers['Referer'] = referer
                
                # 使用提供的解析器或根据 URL 获取解析器
                if parser:
                    custom_download = getattr(parser, "download_image", None)
                    if callable(custom_download):
                        if custom_download(image_url, save_path, headers=headers, timeout=request_timeout):
                            import time
                            time.sleep(max(0.0, float(delay_seconds or 0.0)))
                            return True
                        raise ValueError("Custom parser download hook returned failure")
                    response = parser.scraper.get(image_url, headers=headers, timeout=request_timeout)
                else:
                    # 尝试从 URL 获取解析器
                    url_parser = self.get_parser(image_url)
                    if url_parser:
                        response = url_parser.scraper.get(image_url, headers=headers, timeout=request_timeout)
                    else:
                        # 如果无法确定解析器，使用默认的 cloudscraper
                        from cloudscraper import CloudScraper
                        scraper = CloudScraper()
                        response = scraper.get(image_url, headers=headers, timeout=request_timeout)
                
                response.raise_for_status()
                
                # 内容校验：如果图片过小（通常小于 5KB），很可能是错误页面或被拦截的提示图
                content_size = len(response.content)
                if content_size < 5120:  # 5KB
                    # 检查内容是否为 HTML (某些网站返回 200 OK 的 HTML 错误页)
                    if b"<!DOCTYPE html>" in response.content.lower() or b"<html" in response.content.lower():
                        raise ValueError(f"下载到的内容是 HTML 页面而非图片 (大小: {content_size} bytes)")
                
                with open(save_path, 'wb') as f:
                    f.write(response.content)
                
                # 成功后稍微延迟，避免对服务器造成过大压力
                import time
                time.sleep(max(0.0, float(delay_seconds or 0.0)))
                return True
            except Exception as e:
                logger.warning(f"下载图片失败 (尝试 {retry+1}/{max_retries}): {e}")
                # 指数退避重试
                import time
                time.sleep(1 * (retry + 1))
                if retry == max_retries - 1:
                    return False
    
    def download_chapter(self, comic_title, chapter_name, chapter_url, parser, progress_callback=None, max_workers=None):
        """
        下载单个章节
        
        Args:
            comic_title: 漫画标题
            chapter_name: 章节名称
            chapter_url: 章节 URL
            parser: 解析器实例
            progress_callback: 进度回调函数
            max_workers: 最大并发工作线程数 (如果不指定，将根据解析器决定)
            
        Returns:
            下载是否成功
        """
        try:
            # 清理章节名称，移除特殊字符
            clean_chapter_name = chapter_name.replace(':', '_').replace('?', '').replace('!', '').replace('*', '').replace('"', '').replace('<', '').replace('>', '').replace('|', '')
            
            # 创建保存目录
            chapter_dir = os.path.join(self.base_dir, comic_title, clean_chapter_name)
            os.makedirs(chapter_dir, exist_ok=True)
            
            # 获取章节图片
            if progress_callback:
                progress_callback(f"获取章节 {chapter_name} 的图片列表...")
            
            image_urls = parser.get_chapter_images(chapter_url, progress_callback)
            if not image_urls:
                if progress_callback:
                    progress_callback(f"章节 {chapter_name} 没有找到图片")
                return False
            
            # 下载图片
            if progress_callback:
                progress_callback(f"开始下载章节 {chapter_name} 的 {len(image_urls)} 张图片...")
            
            # 准备下载任务
            tasks = []
            from urllib.parse import urlparse
            for page_num, img_url in enumerate(image_urls, 1):
                if not img_url:
                    continue
                # 尝试从 URL 提取扩展名，默认为 .jpg
                path = urlparse(img_url).path
                ext = os.path.splitext(path)[1].lower()
                if ext not in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                    ext = ".jpg"
                
                filename = f"{page_num:03d}{ext}"
                filepath = os.path.join(chapter_dir, filename)
                tasks.append((page_num, img_url, filepath))
            
            # 根据站点模块决定并发数，避免把站点特性硬编码在主下载器里
            if max_workers is None:
                max_workers = self.get_default_max_workers(chapter_url)
            download_max_retries = self.get_default_max_retries(chapter_url)
            download_delay_seconds = self.get_default_download_delay(chapter_url)
            request_timeout_seconds = self.get_default_request_timeout(chapter_url)
            
            # 使用线程池并发下载
            completed = 0
            total = len(tasks)
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_page = {
                    executor.submit(
                        self.download_image,
                        img_url,
                        filepath,
                        max_retries=download_max_retries,
                        parser=parser,
                        referer=chapter_url,
                        delay_seconds=download_delay_seconds,
                        request_timeout=request_timeout_seconds,
                    ): page_num
                    for page_num, img_url, filepath in tasks
                }
                for future in concurrent.futures.as_completed(future_to_page):
                    completed += 1
                    page_num = future_to_page[future]
                    if future.result():
                        if progress_callback:
                            progress_callback(f"下载进度: {completed}/{total}")
                    else:
                        logger.error(f"图片 {page_num} 下载失败: {tasks[page_num-1][1]}")
            
            # 检查是否下载了足够的图片 (允许少量失败，但不能全失败)
            downloaded_files = [f for f in os.listdir(chapter_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp'))]
            if len(downloaded_files) == 0:
                if progress_callback:
                    progress_callback(f"章节 {chapter_name} 下载失败：未成功下载任何图片")
                return False
            
            # 生成 CBZ 文件
            cbz_path = os.path.join(self.base_dir, comic_title, f"{clean_chapter_name}.cbz")
            with zipfile.ZipFile(cbz_path, 'w') as zipf:
                # 按顺序写入，确保阅读器顺序正确
                for page_num, img_url, filepath in tasks:
                    if os.path.exists(filepath):
                        zipf.write(filepath, os.path.basename(filepath))
            
            # 删除临时图片文件夹
            import shutil
            shutil.rmtree(chapter_dir)
            
            if progress_callback:
                progress_callback(f"章节 {chapter_name} 下载完成并打包为 CBZ")
            
            return True
        except Exception as e:
            logger.error(f"下载章节失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            if progress_callback:
                progress_callback(f"章节 {chapter_name} 下载过程中出现错误: {str(e)}")
            return False
    
    def run(self, url):
        """运行下载器"""
        parser = None
        try:
            # 获取解析器
            parser = self.get_parser(url)
            if not parser:
                logger.error("不支持的网站")
                return False
            
            # 获取漫画信息
            logger.info("获取漫画信息...")
            comic_title, chapter_links = parser.get_comic_info(url)
            if not comic_title:
                logger.error("无法获取漫画信息")
                return False
            
            logger.info(f"漫画标题: {comic_title}")
            logger.info(f"找到 {len(chapter_links)} 个章节")
            
            # 下载所有章节
            for chapter_name, chapter_url in chapter_links:
                logger.info(f"开始下载章节: {chapter_name}")
                
                # 确保 URL 完整
                if not chapter_url.startswith('http'):
                    chapter_url = self.resolve_chapter_url(url, chapter_url)
                
                success = self.download_chapter(comic_title, chapter_name, chapter_url, parser)
                if not success:
                    logger.error(f"章节 {chapter_name} 下载失败")
                    if self.get_default_chapter_failure_policy(chapter_url) == "stop":
                        logger.error("Stopping remaining chapters due to site failure policy")
                        return False
                else:
                    logger.info(f"章节 {chapter_name} 下载完成")
            
            logger.info("所有章节下载完成")
            return True
        except Exception as e:
            logger.error(f"运行失败: {e}")
            return False
        finally:
            close_method = getattr(parser, "close", None)
            if callable(close_method):
                try:
                    close_method()
                except Exception as e:
                    logger.debug(f"Failed to close parser after run: {e}")

    def convert_to_cbz(self, input_path, output_path, progress_callback=None):
        """
        将文件夹或 zip 文件转换为 CBZ 文件
        
        Args:
            input_path: 输入文件夹或 zip 文件路径
            output_path: 输出 CBZ 文件路径
            progress_callback: 进度回调函数
            
        Returns:
            转换是否成功
        """
        try:
            if progress_callback:
                progress_callback(f"开始转换: {input_path}")
            
            # 创建 CBZ 文件
            with zipfile.ZipFile(output_path, 'w') as zipf:
                if os.path.isdir(input_path):
                    # 处理文件夹
                    image_files = []
                    for root, _, files in os.walk(input_path):
                        for file in files:
                            if file.lower().endswith(('.jpg', '.jpeg', '.png', '.gif')):
                                image_files.append(os.path.join(root, file))
                    
                    if not image_files:
                        if progress_callback:
                            progress_callback("错误: 文件夹中没有找到图片文件")
                        return False
                    
                    total = len(image_files)
                    for i, img_path in enumerate(image_files, 1):
                        arcname = os.path.relpath(img_path, input_path)
                        zipf.write(img_path, arcname)
                        if progress_callback:
                            progress_callback(f"添加图片 {i}/{total}")
                elif os.path.isfile(input_path) and input_path.lower().endswith('.zip'):
                    # 处理 zip 文件
                    with zipfile.ZipFile(input_path, 'r') as input_zip:
                        # 过滤出图片文件
                        image_files = [f for f in input_zip.namelist() 
                                     if f.lower().endswith(('.jpg', '.jpeg', '.png', '.gif'))]
                        
                        if not image_files:
                            if progress_callback:
                                progress_callback("错误: ZIP 文件中没有找到图片文件")
                            return False
                        
                        total = len(image_files)
                        for i, img_name in enumerate(image_files, 1):
                            # 读取文件内容并写入新的 CBZ
                            with input_zip.open(img_name) as f:
                                zipf.writestr(img_name, f.read())
                            if progress_callback:
                                progress_callback(f"添加图片 {i}/{total}")
                else:
                    if progress_callback:
                        progress_callback("错误: 输入路径必须是文件夹或 ZIP 文件")
                    return False
            
            if progress_callback:
                progress_callback(f"转换完成: {output_path}")
            
            return True
        except Exception as e:
            logger.error(f"转换失败: {e}")
            if progress_callback:
                progress_callback(f"转换失败: {str(e)}")
            return False

if __name__ == "__main__":
    downloader = ComicDownloader()
    # 测试 URL - 使用 readcomiconline.li
    test_url = "https://readcomiconline.li/Comic/Spawn"
    downloader.run(test_url)
