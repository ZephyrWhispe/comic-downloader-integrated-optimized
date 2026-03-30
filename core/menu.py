import argparse
import sys
from datetime import datetime
from pathlib import Path
import json
import os
import subprocess

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from .download import is_aria2c_available
from .logger import menu_logger

console = Console()

CONFIG_FILE = Path(".") / ".config.json"

def save_options(args):
    try:
        # 确保配置文件目录存在
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        with open(CONFIG_FILE, 'w') as f:
            args_dict = vars(args)
            if 'download_path' in args_dict and isinstance(args_dict['download_path'], Path):
                args_dict['download_path'] = str(args_dict['download_path'])
            json.dump(args_dict, f, indent=4)
        console.print(f"[green]Options saved to {CONFIG_FILE}[/green]")
        menu_logger.info(f"Options saved to {CONFIG_FILE}")
    except Exception as e:
        error_msg = f"Error saving options: {e}"
        console.print(f"[bold red]{error_msg}[/bold red]")
        menu_logger.error(error_msg)

def load_options():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r') as f:
                try:
                    options = json.load(f)
                    if 'download_path' in options and isinstance(options['download_path'], str):
                        try:
                            options['download_path'] = Path(options['download_path'])
                        except Exception as e:
                            warning_msg = f"Invalid download path in config: {e}. Using default path."
                            console.print(f"[yellow]Warning: {warning_msg}[/yellow]")
                            menu_logger.warning(warning_msg)
                            options['download_path'] = Path("Downloads/Comics").expanduser()
                    if 'use_aria2c' not in options:
                        options['use_aria2c'] = False
                    menu_logger.info("Loaded options from config file")
                    return argparse.Namespace(**options)
                except json.JSONDecodeError:
                    warning_msg = f"Could not read config file {CONFIG_FILE}. Using default options."
                    console.print(f"[yellow]Warning: {warning_msg}[/yellow]")
                    menu_logger.warning(warning_msg)
                    return None
        except Exception as e:
            warning_msg = f"Error reading config file: {e}. Using default options."
            console.print(f"[yellow]Warning: {warning_msg}[/yellow]")
            menu_logger.warning(warning_msg)
            return None
    menu_logger.info("No config file found, using default options")
    return None

def parse_arguments():
    if len(sys.argv) == 1:
        menu_logger.info("No command line arguments provided, using interactive mode")
        return None  # if no arguments provided trigger the menu

    parser = argparse.ArgumentParser(
        description="Search for and/or download content from getcomics.org."
    )
    parser.add_argument("query", type=str, nargs='?', default=None, help="Search term for comics")

    parser.add_argument("-date", "--d", dest='date', type=str, default=None, help="Get newer ones (YYYY)")
    parser.add_argument("-output", "--o", dest="download_path", type=str, default="Downloads/Comics", help='Download directory')
    parser.add_argument("-min", dest="min", type=int, default=None, help="Minimum issue number")
    parser.add_argument("-max", dest="max", type=int, default=None, help="Maximum issue number")
    parser.add_argument("-results", "--r", dest="results", type=int, default=15, help="Number of results to show")
    parser.add_argument("-verbose", "--v", dest="verbose", action="store_true", default=False, help="Detailed output")
    parser.add_argument("-aria2c", "--a", dest="use_aria2c", action="store_true", default=False, help="Use aria2c for downloads")

    try:
        args = parser.parse_args()
        try:
            args.download_path = Path(args.download_path).expanduser()
        except Exception as e:
            warning_msg = f"Invalid download path: {e}. Using default path."
            console.print(f"[yellow]Warning: {warning_msg}[/yellow]")
            menu_logger.warning(warning_msg)
            args.download_path = Path("Downloads/Comics").expanduser()
        
        if args.date:
            try:
                args.date = datetime.strptime(args.date, "%Y").year
            except Exception as e:
                warning_msg = "Date format should be YYYY. Date filter disabled."
                console.print(f"[yellow]Warning: {warning_msg}[/yellow]")
                menu_logger.warning(warning_msg)
                args.date = None

        menu_logger.info(f"Parsed command line arguments: query={args.query}, date={args.date}, results={args.results}")
        return args
    except SystemExit:
        # 处理参数解析错误
        console.print("[yellow]Error parsing command line arguments. Using interactive mode.[/yellow]")
        menu_logger.warning("Error parsing command line arguments, using interactive mode")
        return None
    except Exception as e:
        error_msg = f"Error parsing arguments: {e}. Using interactive mode."
        console.print(f"[yellow]{error_msg}[/yellow]")
        menu_logger.error(error_msg)
        return None

def show_interactive_menu(comic_links, search_term):
    menu_logger.info(f"Showing interactive menu for search term: {search_term}")
    
    if not comic_links:
        error_msg = f"No downloadable links found for '{search_term}'."
        console.print(f"[bold red]{error_msg}[/bold red]")
        menu_logger.warning(error_msg)
        return []

    console.clear()
    table = Table(
        title=f"""
[bold magenta]Results for: {search_term}[/bold magenta]""",
        show_header=True, 
        header_style="bold cyan",
        border_style="bright_black"
    )
    table.add_column("No", style="dim", width=4, justify="center")
    table.add_column("Comic Title", style="white")
    table.add_column("Source", width=12, justify="center")

    comics_list = []
    for i, (url, title) in enumerate(comic_links.items(), 1):
        is_mediafire = url.startswith("_MEDIAFIRE_")
        source_type = "[yellow]Mediafire[/yellow]" if is_mediafire else "[green]Direct[/green]"
        table.add_row(str(i), title, source_type)
        comics_list.append((url, title))

    console.print(table)
    menu_logger.info(f"Displayed {len(comics_list)} comic results")
    
    while True:
        choice = Prompt.ask(
            """
Enter numbers to download (e.g. [bold]1,3[/bold]), [bold]'a'[/bold] for all, [bold]'n'[/bold] for next page, or [bold]'q'[/bold] to quit""",
            default="q"
        )

        if choice.lower() == 'q':
            menu_logger.info("User chose to quit")
            return []
        if choice.lower() == 'a':
            menu_logger.info(f"User chose to download all {len(comics_list)} comics")
            return comics_list
        if choice.lower() == 'n':
            menu_logger.info("User chose to go to next page")
            return "next"
        
        try:
            indices = [int(x.strip()) - 1 for x in choice.split(",") if x.strip().isdigit()]
            valid_indices = [i for i in indices if 0 <= i < len(comics_list)]
            if not valid_indices:
                console.print("[yellow]No valid comic numbers entered. Please try again.[/yellow]")
                menu_logger.warning("No valid comic numbers entered")
                continue
            selected_comics = [comics_list[i] for i in valid_indices]
            menu_logger.info(f"User selected {len(selected_comics)} comics to download")
            return selected_comics
        except Exception as e:
            error_msg = f"Invalid input: {e}. Please try again."
            console.print(f"[yellow]{error_msg}[/yellow]")
            menu_logger.error(error_msg)
            continue

def interactive_main_menu():
    menu_logger.info("Starting interactive main menu")
    args = argparse.Namespace()

    loaded_args = load_options()
    if loaded_args:
        menu_logger.info("Loaded options from config file")
        args = loaded_args
    else:
        menu_logger.info("No saved options found, using defaults")

    args.query = None if not hasattr(args, 'query') else args.query
    args.date = None if not hasattr(args, 'date') else args.date
    if hasattr(args, 'download_path'):
        try:
            args.download_path = Path(args.download_path).expanduser()
            menu_logger.debug(f"Set download path to: {args.download_path}")
        except Exception as e:
            warning_msg = f"Invalid download path: {e}. Using default path."
            console.print(f"[yellow]Warning: {warning_msg}[/yellow]")
            menu_logger.warning(warning_msg)
            args.download_path = Path("Downloads/Comics").expanduser()
            menu_logger.info(f"Using default download path: {args.download_path}")
    else:
        args.download_path = Path("Downloads/Comics").expanduser()
        menu_logger.info(f"Using default download path: {args.download_path}")
    args.min = None if not hasattr(args, 'min') else args.min
    args.max = None if not hasattr(args, 'max') else args.max
    args.results = 15 if not hasattr(args, 'results') else args.results
    args.verbose = False if not hasattr(args, 'verbose') else args.verbose
    args.use_aria2c = False if not hasattr(args, 'use_aria2c') else args.use_aria2c
    
    menu_logger.info(f"Initialized menu with options: query={args.query}, download_path={args.download_path}, results={args.results}, use_aria2c={args.use_aria2c}")
    
    while True:
        menu_choices = {"q": "Search by [bold]Q[/bold]uery", "o": "[bold]O[/bold]ptions"}
        if args.use_aria2c and is_aria2c_available():
            menu_choices["c"] = "[bold]C[/bold]ontinue interrupted downloads"
        
        choice_str = ", or ".join(menu_choices.values())
        choice = Prompt.ask(choice_str + "?", default="q")
        menu_logger.debug(f"User chose: {choice}")

        if choice.lower() == 'q':
            args.query = Prompt.ask(f"Enter search query (Leave empty to lookup last {args.results} comic, or use /series <name> for series download)")
            menu_logger.info(f"User entered search query: '{args.query}'")
            return args
        elif choice.lower() == 'o':
            try:
                args = options_menu(args)
                menu_logger.info("User exited options menu")
            except Exception as e:
                error_msg = f"Error in options menu: {e}"
                console.print(f"[bold red]{error_msg}[/bold red]")
                menu_logger.error(error_msg, exc_info=True)
            continue 
        elif choice.lower() == 'c' and args.use_aria2c and is_aria2c_available():
            try:
                handle_interrupted_downloads(args.download_path, args.verbose)
                menu_logger.info("Handled interrupted downloads")
            except Exception as e:
                error_msg = f"Error handling interrupted downloads: {e}"
                console.print(f"[bold red]{error_msg}[/bold red]")
                menu_logger.error(error_msg, exc_info=True)
            Prompt.ask("Press any key to return to the main menu")
            continue
        else:
            console.print("[bold red]Invalid choice. Please try again.[/bold red]")
            menu_logger.warning(f"Invalid menu choice: {choice}")
            Prompt.ask("Press Enter to continue...")

def options_menu(args):
    menu_logger.info("Starting options menu")
    
    while True:
        console.print("""
[bold]Current Options:[/bold]""")
        console.print(f"  [cyan]1. Date (YYYY):[/cyan] {args.date or 'Not set'}")
        console.print(f"  [cyan]2. Download Path:[/cyan] {args.download_path}")
        console.print(f"  [cyan]3. Min Issue:[/cyan] {args.min or 'Not set'}")
        console.print(f"  [cyan]4. Max Issue:[/cyan] {args.max or 'Not set'}")
        console.print(f"  [cyan]5. Results:[/cyan] {args.results}")
        console.print(f"  [cyan]6. Display Log:[/cyan] {args.verbose}")
        console.print(f"  [cyan]7. Use aria2c:[/cyan] {args.use_aria2c}")

        choice = Prompt.ask(
            """Choose an option to change, or press [bold]b[/bold]ack""",
            default="b"
        )
        menu_logger.debug(f"User chose option: {choice}")

        if choice == 'b':
            menu_logger.info("User chose to go back from options menu")
            return args
        
        if choice == '1':
            date_str = Prompt.ask("Enter date (YYYY)", default=str(args.date) if args.date else "")
            try:
                if date_str:
                    args.date = datetime.strptime(date_str, "%Y").year
                    menu_logger.info(f"Set date to: {args.date}")
                else:
                    args.date = None
                    menu_logger.info("Date filter disabled")
            except Exception as e:
                warning_msg = "Date format should be YYYY. Date filter disabled."
                console.print(f"[yellow]Warning: {warning_msg}[/yellow]")
                menu_logger.warning(warning_msg)
                args.date = None
            save_options(args)
        elif choice == '2':
            path_str = Prompt.ask("Enter download path", default=str(args.download_path))
            try:
                new_path = Path(path_str).expanduser()
                # 验证路径是否可写
                test_file = new_path / ".test_write.txt"
                new_path.mkdir(parents=True, exist_ok=True)
                test_file.write_text("test")
                test_file.unlink()
                args.download_path = new_path
                console.print("[green]Download path set successfully.[/green]")
                menu_logger.info(f"Set download path to: {args.download_path}")
            except Exception as e:
                warning_msg = f"Invalid download path: {e}. Keeping current path."
                console.print(f"[yellow]Warning: {warning_msg}[/yellow]")
                menu_logger.warning(warning_msg)
            save_options(args)
        elif choice == '3':
            min_str = Prompt.ask("Enter min issue number", default=str(args.min) if args.min else "")
            try:
                args.min = int(min_str) if min_str else None
                menu_logger.info(f"Set min issue to: {args.min}")
            except Exception as e:
                warning_msg = f"Invalid min issue number: {e}. Keeping current value."
                console.print(f"[yellow]Warning: {warning_msg}[/yellow]")
                menu_logger.warning(warning_msg)
            save_options(args)
        elif choice == '4':
            max_str = Prompt.ask("Enter max issue number", default=str(args.max) if args.max else "")
            try:
                args.max = int(max_str) if max_str else None
                menu_logger.info(f"Set max issue to: {args.max}")
            except Exception as e:
                warning_msg = f"Invalid max issue number: {e}. Keeping current value."
                console.print(f"[yellow]Warning: {warning_msg}[/yellow]")
                menu_logger.warning(warning_msg)
            save_options(args)
        elif choice == '5':
            results_str = Prompt.ask("Enter number of results", default=str(args.results))
            try:
                args.results = int(results_str) if results_str else 15
                if args.results < 1:
                    args.results = 15
                    warning_msg = "Number of results must be at least 1. Setting to 15."
                    console.print(f"[yellow]Warning: {warning_msg}[/yellow]")
                    menu_logger.warning(warning_msg)
                menu_logger.info(f"Set results to: {args.results}")
            except Exception as e:
                warning_msg = f"Invalid number of results: {e}. Keeping current value."
                console.print(f"[yellow]Warning: {warning_msg}[/yellow]")
                menu_logger.warning(warning_msg)
            save_options(args)
        elif choice == '6':
            args.verbose = not args.verbose
            console.print(f"Verbose output set to {args.verbose}")
            menu_logger.info(f"Set verbose output to: {args.verbose}")
            save_options(args)
        elif choice == '7':
            args.use_aria2c = not args.use_aria2c
            if args.use_aria2c and not is_aria2c_available():
                warning_msg = "aria2c not found. This option will have no effect."
                console.print(f"[yellow]Warning: {warning_msg}[/yellow]")
                menu_logger.warning(warning_msg)
            console.print(f"Use aria2c set to {args.use_aria2c}")
            menu_logger.info(f"Set use_aria2c to: {args.use_aria2c}")
            save_options(args)
        else:
            console.print("[yellow]Invalid choice. Please try again.[/yellow]")
            menu_logger.warning(f"Invalid option choice: {choice}")

def handle_interrupted_downloads(download_path: Path, verbose: bool):
    menu_logger.info(f"Handling interrupted downloads in: {download_path}")
    
    try:
        console.print(f"[bold green]Scanning for interrupted downloads in {download_path}...[/bold green]")
        
        # 确保目录存在
        if not download_path.exists():
            console.print(f"[yellow]Directory {download_path} does not exist. Creating it...[/yellow]")
            menu_logger.info(f"Creating directory: {download_path}")
            try:
                download_path.mkdir(parents=True, exist_ok=True)
                menu_logger.info(f"Created directory: {download_path}")
            except Exception as e:
                error_msg = f"Error creating directory: {e}"
                console.print(f"[bold red]{error_msg}[/bold red]")
                menu_logger.error(error_msg)
                return
        
        aria2_files = list(download_path.glob("*.aria2"))
        menu_logger.info(f"Found {len(aria2_files)} interrupted downloads")

        if not aria2_files:
            console.print("[yellow]No interrupted downloads (.aria2 files) found in this directory.[/yellow]")
            menu_logger.info("No interrupted downloads found")
            return

        aria2c_command = [
            "aria2c",
            "--continue",
        ]
        if not verbose:
            aria2c_command.append("--quiet")
        
        for aria2_file in aria2_files:
            aria2c_command.append(str(aria2_file))

        try:
            console.print(f"[bold green]Attempting to resume {len(aria2_files)} download(s) using aria2c...[/bold green]")
            menu_logger.info(f"Attempting to resume {len(aria2_files)} download(s) using aria2c")

            subprocess.run(aria2c_command, check=True, cwd=download_path)
            console.print("[bold green]aria2c resume process completed.[/bold green]")
            menu_logger.info("aria2c resume process completed successfully")
        except subprocess.CalledProcessError as e:
            error_msg = f"aria2c resume failed: {e}"
            console.print(f"[bold red]{error_msg}[/bold red]")
            menu_logger.error(error_msg)
        except FileNotFoundError:
            error_msg = "aria2c not found. Cannot resume downloads."
            console.print(f"[bold red]{error_msg}[/bold red]")
            menu_logger.error(error_msg)
        except Exception as e:
            error_msg = f"Error during resume: {e}"
            console.print(f"[bold red]{error_msg}[/bold red]")
            menu_logger.error(error_msg)
    except Exception as e:
        error_msg = f"Error handling interrupted downloads: {e}"
        console.print(f"[bold red]{error_msg}[/bold red]")
        menu_logger.error(error_msg)
