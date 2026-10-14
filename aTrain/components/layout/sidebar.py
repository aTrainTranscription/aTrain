from nicegui import ui


def sidebar():
    with ui.left_drawer().classes("bg-gray-100") as drawer_handle:
        nav_button(icon="headphones", text="Transcribe", path="/")
        nav_button(icon="inventory_2", text="Archive", path="/archive")
        nav_button(icon="memory", text="Models", path="/models")
        nav_button(icon="tune", text="Advanced Settings", path="/advanced")
        nav_button(icon="help_outline", text="FAQ", path="/faq")
        ui.separator()
        nav_button(icon="info_outline", text="About", path="/about")
    return drawer_handle


def nav_button(icon: str, text: str, path: str):
    is_current_page = ui.context.client.page.path == path
    button_color = "gray-200" if is_current_page else "white"
    with ui.link(target=path).classes("w-full"):
        with ui.button(color=button_color) as nav_item:
            nav_item.props("text-color=black align=left flat no-caps")
            nav_item.classes("w-full rounded-lg")
            ui.icon(icon).classes("text-xl text-gray-600 mr-4")
            ui.label(text).classes("text-base font-medium")
