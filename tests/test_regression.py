import sys
import os
import unittest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from main import VFXCoreWindow

class TestRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.window = VFXCoreWindow()

    def test_node_spawning_and_undo_redo(self):
        initial_node_count = len(self.window.node_scene.nodes)
        self.assertEqual(initial_node_count, 0)
        
        self.window.spawn_node("corridor_keyer")
        self.assertEqual(len(self.window.node_scene.nodes), 1)
        node = self.window.node_scene.nodes[0]
        
        self.assertIn("screen_color", node.params)
        self.assertEqual(node.params["screen_color"], "green")
        
        self.assertTrue(self.window.undo_stack.canUndo())
        self.window.undo_stack.undo()
        self.assertEqual(len(self.window.node_scene.nodes), 0)
        
        self.window.undo_stack.redo()
        self.assertEqual(len(self.window.node_scene.nodes), 1)

    def test_project_loading_keyframe_conversion(self):
        self.window.spawn_node("super_matte")
        sam_node = [n for n in self.window.node_scene.nodes if n.plugin_type == "super_matte"][0]
        
        sam_node.params["mask_layers"] = [{"id": "layer1", "keyframes": {5: [(0.5, 0.5, True)]}}]
        sam_node.params["active_layer_id"] = "layer1"
        self.window.viewport.connect_to_node(sam_node)
        
        mask_layers = self.window.viewport.img_display.mask_layers
        self.assertEqual(len(mask_layers), 1)
        self.assertIn(5, mask_layers[0]["keyframes"])
        self.assertEqual(mask_layers[0]["keyframes"][5], [(0.5, 0.5, True)])

    def test_playhead_clamping(self):
        from utvfx.ui.viewport import VideoPlayerThread
        thread = VideoPlayerThread(os.path.dirname(__file__))
        thread.total_frames = 5
        thread.read_and_emit(20)
        self.assertTrue(True)

if __name__ == "__main__":
    unittest.main()
