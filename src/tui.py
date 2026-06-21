import time

from rich.live import Live
from rich.table import Table

table = Table()
table.add_column("Row ID")
table.add_column("Description")
table.add_column("Level")

with Live(table, refresh_per_second=4):
    for row in range(12):
        time.sleep(0.4)
        table.add_row(f"{row}", f"description {row}", "[red]ERROR")
