#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""YOLOv8 推理脚本 - 用于从 OpenPnP Jython 脚本调用
支持实例分割模型，自动计算虚拟极性标识点
接收图像路径，返回检测结果 JSON

Usage:
    python yolo_inference.py <model_path> <image_path> [confidence_threshold]

Parameters:
    model_path: YOLOv8 模型文件路径 (.pt)
    image_path: 输入图像路径
    confidence_threshold: 置信度阈值 (默认: 0.25)

Note:
    对于 ReferenceLoosePartFeeder，脚本需要自己返回 OpenPnP 坐标系中的最终取料角。
    图像坐标系（Y 轴向下）与 OpenPnP 坐标系（Y 轴向上）之间存在旋转符号翻转。

虚拟 MarkingPoint 计算：
    - 从分割掩码提取元件几何信息
    - 根据矩形角度判断哪条短边落在 [-90, 90] 范围内
    - 如接近垂直歧义(±90°边界)，顺时针旋转15°重新判断
    - 在选中的短边中点放置虚拟标识点
    - 用户需手动统一极性元件的摆放方向

Output:
    JSON格式的检测结果，包含：
    - detections: 检测框列表，每个包含 [center_x, center_y, width, height, angle, confidence, marker_center_x, marker_center_y]
    - 使用实例分割模型计算精确的旋转角度和虚拟标识点位置
    - 返回角度统一规范化到 [-180, 180) 范围
    - 已应用图像坐标系到OpenPnP坐标系的转换（Y轴翻转）
"""

import sys
import json
import os
import base64
import cv2
import numpy as np
from pathlib import Path
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    from ultralytics import YOLO
except ImportError:
    print(json.dumps({"error": "ultralytics not installed. Please install: pip install ultralytics"}))
    sys.exit(1)

# 日志文件路径
LOG_FILE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "yolo_inference.log"
)

MODEL_CACHE = {}

# 元件检测配置
COMPONENT_CLASS = "ValidComponent"  # 统一元件类别，匹配YOLO数据集标签
MIN_CONFIDENCE = 0.25

# 虚拟 MarkingPoint 计算参数
VERTICAL_AMBIGUITY_THRESHOLD = 80.0  # 接近垂直的阈值(度)
ROTATION_TO_BREAK_SYMMETRY = 15.0   # 顺时针旋转角度，打破垂直歧义
ASPECT_RATIO_THRESHOLD = 1.2        # 长宽比阈值，低于此值视为正方形
def log_message(message):
    """
    写入日志消息到文件
    
    Args:
        message: 要记录的日志消息
    """
    try:
        # 确保日志目录存在
        log_dir = os.path.dirname(LOG_FILE_PATH)
        if log_dir and not os.path.exists(log_dir):
            try:
                os.makedirs(log_dir, exist_ok=True)
            except Exception as dir_error:
                # If directory creation fails, try to write to user home
                try:
                    user_home = os.path.expanduser("~")
                    fallback_log = os.path.join(user_home, "yolo_inference_fallback.log")
                    with open(fallback_log, 'a', encoding='utf-8') as f:
                        f.write(f"[{datetime.now()}] {message}\n")
                        f.flush()
                    return
                except:
                    pass
                print(f"Log directory error: {dir_error}", file=sys.stderr)
                return
        
        # 写入日志
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        log_entry = f"{timestamp} - {message}\n"
        
        with open(LOG_FILE_PATH, 'a', encoding='utf-8') as f:
            f.write(log_entry)
            f.flush()
    except Exception as e:
        # 如果日志写入失败，尝试输出到 stderr（不会影响 JSON 输出）
        try:
            print(f"Log error: {e}", file=sys.stderr)
            # Also try fallback log in user home
            try:
                user_home = os.path.expanduser("~")
                fallback_log = os.path.join(user_home, "yolo_inference_error.log")
                with open(fallback_log, 'a', encoding='utf-8') as f:
                    f.write(f"[{datetime.now()}] {message} (log error: {e})\n")
                    f.flush()
            except:
                pass
        except:
            pass


def normalize_angle_180(angle):
    """Normalize angle to [-180, 180)."""
    while angle >= 180.0:
        angle -= 360.0
    while angle < -180.0:
        angle += 360.0
    return angle


def normalize_angle_90(angle):
    """Normalize angle to [-90, 90)."""
    angle = normalize_angle_180(angle)
    while angle >= 90.0:
        angle -= 180.0
    while angle < -90.0:
        angle += 180.0
    return angle


def is_angle_in_range(angle, range_min=-90.0, range_max=90.0):
    """检查角度是否在指定范围内"""
    normalized = normalize_angle_180(angle)
    return range_min <= normalized <= range_max


def compute_virtual_marker(rect_center, rect_size, rect_angle, is_short_edge=True):
    """
    计算虚拟 MarkingPoint 位置

    对于矩形元件，在指定的短边/长边中点放置虚拟标识点

    Args:
        rect_center: (x, y) 矩形中心
        rect_size: (width, height) 矩形尺寸，width是长边，height是短边（在angle=0时）
        rect_angle: 矩形角度（度）
        is_short_edge: True=在短边放置, False=在长边放置

    Returns:
        (marker_x, marker_y) 虚拟标识点坐标
    """
    cx, cy = rect_center
    width, height = rect_size  # width=长边, height=短边

    # 确定要在哪条边放置标识点
    if is_short_edge:
        # 短边中点距离中心的偏移
        offset = height / 2.0
    else:
        # 长边中点距离中心的偏移
        offset = width / 2.0

    # 计算矩形方向的单位向量
    radians = np.deg2rad(rect_angle)
    ux = np.cos(radians)  # 长轴方向单位向量
    uy = np.sin(radians)

    # 在垂直于长轴的方向上放置标识点
    # 对于短边，方向垂直于长轴
    if is_short_edge:
        marker_x = cx - uy * offset
        marker_y = cy + ux * offset
    else:
        marker_x = cx + ux * offset
        marker_y = cy + uy * offset

    return float(marker_x), float(marker_y)


def select_edge_for_marker(rect_angle, aspect_ratio):
    """
    选择哪条边放置虚拟 MarkingPoint

    策略：
    1. 标识点放在元件两端的短边中心点，也就是沿长轴方向的两个端点二选一
    2. 检查哪个端点方向落在 [-90, 90] 范围内
    3. 如端点方向正好接近 ±90° 边界，先顺时针旋转15°重新判断
    4. 对于正方形（aspect_ratio < 1.2），仍按同样的端点方向逻辑处理

    Args:
        rect_angle: 矩形角度（度）
        aspect_ratio: 长宽比 (长边/短边)

    Returns:
        dict: {
            'selected_edge': 'end_edge_1' or 'end_edge_2',
            'final_angle': 调整后的角度（如有旋转），
            'was_rotated': 是否进行了旋转,
            'original_angle': 原始角度,
            'marker_position': (x, y) 标识点位置偏移方向
        }
    """
    original_angle = rect_angle
    was_rotated = False
    final_angle = rect_angle

    # 归一化到 [-90, 90]
    normalized_angle = normalize_angle_90(rect_angle)

    # 检查是否接近垂直歧义（|angle| > 80°）
    if abs(normalized_angle) > VERTICAL_AMBIGUITY_THRESHOLD:
        # 顺时针旋转15°打破对称
        final_angle = normalize_angle_90(rect_angle + ROTATION_TO_BREAK_SYMMETRY)
        was_rotated = True
        log_message(f"  -> Near vertical ambiguity (|{normalized_angle:.1f}|° > {VERTICAL_AMBIGUITY_THRESHOLD}°), "
                     f"rotated clockwise {ROTATION_TO_BREAK_SYMMETRY}° -> {final_angle:.1f}°")

    if aspect_ratio < ASPECT_RATIO_THRESHOLD:
        log_message(f"  -> Square-like component (aspect_ratio={aspect_ratio:.2f} < {ASPECT_RATIO_THRESHOLD}), "
                     "using endpoint selection")

    # 判断元件两端的短边中心点方向。
    # 端点1在长轴正方向：final_angle
    # 端点2在长轴反方向：final_angle + 180°
    end_edge_angle_1 = normalize_angle_180(final_angle)
    end_edge_angle_2 = normalize_angle_180(final_angle + 180.0)

    in_range_1 = is_angle_in_range(end_edge_angle_1, -90, 90)
    in_range_2 = is_angle_in_range(end_edge_angle_2, -90, 90)

    if in_range_1 and not in_range_2:
        selected = 'end_edge_1'
        direction = 1
    elif in_range_2 and not in_range_1:
        selected = 'end_edge_2'
        direction = -1
    elif in_range_1 and in_range_2:
        if abs(end_edge_angle_1) <= abs(end_edge_angle_2):
            selected = 'end_edge_1'
            direction = 1
        else:
            selected = 'end_edge_2'
            direction = -1
    else:
        selected = 'end_edge_1'
        direction = 1

    log_message(f"  -> End edge 1: {end_edge_angle_1:.1f}° (in range: {in_range_1}), "
                 f"End edge 2: {end_edge_angle_2:.1f}° (in range: {in_range_2}), "
                 f"Selected: {selected}")

    return {
        'selected_edge': selected,
        'final_angle': final_angle,
        'was_rotated': was_rotated,
        'original_angle': original_angle,
        'marker_direction': direction
    }


def compute_mask_centroid(mask):
    moments = cv2.moments(mask.astype(np.uint8))
    if abs(moments["m00"]) < 1e-6:
        return None
    return np.array([
        float(moments["m10"] / moments["m00"]),
        float(moments["m01"] / moments["m00"])
    ], dtype=np.float32)


def find_largest_contour(mask):
    """从掩码中找到最大的轮廓"""
    contours, _ = cv2.findContours(
        mask.astype(np.uint8),
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours:
        return None
    return max(contours, key=cv2.contourArea)


def compute_body_geometry_from_contour(contour):
    """
    从轮廓计算元件几何信息

    Returns:
        dict: {
            'center': (cx, cy),
            'size': (width, height),  # width >= height
            'angle': angle,  # 长轴角度，归一化到 [-90, 90]
            'aspect_ratio': width / height
        }
    """
    if contour is None or len(contour) == 0:
        return None

    # 获取最小外接矩形
    rect = cv2.minAreaRect(contour)
    (cx, cy), (w, h), raw_angle = rect

    # OpenCV的minAreaRect返回的宽度/高度可能互换，需要标准化
    # 确保 width >= height，angle 对应长轴
    width, height = float(w), float(h)
    angle = float(raw_angle)

    if width < height:
        # 交换，使 width 始终为长边
        width, height = height, width
        angle += 90.0

    # 归一化角度到 [-90, 90]
    angle = normalize_angle_90(angle)

    # 计算质心（更稳定的中心点）
    moments = cv2.moments(contour)
    if abs(moments["m00"]) > 1e-6:
        cx = moments["m10"] / moments["m00"]
        cy = moments["m01"] / moments["m00"]

    aspect_ratio = width / height if height > 0 else 1.0

    return {
        'center': (float(cx), float(cy)),
        'size': (width, height),
        'angle': angle,
        'aspect_ratio': aspect_ratio,
        'raw_rect': rect
    }


def process_component_with_virtual_marker(mask, confidence):
    """
    处理单个元件，计算虚拟MarkingPoint

    Args:
        mask: 分割掩码
        confidence: 检测置信度

    Returns:
        dict: 包含元件几何和虚拟标记点信息的字典，失败返回None
    """
    try:
        # 提取轮廓
        contour = find_largest_contour(mask)
        if contour is None:
            log_message("  -> No contour found in mask")
            return None

        # 计算几何信息
        geometry = compute_body_geometry_from_contour(contour)
        if geometry is None:
            log_message("  -> Failed to compute geometry from contour")
            return None

        cx, cy = geometry['center']
        width, height = geometry['size']
        angle = geometry['angle']
        aspect_ratio = geometry['aspect_ratio']

        log_message(f"  -> Geometry: center=({cx:.1f}, {cy:.1f}), size=({width:.1f}, {height:.1f}), "
                     f"angle={angle:.1f}°, aspect_ratio={aspect_ratio:.2f}")

        # 选择在哪条边放置虚拟标记点
        edge_selection = select_edge_for_marker(angle, aspect_ratio)

        # 计算虚拟MarkingPoint位置
        direction = edge_selection['marker_direction']
        was_rotated = edge_selection['was_rotated']

        # 在元件两端的短边中心点放置虚拟标记点。
        # 这个点位于长轴方向的端点，所以距离中心 offset = width/2（width是长边长度）。
        offset = width / 2.0

        # 重要：标记点位置必须基于原始矩形几何（原始angle）
        # 旋转（final_angle）仅用于判断选择哪条短边（direction）
        # 但实际位置计算要用原始angle
        radians = np.deg2rad(angle)  # 使用原始angle，不是final_angle
        ux = np.cos(radians)  # 长轴单位向量 (沿长边方向)
        uy = np.sin(radians)

        # direction=1: 长轴正方向端点，即右端/下端等，取决于元件角度
        # direction=-1: 长轴反方向端点
        if direction > 0:
            marker_cx = cx + ux * offset
            marker_cy = cy + uy * offset
        else:
            marker_cx = cx - ux * offset
            marker_cy = cy - uy * offset

        # 计算最终OpenPnP角度（Y轴翻转）
        # 图像坐标系 -> OpenPnP坐标系: 角度取反
        openpnp_angle = normalize_angle_180(-angle)

        log_message(f"  -> Virtual marker: ({marker_cx:.1f}, {marker_cy:.1f}), "
                     f"openpnp_angle={openpnp_angle:.1f}°")

        return {
            'center_x': cx,
            'center_y': cy,
            'width': width,
            'height': height,
            'angle': openpnp_angle,  # 已转换为OpenPnP坐标系
            'confidence': confidence,
            'marker_center_x': marker_cx,
            'marker_center_y': marker_cy,
            'aspect_ratio': aspect_ratio,
            'was_rotated': was_rotated,
            'original_angle': edge_selection['original_angle'],
            'selected_edge': edge_selection['selected_edge'],
            'contour_area': cv2.contourArea(contour)
        }

    except Exception as e:
        log_message(f"  -> Error processing component: {e}")
        import traceback
        log_message(f"  Traceback: {traceback.format_exc()}")
        return None


def extract_detections(result, model_names):
    """
    提取检测结果并计算虚拟MarkingPoint
    
    简化版本：不再检测MarkingPoint，而是基于几何计算虚拟标识点
    """
    detections = []
    component_count = 0
    rejected_count = 0

    if result.boxes is None or len(result.boxes) == 0:
        log_message("No detections found in results")
        return {
            "detections": detections,
            "component_count": 0,
            "rejected_count": 0,
        }

    boxes = result.boxes.xyxy.cpu().numpy()
    confidences = result.boxes.conf.cpu().numpy()
    classes = result.boxes.cls.cpu().numpy().astype(int)
    log_message(f"Found {len(boxes)} raw detection(s)")

    has_masks = result.masks is not None and len(result.masks) > 0
    masks = result.masks.data.cpu().numpy() if has_masks else None
    
    if not has_masks:
        log_message("ERROR: Model does not produce segmentation masks. This script requires an instance segmentation model.")
        return {
            "detections": [],
            "component_count": 0,
            "rejected_count": len(boxes),
        }

    orig_shape = result.orig_shape
    log_message(f"Processing with segmentation masks. Image shape: {orig_shape}")

    for i in range(len(boxes)):
        box = boxes[i]
        conf = confidences[i]
        cls_id = classes[i]
        cls_name = model_names.get(cls_id, f"Unknown_{cls_id}")
        mask = masks[i] if has_masks else None

        log_message(
            f"Processing detection {i + 1}/{len(boxes)}: class='{cls_name}' (ID={cls_id}), "
            f"conf={conf:.3f}"
        )

        # 检查置信度
        if conf < MIN_CONFIDENCE:
            log_message(f"  -> Rejected: confidence {conf:.3f} < threshold {MIN_CONFIDENCE}")
            rejected_count += 1
            continue

        # 检查掩码
        if mask is None:
            log_message(f"  -> Rejected: no segmentation mask available")
            rejected_count += 1
            continue

        # 调整掩码尺寸
        if mask.shape != (orig_shape[0], orig_shape[1]):
            log_message(f"  Resizing mask from {mask.shape} to {orig_shape}")
            mask = cv2.resize(
                mask.astype(np.float32),
                (orig_shape[1], orig_shape[0]),
                interpolation=cv2.INTER_NEAREST
            )
        mask_binary = (mask > 0.5).astype(np.uint8) * 255

        # 处理元件并计算虚拟MarkingPoint
        component_data = process_component_with_virtual_marker(mask_binary, conf)
        
        if component_data is None:
            log_message(f"  -> Failed to process component geometry, skipping")
            rejected_count += 1
            continue

        # 构建最终结果（确保所有值都是Python原生类型，可JSON序列化）
        detection = {
            'center_x': float(component_data['center_x']),
            'center_y': float(component_data['center_y']),
            'width': float(component_data['width']),
            'height': float(component_data['height']),
            'angle': float(component_data['angle']),  # 已转换为OpenPnP坐标系
            'confidence': float(component_data['confidence']),
            'marker_center_x': float(component_data['marker_center_x']),
            'marker_center_y': float(component_data['marker_center_y']),
            'aspect_ratio': float(component_data['aspect_ratio']),
            'contour_area': float(component_data['contour_area']),
            'class_name': str(cls_name),
        }
        
        detections.append(detection)
        component_count += 1

        log_message(
            f"  -> Added component: center=({detection['center_x']:.1f}, {detection['center_y']:.1f}), "
            f"size=({detection['width']:.1f}, {detection['height']:.1f}), angle={detection['angle']:.1f}°, "
            f"conf={detection['confidence']:.3f}, marker=({detection['marker_center_x']:.1f}, {detection['marker_center_y']:.1f}), "
            f"aspect_ratio={detection['aspect_ratio']:.2f}"
        )

    log_message(
        f"Summary: {component_count} components added, {rejected_count} rejected"
    )

    return {
        "detections": detections,
        "component_count": component_count,
        "rejected_count": rejected_count,
    }


def get_model(model_path):
    model_path = os.path.abspath(model_path)
    model = MODEL_CACHE.get(model_path)
    if model is None:
        log_message(f"Loading YOLOv8 model into cache: {model_path}")
        model = YOLO(model_path)
        MODEL_CACHE[model_path] = model
        log_message(f"Model cached successfully: {model_path}")
    else:
        log_message(f"Reusing cached model: {model_path}")
    return model


def detect_with_yolo_image(model_path, image, conf_threshold=0.25):
    """使用YOLOv8实例分割模型检测元件并计算虚拟MarkingPoint"""
    try:
        log_message("=" * 60)
        log_message("Starting YOLOv8 inference with virtual MarkingPoint")
        log_message(f"Model path: {model_path}")
        log_message(f"Confidence threshold: {conf_threshold}")
        log_message(f"Note: virtual marker computed from component geometry")

        if not os.path.exists(model_path):
            error_msg = f"Model file not found: {model_path}"
            log_message(f"ERROR: {error_msg}")
            return {"error": error_msg, "success": False}

        if image is None:
            error_msg = f"Input image is None"
            log_message(f"ERROR: {error_msg}")
            return {"error": error_msg, "success": False}

        img_height, img_width = image.shape[:2]
        img_channels = image.shape[2] if len(image.shape) > 2 else 1
        log_message(f"In-memory image loaded: {img_width}x{img_height}, {img_channels} channel(s)")

        model = get_model(model_path)

        log_message("Running YOLOv8 inference...")
        import time
        start_time = time.time()
        results = model(image, conf=conf_threshold, verbose=False)
        inference_time = time.time() - start_time
        log_message(f"Inference completed in {inference_time:.3f} seconds")

        model_names = model.names
        log_message(f"Model classes: {model_names}")

        detections = []
        component_count = 0
        rejected_count = 0

        if results and len(results) > 0:
            result = results[0]
            log_message("Processing inference results with virtual marker computation...")
            extracted = extract_detections(result, model_names)
            detections = extracted["detections"]
            component_count = extracted["component_count"]
            rejected_count = extracted["rejected_count"]

        log_message(
            f"Workflow result: {len(detections)} detections, "
            f"{component_count} accepted, {rejected_count} rejected"
        )
        for i, det in enumerate(detections):
            log_message(
                f"  Detection {i+1}: center=({det['center_x']:.1f}, {det['center_y']:.1f}), "
                f"size=({det['width']:.1f}, {det['height']:.1f}), angle={det['angle']:.1f}°, "
                f"conf={det['confidence']:.3f}, marker=({det['marker_center_x']:.1f}, {det['marker_center_y']:.1f}), "
                f"aspect_ratio={det['aspect_ratio']:.2f}"
            )

        log_message("YOLOv8 inference completed successfully")
        log_message("=" * 60)

        return {
            "success": True,
            "detections": detections,
            "count": len(detections),
            "component_count": component_count,
            "rejected_count": rejected_count
        }

    except Exception as e:
        error_msg = str(e)
        log_message(f"ERROR in detect_with_yolo_image: {error_msg}")
        import traceback
        log_message(f"Traceback:\n{traceback.format_exc()}")
        log_message("=" * 60)
        return {
            "error": error_msg,
            "success": False
        }


def detect_with_yolo(model_path, image_path, conf_threshold=0.25):
    """
    使用 YOLOv8 模型进行检测
    
    注意：脚本需要自己把图像坐标系角度转换成 OpenPnP 坐标系角度后再返回。
    
    Args:
        model_path: YOLOv8 模型文件路径 (.pt)
        image_path: 输入图像路径
        conf_threshold: 置信度阈值
    
    Returns:
        dict: 包含检测结果的字典
    """
    try:
        log_message("=" * 60)
        log_message("Starting YOLOv8 inference")
        log_message(f"Model path: {model_path}")
        log_message(f"Image path: {image_path}")
        log_message(f"Confidence threshold: {conf_threshold}")
        log_message("Note: script converts image-space angle into OpenPnP rotation before returning detections")
        
        # 检查模型文件
        if not os.path.exists(model_path):
            error_msg = f"Model file not found: {model_path}"
            log_message(f"ERROR: {error_msg}")
            return {"error": error_msg, "success": False}
        
        log_message(f"Model file exists, size: {os.path.getsize(model_path) / (1024*1024):.2f} MB")
        
        # 读取图像
        if not os.path.exists(image_path):
            error_msg = f"Image file not found: {image_path}"
            log_message(f"ERROR: {error_msg}")
            return {"error": error_msg, "success": False}
        
        # 读取图像信息
        image = cv2.imread(image_path)
        if image is None:
            error_msg = f"Failed to read image: {image_path}"
            log_message(f"ERROR: {error_msg}")
            return {"error": error_msg, "success": False}
        
        return detect_with_yolo_image(model_path, image, conf_threshold)
        
    except Exception as e:
        error_msg = str(e)
        log_message(f"ERROR in detect_with_yolo: {error_msg}")
        import traceback
        log_message(f"Traceback:\n{traceback.format_exc()}")
        log_message("=" * 60)
        return {
            "error": error_msg,
            "success": False
        }


class InferenceRequestHandler(BaseHTTPRequestHandler):
    def _send_json(self, status_code, payload):
        response = json.dumps(payload).encode('utf-8')
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def do_GET(self):
        if self.path == '/health':
            self._send_json(200, {"success": True, "status": "ok", "cached_models": len(MODEL_CACHE)})
        else:
            self._send_json(404, {"success": False, "error": "Not found"})

    def do_POST(self):
        if self.path != '/infer':
            self._send_json(404, {"success": False, "error": "Not found"})
            return

        try:
            content_length = int(self.headers.get('Content-Length', '0'))
            body = self.rfile.read(content_length)
            payload = json.loads(body.decode('utf-8'))

            model_path = payload.get('model_path')
            image_base64 = payload.get('image_base64')
            conf_threshold = float(payload.get('confidence_threshold', 0.25))

            if not model_path:
                self._send_json(400, {"success": False, "error": "model_path is required"})
                return

            if not image_base64:
                self._send_json(400, {"success": False, "error": "image_base64 is required"})
                return

            image_bytes = base64.b64decode(image_base64)
            image_array = np.frombuffer(image_bytes, dtype=np.uint8)
            image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)

            if image is None:
                self._send_json(400, {"success": False, "error": "Failed to decode image bytes"})
                return

            result = detect_with_yolo_image(model_path, image, conf_threshold)
            self._send_json(200 if result.get("success") else 500, result)
        except Exception as e:
            log_message(f"ERROR in HTTP server request: {str(e)}")
            import traceback
            log_message(f"Traceback:\n{traceback.format_exc()}")
            self._send_json(500, {"success": False, "error": str(e)})

    def log_message(self, format, *args):
        return


def run_server(host='127.0.0.1', port=8765):
    server = ThreadingHTTPServer((host, port), InferenceRequestHandler)
    log_message(f"YOLO inference server started on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        log_message("YOLO inference server stopping")
        server.server_close()


def main():
    try:
        log_message("=" * 60)
        log_message("yolo_inference.py started")
        log_message(f"Command line args: {sys.argv}")

        if len(sys.argv) >= 2 and sys.argv[1] == "--server":
            host = sys.argv[2] if len(sys.argv) > 2 else '127.0.0.1'
            port = int(sys.argv[3]) if len(sys.argv) > 3 else 8765
            run_server(host, port)
            return
        
        if len(sys.argv) < 3:
            error_msg = "Usage: python yolo_inference.py <model_path> <image_path> [confidence_threshold]"
            log_message(f"ERROR: {error_msg}")
            print(json.dumps({"error": error_msg}))
            sys.exit(1)
        
        model_path = sys.argv[1]
        image_path = sys.argv[2]
        conf_threshold = float(sys.argv[3]) if len(sys.argv) > 3 else 0.25
        
        log_message(f"Parsed arguments: model={model_path}, image={image_path}, conf={conf_threshold}")
        log_message("Note: script converts image-space angle into OpenPnP rotation before returning detections")
        
        # 执行检测
        result = detect_with_yolo(model_path, image_path, conf_threshold)
        
        # 输出 JSON 结果（只输出 JSON，不输出日志信息）
        print(json.dumps(result, indent=2))
        
        # 记录最终结果
        if result.get("success", False):
            log_message(f"Script completed successfully, returning {result.get('count', 0)} detections")
        else:
            log_message(f"Script completed with error: {result.get('error', 'Unknown error')}")
        
        log_message("=" * 60)
        
        # 如果出错，返回非零退出码
        if not result.get("success", False) or "error" in result:
            sys.exit(1)
    except Exception as e:
        error_msg = f"Fatal error in main: {str(e)}"
        try:
            log_message(error_msg)
            import traceback
            log_message(traceback.format_exc())
        except:
            pass
        print(json.dumps({"error": error_msg}))
        sys.exit(1)


if __name__ == "__main__":
    main()
