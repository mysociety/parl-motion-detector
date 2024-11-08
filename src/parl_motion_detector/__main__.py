import rich_click as click

from .snapshot import generate_all_snapshots


@click.group()
def cli():
    pass


def main():
    cli()


@cli.command()
def refresh_snapshot():
    generate_all_snapshots()


if __name__ == "__main__":
    main()
