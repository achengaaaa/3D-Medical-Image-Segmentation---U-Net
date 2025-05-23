# -*- coding: utf-8 -*-
"""hw2_q2.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1xqdt7e8GEMuQYZsf_AeTBKYELXBOMkqB

## Setup imports
"""

#!unzip /content/drive/MyDrive/SpleenDataset.zip

#!pip install monai --no-deps

import wandb

# Log in to W&B (run this cell and paste your API key when prompted)
wandb.login()

import torch
from tqdm import tqdm
import numpy as np
import os
import random
import warnings
# print out the version of transformers
import transformers
print(f"Transformers version: {transformers.__version__}")


import monai

from monai.utils import first, set_determinism
from monai.transforms import (
    AsDiscrete,
    AsDiscreted,
    EnsureChannelFirstd,
    Compose,
    CropForegroundd,
    LoadImaged,
    Orientationd,
    RandCropByPosNegLabeld,
    SaveImaged,
    ScaleIntensityRanged,
    Spacingd,
    Invertd, SaveImage,
)
from monai.handlers.utils import from_engine
from monai.networks.nets import UNet
from monai.networks.layers import Norm
from monai.metrics import DiceMetric, compute_average_surface_distance, compute_hausdorff_distance
from monai.losses import DiceLoss
from monai.inferers import sliding_window_inference
from monai.data import CacheDataset, DataLoader, Dataset, decollate_batch
import torch
import matplotlib.pyplot as plt
import shutil
import os
import glob

"""## Set train/validation/test data filepath"""

# from google.colab import drive
# drive.mount('/content/drive')

data_dir = "SpleenDataset"
train_images = sorted(glob.glob(os.path.join(data_dir,"train" ,"image", "*.nii.gz")))
train_labels = sorted(glob.glob(os.path.join(data_dir,"train" , "mask", "*.nii.gz")))
train_data_dicts = [{"image": image_name, "mask": label_name} for image_name, label_name in zip(train_images, train_labels)]

val_images = sorted(glob.glob(os.path.join(data_dir,"val" ,"image", "*.nii.gz")))
val_labels = sorted(glob.glob(os.path.join(data_dir,"val" , "mask", "*.nii.gz")))
val_data_dicts = [{"image": image_name, "mask": label_name} for image_name, label_name in zip(val_images, val_labels)]

test_images = sorted(glob.glob(os.path.join(data_dir,"test" ,"image", "*.nii.gz")))
test_labels = sorted(glob.glob(os.path.join(data_dir,"test" , "mask", "*.nii.gz")))
test_data_dicts = [{"image": image_name, "mask": label_name} for image_name, label_name in zip(test_images, test_labels)]

"""## Setup data augmentation

For data augmentation, here are the basic requirements:

1. `LoadImaged` loads the spleen CT images and labels from NIfTI format files.
1. `EnsureChannelFirstd` ensures the original data to construct "channel first" shape.
1. `ScaleIntensityRanged` clips the CT's data format, HU value, into a certain range (-57,164) and normalize it to (0,1)
1. `CropForegroundd` removes all zero borders to focus on the valid body area of the images and labels.
1. `RandCropByPosNegLabeld` randomly crop patch samples from big image based on pos / neg ratio.  
The image centers of negative samples must be in valid body area.

You can try more data augmentation techniques to further improve the performance.
"""


from monai.metrics import DiceMetric, HausdorffDistanceMetric, SurfaceDistanceMetric
from monai.transforms import (
    Compose, LoadImaged, EnsureChannelFirstd, Spacingd, Orientationd,
    ScaleIntensityRanged, CropForegroundd, SpatialCropd, SpatialPadd,
    AsDiscrete, SaveImaged, RandCropByPosNegLabeld
)
from tqdm import tqdm
from torch.utils.data import DataLoader
import numpy as np
import torch

# Reduced sizes
TRAIN_PATCH_SIZE = (128, 128, 128)  # Smaller training patches
VAL_PATCH_SIZE =(256,256,256)
VAL_SIZE = (128, 128, 32)        # Smaller validation/test volumes
MIN_DEPTH = 32

# Training transforms (assuming you have something like this)

train_transforms = Compose([
    LoadImaged(keys=["image", "mask"]),
    EnsureChannelFirstd(keys=["image", "mask"]),
    Spacingd(keys=["image", "mask"], pixdim=(1.0, 1.0, 1.0), mode=("bilinear", "nearest")),
    Orientationd(keys=["image", "mask"], axcodes="RAS"),
    CropForegroundd(keys=["image", "mask"], source_key="image"),
    ScaleIntensityRanged(
        keys=["image"],
        a_min=-57,
        a_max=164,
        b_min=0.0,
        b_max=1.0,
        clip=True,
    ),
    RandCropByPosNegLabeld(
        keys=["image", "mask"],
        label_key="mask",
        spatial_size=TRAIN_PATCH_SIZE,
        pos=1,
        neg=1,
        num_samples=1,
        image_key="image",
        image_threshold=0,
    ),
    SpatialPadd(keys=["image", "mask"], spatial_size=TRAIN_PATCH_SIZE),
])

# Validation transforms with reduced size
val_transforms = Compose([
    LoadImaged(keys=["image", "mask"]),
    EnsureChannelFirstd(keys=["image", "mask"]),  # Add this to ensure [C, H, W, D]
    ScaleIntensityRanged(
        keys=["image"],
        a_min=-57,
        a_max=164,
        b_min=0.0,
        b_max=1.0,
        clip=True,
    )
])

import os
import torch
from torch.utils.data import Dataset, DataLoader
import SimpleITK as sitk

class CT_Dataset(Dataset):
    def __init__(self, dataset_path, transform=None, split='test'):
        self.data = dataset_path
        self.transform = transform
        # self.data_list = []
        #
        # for data in os.listdir(data_dir):
        #     self.data_list.append(os.path.join(data_dir,data))

        self.split = split
        # if not self.data:
        #     raise ValueError(f"No data found for split '{split}'. Check file paths.")

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx):
      data_dict = self.data[idx]
      if self.transform:
          transformed_data = self.transform(data_dict)
          if isinstance(transformed_data, list):
              data_dict = transformed_data[0]
          else:
              data_dict = transformed_data
          print(f"{self.split} sample {idx} - Image shape: {data_dict['image'].shape}, "
                f"Mask shape: {data_dict['mask'].shape}, "
                f"Mask unique: {torch.unique(data_dict['mask'])}")
      return data_dict





class CT_Dataset_new(Dataset):
    def __init__(self, dataset_path, transform=None, split='test'):
        self.data = dataset_path
        self.transform = transform
        self.data_list = []

        for data in os.listdir(data_dir):
            self.data_list.append(os.path.join(data_dir,data))


        # self.split = split
        # if not self.data:
        #     raise ValueError(f"No data found for split '{split}'. Check file paths.")

    def __len__(self):
        return len(self.data_list)

    def __getitem__(self, idx):
        data_path, label_path = self.data_list[idx]
        image,label = self.read_data(data_path,label_path)
        p5 = np.percentile(image.flatten(),0.5)
        p95=np.percentile(image.flattend(),99.5)
        image=image.clip(min=p5,max=p95)
        image = (image-image.min()) / (image.max()-image.min())

        image = self.transform(image)

        return image,label

    def read_data(self,data_path,label_path):
        nifti_image = sitk.ReadImage(data_path)
        image_arr = sitk.GetArrayFromImage(nifti_image)
        nifti_label = sitk.ReadImage(label_path)
        label_arr = sitk.GetArrayFromImage(nifti_label)
        return image_arr,label_arr

# DataLoaders (assuming CT_Dataset, train_data_dicts, val_data_dicts, test_data_dicts are defined)
train_ds = CT_Dataset(train_data_dicts, train_transforms, split='train')
train_loader = DataLoader(train_ds, batch_size=1, shuffle=True, num_workers=0, pin_memory=True)

val_ds = CT_Dataset(val_data_dicts, val_transforms, split='val')
val_loader = DataLoader(val_ds, batch_size=1, shuffle=False, num_workers=0, pin_memory=True)

test_ds = CT_Dataset(test_data_dicts, val_transforms, split='test')
test_loader = DataLoader(test_ds, batch_size=1, shuffle=False, num_workers=0, pin_memory=True)

"""# Implement a 3D UNet for segmentation task

We give a possible network structure here, and you can modify it for a stronger performance.

In the block ```double_conv```, you can implement the following structure：

| Layer |
|-------|
| Conv3d |
| BatchNorm3d |
| PReLU |
| Conv3d |
| BatchNorm3d |
| PReLU |


In the overall UNet structure, you can implement the following structure. ```conv_down``` and ```conv_up``` refers to the function block you defined above.

| Layer | Input Channel | Output Channel |
|-------|-------------|--------------|
| conv_down1 | 1 | 16 |
| maxpool | 16 | 16 |
| conv_down2 | 16 | 32 |
| maxpool | 32 | 32 |
| conv_down3 | 32 | 64 |
| maxpool | 64 | 64 |
| conv_down4 | 64 | 128 |
| maxpool | 128 | 128 |
| conv_down5 | 128 | 256 |
| upsample | 256 | 256 |
| conv_up4 | 128+256 | 128 |
| upsample | 128 | 128 |
| conv_up3 | 64+128 | 64 |
| upsample | 64 | 32 |
| conv_up4 | 32+64 | 32 |
| upsample | 32 | 32 |
| conv_up4 | 16+32 | 16 |
| conv_out | 16 | 2 |

"""

import torch
import torch.nn as nn

def double_conv(in_channels, out_channels):
    return nn.Sequential(
        nn.Conv3d(in_channels, out_channels, kernel_size=3, padding=1),  # Fixed: use out_channels, added kernel_size
        nn.BatchNorm3d(out_channels),
        nn.PReLU(),
        nn.Conv3d(out_channels, out_channels, kernel_size=3, padding=1),  # Fixed: use out_channels, added kernel_size
        nn.BatchNorm3d(out_channels),
        nn.PReLU()
    )

class UNet(nn.Module):

    def __init__(self,n_classes):
        super().__init__()

        self.conv_down1 = double_conv(1,16)
        self.conv_down2 = double_conv(16,32)
        self.conv_down3 = double_conv(32,64)
        self.conv_down4 = double_conv(64,128)
        self.conv_down5 = double_conv(128,256)
        self.maxpool = nn.MaxPool3d(2)

        self.upsample = nn.Upsample(scale_factor=2,mode='trilinear',align_corners=True)
        self.conv_up4 = double_conv(128+256,128)
        self.conv_up3 = double_conv(64+128,64)
        self.conv_up2 = double_conv(64+32,32)
        self.conv_up1 = double_conv(32+16,16)
        self.last_conv = nn.Conv3d(16,n_classes,kernel_size=1)


    def forward(self, x):
        conv1 = self.conv_down1(x)
        x = self.maxpool(conv1)

        conv2 = self.conv_down2(x)
        x = self.maxpool(conv2)

        conv3 = self.conv_down3(x)
        x = self.maxpool(conv3)

        conv4 = self.conv_down4(x)
        x = self.maxpool(conv4)

        x = self.conv_down5(x)

        x=self.upsample(x)
        x=torch.cat([x,conv4],dim=1)
        x=self.conv_up4(x)
        x=self.upsample(x)
        x=torch.cat([x,conv3],dim=1)
        x=self.conv_up3(x)
        x=self.upsample(x)
        x=torch.cat([x,conv2],dim=1)
        x=self.conv_up2(x)
        x=self.upsample(x)
        x=torch.cat([x,conv1],dim=1)
        x=self.conv_up1(x)
        out=self.last_conv(x)
        return out

"""## Create Model, Loss, Optimizer"""

# standard PyTorch program style: create UNet, DiceLoss and Adam optimizer
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model = UNet(n_classes=2).to(device)
loss_function =DiceLoss(to_onehot_y=True, softmax=True)
optimizer = torch.optim.Adam(model.parameters(), lr=1e-4)
dice_metric = DiceMetric(include_background=False, reduction="mean")

"""## Define your training/val/test loop"""



# Model Definition
from monai.networks.nets import UNet
from monai.networks.layers import Norm

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model = UNet(
    spatial_dims=3,
    in_channels=1,    # Match input channels
    out_channels=2,   # Match number of classes
    channels=(16, 32, 64, 128, 256),
    strides=(2, 2, 2, 2),
    num_res_units=2,
    norm=Norm.BATCH,
).to(device)

loss_function = DiceLoss(to_onehot_y=True, softmax=True)
optimizer = torch.optim.Adam(model.parameters(), lr=1e-4)

# Training Loop
max_epochs = 500
val_interval = 20
best_metric = -1
best_metric_epoch = -1
epoch_loss_values = []
metric_values = []
post_pred = Compose([AsDiscrete(argmax=True, to_onehot=2)])
post_label = Compose([AsDiscrete(to_onehot=2)])
dice_metric = DiceMetric(include_background=False, reduction="mean")

# Model Definition
from monai.networks.nets import UNet
from monai.networks.layers import Norm

wandb.init(
    project="spleen-segmentation",  # Name your project
    config={
        "learning_rate": 1e-4,
        "epochs": 50,
        "batch_size": 1,
        "patch_size": TRAIN_PATCH_SIZE,
        "architecture": "3D UNet",
    }
)


device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model = UNet(
    spatial_dims=3,
    in_channels=1,    # Match input channels
    out_channels=2,   # Match number of classes
    channels=(16, 32, 64, 128, 256),
    strides=(2, 2, 2, 2),
    num_res_units=2,
    norm=Norm.BATCH,
).to(device)

loss_function = DiceLoss(to_onehot_y=True, softmax=True)
optimizer = torch.optim.Adam(model.parameters(), lr=1e-4)

# Training Loop
max_epochs = 600
val_interval = 20
best_metric = -1
best_metric_epoch = -1
epoch_loss_values = []
metric_values = []
post_pred = Compose([AsDiscrete(argmax=True, to_onehot=2)])
post_label = Compose([AsDiscrete(to_onehot=2)])
dice_metric = DiceMetric(include_background=False, reduction="mean")

def train():
    early_stop_dice_threshold = 0.6
    for epoch in range(max_epochs):
        model.train()
        epoch_loss = 0
        train_dice = 0
        step = 0
        with tqdm(train_loader, desc=f"Epoch {epoch + 1}/{max_epochs} [Train]", unit="batch") as t:
            for batch_data in t:
                step += 1
                inputs, labels = batch_data["image"].to(device), batch_data["mask"].to(device)
                optimizer.zero_grad()
                outputs = model(inputs)
                loss = loss_function(outputs, labels)
                loss.backward()
                optimizer.step()
                epoch_loss += loss.item()

                # Compute training Dice
                outputs_post = [post_pred(outputs[0])]
                labels_post = [post_label(labels[0])]
                dice_metric(y_pred=outputs_post, y=labels_post)
                train_dice += dice_metric.aggregate().item()
                dice_metric.reset()

                if step % 10 == 0:
                    t.set_postfix(loss=loss.item(), dice=train_dice/step)
        epoch_loss /= len(train_loader)
        train_dice /= len(train_loader)
        epoch_loss_values.append(epoch_loss)

        # Log training metrics to W&B
        wandb.log({
            "epoch": epoch + 1,
            "train/loss": epoch_loss,
            "train/dice": train_dice,
            "learning_rate": optimizer.param_groups[0]["lr"]
        })

        print(f"Epoch {epoch + 1} Average Train Loss: {epoch_loss:.4f}, Train Dice: {train_dice:.4f}")

        if (epoch + 1) % val_interval == 0:
            model.eval()
            with torch.no_grad():
                val_loss = 0
                val_dice = 0
                torch.cuda.empty_cache()
                with tqdm(val_loader, desc=f"Epoch {epoch + 1}/{max_epochs} [Val]", unit="batch") as v:
                    for val_data in v:
                        val_inputs, val_labels = val_data["image"].to(device), val_data["mask"].to(device)
                        val_outputs = sliding_window_inference(val_inputs, TRAIN_PATCH_SIZE, 1, model, overlap=0.5)
                        val_loss += loss_function(val_outputs, val_labels).item()
                        val_outputs = post_pred(val_outputs[0])
                        val_labels = post_label(val_labels[0])
                        dice_metric(y_pred=[val_outputs], y=[val_labels])
                        current_dice = dice_metric.aggregate().item()
                        v.set_postfix(dice=current_dice)
                val_loss /= len(val_loader)
                val_dice = dice_metric.aggregate().item()
                dice_metric.reset()
                metric_values.append(val_dice)

                # Log validation metrics to W&B
                wandb.log({
                    "val/loss": val_loss,
                    "val/dice": val_dice
                })

                print(f"Epoch {epoch + 1} Validation Loss: {val_loss:.4f}, Validation Dice: {val_dice:.4f}")

                if val_dice > best_metric:
                    best_metric = val_dice
                    best_metric_epoch = epoch + 1
                    torch.save(model.state_dict(), "best_model.pth")
                    # Log the best model checkpoint to W&B
                    # wandb.save("best_model.pth")
                    print(f"Saved new best model at epoch {best_metric_epoch} with Dice: {best_metric:.4f}")

                if val_dice > early_stop_dice_threshold:
                    print(f"Early stopping triggered: Validation Dice {val_dice:.4f} exceeds threshold {early_stop_dice_threshold}")
                    break

    # Finish the W&B run
    wandb.finish()


def test():
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if not os.path.exists("best_model.pth"):
        raise FileNotFoundError("best_model.pth not found. Please train the model first.")
    model.load_state_dict(torch.load("best_model.pth"))
    model.eval()

    dice_metric = DiceMetric(include_background=False, reduction="mean")
    post_pred = Compose([AsDiscrete(argmax=True, to_onehot=2)])  # Binary: 2 classes
    post_label = Compose([AsDiscrete(to_onehot=2)])
    save_pred = SaveImage(output_dir="./predictions", output_ext=".nii.gz", output_postfix="pred", separate_folder=False)

    test_dice_values = []
    test_jaccard_values = []
    test_asd_values = []
    test_95hd_values = []

    with torch.no_grad():
        for i, test_data in enumerate(tqdm(test_loader, desc="Testing")):
            print(f"Processing test sample {i} - {test_data['image'].meta['filename_or_obj']}")
            test_inputs, test_labels = test_data["image"].to(device), test_data["mask"].to(device)
            print(f"test_inputs shape: {test_inputs.shape}")
            test_outputs = sliding_window_inference(test_inputs, TRAIN_PATCH_SIZE, 1, model, overlap=0.75)
            print(f"test_outputs shape: {test_outputs.shape}")
            print(f"test_outputs unique: {torch.unique(test_outputs)}")

            # Post-process for Dice
            test_outputs_onehot = post_pred(test_outputs[0])  # [2, H, W, D]
            test_labels_onehot = post_label(test_labels[0])   # [2, H, W, D]
            print(f"test_outputs_onehot shape: {test_outputs_onehot.shape}, unique: {torch.unique(test_outputs_onehot)}")
            print(f"test_labels_onehot shape: {test_labels_onehot.shape}, unique: {torch.unique(test_labels_onehot)}")
            dice_metric(y_pred=[test_outputs_onehot], y=[test_labels_onehot])
            dice_value = dice_metric.aggregate().item()
            test_dice_values.append(dice_value)
            jaccard_value = dice_value / (2 - dice_value) if dice_value != 0 else 0
            test_jaccard_values.append(jaccard_value)
            dice_metric.reset()

            # Post-process for ASD and HD
            test_outputs_binary = test_outputs_onehot[1:2]  # Spleen class only, shape: [1, 512, 512, 112]
            test_labels_binary = test_labels_onehot[1:2]  # Spleen class only, shape: [1, 512, 512, 112]

            # Add batch dimension if not already present
            test_outputs_binary = test_outputs_binary.unsqueeze(0)  # Shape: [1, 1, 512, 512, 112]
            test_labels_binary = test_labels_binary.unsqueeze(0)  # Shape: [1, 1, 512, 512, 112]

            asd_value = compute_average_surface_distance(
                test_outputs_binary, test_labels_binary, include_background=False
            ).mean().item()
            test_asd_values.append(asd_value if not torch.isnan(torch.tensor(asd_value)) else 0.0)

            hd95_value = compute_hausdorff_distance(
                test_outputs_binary, test_labels_binary, include_background=False, percentile=95
            ).mean().item()
            test_95hd_values.append(hd95_value if not torch.isnan(torch.tensor(hd95_value)) else 0.0)

            # Save predictions
            output = test_outputs_binary.unsqueeze(0).cpu()  # [1, 1, H, W, D]
            save_pred(output, meta_data=test_data["image"].meta)

    print("\nTest Set Performance:")
    print(f"Dice: {np.mean(test_dice_values):.4f} ± {np.std(test_dice_values):.4f}")
    print(f"Jaccard: {np.mean(test_jaccard_values):.4f} ± {np.std(test_jaccard_values):.4f}")
    print(f"ASD: {np.mean(test_asd_values):.4f} ± {np.std(test_asd_values):.4f}")
    print(f"95HD: {np.mean(test_95hd_values):.4f} ± {np.std(test_95hd_values):.4f}")


def output():
    from monai.transforms import SaveImage
    from tqdm import tqdm

    # Define saver for predictions
    save_pred = SaveImage(output_dir="./predictions", output_ext=".nii.gz", output_postfix="pred", separate_folder=False)

    # Inference on test set
    with torch.no_grad():
        for test_data in tqdm(test_loader, desc="Testing"):
            test_inputs, test_labels = test_data["image"].to(device), test_data["mask"].to(device)
            TRAIN_PATCH_SIZE = (128, 128, 32)  # Adjust to your patch size
            print(f"TRAIN_PATCH_SIZE: {TRAIN_PATCH_SIZE}")
            print(f"test_inputs shape: {test_inputs.shape}")
            test_outputs = sliding_window_inference(test_inputs, TRAIN_PATCH_SIZE, 1, model, overlap=0.5)

            # Post-process the single output tensor (batch size = 1)
            test_outputs = post_pred(test_outputs[0])  # Shape: [C, H, W, D], e.g., [2, 96, 96, 96]

            # Convert to proper format for saving (remove channel dim if necessary)
            output = test_outputs.argmax(dim=0, keepdim=True).cpu()  # Shape: [1, H, W, D], e.g., [1, 96, 96, 96]
            save_pred(output, meta_data=test_data["image"].meta)



# Model Definition
from monai.networks.nets import UNet
from monai.networks.layers import Norm
from monai.losses import DiceLoss
import torch.nn as nn
import wandb
from monai.transforms import AsDiscrete, Compose
from monai.metrics import DiceMetric
from monai.inferers import sliding_window_inference
from tqdm import tqdm

# Device
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# Define Loss Functions
dice_loss = DiceLoss(to_onehot_y=True, softmax=True)
ce_loss = nn.CrossEntropyLoss()

class CombinedLoss(nn.Module):
    def __init__(self, alpha=0.5, beta=0.5):
        super(CombinedLoss, self).__init__()
        self.dice_loss = DiceLoss(to_onehot_y=True, softmax=True)
        self.ce_loss = nn.CrossEntropyLoss()
        self.alpha = alpha
        self.beta = beta

    def forward(self, outputs, labels):
        dice = self.dice_loss(outputs, labels)
        ce = self.ce_loss(outputs, labels)
        return self.alpha * dice + self.beta * ce

loss_functions = {
    "Dice": dice_loss,
    "CrossEntropy": ce_loss,
    "Combined": CombinedLoss(alpha=0.5, beta=0.5)  # 可调整 alpha 和 beta
}

# Training Function
def train_model(loss_name, loss_function, max_epochs=50):
    wandb.init(
        project="spleen-segmentation",
        name=f"run_{loss_name}",
        config={
            "loss_function": loss_name,
            "learning_rate": 1e-4,
            "epochs": max_epochs,
            "batch_size": 1,
            "patch_size": TRAIN_PATCH_SIZE,
            "architecture": "3D UNet",
        }
    )

    model = UNet(
        spatial_dims=3,
        in_channels=1,
        out_channels=2,
        channels=(16, 32, 64, 128, 256),
        strides=(2, 2, 2, 2),
        num_res_units=2,
        norm=Norm.BATCH,
    ).to(device)

    optimizer = torch.optim.Adam(model.parameters(), lr=1e-4)
    post_pred = Compose([AsDiscrete(argmax=True, to_onehot=2)])
    post_label = Compose([AsDiscrete(to_onehot=2)])
    dice_metric = DiceMetric(include_background=False, reduction="mean")


    best_metric = -1
    best_metric_epoch = -1
    epoch_loss_values = []
    metric_values = []
    early_stop_dice_threshold = 0.6

    for epoch in range(max_epochs):
        model.train()
        epoch_loss = 0
        train_dice = 0
        step = 0
        with tqdm(train_loader, desc=f"Epoch {epoch + 1}/{max_epochs} [Train-{loss_name}]", unit="batch") as t:
            for batch_data in t:
                step += 1
                inputs, labels = batch_data["image"].to(device), batch_data["mask"].to(device)
                optimizer.zero_grad()
                outputs = model(inputs)
                loss = loss_function(outputs, labels)
                loss.backward()
                optimizer.step()
                epoch_loss += loss.item()

                outputs_post = [post_pred(outputs[0])]
                labels_post = [post_label(labels[0])]
                dice_metric(y_pred=outputs_post, y=labels_post)
                train_dice += dice_metric.aggregate().item()
                dice_metric.reset()

                if step % 10 == 0:
                    t.set_postfix(loss=loss.item(), dice=train_dice/step)
        epoch_loss /= len(train_loader)
        train_dice /= len(train_loader)
        epoch_loss_values.append(epoch_loss)

        wandb.log({
            "epoch": epoch + 1,
            f"train/loss_{loss_name}": epoch_loss,
            f"train/dice_{loss_name}": train_dice,
            "learning_rate": optimizer.param_groups[0]["lr"]
        })
        print(f"Epoch {epoch + 1} ({loss_name}) Average Train Loss: {epoch_loss:.4f}, Train Dice: {train_dice:.4f}")

        if (epoch + 1) % 1 == 0:  # val_interval = 1
            model.eval()
            with torch.no_grad():
                val_loss = 0
                val_dice = 0
                torch.cuda.empty_cache()
                with tqdm(val_loader, desc=f"Epoch {epoch + 1}/{max_epochs} [Val-{loss_name}]", unit="batch") as v:
                    for val_data in v:
                        val_inputs, val_labels = val_data["image"].to(device), val_data["mask"].to(device)
                        val_outputs = sliding_window_inference(val_inputs, TRAIN_PATCH_SIZE, 1, model, overlap=0.5)
                        val_loss += loss_function(val_outputs, val_labels).item()
                        val_outputs = post_pred(val_outputs[0])
                        val_labels = post_label(val_labels[0])
                        dice_metric(y_pred=[val_outputs], y=[val_labels])
                        current_dice = dice_metric.aggregate().item()
                        v.set_postfix(dice=current_dice)
                val_loss /= len(val_loader)
                val_dice = dice_metric.aggregate().item()
                dice_metric.reset()
                metric_values.append(val_dice)

                wandb.log({
                    f"val/loss_{loss_name}": val_loss,
                    f"val/dice_{loss_name}": val_dice
                })
                print(f"Epoch {epoch + 1} ({loss_name}) Validation Loss: {val_loss:.4f}, Validation Dice: {val_dice:.4f}")

                if val_dice > best_metric:
                    best_metric = val_dice
                    best_metric_epoch = epoch + 1
                    torch.save(model.state_dict(), f"best_improved_model_{loss_name}.pth")

                    print(f"Saved new best model ({loss_name}) at epoch {best_metric_epoch} with Dice: {best_metric:.4f}")

                if val_dice > early_stop_dice_threshold:
                    print(f"Early stopping triggered ({loss_name}): Validation Dice {val_dice:.4f} exceeds threshold {early_stop_dice_threshold}")
                    break

    wandb.finish()
    return model

def bonus():
    # Run training for each loss function
    for loss_name, loss_func in loss_functions.items():
        print(f"\nTraining with {loss_name} Loss...")
        train_model(loss_name, loss_func, max_epochs=50)




train()
test()
output()
bonus()




