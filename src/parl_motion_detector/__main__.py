from pathlib import Path

import rich_click as click
from mysoc_validator.models.transcripts import Chamber

from .process import (
    delete_current_year_parquets,
    move_to_package,
    render_historical,
    render_latest,
    render_policy_days,
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
@click.option("--chamber", type=str, default=Chamber.COMMONS)
def process_current_year(chamber: Chamber = Chamber.COMMONS):
    """
    Update data for current year
    """
    chamber = Chamber(chamber)
    render_latest(data_dir, chamber=chamber)
    move_to_package(data_dir)


@cli.command()
@click.option("--chamber", type=str, default=Chamber.COMMONS)
def process_historical(chamber: Chamber = Chamber.COMMONS):
    """
    Regenerate parquets for historical information
    """
    chamber = Chamber(chamber)
    render_historical(data_dir, chamber=chamber)
    move_to_package(data_dir)


@cli.command()
@click.option("--chamber", type=str, default=Chamber.COMMONS)
def process_historical_policy_days(chamber: Chamber = Chamber.COMMONS):
    """
    Regenerate parquets for historical information
    """
    chamber = Chamber(chamber)
    render_policy_days(data_dir, chamber=chamber)
    move_to_package(data_dir)


@cli.command()
def recreate_package():
    """
    Just create the overal parquets for packages
    """
    move_to_package(data_dir)


@cli.command()
@click.argument("year", type=int)
@click.option("--chamber", type=str, default=Chamber.COMMONS)
def process_year(year: int, chamber: Chamber = Chamber.COMMONS):
    """
    Process an arbitary year
    """
    chamber = Chamber(chamber)
    render_year(data_dir, year=year, chamber=chamber)
    move_to_package(data_dir)


@cli.command()
def remove_current_year_parquets():
    """
    Remove all parquets for the current year (so not cached every day)
    """
    delete_current_year_parquets(data_dir)


if __name__ == "__main__":
    main()
