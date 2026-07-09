import sys
import os
import torch
import torch.nn as nn
from functools import partial

# Ensure the mock is loaded BEFORE importing MEMatte modeling
from . import detectron2_mock

from .modeling import MEMatte, MattingCriterion, Detail_Capture, ViT

def load_mematte(device="cuda"):
    embed_dim = 768
    num_heads = 12
    
    backbone = ViT(
        in_chans=4,
        img_size=512,
        patch_size=16,
        embed_dim=embed_dim,
        depth=12,
        num_heads=num_heads,
        drop_path_rate=0,
        window_size=14,
        mlp_ratio=4,
        qkv_bias=True,
        norm_layer=partial(nn.LayerNorm, eps=1e-6),
        window_block_indexes=[0,1,3,4,6,7,9,10],
        residual_block_indexes=[2, 5, 8, 11],
        use_rel_pos=True,
        out_feature="last_feat",
        topk = 0.25,
    )
    
    decoder = Detail_Capture(in_chans=768)
    
    criterion = MattingCriterion(
        losses=['unknown_l1_loss', 'known_l1_loss', 'loss_pha_laplacian', 'loss_gradient_penalty']
    )
    
    model = MEMatte(
        teacher_backbone=None,
        backbone=backbone,
        criterion=criterion,
        pixel_mean=[123.675 / 255., 116.280 / 255., 103.530 / 255.],
        pixel_std=[58.395 / 255., 57.120 / 255., 57.375 / 255.],
        input_format="RGB",
        size_divisibility=32,
        decoder=decoder,
        distill=True,
        distill_loss_ratio=1,
        token_loss_ratio=1
    )
    
    weights_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "MEMatte_ViTB_DIM.pth"))
    if not os.path.exists(weights_path):
        raise FileNotFoundError(f"MEMatte weights not found at {weights_path}")
        
    checkpoint = torch.load(weights_path, map_location=device, weights_only=False)
    if 'model' in checkpoint:
        state_dict = checkpoint['model']
    else:
        state_dict = checkpoint
        
    model.load_state_dict(state_dict, strict=False)
    model.to(device)
    model.eval()
    return model
