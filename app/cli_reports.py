"""CLI commands for reports."""

import typer
from typing import Optional
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box
from datetime import datetime

from app.reports import (
    get_activities, get_space_saved_report,
    get_operations_report
)

app = typer.Typer(help="DocuSync Reports")
console = Console()


def format_size(size_bytes: int) -> str:
    """Format bytes to human-readable size."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


@app.command()
def activities(
    activity_type: Optional[str] = typer.Option(
        None, "--type", "-t", help="Filter by activity type"
    ),
    limit: int = typer.Option(
        50, "--limit", "-l", help="Maximum number of results"
    )
):
    """Show activity report."""
    console.print("\n[bold cyan]Activity Report[/bold cyan]\n")

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


@app.command()
def space_saved(
    start_date: Optional[str] = typer.Option(
        None, "--start", "-s", help="Start date (YYYY-MM-DD)"
    ),
    end_date: Optional[str] = typer.Option(
        None, "--end", "-e", help="End date (YYYY-MM-DD)"
    )
):
    """Show space saved report."""
    console.print("\n[bold cyan]Space Saved Report[/bold cyan]\n")

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


@app.command()
def operations(
    start_date: Optional[str] = typer.Option(
        None, "--start", "-s", help="Start date (YYYY-MM-DD)"
    ),
    end_date: Optional[str] = typer.Option(
        None, "--end", "-e", help="End date (YYYY-MM-DD)"
    )
):
    """Show operations report."""
    console.print("\n[bold cyan]Operations Report[/bold cyan]\n")

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


def main():
    """Main entry point."""
    app()


if __name__ == "__main__":
    main()

