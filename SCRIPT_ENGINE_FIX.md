# 脚本引擎错误修复指南

## 错误信息
```
java.lang.Exception: Unable to find scriping engine for BulkFeederScript.js
```

## 问题原因

OpenPnP 的 `ScriptRun` 阶段根据**文件扩展名**来查找脚本引擎：
- `.bsh` 或 `.java` → BeanShell（已注册，默认支持）
- `.js` → JavaScript（Rhino/Nashorn，**需要额外配置**）

**结论**：OpenPnP 默认**不支持 `.js` 文件**，需要使用 BeanShell 语法（`.bsh` 扩展名）。

## 解决方案

### 方案 1：重命名为 .bsh（推荐）

1. **重命名文件**：
   - 将 `BulkFeederScript.js` 重命名为 `BulkFeederScript.bsh`
   - BeanShell 语法与 JavaScript 基本兼容，通常无需修改代码

2. **更新 machine.xml 配置**：
   ```xml
   <cv-stage class="org.openpnp.vision.pipeline.stages.ScriptRun" 
             name="results" enabled="true" 
             file="C:\Users\Administrator\.openpnp2\openPNP_Script\BulkFeederScript.bsh" 
             args="yolo_confidence=0.25"/>
   ```

3. **更新日志路径**（如果脚本中有硬编码路径）：
   ```javascript
   var LOG_FILE_PATH = "C:\\Users\\Administrator\\.openpnp2\\openPNP_Script\\BulkFeederScript.log";
   ```

### 方案 2：使用 Python 脚本（替代方案）

如果 BeanShell 有问题，可以考虑将脚本改为 Python（需要 OpenPnP 支持 Jython），但这更复杂。

## BeanShell 与 JavaScript 的兼容性

BeanShell 与 JavaScript 语法**高度兼容**，以下特性都可以正常使用：
- ✅ `var`, `function` 定义
- ✅ `JavaImporter`（BeanShell 支持）
- ✅ Java 类调用
- ✅ 对象和方法调用
- ✅ 数组和列表操作

**注意**：`new JavaImporter()` 在 BeanShell 中的用法略有不同，但你的代码应该可以工作。

## 验证步骤

1. 重命名文件后，重新加载 OpenPnP
2. 测试飞达视觉管道
3. 检查日志文件是否正常生成
4. 查看是否有语法错误

## 如果方案 1 不行

如果 BeanShell 版本有问题，可以：

1. **检查 OpenPnP 版本**：确保版本支持 BeanShell
2. **查看详细错误日志**：检查是否有语法不兼容的地方
3. **考虑使用 Jython**：将脚本改为 Python（如果 OpenPnP 配置了 Jython）

---

**快速修复**：直接重命名 `.js` → `.bsh` 即可！
