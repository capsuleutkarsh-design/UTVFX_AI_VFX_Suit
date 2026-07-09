import sys
import torch
import torch.nn as nn
from dataclasses import dataclass
from typing import Optional, List, Tuple

class Detectron2Mock:
    pass

# We will inject this into sys.modules
d2 = Detectron2Mock()

class Structures:
    class ImageList:
        def __init__(self, tensor, image_sizes):
            self.tensor = tensor
            self.image_sizes = image_sizes

class Layers:
    class CNNBlockBase(nn.Module):
        def __init__(self, in_channels, out_channels, stride):
            super().__init__()
            self.in_channels = in_channels
            self.out_channels = out_channels
            self.stride = stride

    class Conv2d(nn.Conv2d):
        def __init__(self, *args, **kwargs):
            norm = kwargs.pop("norm", None)
            activation = kwargs.pop("activation", None)
            super().__init__(*args, **kwargs)
            self.norm = norm
            self.activation = activation

        def forward(self, x):
            x = super().forward(x)
            if self.norm is not None:
                x = self.norm(x)
            if self.activation is not None:
                x = self.activation(x)
            return x

    class ChannelFirstLayerNorm(nn.Module):
        def __init__(self, normalized_shape, eps=1e-5):
            super().__init__()
            self.weight = nn.Parameter(torch.ones(normalized_shape))
            self.bias = nn.Parameter(torch.zeros(normalized_shape))
            self.eps = eps

        def forward(self, x):
            u = x.mean(1, keepdim=True)
            s = (x - u).pow(2).mean(1, keepdim=True)
            x = (x - u) / torch.sqrt(s + self.eps)
            x = self.weight[:, None, None] * x + self.bias[:, None, None]
            return x

    def get_norm(norm, out_channels):
        if norm is None:
            return None
        if isinstance(norm, str):
            if len(norm) == 0:
                return None
            if norm == "BN":
                return nn.BatchNorm2d(out_channels)
            if norm == "SyncBN":
                return nn.SyncBatchNorm(out_channels)
            if norm == "GN":
                return nn.GroupNorm(32, out_channels)
            if norm == "LN":
                return Layers.ChannelFirstLayerNorm(out_channels)
            raise ValueError(f"unknown norm: {norm}")
        return norm(out_channels)

    @dataclass
    class ShapeSpec:
        channels: Optional[int] = None
        height: Optional[int] = None
        width: Optional[int] = None
        stride: Optional[int] = None

class Modeling:
    class Backbone:
        class Fpn:
            @staticmethod
            def _assert_strides_are_log2_contiguous(strides):
                pass

class Config:
    class LazyCall:
        def __init__(self, target):
            self.target = target
        
        def __call__(self, *args, **kwargs):
            return self.target(*args, **kwargs)

# Mocking the modules
d2.structures = Structures
d2.layers = Layers
d2.modeling = Modeling
d2.modeling.backbone = Modeling.Backbone
d2.modeling.backbone.fpn = Modeling.Backbone.Fpn
d2.config = Config

sys.modules['detectron2'] = d2
sys.modules['detectron2.structures'] = Structures
sys.modules['detectron2.layers'] = Layers
sys.modules['detectron2.modeling'] = Modeling
sys.modules['detectron2.modeling.backbone'] = Modeling.Backbone
sys.modules['detectron2.modeling.backbone.fpn'] = Modeling.Backbone.Fpn
sys.modules['detectron2.config'] = Config

# Fairscale Mock
class FairscaleMock:
    pass
fs = FairscaleMock()
class NnMock:
    class CheckpointMock:
        @staticmethod
        def checkpoint_wrapper(module):
            return module
fs.nn = NnMock
fs.nn.checkpoint = NnMock.CheckpointMock
sys.modules['fairscale'] = fs
sys.modules['fairscale.nn'] = fs.nn
sys.modules['fairscale.nn.checkpoint'] = fs.nn.checkpoint
