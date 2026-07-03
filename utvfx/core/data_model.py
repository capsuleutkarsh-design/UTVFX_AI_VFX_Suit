from utvfx.core.plugin_manager import PluginManager

# Dynamically fetch the nodes registry from the PluginManager
NODES_REGISTRY = PluginManager().get_registry()
