"""Command-line interface for DocuSync."""

import typer
from typing import Optional, List
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich.panel import Panel
from rich import box

from app.database import init_db, SessionLocal
from app.file_scanner import (
    scan_all_drives, scan_drive, index_document
)
from app.search import (
    search_documents, get_documents_by_drive,
    get_document_statistics
)
from app.sync import analyze_drive_sync, sync_drives
from app.file_scanner import find_duplicates, calculate_space_savings
from app.corrupted_pdf import (
    find_corrupted_pdfs, get_corrupted_pdf_report,
    remove_corrupted_pdf
)

app = typer.Typer(help="DocuSync - Document synchronization and search")
console = Console()


def format_size(size_bytes: int) -> str:
    """Format bytes to human-readable size."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


@app.command()
def scan(
    drive: Optional[str] = typer.Option(
        None, "--drive", "-d",
        help="Drive letter to scan (e.g., C, D). "
              "If not specified, scans all drives."
    ),
    extract_text: bool = typer.Option(
        True, "--extract-text/--no-extract-text",
        help="Extract text content from documents"
    )
):
    """Scan drives for documents and index them."""
    console.print("\n[bold cyan]Scanning for documents...[/bold cyan]\n")

    # Initialize database
    init_db()

    if drive:
        # Scan specific drive
        console.print(f"Scanning drive {drive.upper()}:\\...")
        try:
            files = scan_drive(drive.upper())
            console.print(f"Found {len(files)} documents")

            with console.status("[bold green]Indexing documents...") as status:
                indexed = 0
                for file_path in files:
                    doc = index_document(file_path, extract_text=extract_text)
                    if doc:
                        indexed += 1
                    status.update(
                        f"Indexed {indexed}/{len(files)} documents..."
                    )

            console.print(f"\n[green]Successfully indexed {indexed} documents[/green]")

        except Exception as e:
            console.print(f"[red]Error scanning drive: {e}[/red]")
    else:
        # Scan all drives
        console.print("Scanning all drives...")
        drives_data = scan_all_drives()

        total_files = sum(len(files) for files in drives_data.values())
        console.print(f"Found {total_files} documents across "
                      f"{len(drives_data)} drives")

        with console.status("[bold green]Indexing documents...") as status:
            total_indexed = 0
            for drive_letter, files in drives_data.items():
                status.update(
                    f"Indexing drive {drive_letter}:\\ "
                    f"({total_indexed}/{total_files} indexed)..."
                )
                for file_path in files:
                    doc = index_document(file_path,
                                         extract_text=extract_text)
                    if doc:
                        total_indexed += 1

        console.print(f"\n[green]Successfully indexed "
                      f"{total_indexed} documents[/green]")


@app.command()
def list_documents(
    drive: Optional[str] = typer.Option(
        None, "--drive", "-d",
        help="Filter by drive letter"
    ),
    directory: Optional[str] = typer.Option(
        None, "--directory", "--dir",
        help="Filter by directory"
    )
):
    """List all indexed documents."""
    db = SessionLocal()
    try:
        if drive:
            documents = db.query(Document).filter(
                Document.drive == drive.upper()
            ).all()
        elif directory:
            documents = db.query(Document).filter(
                Document.directory == directory
            ).all()
        else:
            documents = db.query(Document).order_by(
                Document.name
            ).all()

        if not documents:
            console.print("[yellow]No documents found[/yellow]")
            return

        table = Table(title="Indexed Documents", box=box.ROUNDED)
        table.add_column("Name", style="cyan")
        table.add_column("Path", style="dim")
        table.add_column("Author", style="magenta")
        table.add_column("Size", justify="right")
        table.add_column("Drive", justify="center")
        table.add_column("MD5", style="dim")

        for doc in documents:
            table.add_row(
                doc.name[:50],
                doc.file_path[:60] + "..." if len(doc.file_path) > 60
                else doc.file_path,
                doc.author or "N/A",
                format_size(doc.size),
                doc.drive,
                doc.md5_hash[:8] + "..."
            )

        console.print(table)
        console.print(f"\n[dim]Total: {len(documents)} documents[/dim]")
    finally:
        db.close()


@app.command()
def duplicates():
    """Find and manage duplicate documents."""
    console.print("\n[bold cyan]Finding duplicates...[/bold cyan]\n")

    duplicates_dict = find_duplicates()

    if not duplicates_dict:
        console.print("[green]No duplicates found![/green]")
        return

    total_duplicates = sum(len(docs) - 1 for docs in duplicates_dict.values())
    console.print(f"[yellow]Found {total_duplicates} duplicate files "
                  f"({len(duplicates_dict)} unique files have duplicates)[/yellow]\n")

    # Show duplicates
    table = Table(title="Duplicate Files", box=box.ROUNDED)
    table.add_column("MD5", style="dim")
    table.add_column("Name", style="cyan")
    table.add_column("Path", style="dim")
    table.add_column("Size", justify="right")
    table.add_column("Drive", justify="center")

    for hash_val, docs in list(duplicates_dict.items())[:20]:
        for doc in docs:
            table.add_row(
                hash_val[:8] + "...",
                doc.name[:40],
                doc.file_path[:50] + "..." if len(doc.file_path) > 50
                else doc.file_path,
                format_size(doc.size),
                doc.drive
            )

    console.print(table)

    if len(duplicates_dict) > 20:
        console.print(f"\n[dim]... and {len(duplicates_dict) - 20} more "
                      f"groups[/dim]")

    # Ask user about deletion
    if Confirm.ask("\nDo you want to delete duplicates?"):
        preferred_location = Prompt.ask(
            "Enter preferred directory or drive to keep files in",
            default="C:\\"
        )

        # Calculate space savings
        space_saved = calculate_space_savings(
            duplicates_dict, preferred_location
        )

        console.print(f"\n[yellow]You would save: "
                      f"{format_size(space_saved)}[/yellow]")

        if Confirm.ask("Proceed with deletion?"):
            db = SessionLocal()
            deleted_count = 0
            try:
                for hash_val, docs in duplicates_dict.items():
                    # Find document to keep
                    keep_doc = None
                    for doc in docs:
                        if preferred_location.lower() in doc.directory.lower():
                            keep_doc = doc
                            break

                    if not keep_doc:
                        keep_doc = docs[0]

                    # Delete others
                    deleted_files = []
                    for doc in docs:
                        if doc.id != keep_doc.id:
                            try:
                                import os
                                if os.path.exists(doc.file_path):
                                    os.remove(doc.file_path)
                                    deleted_files.append((doc.file_path, doc.size))
                                db.delete(doc)
                                deleted_count += 1
                            except Exception as e:
                                console.print(
                                    f"[red]Error deleting {doc.file_path}: {e}[/red]"
                                )

                    # Log deletion activity
                    if deleted_files:
                        from app.reports import log_activity
                        total_space = sum(size for _, size in deleted_files)
                        log_activity(
                            activity_type="delete",
                            description=f"Deleted {len(deleted_files)} duplicate files",
                            document_path=deleted_files[0][0] if deleted_files else None,
                            space_saved_bytes=total_space,
                            operation_count=len(deleted_files),
                            user_id=None
                        )

                db.commit()

                console.print(f"\n[green]Deleted {deleted_count} duplicate files[/green]")
                console.print(f"[green]Space saved: {format_size(space_saved)}[/green]")
            finally:
                db.close()


@app.command()
def sync(
    drive1: str = typer.Option(..., "--drive1", "-d1", help="First drive"),
    drive2: str = typer.Option(..., "--drive2", "-d2", help="Second drive"),
    dry_run: bool = typer.Option(
        True, "--dry-run/--no-dry-run",
        help="Show what would be done without actually copying"
    )
):
    """Synchronize files between two drives."""
    console.print("\n[bold cyan]Analyzing drive synchronization...[/bold cyan]\n")

    analysis = analyze_drive_sync(drive1.upper(), drive2.upper())

    # Display analysis
    panel_content = f"""
[cyan]Drive 1:[/cyan] {analysis['drive1']}:\\
[cyan]Drive 2:[/cyan] {analysis['drive2']}:\\

[yellow]Missing on {analysis['drive1']}:\\[/yellow] {analysis['missing_on_drive1']} files
[yellow]Missing on {analysis['drive2']}:\\[/yellow] {analysis['missing_on_drive2']} files

[magenta]Space needed on {analysis['drive1']}:\\[/magenta] {format_size(analysis['space_needed_drive1'])}
[magenta]Space needed on {analysis['drive2']}:\\[/magenta] {format_size(analysis['space_needed_drive2'])}
"""

    console.print(Panel(panel_content, title="Sync Analysis",
                        box=box.ROUNDED))

    if analysis['missing_on_drive1'] == 0 and \
       analysis['missing_on_drive2'] == 0:
        console.print("\n[green]Drives are already synchronized![/green]")
        return

    if not dry_run:
        if Confirm.ask("\nProceed with synchronization?"):
            console.print("\n[bold green]Synchronizing...[/bold green]")
            result = sync_drives(
                drive1.upper(), drive2.upper(),
                dry_run=False
            )

            console.print(f"\n[green]Copied {result['copied_to_drive1']} "
                          f"files to {drive1.upper()}:\\[/green]")
            console.print(f"[green]Copied {result['copied_to_drive2']} "
                          f"files to {drive2.upper()}:\\[/green]")

            if result['errors']:
                console.print(f"\n[red]Errors: {len(result['errors'])}[/red]")
                for error in result['errors'][:10]:
                    console.print(f"[dim]{error}[/dim]")
    else:
        console.print("\n[yellow]Dry run mode - no files were copied[/yellow]")
        console.print("Use --no-dry-run to perform actual synchronization")


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query"),
    drive: Optional[str] = typer.Option(
        None, "--drive", "-d", help="Filter by drive"
    ),
    search_content: bool = typer.Option(
        True, "--content/--no-content",
        help="Search in document content"
    )
):
    """Search documents by name, author, or content."""
    console.print(f"\n[bold cyan]Searching for: '{query}'[/bold cyan]\n")

    results = search_documents(
        query,
        search_name=True,
        search_author=True,
        search_content=search_content,
        drive=drive.upper() if drive else None
    )

    if not results:
        console.print("[yellow]No documents found[/yellow]")
        return

    table = Table(title=f"Search Results ({len(results)} found)",
                  box=box.ROUNDED)
    table.add_column("Name", style="cyan")
    table.add_column("Author", style="magenta")
    table.add_column("Path", style="dim")
    table.add_column("Size", justify="right")
    table.add_column("Drive", justify="center")

    for doc in results:
        table.add_row(
            doc.name[:50],
            doc.author or "N/A",
            doc.file_path[:60] + "..." if len(doc.file_path) > 60
            else doc.file_path,
            format_size(doc.size),
            doc.drive
        )

    console.print(table)


@app.command()
def stats():
    """Show document statistics."""
    stats_data = get_document_statistics()

    panel_content = f"""
[cyan]Total Documents:[/cyan] {stats_data['total_documents']}
[cyan]Total Size:[/cyan] {format_size(stats_data['total_size_bytes'])}
[cyan]Duplicates:[/cyan] {stats_data['duplicates_count']}

[magenta]By Drive:[/magenta]
"""
    for drive, count in stats_data['by_drive'].items():
        panel_content += f"  {drive}:\\ - {count} documents\n"

    panel_content += "\n[yellow]By Type:[/yellow]\n"
    for file_type, count in stats_data['by_type'].items():
        panel_content += f"  {file_type} - {count} documents\n"

    console.print(Panel(panel_content, title="Document Statistics",
                        box=box.ROUNDED))


@app.command()
def reports(
    report_type: str = typer.Argument(
        ..., help="Report type: activities, space-saved, operations"
    ),
    activity_type: Optional[str] = typer.Option(
        None, "--type", "-t", help="Filter by activity type"
    ),
    start_date: Optional[str] = typer.Option(
        None, "--start", "-s", help="Start date (YYYY-MM-DD)"
    ),
    end_date: Optional[str] = typer.Option(
        None, "--end", "-e", help="End date (YYYY-MM-DD)"
    ),
    limit: int = typer.Option(
        50, "--limit", "-l", help="Maximum number of results"
    )
):
    """Show reports."""
    from app.reports import (
        get_activities, get_space_saved_report, get_operations_report
    )
    from datetime import datetime

    if report_type == "activities":
        activities = get_activities(activity_type=activity_type, limit=limit)
        if not activities:
            console.print("[yellow]No activities found[/yellow]")
            return

        table = Table(title=f"Recent Activities ({len(activities)} shown)",
                      box=box.ROUNDED)
        table.add_column("Type", style="cyan")
        table.add_column("Description", style="dim")
        table.add_column("Space Saved", justify="right")
        table.add_column("Operations", justify="right")
        table.add_column("Date", style="magenta")

        for activity in activities:
            table.add_row(
                activity.activity_type,
                activity.description[:60] + "..."
                if len(activity.description) > 60
                else activity.description,
                format_size(activity.space_saved_bytes),
                str(activity.operation_count),
                activity.created_at.strftime("%Y-%m-%d %H:%M:%S")
            )
        console.print(table)

    elif report_type == "space-saved":
        start = None
        end = None

        if start_date:
            try:
                start = datetime.strptime(start_date, "%Y-%m-%d")
            except ValueError:
                console.print("[red]Invalid start date format. Use YYYY-MM-DD[/red]")
                return

        if end_date:
            try:
                end = datetime.strptime(end_date, "%Y-%m-%d")
            except ValueError:
                console.print("[red]Invalid end date format. Use YYYY-MM-DD[/red]")
                return

        report = get_space_saved_report(start_date=start, end_date=end)

        panel_content = f"""
[cyan]Total Space Saved:[/cyan] {format_size(report['total_space_saved_bytes'])}
[cyan]Total Operations:[/cyan] {report['total_operations']}

[yellow]Breakdown by Activity Type:[/yellow]
"""

        for activity_type, data in report['breakdown'].items():
            panel_content += (
                f"\n  {activity_type}:\n"
                f"    Space Saved: {format_size(data['space_saved_bytes'])}\n"
                f"    Operations: {data['operation_count']}\n"
            )

        console.print(Panel(panel_content, title="Space Saved Report",
                            box=box.ROUNDED))

    elif report_type == "operations":
        start = None
        end = None

        if start_date:
            try:
                start = datetime.strptime(start_date, "%Y-%m-%d")
            except ValueError:
                console.print("[red]Invalid start date format. Use YYYY-MM-DD[/red]")
                return

        if end_date:
            try:
                end = datetime.strptime(end_date, "%Y-%m-%d")
            except ValueError:
                console.print("[red]Invalid end date format. Use YYYY-MM-DD[/red]")
                return

        report = get_operations_report(start_date=start, end_date=end)

        if not report:
            console.print("[yellow]No operations found[/yellow]")
            return

        table = Table(title="Operations by Type", box=box.ROUNDED)
        table.add_column("Activity Type", style="cyan")
        table.add_column("Activity Count", justify="right")
        table.add_column("Total Operations", justify="right")

        for activity_type, data in report.items():
            table.add_row(
                activity_type,
                str(data['activity_count']),
                str(data['total_operations'])
            )

        console.print(table)

    else:
        console.print(
            f"[red]Unknown report type: {report_type}[/red]\n"
            f"Available types: activities, space-saved, operations"
        )


@app.command()
def corrupted_pdfs(
    drive: Optional[str] = typer.Option(
        None, "--drive", "-d", help="Filter by drive letter"
    ),
    remove: bool = typer.Option(
        False, "--remove", "-r",
        help="Remove corrupted PDF files"
    ),
    dry_run: bool = typer.Option(
        True, "--dry-run/--no-dry-run",
        help="Show what would be done without actually removing"
    )
):
    """Find and manage corrupted PDF files."""
    console.print("\n[bold cyan]Scanning for corrupted PDFs...[/bold cyan]\n")

    report = get_corrupted_pdf_report(drive=drive)

    if report["total_corrupted"] == 0:
        console.print("[green]No corrupted PDFs found![/green]")
        return

    # Display report
    panel_content = f"""
[yellow]Total Corrupted PDFs:[/yellow] {report['total_corrupted']}
[yellow]Total Size:[/yellow] {format_size(report['total_size_bytes'])}

[magenta]By Drive:[/magenta]
"""
    for drive_letter, count in report['by_drive'].items():
        panel_content += f"  {drive_letter}:\\ - {count} corrupted PDFs\n"

    console.print(Panel(panel_content, title="Corrupted PDF Report",
                        box=box.ROUNDED))

    # Show list of corrupted files
    if report["files"]:
        table = Table(title="Corrupted PDF Files",
                      box=box.ROUNDED)
        table.add_column("Name", style="cyan")
        table.add_column("Path", style="dim")
        table.add_column("Size", justify="right")
        table.add_column("Drive", justify="center")

        for file_info in report["files"][:20]:  # Show first 20
            table.add_row(
                file_info["name"][:50],
                file_info["file_path"][:60] + "..."
                if len(file_info["file_path"]) > 60
                else file_info["file_path"],
                format_size(file_info["size"]),
                file_info["drive"]
            )

        console.print(table)

        if len(report["files"]) > 20:
            console.print(
                f"\n[dim]... and {len(report['files']) - 20} more "
                f"corrupted PDFs[/dim]"
            )

    # Ask about removal
    if remove:
        space_saved = report["total_size_bytes"]
        console.print(
            f"\n[yellow]You would save: "
            f"{format_size(space_saved)}[/yellow]"
        )

        if dry_run:
            console.print(
                "\n[yellow]Dry run mode - no files will be removed[/yellow]"
            )
            console.print(
                "Use --no-dry-run to actually remove corrupted PDFs"
            )
        else:
            if Confirm.ask("\nProceed with removing corrupted PDFs?"):
                removed_count = 0
                failed_count = 0

                for file_info in report["files"]:
                    if remove_corrupted_pdf(
                        file_info["file_path"], user_id=None
                    ):
                        removed_count += 1
                    else:
                        failed_count += 1

                console.print(
                    f"\n[green]Removed {removed_count} corrupted PDF files[/green]"
                )
                if failed_count > 0:
                    console.print(
                        f"[yellow]Failed to remove {failed_count} files[/yellow]"
                    )
                console.print(
                    f"[green]Space saved: {format_size(space_saved)}[/green]"
                )


def main():
    """Main entry point."""
    app()


if __name__ == "__main__":
    main()

