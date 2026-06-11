# OpenPnP YOLO 散料飞达配置指南

## 概述

本文档说明如何在 OpenPnP 中配置基于 YOLO 的散料飞达，包括问题诊断、解决方案和配置步骤。

---

## 问题背景

### 原始问题

1. **角度处理问题**：飞达取料时的角度识别不准确，导致贴装角度错误
2. **底部视觉失败**：贴装时的底部视觉检测无法找到元件（`No result found`）
3. **角度补偿错误**：底部视觉检测到接近 -90° 的角度，但只补偿了 2.27°，导致贴装角度偏差

### 根本原因分析

#### 问题 1：飞达视觉管道配置
- **问题**：最初使用了自定义的底部视觉脚本来处理角度，但角度处理逻辑与 OpenPnP 的飞达视觉管道不匹配
- **原因**：OpenPnP 的飞达视觉（Feeder Vision）和底部视觉（Bottom Vision）是两个独立的系统，使用不同的管道和调用时机

#### 问题 2：底部视觉角度搜索范围
- **问题**：`MinAreaRect` 阶段的 `search-angle="45.0"` 限制了角度搜索范围
- **原因**：当元件角度接近 -90° 时，45° 的搜索范围无法正确检测到实际角度，导致角度补偿失败

---

## 解决方案

### 方案 A：统一飞达视觉管道（已采用）

**核心思想**：将 YOLO 检测集成到 OpenPnP 的标准飞达视觉管道中，利用 OpenPnP 的原生角度处理机制。

**优势**：
- 无需维护额外的角度处理脚本
- 利用 OpenPnP 的标准管道结构，稳定性更好
- 角度处理由 OpenPnP 自动处理，减少错误

---

## 配置文件修改

### 1. 飞达视觉管道配置（machine.xml）

**文件位置**：`machine.xml`

**飞达 ID**：`FDR1888297a46b0441c`

**配置结构**：
```xml
<feeder class="org.openpnp.machine.reference.feeder.ReferenceLoosePartFeeder" 
        id="FDR1888297a46b0441c" 
        part-id="C0805-100nF">
  <pipeline>
    <stages>
      <!-- 1. 图像捕获 -->
      <cv-stage class="org.openpnp.vision.pipeline.stages.ImageCapture" 
                name="capture" enabled="true" settle-first="true"/>
      
      <!-- 2. 调试：保存原始图像 -->
      <cv-stage class="org.openpnp.vision.pipeline.stages.ImageWriteDebug" 
                name="debug_capture" enabled="true" 
                prefix="loosepart_capture_" suffix=".png"/>
      
      <!-- 3. 转灰度 -->
      <cv-stage class="org.openpnp.vision.pipeline.stages.ConvertColor" 
                name="gray" enabled="true" conversion="Bgr2Gray"/>
      
      <!-- 4. 调试：保存灰度图像 -->
      <cv-stage class="org.openpnp.vision.pipeline.stages.ImageWriteDebug" 
                name="debug_gray" enabled="true" 
                prefix="loosepart_gray_" suffix=".png"/>
      
      <!-- 5. YOLO 检测（核心） -->
      <cv-stage class="org.openpnp.vision.pipeline.stages.ScriptRun" 
                name="results" enabled="true" 
                file="C:\Users\17299\.openpnp2\openPNP_Script\BulkFeederScript.js" 
                args="yolo_confidence=0.25"/>
      
      <!-- 6. 调试：保存脚本结果 -->
      <cv-stage class="org.openpnp.vision.pipeline.stages.ImageWriteDebug" 
                name="debug_script_result" enabled="true" 
                prefix="loosepart_script_" suffix=".png"/>
      
      <!-- 7. 召回原始图像（用于绘制） -->
      <cv-stage class="org.openpnp.vision.pipeline.stages.ImageRecall" 
                name="recall2" enabled="true" image-stage-name="capture"/>
      
      <!-- 8. 绘制检测结果 -->
      <cv-stage class="org.openpnp.vision.pipeline.stages.DrawRotatedRects" 
                name="draw_results" enabled="true" 
                rotated-rects-stage-name="results" thickness="2" 
                draw-rect-center="true" rect-center-radius="3" 
                show-orientation="true">
        <color r="51" g="255" b="51" a="255"/>
      </cv-stage>
      
      <!-- 9. 调试：保存最终结果 -->
      <cv-stage class="org.openpnp.vision.pipeline.stages.ImageWriteDebug" 
                name="debug_result" enabled="true" 
                prefix="loosepart_result_" suffix=".png"/>
    </stages>
  </pipeline>
</feeder>
```

**关键点**：
- `ScriptRun` 阶段调用 `BulkFeederScript.js` 执行 YOLO 检测
- `results` 阶段名必须输出 `RotatedRect` 对象列表
- 调试图像保存在工作目录，便于分析问题

---

### 2. 底部视觉配置（vision-settings.xml）

**文件位置**：`vision-settings.xml`

**底部视觉设置 ID**：`BVS18833a57dcb17178`（对应 C0805 元件）

**配置结构**：
```xml
<vision-settings class="org.openpnp.model.BottomVisionSettings" 
                 id="BVS18833a57dcb17178" name="C0805" enabled="true" 
                 pre-rotate-usage="Default" 
                 check-part-size-method="Disabled" 
                 check-size-tolerance-percent="300" 
                 max-rotation="Full" asymmetric="true">
  <cv-pipeline>
    <stages>
      <!-- 1. 图像捕获 -->
      <cv-stage class="org.openpnp.vision.pipeline.stages.ImageCapture" 
                name="CaptureImage" enabled="true" 
                default-light="true" settle-option="Settle" count="1"/>
      
      <!-- 2. 圆形遮罩 -->
      <cv-stage class="org.openpnp.vision.pipeline.stages.MaskCircle" 
                name="MaskCircle" enabled="true" diameter="250"/>
      
      <!-- 3. 转灰度 -->
      <cv-stage class="org.openpnp.vision.pipeline.stages.ConvertColor" 
                name="ConvertToGray" enabled="true" conversion="Bgr2Gray"/>
      
      <!-- 4. 高斯模糊 -->
      <cv-stage class="org.openpnp.vision.pipeline.stages.BlurGaussian" 
                name="InitialBlur" enabled="true" kernel-size="9"/>
      
      <!-- 5. 二值化阈值 -->
      <cv-stage class="org.openpnp.vision.pipeline.stages.Threshold" 
                name="Threshold" enabled="true" 
                threshold="120" auto="false" invert="false"/>
      
      <!-- 6. 二次模糊 -->
      <cv-stage class="org.openpnp.vision.pipeline.stages.BlurGaussian" 
                name="SecondBlur" enabled="true" kernel-size="3"/>
      
      <!-- 7. 最小外接矩形检测（关键修复） -->
      <cv-stage class="org.openpnp.vision.pipeline.stages.MinAreaRect" 
                name="MinAreaRect" enabled="true" 
                threshold-min="100" threshold-max="256" 
                expected-angle="0.0" 
                search-angle="180.0"  <!-- 重要：从45.0改为180.0 -->
                left-edge="true" right-edge="true" 
                top-edge="true" bottom-edge="true" 
                diagnostics="false"/>
      
      <!-- 8. 角度方向处理 -->
      <cv-stage class="org.openpnp.vision.pipeline.stages.OrientRotatedRects" 
                name="results" enabled="true" 
                rotated-rects-stage-name="MinAreaRect" 
                orientation="Landscape" 
                negate-angle="false" snap-angle="0"/>
      
      <!-- 9. 召回原始图像 -->
      <cv-stage class="org.openpnp.vision.pipeline.stages.ImageRecall" 
                name="RecallOriginal" enabled="true" 
                image-stage-name="CaptureImage"/>
      
      <!-- 10. 绘制检测结果 -->
      <cv-stage class="org.openpnp.vision.pipeline.stages.DrawRotatedRects" 
                name="DrawRectangle" enabled="true" 
                rotated-rects-stage-name="results" thickness="2" 
                draw-rect-center="false" rect-center-radius="20" 
                show-orientation="false"/>
      
      <!-- 11. 调试：保存结果图像 -->
      <cv-stage class="org.openpnp.vision.pipeline.stages.ImageWriteDebug" 
                name="SaveDebugWithCV" enabled="true" 
                prefix="bv_result_" suffix=".png"/>
    </stages>
  </cv-pipeline>
  <vision-offset units="Millimeters" x="0.0" y="0.0" z="0.0" rotation="0.0"/>
</vision-settings>
```

**关键修复点**：
1. **`search-angle="180.0"`**：从 45.0 改为 180.0，允许全角度搜索
2. **添加 `OrientRotatedRects`**：正确处理非对称元件的角度方向
3. **阈值 `threshold="120"`**：适合 C0805 元件的亮度阈值

---

### 3. 元件包配置（packages.xml）

**文件位置**：`packages.xml`

**配置示例**：
```xml
<package version="1.1" 
         id="C0805" 
         bottom-vision-id="BVS18833a57dcb17178"  <!-- 关联底部视觉设置 -->
         pick-vacuum-level="0.0" 
         place-blow-off-level="0.0">
  <!-- 其他配置... -->
</package>
```

**关键点**：
- `bottom-vision-id` 必须指向对应的底部视觉设置 ID
- 如果缺少此关联，会使用默认底部视觉设置，可能导致检测失败

---

## 为新元件创建飞达的完整步骤

### 步骤 1：准备 YOLO 模型和脚本

确保以下文件已准备好：
- `yolo_inference.py`：YOLO 推理脚本
- `BulkFeederScript.js`：OpenPnP 脚本接口
- YOLO 模型文件（.pt 格式）

### 步骤 2：在 OpenPnP 中创建元件包（Package）

1. 打开 OpenPnP → `Configuration` → `Packages`
2. 创建新包或编辑现有包
3. 设置包的基本参数（尺寸、焊盘等）

### 步骤 3：创建底部视觉设置（Bottom Vision Settings）

1. 打开 OpenPnP → `Configuration` → `Vision` → `Bottom Vision`
2. 点击 `Add` 创建新的底部视觉设置
3. 配置视觉管道（参考上面的底部视觉配置模板）
4. **重要参数**：
   - `search-angle="180.0"`：全角度搜索
   - `threshold`：根据元件调整阈值（通常 100-140）
   - `asymmetric="true"`：如果元件不对称
   - `max-rotation="Full"`：允许全角度旋转
5. 记住底部视觉设置的 **ID**（如 `BVS18833a57dcb17178`）

### 步骤 4：关联元件包和底部视觉设置

1. 编辑元件包配置
2. 在 `Bottom Vision Settings` 中选择刚创建的底部视觉设置
3. 或在 `packages.xml` 中手动添加：
   ```xml
   <package id="YourPackageID" bottom-vision-id="BVSxxxxx" ...>
   ```

### 步骤 5：创建飞达（Feeder）

#### 方法 A：在 OpenPnP GUI 中创建

1. 打开 OpenPnP → `Configuration` → `Feeders`
2. 点击 `Add` → 选择 `ReferenceLoosePartFeeder`
3. 配置飞达位置和参数

#### 方法 B：在 machine.xml 中手动配置

```xml
<feeder class="org.openpnp.machine.reference.feeder.ReferenceLoosePartFeeder" 
        version="1.1" 
        id="FDR_YourFeederID" 
        name="YourFeederName" 
        enabled="true" 
        part-id="YourPartID"  <!-- 对应 packages.xml 中的包 ID -->
        retry-count="3" 
        feed-retry-count="0" 
        pick-retry-count="0">
  
  <!-- 飞达位置 -->
  <location units="Millimeters" x="10.52" y="250.249" z="1.2" rotation="200.0"/>
  
  <!-- 视觉管道（关键） -->
  <pipeline>
    <stages>
      <!-- 参考上面的飞达视觉管道配置 -->
      <cv-stage class="org.openpnp.vision.pipeline.stages.ImageCapture" 
                name="capture" enabled="true" settle-first="true"/>
      
      <cv-stage class="org.openpnp.vision.pipeline.stages.ImageWriteDebug" 
                name="debug_capture" enabled="true" 
                prefix="loosepart_capture_" suffix=".png"/>
      
      <cv-stage class="org.openpnp.vision.pipeline.stages.ConvertColor" 
                name="gray" enabled="true" conversion="Bgr2Gray"/>
      
      <cv-stage class="org.openpnp.vision.pipeline.stages.ImageWriteDebug" 
                name="debug_gray" enabled="true" 
                prefix="loosepart_gray_" suffix=".png"/>
      
      <!-- YOLO 检测脚本 -->
      <cv-stage class="org.openpnp.vision.pipeline.stages.ScriptRun" 
                name="results" enabled="true" 
                file="C:\Users\17299\.openpnp2\openPNP_Script\BulkFeederScript.js" 
                args="yolo_confidence=0.25"/>
      
      <cv-stage class="org.openpnp.vision.pipeline.stages.ImageWriteDebug" 
                name="debug_script_result" enabled="true" 
                prefix="loosepart_script_" suffix=".png"/>
      
      <cv-stage class="org.openpnp.vision.pipeline.stages.ImageRecall" 
                name="recall2" enabled="true" image-stage-name="capture"/>
      
      <cv-stage class="org.openpnp.vision.pipeline.stages.DrawRotatedRects" 
                name="draw_results" enabled="true" 
                rotated-rects-stage-name="results" thickness="2" 
                draw-rect-center="true" rect-center-radius="3" 
                show-orientation="true">
        <color r="51" g="255" b="51" a="255"/>
      </cv-stage>
      
      <cv-stage class="org.openpnp.vision.pipeline.stages.ImageWriteDebug" 
                name="debug_result" enabled="true" 
                prefix="loosepart_result_" suffix=".png"/>
    </stages>
  </pipeline>
</feeder>
```

**关键参数说明**：
- `part-id`：必须匹配 `packages.xml` 中的包 ID
- `file`：`BulkFeederScript.js` 的完整路径
- `args="yolo_confidence=0.25"`：YOLO 置信度阈值（可调整）
- `results`：阶段名必须输出 `RotatedRect` 对象列表

### 步骤 6：测试和调试

1. **测试飞达视觉**：
   - 在 OpenPnP 中点击飞达的 `Feed` 按钮
   - 检查调试图像：`loosepart_capture_*.png`、`loosepart_result_*.png`
   - 确认 YOLO 能正确检测到元件

2. **测试底部视觉**：
   - 手动取料后，在底部视觉位置测试
   - 检查调试图像：`bv_result_*.png`
   - 确认角度检测正确

3. **常见问题排查**：
   - **检测不到元件**：调整阈值、检查光照
   - **角度错误**：确认 `search-angle="180.0"`、检查 `OrientRotatedRects` 配置
   - **脚本错误**：检查 Python 环境和 YOLO 模型路径

---

## 关键配置文件总结

| 文件 | 位置 | 关键配置 |
|------|------|----------|
| **machine.xml** | `C:\Users\17299\.openpnp2\` | 飞达配置、飞达视觉管道 |
| **vision-settings.xml** | `C:\Users\17299\.openpnp2\` | 底部视觉设置、角度搜索范围 |
| **packages.xml** | `C:\Users\17299\.openpnp2\` | 元件包配置、底部视觉关联 |
| **BulkFeederScript.js** | `openPNP_Script\` | YOLO 脚本接口 |
| **yolo_inference.py** | `openPNP_Script\` | YOLO 推理脚本 |

---

## 重要注意事项

1. **角度搜索范围**：必须设置 `search-angle="180.0"` 以支持全角度检测
2. **元件包关联**：`packages.xml` 中必须正确关联 `bottom-vision-id`
3. **脚本路径**：`BulkFeederScript.js` 路径必须是绝对路径
4. **YOLO 置信度**：根据实际效果调整 `yolo_confidence` 参数
5. **调试图像**：开启 `ImageWriteDebug` 阶段有助于问题诊断

---

## 参考示例：C0805 元件完整配置

### packages.xml
```xml
<package version="1.1" 
         bottom-vision-id="BVS18833a57dcb17178" 
         id="C0805" 
         pick-vacuum-level="0.0" 
         place-blow-off-level="0.0">
  <!-- 包的其他配置... -->
</package>
```

### vision-settings.xml（底部视觉）
```xml
<vision-settings class="org.openpnp.model.BottomVisionSettings" 
                 id="BVS18833a57dcb17178" name="C0805" 
                 search-angle="180.0"  <!-- 关键 -->
                 asymmetric="true">
  <!-- 管道配置（见上文） -->
</vision-settings>
```

### machine.xml（飞达）
```xml
<feeder id="FDR1888297a46b0441c" part-id="C0805-100nF">
  <pipeline>
    <!-- YOLO 脚本集成（见上文） -->
  </pipeline>
</feeder>
```

---

## 问题排查检查清单

- [ ] YOLO 脚本路径正确
- [ ] Python 环境可执行
- [ ] YOLO 模型文件存在
- [ ] 飞达视觉管道中 `results` 阶段输出 `RotatedRect`
- [ ] 底部视觉 `search-angle="180.0"`
- [ ] 底部视觉包含 `OrientRotatedRects` 阶段
- [ ] `packages.xml` 中正确关联 `bottom-vision-id`
- [ ] 阈值参数适合元件类型
- [ ] 调试图像已启用，便于分析

---

**最后更新**：2026-01-10  
**配置版本**：OpenPnP 2.0+  
**测试元件**：C0805 (100nF 电容)
