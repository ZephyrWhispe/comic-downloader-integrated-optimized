import re
from pathlib import Path
from typing import Dict, Optional

from rich.console import Console
from rich.prompt import Prompt

from .download import download_comics
from .getinfo import GetComics
from .logger import main_logger

console = Console()


def extract_year(filename: str) -> str:
    match = re.search(r"\((\d{4})\)", filename)
    if match:
        return match.group(1)
    return "Unknown"


def rename_file(path: Path, comic: str, issue: str, year: str) -> Path:
    new_name = f"{comic} #{issue} ({year}).cbz"
    new_path = path.parent / new_name
    try:
        path.rename(new_path)
        main_logger.info("Renamed file: %s -> %s", path.name, new_name)
        return new_path
    except Exception as exc:
        error_msg = f"Error renaming file: {exc}"
        console.print(f"[bold red]{error_msg}[/bold red]")
        main_logger.error(error_msg)
        return path


def find_exact_issue(results: Dict[str, str], comic: str, issue: int) -> Optional[str]:
    target = f"{comic} #{issue}".lower()
    banned = ["vol", "collection", "omnibus", "tpb", "incursion", "special", "annual", "w.i.p"]
    for url, title in results.items():
        normalized_title = title.lower()
        if any(word in normalized_title for word in banned):
            continue
        if not normalized_title.startswith(comic.lower()):
            continue
        if target in normalized_title:
            return url
    return None


async def search_issue_pages(comic: str, issue: int, max_pages: int = 5) -> Optional[str]:
    comics = GetComics(f"{comic} #{issue}", 15, False)
    for _ in range(max_pages):
        await comics.find_pages()
        await comics.get_download_links()
        post = find_exact_issue(comics.comic_links, comic, issue)
        if post:
            return post
        comics.page_links.clear()
        comics.comic_links.clear()
    return None


async def download_series(comic: str, download_path: Path, verbose: bool, use_aria2c: bool) -> None:
    rng = Prompt.ask("Issue range (example 1-10)", default="1-10")
    if "-" not in rng:
        console.print("[bold red]Invalid range.[/bold red]")
        main_logger.warning("Invalid issue range format")
        return

    try:
        start, end = map(int, rng.split("-"))
    except ValueError:
        console.print("[bold red]Invalid range format.[/bold red]")
        main_logger.warning("Invalid issue range format")
        return

    downloaded_files = []
    last_year = None

    console.print(f"[green]Starting download of {comic} issues {start}-{end}[/green]")
    main_logger.info("Starting series download: %s issues %s-%s", comic, start, end)

    for issue in range(start, end + 1):
        console.print(f"\n[cyan]Searching for issue #{issue}...[/cyan]")
        main_logger.info("Searching for issue #%s", issue)

        post = await search_issue_pages(comic, issue)
        if not post:
            console.print(f"[yellow]Issue #{issue} not found or failed to resolve.[/yellow]")
            main_logger.warning("Issue #%s not found", issue)
            continue

        comic_links = {post: f"{comic} #{issue}"}

        console.print(f"[green]Downloading issue #{issue}...[/green]")
        main_logger.info("Downloading issue #%s", issue)

        download_comics(
            comic_links,
            download_path,
            verbose,
            prompt=False,
            use_aria2c=use_aria2c,
            rename_downloaded_files=False,
        )

        for file in download_path.iterdir():
            if file.is_file() and file.suffix in [".cbz", ".cbr"]:
                if f"{comic}" in file.name and f"#{issue}" in file.name:
                    downloaded_files.append(file)
                    year = extract_year(file.name)
                    if year != "Unknown":
                        last_year = year
                    break

    if downloaded_files:
        console.print("\n[bold green]All downloaded issues:[/bold green]")
        for i, path in enumerate(downloaded_files, start=1):
            console.print(f"{i}. {path.name}")

        rename = Prompt.ask("Rename all downloaded files? (y/n)", default="y")
        if rename.lower() == "y":
            issue_number = start
            for path in downloaded_files:
                year = extract_year(path.name) or last_year or "Unknown"
                new_path = rename_file(path, comic, str(issue_number), year)
                downloaded_files[issue_number - start] = new_path
                issue_number += 1

            console.print("\n[green]Files renamed successfully![/green]")
            main_logger.info("Files renamed successfully")
    else:
        console.print("[yellow]No issues downloaded.[/yellow]")
        main_logger.warning("No issues downloaded")

    console.print("\n[green]Series download complete.[/green]")
    main_logger.info("Series download complete")
    Prompt.ask("Press any key to return to main menu")
