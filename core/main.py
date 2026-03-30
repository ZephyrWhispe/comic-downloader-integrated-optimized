#!/usr/bin/env python3
import sys
import asyncio
import os
from typing import Optional, Dict, List, Tuple, Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

# 添加父目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 导入comic-dl的模块
from .comic_downloader import ComicDownloader

# 导入getcomics-downloader的模块
from .getinfo import GetComics
from .download import download_comics
from .menu import parse_arguments, interactive_main_menu, show_interactive_menu
from .series_downloader import download_series
from .logger import main_logger

console = Console()

def display_header() -> None:
    """显示程序标题和欢迎信息"""
    console.clear()
    console.print()
    console.print("=" * 70)
    console.print(r"""[bold purple]
      ____      _    ____                _                    
     / ___| ___| |_ / ___|___  _ __ ___ (_) ___ ___          
    | |  _ / _ \ __| |   / _ \| '_ ` _ \| |/ __/ __|         
    | |_| |  __/ |_| |__| (_) | | | | | | | (__\__ \         
     \____|\___|\__|\____\___/|_| |_| |_|_|\___|___/         
    |  _ \  _____      ___ __ | | ___   __ _  __| | ___ _ __ 
    | | | |/ _ \ \ /\ / / '_ \| |/ _ \ / _` |/ _` |/ _ \ '__|
    | |_| | (_) \ V  V /| | | | | (_) | (_| | (_| |  __/ |   
    |____/ \___/ \_/\_/ |_| |_|_|\___/ \__,_|\__,_|\___|_|  [/bold purple]
                        """)
    console.print("    Comic Downloader Integrated v1.0")
    console.print()
    console.print("=" * 70)
    console.print()

def show_main_menu() -> Optional[str]:
    """显示主菜单"""
    console.print("[bold cyan]Main Menu[/bold cyan]")
    console.print("1. [green]GetComics Downloader[/green] - Download comics from GetComics")
    console.print("2. [green]Comic-DL Downloader[/green] - Download comics from multiple sites")
    console.print("3. [red]Exit[/red]")
    console.print()
    
    choice = Prompt.ask("Enter your choice", choices=["1", "2", "3"], default="1")
    return choice

async def run_getcomics_downloader() -> None:
    """运行GetComics下载器"""
    while True:
        try:
            display_header()
            
            args = parse_arguments()
            if args is None:
                args = interactive_main_menu()
                if args is None:
                    console.print("[yellow]Returning to main menu.[/yellow]")
                    return
            
            main_logger.info(
                "User provided args: query=%s, date=%s, min=%s, max=%s, download_path=%s, results=%s",
                args.query,
                args.date,
                args.min,
                args.max,
                args.download_path,
                args.results,
            )
            
            # 确保下载目录存在
            args.download_path.mkdir(parents=True, exist_ok=True)

            # 检查是否为系列下载命令
            if args.query and args.query.startswith("/series"):
                comic = args.query.replace("/series", "").strip()
                if not comic:
                    console.print("[yellow]Usage: /series <comic name>[/yellow]")
                    main_logger.warning("Empty comic name for series download")
                    Prompt.ask("Press any key to return to main menu")
                    return
                await download_series(comic, args.download_path, args.verbose, args.use_aria2c)
                return

            search_query = (args.query or "").strip()
            display_query = search_query or "latest releases"

            main_logger.info(
                "Initializing GetComics with query=%s year=%s min=%s max=%s results=%s",
                search_query or "<latest releases>",
                args.date,
                args.min,
                args.max,
                args.results,
            )
            comics = GetComics(
                search_query,
                args.results,
                args.verbose,
                min_issue=args.min,
                max_issue=args.max,
                date=args.date,
            )
            
            while True:
                with console.status(f"[bold green]Scanning GetComics: {display_query} (Page {comics.page})..."):
                    main_logger.info(f"Scanning GetComics: {display_query} (Page {comics.page})")
                    await comics.find_pages()
                    await comics.get_download_links()

                if not comics.comic_links:
                    console.print(f"[bold red]No results found for '{display_query}'.[/bold red]")
                    main_logger.warning(f"No results found for '{display_query}'")
                    Prompt.ask("Press any key to return to main menu")
                    return

                selected_comics = show_interactive_menu(comics.comic_links, display_query)

                if selected_comics == "next":
                    main_logger.info("User chose to go to next page")
                    comics.comic_links.clear()
                    comics.page_links.clear()
                    continue
                
                if not selected_comics:
                    console.print("[yellow]Returning to main menu.[/yellow]")
                    return

                main_logger.info(f"User selected {len(selected_comics)} comics to download")
                download_comics(dict(selected_comics), args.download_path, args.verbose, prompt=False, use_aria2c=args.use_aria2c)
                Prompt.ask("Press any key to return to main menu")
                return

        except KeyboardInterrupt:
            console.print("\n[bold red]Operation cancelled by user.[/bold red]")
            main_logger.info("Operation cancelled by user")
            return
        except Exception as e:
            error_msg = f"Unexpected error: {e}"
            console.print(f"[bold red]{error_msg}[/bold red]")
            main_logger.error(error_msg, exc_info=True)
            Prompt.ask("Press any key to return to main menu")
            return

def run_comic_dl_downloader() -> None:
    """运行Comic-DL下载器"""
    try:
        display_header()
        console.print("[bold cyan]Comic-DL Downloader[/bold cyan]")
        console.print()
        
        url = Prompt.ask("Enter comic URL")
        if not url:
            console.print("[yellow]Returning to main menu.[/yellow]")
            return
        
        downloader = ComicDownloader()
        
        # 询问保存目录
        default_dir = os.path.join(os.path.expanduser("~"), "Documents", "Comics")
        save_dir = Prompt.ask(f"Enter save directory", default=default_dir)
        downloader.set_base_dir(save_dir)
        
        console.print(f"[green]Starting download from: {url}[/green]")
        console.print(f"[green]Saving to: {save_dir}[/green]")
        console.print()
        
        success = downloader.run(url)
        if success:
            console.print("[bold green]Download completed successfully![/bold green]")
        else:
            console.print("[bold red]Download failed![/bold red]")
        
        Prompt.ask("Press any key to return to main menu")
    except KeyboardInterrupt:
        console.print("\n[bold red]Operation cancelled by user.[/bold red]")
        return
    except Exception as e:
        error_msg = f"Unexpected error: {e}"
        console.print(f"[bold red]{error_msg}[/bold red]")
        Prompt.ask("Press any key to return to main menu")
        return

async def main() -> None:
    """主函数"""
    main_logger.info("Starting Comic Downloader Integrated")
    
    while True:
        try:
            display_header()
            choice = show_main_menu()
            
            if choice == "1":
                await run_getcomics_downloader()
            elif choice == "2":
                run_comic_dl_downloader()
            elif choice == "3":
                console.print("[yellow]Exiting. Bye![/yellow]")
                main_logger.info("User exited the program")
                return
        except KeyboardInterrupt:
            console.print("\n[bold red]Operation cancelled by user.[/bold red]")
            main_logger.info("Operation cancelled by user")
            sys.exit(1)
        except Exception as e:
            error_msg = f"Unexpected error: {e}"
            console.print(f"[bold red]{error_msg}[/bold red]")
            main_logger.error(error_msg, exc_info=True)
            Prompt.ask("Press any key to continue")

if __name__ == "__main__":
    asyncio.run(main())
