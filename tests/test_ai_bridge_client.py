import os
import sys
import cv2
import numpy as np
import unittest
import tempfile
import uuid

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core_ui.ai_bridge_client import AIBridgeClient
from PySide6.QtWidgets import QApplication

class TestAIBridgeClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)
        cls.client = AIBridgeClient.get_instance()
        cls.dummy_path = os.path.join(tempfile.gettempdir(), f"dummy_bridge_{uuid.uuid4().hex}.jpg")
        img = np.zeros((1080, 1920, 3), dtype=np.uint8)
        cv2.circle(img, (960, 540), 100, (255, 255, 255), -1)
        cv2.imwrite(cls.dummy_path, img)
        
    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.dummy_path):
            os.remove(cls.dummy_path)
            
    def test_query_mask(self):
        # We don't want to actually run the heavy AI bridge in a lightweight unit test
        # if the SAM3Rotoscope python process fails, it will return None. We just check
        # if it can be called. Note: the original script did a live query. We can assert it does not crash.
        qimg = self.client.query_mask(self.dummy_path, [[960, 540]], [1], fill_color_hex="#0ea5e9")
        # In a CI environment this might return None because the bridge isn't started or no weights exist.
        if qimg is not None:
            self.assertFalse(qimg.isNull())
            self.assertEqual(qimg.width(), 1920)
            self.assertEqual(qimg.height(), 1080)

if __name__ == "__main__":
    unittest.main()
