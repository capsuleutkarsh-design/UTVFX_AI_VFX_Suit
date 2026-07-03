import os
import json
import importlib
import sys

class PluginManager:
    """
    Scans the plugins directory, loads plugin.json manifests, and provides 
    the central registry for node definitions and worker classes.
    """
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(PluginManager, cls).__new__(cls)
            cls._instance._init()
        return cls._instance
        
    def _init(self):
        self.plugins_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "plugins")
        self.registry = {}
        self.worker_classes = {}
        self._scan_plugins()
        
    def _scan_plugins(self):
        if not os.path.exists(self.plugins_dir):
            return
            
        for plugin_folder in os.listdir(self.plugins_dir):
            folder_path = os.path.join(self.plugins_dir, plugin_folder)
            if not os.path.isdir(folder_path):
                continue
                
            manifest_path = os.path.join(folder_path, "plugin.json")
            if not os.path.exists(manifest_path):
                continue
                
            try:
                with open(manifest_path, 'r', encoding='utf-8') as f:
                    manifest = json.load(f)
                    
                ptype = manifest.get("plugin_type")
                if not ptype:
                    print(f"[PluginManager] Warning: {plugin_folder}/plugin.json missing 'plugin_type'.")
                    continue
                    
                cat = manifest.get("category", "VFX NODE")
                
                # Dynamic node coloring by category
                color_map = {
                    "Compositing": "#3b82f6", # Blue
                    "AI Matting": "#ef4444",  # Red
                    "Tracking": "#10b981",    # Green
                    "Input/Output": "#8b5cf6",# Purple
                    "Color": "#f59e0b",       # Amber
                    "Utility": "#888888",     # Gray
                    "VFX NODE": "#f59e0b"
                }
                default_color = color_map.get(cat, "#f59e0b")
                
                # Store node definition for UI
                self.registry[ptype] = {
                    "name": manifest.get("name", ptype),
                    "category": cat,
                    "color": manifest.get("color", default_color),
                    "inputs": manifest.get("inputs", []),
                    "outputs": manifest.get("outputs", []),
                    "parameters": manifest.get("parameters", [])
                }
                
                # Store worker class info for execution engine
                worker_module = manifest.get("worker_module")
                worker_class = manifest.get("worker_class")
                if worker_module and worker_class:
                    self.worker_classes[ptype] = (worker_module, worker_class)
                    
            except Exception as e:
                print(f"[PluginManager] Error loading manifest from {plugin_folder}: {e}")
                
    def get_registry(self):
        """Returns the dictionary needed by data_model.py"""
        return self.registry
        
    def get_worker_class(self, plugin_type):
        """
        Dynamically imports and returns the worker class for the given plugin_type.
        Returns None if not found or import fails.
        """
        if plugin_type not in self.worker_classes:
            return None
            
        module_name, class_name = self.worker_classes[plugin_type]
        try:
            # Ensure the project root is in sys.path
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            if project_root not in sys.path:
                sys.path.insert(0, project_root)
                
            module = importlib.import_module(module_name)
            return getattr(module, class_name)
        except Exception as e:
            print(f"[PluginManager] Error importing worker {class_name} from {module_name}: {e}")
            return None
