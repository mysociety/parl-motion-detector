from pathlib import Path

import rich_click as click

from .process import (
    delete_current_year_parquets,
    move_to_package,
    render_historical,
    render_latest,
    render_year,
)
from .snapshot import generate_all_snapshots

data_dir = Path(__file__).parent.parent.parent / "data"


@click.group()
def cli():
    pass


def main():
    cli()


@cli.command()
def refresh_snapshot():
    """
    Refresh motion snapshots for tests
    """
    generate_all_snapshots()


@cli.command()
def process_current_year():
    """
    Update data for current year
    """
    render_latest(data_dir)
    move_to_package(data_dir)


@cli.command()
def process_historical():
    """
    Regenerate parquets for historical information
    """
    render_historical(data_dir)
    move_to_package(data_dir)


@cli.command()
def recreate_package():
    """
    Just create the overal parquets for packages
    """
    move_to_package(data_dir)


@cli.command()
@click.argument("year", type=int)
def process_year(year: int):
    """
    Process an arbitary year
    """
    render_year(data_dir, year=year)
    move_to_package(data_dir)


@cli.command()
def remove_current_year_parquets():
    """
    Remove all parquets for the current year (so not cached every day)
    """
    delete_current_year_parquets(data_dir)


if __name__ == "__main__":
    main()
