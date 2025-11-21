# ui.py

import json
from decimal import Decimal, InvalidOperation
import subprocess # Import subprocess for running external commands

from textual.app import App, ComposeResult
from textual.containers import Vertical, VerticalScroll, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Header, Footer, Input, Static, Label, SelectionList, ListView, ListItem
from textual.widgets.selection_list import Selection
from textual.message import Message
from textual.widget import Widget
from textual.reactive import reactive
from textual.validation import Number

# Import the business logic functions
import logic


# --- NEW WIDGETS ---
class PersonControl(Static):
    """A widget to control a person's share of an item."""

    def __init__(self, person_name: str) -> None:
        super().__init__(id=f"ctrl-{person_name}")
        self.person_name = person_name
        self.count = 0

    def compose(self) -> ComposeResult:
        yield Button(self.person_name, id="btn-add", classes="add-btn")
        yield Button("-", id="btn-sub", classes="sub-btn")
        yield Button("x", id="btn-remove-person", classes="remove-person-btn", variant="error")

    def update_count(self, count: int) -> None:
        self.count = count
        add_btn = self.query_one("#btn-add", Button)
        sub_btn = self.query_one("#btn-sub", Button)

        if count > 0:
            add_btn.label = f"{self.person_name} ({count})"
            add_btn.variant = "success"
            sub_btn.variant = "error"
        else:
            add_btn.label = self.person_name
            add_btn.variant = "default"
            sub_btn.variant = "default"


class BillItemRow(Static):
    """A widget for a single item in the bill."""

    def __init__(self, name: str, price: float, item_id: str) -> None:
        super().__init__()
        self.display_text = f"{name} (${price:.2f})"
        self.item_id = item_id

    def compose(self) -> ComposeResult:
        yield Label(self.display_text, classes="item-label")
        yield Button("x", id=f"del-{self.item_id}", classes="btn-del-row", variant="error")


# --- MODAL SCREEN (Unchanged) ---
class SelectPersonScreen(ModalScreen[list[str]]):
    """A modal screen to select one or more people from a list."""

    def __init__(self, people: list[str]) -> None:
        self.people = people
        super().__init__()

    def compose(self) -> ComposeResult:
        with Vertical(id="select_person_dialog"):
            yield SelectionList[str](
                *[Selection(person, person, id=person) for person in self.people]
            )
            with Vertical(id="dialog_buttons"):
                yield Button("Add Selected", variant="primary", id="add")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add":
            self.dismiss(self.query_one(SelectionList).selected)


# --- MAIN APP (Refactored to use logic.py) ---
class BillSplitterApp(App):
    """A Textual app to split a bill among a variable number of people."""

    CSS_PATH = "bill_splitter.css"
    BINDINGS = [
        ("d", "toggle_dark", "Toggle dark mode"),
        ("escape", "dismiss_modal", "Dismiss Modal"),
    ]

    selected_item_id = reactive(None)
    allocations = reactive({})
    item_prices = {}
    id_counter = 0

    def __init__(self):
        self.all_people = []
        super().__init__()

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="main-container"):
            # TOP: People
            with Vertical(id="left-pane-content"):
                with VerticalScroll(id="people_list"):
                    pass # People will be added here
                yield Button("Add Person", id="add_person", variant='primary')

            # BOTTOM: Items
            with Vertical(id="right-pane"):
                yield ListView(id="item-list")
                with Horizontal(id="input-row"):
                    yield Input(placeholder="Item Name", id="input-name")
                    yield Input(placeholder="Cost", id="input-price", validators=[Number(minimum=0.0)])
                    yield Button("+", id="btn-create")
        
        # Bottom Bar
        yield Input(placeholder="Other charges (e.g., 15/2)", id="other_charges")
        yield Horizontal(
            Button("Calculate", variant="primary", id="calculate", classes="action-button"),
            Button("Share", variant="success", id="share", classes="action-button"),
            classes="action-buttons-row"
        )
        yield Static(id="results")
        yield Footer()

    def on_mount(self) -> None:
        try:
            self.all_people = logic.load_people_from_file("people.json")
            people_list = self.query_one("#people_list")
            for person in self.all_people:
                people_list.mount(PersonControl(person))
        except FileNotFoundError:
            self.query_one("#results").update(
                "[bold red]Error: people.json not found.[/bold red]"
            )
        except json.JSONDecodeError:
            self.query_one("#results").update(
                "[bold red]Error: Could not decode people.json.[/bold red]"
            )

    def create_item(self, name: str, price: float) -> None:
        self.id_counter += 1
        new_id = f"item-{self.id_counter}"
        
        self.item_prices[new_id] = price
        self.allocations[new_id] = {p: 0 for p in self.all_people}
        
        list_view = self.query_one("#item-list", ListView)
        
        row_widget = BillItemRow(name, price, new_id)
        
        list_view.append(ListItem(row_widget, id=new_id))

    def _safe_eval_with_notify(self, expression: str) -> Decimal:
        """UI-aware wrapper for safe_decimal_eval that notifies on error."""
        try:
            return logic.safe_decimal_eval(expression)
        except logic.CalculationError:
            self.notify("⚠️ Invalid expression, using 0 instead.", severity="error")
            return Decimal(0)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id

        if "del-" in str(btn_id):
            item_id_to_delete = str(btn_id).replace("del-", "")
            
            self.allocations.pop(item_id_to_delete, None)
            self.item_prices.pop(item_id_to_delete, None)

            list_view = self.query_one("#item-list", ListView)
            try:
                list_view.get_child_by_id(item_id_to_delete).remove()
            except:
                pass

            if self.selected_item_id == item_id_to_delete:
                self.selected_item_id = None
                self.refresh_people_ui()
            
            event.stop()
            return

        if btn_id == "btn-create":
            name_inp = self.query_one("#input-name", Input)
            price_inp = self.query_one("#input-price", Input)
            
            if not name_inp.value or not price_inp.value:
                self.notify("Enter name and price", severity="error")
                return
            
            if not price_inp.is_valid:
                self.notify("Invalid price", severity="error")
                return

            self.create_item(name_inp.value, float(price_inp.value))
            
            name_inp.value = ""
            price_inp.value = ""
            name_inp.focus()
            return

        control = event.button.parent
        if isinstance(control, PersonControl):
            person = control.person_name
            if btn_id == "btn-remove-person":
                self.all_people.remove(person)
                for item_id in self.allocations:
                    if person in self.allocations[item_id]:
                        del self.allocations[item_id][person]
                
                control.remove()
                self.notify(f"Removed {person}")
                return

            if not self.selected_item_id:
                self.notify("Select an item first!", severity="warning")
                return

            if btn_id == "btn-add":
                self.allocations[self.selected_item_id][person] += 1
            elif btn_id == "btn-sub":
                if self.allocations[self.selected_item_id][person] > 0:
                    self.allocations[self.selected_item_id][person] -= 1
            
            self.refresh_people_ui()

        if event.button.id == "calculate":
            self.calculate_split()
        elif event.button.id == "add_person":
            self.action_add_person()
        elif event.button.id == "share":
            self.action_share_results()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item:
            self.selected_item_id = event.item.id
            self.refresh_people_ui()

    def refresh_people_ui(self) -> None:
        if not self.selected_item_id:
            for p in self.all_people:
                self.query_one(f"#ctrl-{p}", PersonControl).update_count(0)
            return
        
        counts = self.allocations[self.selected_item_id]
        for p in self.all_people:
            self.query_one(f"#ctrl-{p}", PersonControl).update_count(counts[p])

    def action_add_person(self) -> None:
        current_people = {p.person_name for p in self.query(PersonControl)}
        all_people_from_file = logic.load_people_from_file("people.json")
        available_people = [p for p in all_people_from_file if p not in current_people]

        if not available_people:
            self.query_one("#results").update(
                "[bold yellow]All people from people.json have been added.[/bold yellow]"
            )
            return

        def add_people_callback(people_names: list[str]) -> None:
            if people_names:
                people_list = self.query_one("#people_list")
                for name in people_names:
                    person_widget = PersonControl(person_name=name)
                    people_list.mount(person_widget)
                    self.all_people.append(name)
                
                # Add the new people to the allocations for each item
                for item_id in self.allocations:
                    for name in people_names:
                        self.allocations[item_id][name] = 0


        self.push_screen(SelectPersonScreen(available_people), add_people_callback)

    def calculate_split(self) -> None:
        results_widget = self.query_one("#results")
        
        other_charges_input = self.query_one("#other_charges", Input)
        other_charges = self._safe_eval_with_notify(other_charges_input.value)
        
        result = logic.calculate_split_from_items(
            self.item_prices, self.allocations, self.all_people, other_charges
        )
        
        if not result:
            results_widget.update("Nothing to calculate.")
            return

        if result.get("is_equal_split"):
            output = (
                f"[bold]Total: {result['grand_total']:.2f}[/bold]\n\n"
                f"[bold]Final amounts (charges split equally):[/bold]\n"
            )
            for name, amount in result["final_amounts"]:
                output += f"{name}: {amount:.2f}\n"
        else:
            output = (
                f"[bold]Subtotal: {result['subtotal']:.2f}\n"
                f"Grand Total: {result['grand_total']:.2f}[/bold]\n\n"
                f"[bold]Final amounts per person:[/bold]\n"
            )
            for name, amount in result["final_amounts"]:
                output += f"{name}: {amount:.2f}\n"

        results_widget.update(output)

    def action_share_results(self) -> None:
        """Shares the content of the results widget using termux-share."""
        results_widget = self.query_one("#results", Static)
        share_text = results_widget.renderable
        if share_text:
            try:
                # Convert Textual Renderable to plain text for sharing
                plain_text = str(share_text).replace("[bold]", "").replace("[/bold]", "")

                # Use subprocess to run the termux-share command
                subprocess.run(["termux-share", "-a", "send"], input=plain_text.encode(), check=True)
                self.notify("Results shared successfully!")
            except FileNotFoundError:
                self.notify(
                    "Error: 'termux-share' command not found. Are you in Termux?",
                    severity="error",
                )
            except subprocess.CalledProcessError as e:
                self.notify(f"Error sharing: {e}", severity="error")
            except Exception as e:
                self.notify(f"An unexpected error occurred: {e}", severity="error")
        else:
            self.notify("Nothing to share yet. Calculate the bill first!", severity="warning")

    def action_toggle_dark(self) -> None:
        self.dark = not self.dark

    def action_dismiss_modal(self) -> None:
        if isinstance(self.screen, ModalScreen):
            self.pop_screen()
