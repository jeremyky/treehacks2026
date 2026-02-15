# Model Files Setup

This repository uses YOLO models for object detection. These model files are **not included** in the repository due to their large size.

## Required Model Files

### YOLOv8 Nano (Basic Detection)
- **File**: `yolov8n.pt` (~6MB)
- **Location**: `himpublic-py/yolov8n.pt`
- **Download**: 
  ```bash
  cd himpublic-py
  wget https://github.com/ultralytics/assets/releases/download/v0.0.0/yolov8n.pt
  ```

### YOLOv8 Small World v2 (Open Vocabulary Detection)
- **File**: `yolov8s-worldv2.pt` (~25MB)
- **Location**: `himpublic-py/yolov8s-worldv2.pt` and `webapp/yolov8s-worldv2.pt`
- **Download**:
  ```bash
  # For himpublic-py
  cd himpublic-py
  wget https://github.com/ultralytics/assets/releases/download/v8.2.0/yolov8s-worldv2.pt
  
  # For webapp
  cd ../webapp
  wget https://github.com/ultralytics/assets/releases/download/v8.2.0/yolov8s-worldv2.pt
  ```

## Alternative: Use Python/Ultralytics

The models will be automatically downloaded when you first run the code if you have `ultralytics` installed:

```python
from ultralytics import YOLO

# This will auto-download if not present
model = YOLO('yolov8n.pt')
# or
model = YOLO('yolov8s-worldv2.pt')
```

## Configuration

Set the model path in your `.env` file:

```bash
HIMPUBLIC_YOLO_MODEL=yolov8n.pt
# or
HIMPUBLIC_YOLO_MODEL=yolov8s-worldv2.pt
```
