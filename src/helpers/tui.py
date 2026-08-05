from collections.abc import Callable
from blessed import Terminal


def wait_for_selection(
    terminal: Terminal, options_count: int, render: Callable[[int], None]
) -> int | None:
    """Little helper here for all the tui menu waiting for a navigation option to be selected"""
    selected_idx = 0
    render(selected_idx)
    with terminal.cbreak(), terminal.hidden_cursor():
        while True:
            k = terminal.inkey()
            k_name = k.name if k.name else k
            match k_name:
                case "q":
                    return None
                case "j" | "KEY_DOWN":
                    selected_idx = min(selected_idx + 1, options_count - 1)
                case "k" | "KEY_UP":
                    selected_idx = max(selected_idx - 1, 0)
                case "KEY_ENTER" | "\n" | "\r":
                    return selected_idx
                case _:
                    continue
            render(selected_idx)
