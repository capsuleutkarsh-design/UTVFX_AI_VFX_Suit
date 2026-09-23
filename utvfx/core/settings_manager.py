import json
import os
import logging
import re
import shutil

# Folders the user picks in Settings. Everything else is derived from these.
USER_FOLDER_KEYS = ("workspace_dir", "default_output_dir")
# Per-project folders, recomputed whenever the project changes; never loaded from disk.
DERIVED_KEYS = ("output_dir", "cache_dir", "log_dir", "temp_dir")


def safe_project_name(name):
    """A project name that is safe as a folder name on Windows."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", (name or "").strip()).strip(". ")
    return name or "Untitled"


def link_tree(src, dst):
    """Copy a folder tree using hard links where possible: instant and no extra disk on one drive."""
    def link_or_copy(s, d):
        try:
            os.link(s, d)
        except OSError:
            shutil.copy2(s, d)
    shutil.copytree(src, dst, copy_function=link_or_copy, dirs_exist_ok=True)


class SettingsManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SettingsManager, cls).__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self):
        import sys

        # Smart Pathing: Detect if running from compiled EXE or from Python source
        if getattr(sys, 'frozen', False):
            # Compiled EXE: Use AppData to avoid permission errors on Windows
            appdata_base = os.environ.get('APPDATA', os.path.expanduser('~'))
            self.project_root = os.path.join(appdata_base, "ContourVFX")
            os.makedirs(self.project_root, exist_ok=True)
            self.models_dir = os.path.join(os.path.dirname(sys.executable), "models")
        else:
            # Source: Use the repository root
            self.project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            os.makedirs(self.project_root, exist_ok=True)
            self.models_dir = os.path.join(self.project_root, "models")

        os.makedirs(self.models_dir, exist_ok=True)

        self.settings_file = os.path.join(self.project_root, "settings.json")
        self.current_project_name = "Untitled"
        self.settings = {}
        self.load_settings()
        self.set_project_name(self.current_project_name)

    # ---- folders -----------------------------------------------------------
    @property
    def workspace_dir(self):
        return self.settings.get("workspace_dir") or os.path.join(self.project_root, "workspace")

    def project_dir(self, project_name=None):
        return os.path.join(self.workspace_dir, "projects", safe_project_name(project_name or self.current_project_name))

    def _derive_folders(self):
        project_dir = self.project_dir()
        out_base = self.settings.get("default_output_dir")
        self.settings["output_dir"] = (os.path.join(out_base, self.current_project_name) if out_base
                                       else os.path.join(project_dir, "outputs"))
        self.settings["cache_dir"] = os.path.join(project_dir, "cache")
        self.settings["log_dir"] = os.path.join(project_dir, "logs")
        self.settings["temp_dir"] = os.path.join(project_dir, "temp")

    def set_project_name(self, project_name, carry_cache=True):
        """Switch the project whose folders the app uses.

        With carry_cache, the previous project's renders are brought along when the
        new project has none yet: "Untitled" is moved, a named project is hard-linked
        (Save As keeps both projects' renders).
        """
        project_name = safe_project_name(project_name)
        old_name = getattr(self, "current_project_name", None)
        old_dir = self.project_dir(old_name) if old_name else None
        self.current_project_name = project_name
        new_dir = self.project_dir()

        if carry_cache and old_dir and old_name != project_name and os.path.isdir(old_dir) \
                and not os.path.exists(new_dir):
            try:
                if old_name == "Untitled":
                    shutil.move(old_dir, new_dir)
                else:
                    link_tree(os.path.join(old_dir, "cache"), os.path.join(new_dir, "cache"))
            except Exception as e:
                print(f"Warning: could not bring renders from {old_name} to {project_name}: {e}")

        self._derive_folders()
        self.save_settings()

        try:
            from utvfx.core.logger import update_logger_directory
            update_logger_directory()
        except ImportError:
            pass

    # ---- persistence -------------------------------------------------------
    def load_settings(self):
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                for k, v in loaded.items():
                    if k not in DERIVED_KEYS:
                        self.settings[k] = v
            except Exception as e:
                print(f"Failed to load settings: {e}")
        self._derive_folders()
        self._ensure_dirs()

    def save_settings(self):
        try:
            tmp = self.settings_file + ".tmp"
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=4)
            os.replace(tmp, self.settings_file)
            self._ensure_dirs()
        except Exception as e:
            print(f"Failed to save settings: {e}")

    def _ensure_dirs(self):
        for k in DERIVED_KEYS:
            path = self.settings.get(k)
            if path and not os.path.exists(path):
                try:
                    os.makedirs(path, exist_ok=True)
                except Exception:
                    logging.getLogger(__name__).debug("Ignored error", exc_info=True)

    def get(self, key, default=None):
        return self.settings.get(key, default)

    def set(self, key, value):
        self.settings[key] = value
        if key in USER_FOLDER_KEYS:
            self._derive_folders()
        self.save_settings()

    def get_cache_dir(self, node_id=""):
        base_cache = self.get("cache_dir") or os.path.join(self.workspace_dir, "temp")
        if not node_id:
            return base_cache
        node_cache = os.path.join(base_cache, str(node_id))
        os.makedirs(node_cache, exist_ok=True)
        return node_cache

    def clear_cache(self):
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
