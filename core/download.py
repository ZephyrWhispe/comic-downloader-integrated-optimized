import re
import shutil
import tempfile
import textwrap
import time
from pathlib import Path
from urllib.parse import unquote

import requests
from rich.console import Console
from rich.progress import Progress, BarColumn, DownloadColumn, TextColumn, TimeRemainingColumn, TransferSpeedColumn
from rich.prompt import Prompt
import subprocess
from .logger import download_logger

console = Console()

def is_aria2c_available() -> bool:
    # 首先检查当前目录是否有 aria2c.exe
    import os
    current_dir = os.path.dirname(os.path.abspath(__file__))
    aria2c_path = os.path.join(current_dir, "aria2c.exe")
    
    # 检查当前目录的 aria2c
    try:
        subprocess.run(
            [aria2c_path, "--version"], 
            check=True, 
            capture_output=True, 
            text=True
        )
        download_logger.debug("aria2c is available in current directory")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    
    # 检查系统 PATH 中的 aria2c
    try:
        subprocess.run(
            ["aria2c", "--version"], 
            check=True, 
            capture_output=True, 
            text=True
        )
        download_logger.debug("aria2c is available in PATH")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        download_logger.debug("aria2c is not available")
        return False


def extract_year(filename: str) -> str:
    """从文件名中提取年份"""
    match = re.search(r"\((\d{4})\)", filename)
    if match:
        return match.group(1)
    return "Unknown"

def rename_file(path: Path, comic: str, issue: str, year: str) -> Path:
    """重命名文件为一致的格式"""
    new_name = f"{comic} #{issue} ({year}).cbz"
    new_path = path.parent / new_name
    try:
        path.rename(new_path)
        download_logger.info(f"Renamed file: {path.name} -> {new_name}")
        return new_path
    except Exception as e:
        error_msg = f"Error renaming file: {e}"
        console.print(f"[bold red]{error_msg}[/bold red]")
        download_logger.error(error_msg)
        return path

def download_comics(
    comic_links,
    download_path,
    verbose=False,
    prompt=True,
    use_aria2c=False,
    progress_callback=None,
    rename_downloaded_files=None,
    cancel_callback=None,
):
    if not comic_links:
        download_logger.warning("No comic links to download")
        return
    
    download_path = Path(download_path).expanduser()
    download_path.mkdir(parents=True, exist_ok=True)
    download_logger.info(f"Starting download of {len(comic_links)} comics to {download_path}")
    downloaded_files = []
    
    total_comics = len(comic_links)
    for i, (url, title) in enumerate(comic_links.items()):
        if cancel_callback and cancel_callback():
            download_logger.info(f"Download cancelled before processing {title}")
            if progress_callback:
                progress_callback("Download cancelled.")
            break
        if progress_callback:
            progress_callback(f"正在下载第 {i+1}/{total_comics} 个漫画: {title}")
            progress_callback(("progress", (i / total_comics) * 100))
        if url.startswith("_MEDIAFIRE_"):
            try:
                mediafire_url = url[url.index('http'):]
                console.print(f"""{title}:
Please download from the following Mediafire link:
[link={mediafire_url}]{mediafire_url}[/link]""")
                download_logger.info(f"Mediafire link for {title}: {mediafire_url}")
            except Exception as e:
                error_msg = f"Error processing Mediafire link for {title}: {e}"
                console.print(f"[bold red]{error_msg}[/bold red]")
                download_logger.error(error_msg)
            continue
        
        if verbose:
            console.print(f"Downloading {title} from {url}")
        download_logger.info(f"Processing {title} from {url}")

        # 获取最终URL，添加错误处理和重试
        max_retries = 3
        final_url = url
        for attempt in range(max_retries):
            try:
                if "." not in url.rpartition("/")[-1]:
                    response = requests.head(url, allow_redirects=True, timeout=10)
                    response.raise_for_status()
                    final_url = response.url
                break
            except requests.exceptions.RequestException as e:
                error_msg = f"Error getting final URL: {e} (Attempt {attempt+1}/{max_retries})"
                console.print(error_msg)
                download_logger.error(error_msg)
                if attempt < max_retries - 1:
                    console.print("Retrying in 2 seconds...")
                    time.sleep(2)
                else:
                    error_msg = f"Failed to get final URL for {title}. Continuing with original URL."
                    console.print(f"[bold red]{error_msg}[/bold red]")
                    download_logger.warning(error_msg)
                    break
            except Exception as e:
                error_msg = f"Unexpected error getting final URL: {e}"
                console.print(f"[bold red]{error_msg}[/bold red]")
                download_logger.error(error_msg, exc_info=True)
                break
        else:
            continue  # Skip to next comic if all retries failed
        
        try:
            file_name = safe_filename(unquote(final_url.rpartition("/")[-1]))
            
            if not use_aria2c: # apply create_file_name if not using aria
                file_name = create_file_name(str(download_path / file_name))
            else:
                file_name = str(download_path / file_name) #full path string for aria
            
            if prompt and "n" in Prompt.ask(f"Download '{title}'?", choices=["y", "n"], default="y").lower():
                download_logger.info(f"User skipped download of {title}")
                continue

            def file_progress_callback(msg):
                if progress_callback:
                    if isinstance(msg, tuple) and msg[0] == "file_progress":
                        # 计算整体进度：(已完成漫画数 + 当前漫画进度) / 总漫画数
                        current_comic_progress = msg[1] / 100
                        overall_progress = ((i + current_comic_progress) / total_comics) * 100
                        progress_callback(("progress", overall_progress))
                    else:
                        progress_callback(msg)

            downloaded_path = download_file(
                final_url, 
                filename=Path(file_name),
                verbose=True, 
                transient=True,
                use_aria2c=use_aria2c,
                progress_callback=file_progress_callback
            )
            console.print(f"'{title}' downloaded.")
            download_logger.info(f"Successfully downloaded {title}")
            downloaded_files.append(Path(downloaded_path) if downloaded_path else Path(file_name))
        except Exception as e:
            error_msg = f"Error processing {title}: {e}"
            console.print(f"[bold red]{error_msg}[/bold red]")
            download_logger.error(error_msg, exc_info=True)
            continue
    
    # 处理文件重命名
    if downloaded_files:
        rename = rename_downloaded_files
        if rename is None:
            rename = Prompt.ask("Rename downloaded files? (y/n)", default="y").lower() == "y"
        if rename:
            for path in downloaded_files:
                # 尝试从文件名中提取漫画名称和期数
                filename = path.name
                comic_name = filename.split("#")[0].strip() if "#" in filename else filename.split(".")[0].strip()
                issue_match = re.search(r"#(\d+)", filename)
                issue = issue_match.group(1) if issue_match else "1"
                year = extract_year(filename) or "Unknown"
                
                rename_file(path, comic_name, issue, year)
            
            console.print("[green]Files renamed successfully![/green]")
            download_logger.info("Files renamed successfully")
    
    download_logger.info("Download process completed")

def download_file(url, filename=None, chunk_size=1024, verbose=False, transient=False, use_aria2c=False, progress_callback=None):
    if not filename:
        raise ValueError("Filename must be provided")
    
    if not url:
        raise ValueError("URL must be provided")
    
    destination = filename
    temp_file = Path(tempfile.gettempdir()) / filename.name
    download_logger.info(f"Starting download of {destination.name} from {url}")

    if use_aria2c and is_aria2c_available():
        try:
            # 确定 aria2c 可执行文件的路径
            import os
            current_dir = os.path.dirname(os.path.abspath(__file__))
            aria2c_path = os.path.join(current_dir, "aria2c.exe")
            
            # 检查当前目录是否有 aria2c.exe
            if not os.path.exists(aria2c_path):
                # 如果没有，使用系统 PATH 中的 aria2c
                aria2c_path = "aria2c"
            
            aria2c_command = [
                aria2c_path,
                "--console-log-level=warn",
                "--summary-interval=0",
                "-d", str(destination.parent),
                "-o", destination.name,
                url
            ]
            if not verbose:
                aria2c_command.insert(1, "--quiet")

            console.print(f"[bold green]Downloading with aria2c: {destination.name}[/bold green]")
            download_logger.info(f"Using aria2c to download {destination.name}")
            subprocess.run(aria2c_command, check=True)
            download_logger.info(f"Successfully downloaded {destination.name} with aria2c")
            return destination
        except subprocess.CalledProcessError as e:
            error_msg = f"aria2c download failed: {e}"
            console.print(f"[bold red]{error_msg}[/bold red]")
            download_logger.error(error_msg)
            console.print("[yellow]Falling back to requests download.[/yellow]")
            download_logger.info("Falling back to requests download")
        except FileNotFoundError:
            console.print("[bold red]aria2c not found. Falling back to requests download.[/bold red]")
            download_logger.warning("aria2c not found. Falling back to requests download")
        except Exception as e:
            error_msg = f"Unexpected error with aria2c: {e}"
            console.print(f"[bold red]{error_msg}[/bold red]")
            download_logger.error(error_msg, exc_info=True)
            console.print("[yellow]Falling back to requests download.[/yellow]")
            download_logger.info("Falling back to requests download")

    # 尝试使用requests下载，添加错误处理和重试
    max_retries = 3
    response = None
    for attempt in range(max_retries):
        try:
            response = requests.get(url, stream=True, timeout=30)
            response.raise_for_status()
            break
        except requests.exceptions.RequestException as e:
            error_msg = f"Error starting download: {e} (Attempt {attempt+1}/{max_retries})"
            console.print(error_msg)
            download_logger.error(error_msg)
            if attempt < max_retries - 1:
                console.print("Retrying in 2 seconds...")
                time.sleep(2)
            else:
                console.print("[bold red]Max retries reached. Download failed.[/bold red]")
                download_logger.error("Max retries reached. Download failed")
                raise
        except Exception as e:
            error_msg = f"Unexpected error starting download: {e}"
            console.print(f"[bold red]{error_msg}[/bold red]")
            download_logger.error(error_msg, exc_info=True)
            if attempt < max_retries - 1:
                console.print("Retrying in 2 seconds...")
                time.sleep(2)
            else:
                raise

    if not response:
        error_msg = "Failed to get response for download"
        console.print(f"[bold red]{error_msg}[/bold red]")
        download_logger.error(error_msg)
        raise ValueError(error_msg)

    if response.history:
        redirected_name = safe_filename(unquote(Path(response.url).name))
        if redirected_name:
            filename = destination.with_name(redirected_name)
    destination = filename
    temp_file = Path(tempfile.gettempdir()) / filename.name
    
    total_size_in_bytes = int(response.headers.get('content-length', 0))
    download_logger.info(f"Downloading {destination.name} ({total_size_in_bytes} bytes)")
    
    if verbose:
        console.print(f"[bold cyan]{destination.name}[/bold cyan]")

    try:
        with open(temp_file, "wb") as file:
            progress = Progress(
                BarColumn(bar_width=None), 
                "[progress.percentage]{task.percentage:>3.1f}%",
                "•",
                DownloadColumn(binary_units=True),
                "•",
                TransferSpeedColumn(),
                "•",
                TimeRemainingColumn(compact=True),
                disable=not verbose,
                transient=transient
            )
            
            with progress:
                task_id = progress.add_task(
                    description="", 
                    total=total_size_in_bytes,
                    visible=verbose
                )
                
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        file.write(chunk)
                        progress.update(task_id, advance=len(chunk))
                        if progress_callback and total_size_in_bytes > 0:
                            # 报告文件内进度
                            done = progress.tasks[task_id].completed
                            file_progress = (done / total_size_in_bytes) * 100
                            progress_callback(("file_progress", file_progress))
    except Exception as e:
        error_msg = f"Error writing file: {e}"
        console.print(f"[bold red]{error_msg}[/bold red]")
        download_logger.error(error_msg, exc_info=True)
        # 清理临时文件
        try:
            if temp_file.exists():
                temp_file.unlink()
                download_logger.debug(f"Cleaned up temporary file: {temp_file}")
        except Exception as cleanup_error:
            download_logger.debug(f"Error cleaning up temporary file: {cleanup_error}")
        raise
                
    # 尝试移动文件，处理权限错误
    try:
        # 确保目标目录存在
        destination.parent.mkdir(parents=True, exist_ok=True)
        download_logger.debug(f"Ensured destination directory exists: {destination.parent}")
        
        # 如果目标文件已存在，先删除
        if destination.exists():
            try:
                destination.unlink()
                download_logger.debug(f"Removed existing file: {destination}")
            except PermissionError:
                # 如果无法删除，使用不同的文件名
                timestamp = int(time.time())
                new_destination = destination.parent / f"{destination.stem}_{timestamp}{destination.suffix}"
                shutil.move(str(temp_file), str(new_destination))
                console.print(f"[yellow]目标文件已存在，使用新文件名: {new_destination.name}[/yellow]")
                download_logger.info(f"File already exists, using new filename: {new_destination.name}")
                return new_destination
        
        shutil.move(str(temp_file), str(destination))
        download_logger.info(f"Successfully moved file to: {destination}")
        return destination
    except PermissionError as e:
        error_msg = f"权限错误: {e}"
        console.print(f"[bold red]{error_msg}[/bold red]")
        download_logger.error(error_msg)
        console.print("[yellow]尝试以管理员权限运行程序，或选择其他下载目录[/yellow]")
        
        # 尝试使用用户主目录的临时位置
        try:
            import os
            user_home = os.path.expanduser("~")
            temp_download_dir = os.path.join(user_home, "Downloads", "ComicDownloaderTemp")
            os.makedirs(temp_download_dir, exist_ok=True)
            
            fallback_destination = Path(temp_download_dir) / destination.name
            
            # 尝试复制到临时目录
            shutil.copy2(temp_file, fallback_destination)
            temp_file.unlink()
            console.print(f"[green]成功保存到临时目录: {fallback_destination}[/green]")
            download_logger.info(f"Successfully saved to temporary directory: {fallback_destination}")
            console.print("[yellow]请手动将文件移动到您想要的位置[/yellow]")
            return fallback_destination
        except Exception as fallback_error:
            # 尝试复制文件而不是移动
            try:
                shutil.copy2(temp_file, destination)
                temp_file.unlink()
                console.print("[green]成功通过复制方式完成下载[/green]")
                download_logger.info("Successfully completed download via copy")
                return destination
            except Exception as copy_error:
                error_msg = f"复制文件失败: {copy_error}"
                console.print(f"[bold red]{error_msg}[/bold red]")
                download_logger.error(error_msg, exc_info=True)
                # 保留临时文件路径
                console.print(f"[yellow]临时文件保存位置: {temp_file}[/yellow]")
                download_logger.info(f"Temporary file saved at: {temp_file}")
                raise
    except Exception as e:
        error_msg = f"移动文件失败: {e}"
        console.print(f"[bold red]{error_msg}[/bold red]")
        download_logger.error(error_msg, exc_info=True)
        # 保留临时文件路径
        console.print(f"[yellow]临时文件保存位置: {temp_file}[/yellow]")
        download_logger.info(f"Temporary file saved at: {temp_file}")
        raise

def safe_filename(filename: str) -> str:
    result = re.sub(r'[\\/\\:\\*\\?\"<>\\|]', "", filename)
    download_logger.debug(f"Sanitized filename: {filename} -> {result}")
    return result

def create_file_name(filename: str) -> str:
    filename = filename.replace("\\", "/")
    if not Path(filename).exists():
        return filename
    
    if "/" in filename:
        directories, _, filename = filename.rpartition("/") 
        directories += "/"
    else:
        directories = ""
    
    if "." in filename:
        stem, _, suffix = filename.rpartition(".")
        suffix = "." + suffix
    else:
        stem, suffix = filename, ""

    num = 0
    while Path(f"{directories}{stem} ({num}){suffix}").exists():
        num += 1
    result = f"{directories}{stem} ({num}){suffix}"
    download_logger.debug(f"Created unique filename: {filename} -> {result}")
    return result
