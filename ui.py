# ui.py

import json
from decimal import Decimal, InvalidOperation
import subprocess  # Import subprocess for running external commands
from PIL import Image, ImageOps  # For image handling and preprocessing
import os  # For file operations
from PyQt6.QtWidgets import QApplication, QFileDialog  # Replace tkinter imports
import pytesseract  # For OCR
import cv2  # OpenCV for advanced image preprocessing
import numpy as np  # For array manipulations

from textual.app import App, ComposeResult
from textual.containers import Vertical, VerticalScroll, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Header, Footer, Input, Static, Label, SelectionList
from textual.widgets.selection_list import Selection
from textual.message import Message
from textual.widget import Widget

# Import the business logic functions
import logic


# --- NEW WIDGET FOR PERSON INPUT (Unchanged) ---
class PersonInput(Widget):
    """A widget containing a person's name, input, and a remove button."""

    class Remove(Message):
        """Message posted when the remove button is clicked."""

        def __init__(self, to_remove: Widget) -> None:
            self.to_remove = to_remove
            super().__init__()

    def __init__(self, name: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.person_name = name
        self.input = Input(placeholder="0.00")

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield self.input
            yield Button("✕", variant="error", classes="remove-button")

    def on_mount(self) -> None:
        self.border_title = self.person_name

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.post_message(self.Remove(self))

    @property
    def value(self) -> str:
        return self.query_one(Input).value

    def focus_input(self) -> None:
        self.input.focus()


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

    def __init__(self):
        self.all_people = []
        super().__init__()

    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(
            Label("Enter amounts for each person:"),
            VerticalScroll(id="people_list"),
            Button("Add Person", id="add_person", variant='primary'),
            Input(placeholder="Other charges (e.g., 15/2)", id="other_charges"),
            Button("Upload Bill Image", id="upload_image", variant="primary"),
            Static(id="uploaded_image_preview"),  # Placeholder for image preview
            # Wrap Calculate and Share buttons in a Horizontal container
            # Added a class "action-buttons-row" for more specific CSS targeting
            Horizontal(
                Button("Calculate", variant="primary", id="calculate", classes="action-button"),
                Button("Share", variant="success", id="share", classes="action-button"),
                classes="action-buttons-row"  # Use a class for this Horizontal container
            ),
            Static(id="results"),
            id="main_container",
        )
        yield Footer()

    def on_mount(self) -> None:
        try:
            self.all_people = logic.load_people_from_file("people.json")
        except FileNotFoundError:
            self.query_one("#results").update(
                "[bold red]Error: people.json not found.[/bold red]"
            )
        except json.JSONDecodeError:
            self.query_one("#results").update(
                "[bold red]Error: Could not decode people.json.[/bold red]"
            )

    def _safe_eval_with_notify(self, expression: str) -> Decimal:
        """UI-aware wrapper for safe_decimal_eval that notifies on error."""
        try:
            return logic.safe_decimal_eval(expression)
        except logic.CalculationError:
            self.notify("⚠️ Invalid expression, using 0 instead.", severity="error")
            return Decimal(0)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "calculate":
            self.calculate_split()
        elif event.button.id == "add_person":
            self.action_add_person()
        elif event.button.id == "share":  # Handle the new share button
            self.action_share_results()
        elif event.button.id == "upload_image":
            self.action_upload_image()

    def action_add_person(self) -> None:
        current_people = {inp.border_title for inp in self.query(PersonInput)}
        available_people = [p for p in self.all_people if p not in current_people]

        if not available_people:
            self.query_one("#results").update(
                "[bold yellow]All people from people.json have been added.[/bold yellow]"
            )
            return

        def add_people_callback(people_names: list[str]) -> None:
            if people_names:
                people_list = self.query_one("#people_list")
                last_input = None
                for name in people_names:
                    person_widget = PersonInput(name=name)
                    people_list.mount(person_widget)
                    last_input = person_widget
                if last_input:
                    last_input.focus_input()

        self.push_screen(SelectPersonScreen(available_people), add_people_callback)

    def on_person_input_remove(self, message: PersonInput.Remove) -> None:
        message.to_remove.remove()
        self.query_one("#results").update("Person removed.")

    def calculate_split(self) -> None:
        results_widget = self.query_one("#results")
        try:
            # 1. Gather data from UI widgets
            person_widgets = self.query(PersonInput)
            person_amounts = [
                (w.border_title, self._safe_eval_with_notify(w.value))
                for w in person_widgets
            ]
            other_charges_input = self.query_one("#other_charges", Input)
            other_charges = self._safe_eval_with_notify(other_charges_input.value)

            # 2. Call the business logic function
            result = logic.calculate_split_bill(person_amounts, other_charges)

            # 3. Format and display the result from the logic function
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

        except InvalidOperation:
            results_widget.update(
                "[bold red]Error: Invalid number or expression.[/bold red]"
            )

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

    def action_upload_image(self) -> None:
        """Handles uploading, preprocessing, performing OCR, and displaying the bill image."""
        try:
            # Open a file dialog to select an image
            app = QApplication([])  # Create a QApplication instance
            file_path, _ = QFileDialog.getOpenFileName(
                None,
                "Select Bill Image",
                "",
                "Image Files (*.png *.jpg *.jpeg *.bmp *.gif)"
            )
            app.quit()  # Close the QApplication instance

            if not file_path:  # If no file is selected
                self.notify("No file selected.", severity="warning")
                return

            image = cv2.imread(file_path, cv2.IMREAD_GRAYSCALE)

            # Preprocess the image
            # 1. Apply thresholding to make text stand out
            _, image = cv2.threshold(image, 128, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)

            # 2. Apply dilation to connect broken text
            kernel = np.ones((2, 2), np.uint8)
            image = cv2.dilate(image, kernel, iterations=1)

            image = cv2.resize(image, (image.shape[1] * 2, image.shape[0] * 2), interpolation=cv2.INTER_LINEAR)

            # Perform OCR with table recognition mode
            config = "--psm 6"  # Assume a single uniform block of text
            extracted_text = pytesseract.image_to_string(image, config=config)

            # Update the UI with the extracted text (if required for debugging)
            # self.query_one("#uploaded_image_preview", Static).update(
            #     f"[bold]Uploaded Image:[/bold]\n{file_path}\n\n"
            #     f"[bold]Extracted Text:[/bold]\n{extracted_text}"
            # )
            self.notify("Image uploaded and OCR completed successfully!", severity="success")
        except Exception as e:
            self.notify(f"Error uploading or processing image: {e}", severity="error")

    def action_toggle_dark(self) -> None:
        self.dark = not self.dark

    def action_dismiss_modal(self) -> None:
        if isinstance(self.screen, ModalScreen):
            self.pop_screen()
