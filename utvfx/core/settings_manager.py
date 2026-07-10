import os
import json

class SettingsManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SettingsManager, cls).__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self):
        # Determine project root
        self.project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.settings_file = os.path.join(self.project_root, "settings.json")
        self.current_project_name = "Untitled"
        self.settings = {}
        self.load_settings()
        self.set_project_name(self.current_project_name)

    def set_project_name(self, project_name):
        old_project = getattr(self, "current_project_name", None)
        self.current_project_name = project_name
        project_dir = os.path.join(self.project_root, "workspace", "projects", project_name)
        
        # Cleanup Untitled folder
        if old_project == "Untitled" and project_name != "Untitled":
            untitled_dir = os.path.join(self.project_root, "workspace", "projects", "Untitled")
            if os.path.exists(untitled_dir) and not os.path.exists(project_dir):
                import shutil
                try:
                    from utvfx.core.logger import shutdown_logger
                    shutdown_logger()
                    shutil.move(untitled_dir, project_dir)
                except Exception:
                    pass
                    
        self.settings["output_dir"] = os.path.join(project_dir, "outputs")
        self.settings["cache_dir"] = os.path.join(project_dir, "cache")
        self.settings["log_dir"] = os.path.join(project_dir, "logs")
        self.settings["temp_dir"] = os.path.join(project_dir, "temp")
        
        self.save_settings()
        
        try:
            from utvfx.core.logger import update_logger_directory
            update_logger_directory()
        except ImportError:
            pass

    def load_settings(self):
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    for k, v in loaded.items():
                        # Don't overwrite dynamic paths with old static ones
                        if k not in ["output_dir", "cache_dir", "log_dir", "temp_dir"]:
                            self.settings[k] = v
            except Exception as e:
                print(f"Failed to load settings: {e}")
        self._ensure_dirs()

    def save_settings(self):
        try:
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=4)
            self._ensure_dirs()
        except Exception as e:
            print(f"Failed to save settings: {e}")

    def _ensure_dirs(self):
        for k in ["output_dir", "cache_dir", "log_dir", "temp_dir"]:
            path = self.settings.get(k)
            if path and not os.path.exists(path):
                try:
                    os.makedirs(path, exist_ok=True)
                except Exception:
                    pass

    def get(self, key, default=None):
        return self.settings.get(key, default)

    def set(self, key, value):
        self.settings[key] = value
        self.save_settings()

    def get_cache_dir(self, node_id=""):
        base_cache = self.get("cache_dir")
        if not base_cache:
            base_cache = os.path.join(self.project_root, "workspace", "temp")
        if not node_id:
            return base_cache
        node_cache = os.path.join(base_cache, str(node_id))
        os.makedirs(node_cache, exist_ok=True)
        return node_cache
        
    def clear_cache(self):
        import shutil
        cache_dir = self.get("cache_dir")
        if cache_dir and os.path.exists(cache_dir):
            try:
                for item in os.listdir(cache_dir):
                    item_path = os.path.join(cache_dir, item)
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                    else:
                        os.remove(item_path)
                return True
            except Exception as e:
                print(f"Error clearing cache: {e}")
                return False
        return True
