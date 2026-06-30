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
        self.project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.settings_file = os.path.join(self.project_root, "settings.json")
        
        # Default settings
        self.default_settings = {
            "output_dir": os.path.join(self.project_root, "outputs"),
            "cache_dir": os.path.join(self.project_root, "temp"),
            "log_dir": os.path.join(self.project_root, "logs")
        }
        
        self.settings = self.default_settings.copy()
        self.load_settings()

    def load_settings(self):
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    for k, v in loaded.items():
                        if k in self.settings:
                            self.settings[k] = v
            except Exception as e:
                print(f"Failed to load settings: {e}")
        
        # Ensure directories exist
        for k in ["output_dir", "cache_dir", "log_dir"]:
            path = self.settings.get(k)
            if path and not os.path.exists(path):
                try:
                    os.makedirs(path, exist_ok=True)
                except:
                    pass

    def save_settings(self):
        try:
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=4)
            # Ensure new directories exist
            for k in ["output_dir", "cache_dir", "log_dir"]:
                path = self.settings.get(k)
                if path and not os.path.exists(path):
                    try:
                        os.makedirs(path, exist_ok=True)
                    except:
                        pass
        except Exception as e:
            print(f"Failed to save settings: {e}")

    def get(self, key, default=None):
        return self.settings.get(key, default)

    def set(self, key, value):
        self.settings[key] = value
        self.save_settings()

    def get_cache_dir(self, node_id=""):
        base_cache = self.get("cache_dir")
        if not node_id:
            return base_cache
        node_cache = os.path.join(base_cache, str(node_id))
        os.makedirs(node_cache, exist_ok=True)
        return node_cache
        
    def clear_cache(self):
        import shutil
        cache_dir = self.get("cache_dir")
        if os.path.exists(cache_dir):
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
