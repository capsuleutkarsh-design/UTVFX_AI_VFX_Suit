import os
import sys
import importlib
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
plugins_dir = os.path.join(project_root, "plugins")
print(f"Plugins dir: {plugins_dir}")

if plugins_dir not in sys.path:
    sys.path.insert(0, plugins_dir)

for plugin_name in os.listdir(plugins_dir):
    plugin_path = os.path.join(plugins_dir, plugin_name)
    if os.path.isdir(plugin_path):
        ui_file = os.path.join(plugin_path, "ui.py")
        if os.path.exists(ui_file):
            print(f"Found ui.py for {plugin_name}")
            try:
                module = importlib.import_module(f"{plugin_name}.ui")
                if hasattr(module, "get_ui"):
                    print(f"  Has get_ui, calling...")
                    w = module.get_ui()
                elif hasattr(module, "PluginUI"):
                    print(f"  Has PluginUI, calling...")
                    w = module.PluginUI()
                else:
                    print(f"  No UI class")
            except Exception as e:
                import traceback
                print(f"  Exception: {e}")
                traceback.print_exc()
        else:
            print(f"No ui.py for {plugin_name}")

