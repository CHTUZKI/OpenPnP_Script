/**
 * Bulk Feeder Recognition Script - Use YOLOv8 to recognize bulk components
 * JavaScript (Rhino) version for OpenPnP vision pipeline ScriptRun stage
 * 
 * Usage:
 * 1. Add ScriptRun stage to feeder vision pipeline
 * 2. Set ScriptRun file property to this script file
 * 3. Pass configuration through args parameter (format: key1=value1,key2=value2)
 * 4. Script will automatically recognize components in image using YOLOv8 and return RotatedRect list
 * 
 * Return Result:
 * - Return Result object containing recognized component positions (RotatedRect list)
 * - If no components recognized, return empty list
 * 
 * Parameter Configuration (passed through args):
 * - yolo_model_path: path to YOLOv8 model file (.pt) (default: best.pt in script directory)
 * - yolo_confidence: confidence threshold for YOLOv8 (default 0.25)
 * - python_exe: Python executable path (default: 'python', use full path if not in PATH)
 * 
 * Note:
 * - OpenPnP automatically handles angle reversal and PCB rotation compensation
 * - Script only needs to return the actual angle of the component in camera coordinate system
 * 
 * Example args:
 *   yolo_confidence=0.25
 *   or
 *   yolo_model_path=C:\\path\\to\\model.pt,yolo_confidence=0.3
 */

// Import Java classes
var imports = new JavaImporter(
    org.opencv.core,
    org.opencv.imgcodecs.Imgcodecs,
    org.opencv.imgproc.Imgproc,
    org.openpnp.vision.pipeline.CvStage,
    org.openpnp.vision.FluentCv,
    java.util,
    java.awt,
    java.io,
    java.text,
    java.lang
);

// Get script directory dynamically (works on any machine)
var scriptFile = null;
try {
    // Try to get script file from stage object
    if (typeof stage !== "undefined" && stage !== null && stage.getFile !== undefined) {
        scriptFile = stage.getFile();
    }
} catch (e) {
    // Fallback: use user.home
}

var scriptDir = null;
if (scriptFile !== null && scriptFile.exists()) {
    scriptDir = scriptFile.getParentFile();
} else {
    // Fallback: use user.home/.openpnp2/openPNP_Script
    var userHome = java.lang.System.getProperty("user.home");
    var openpnpDir = new java.io.File(userHome, ".openpnp2");
    scriptDir = new java.io.File(openpnpDir, "openPNP_Script");
}

// Constants - use dynamic path
var LOG_FILE_PATH = new java.io.File(scriptDir, "BulkFeederScript.log").getAbsolutePath();

// Simple logging function - use basic Java classes only
function logMessage(message) {
    try {
        var logFile = new java.io.File(LOG_FILE_PATH);
        var parent = logFile.getParentFile();
        if (parent !== null && !parent.exists()) {
            parent.mkdirs();
        }
        
        var writer = new java.io.PrintWriter(new java.io.FileWriter(logFile, true));
        writer.println(String(message));
        writer.flush();
        writer.close();
    } catch (e) {
        // Fallback: try user home
        try {
            var userHome = java.lang.System.getProperty("user.home");
            var fallbackLog = new java.io.File(userHome, "BulkFeederScript_js_error.log");
            var fallbackWriter = new java.io.FileWriter(fallbackLog, true);
            fallbackWriter.write(String(message) + "\n");
            fallbackWriter.close();
        } catch (e2) {
            // Last resort: stderr
            try {
                java.lang.System.err.println("BulkFeederScript.js: " + String(message));
            } catch (e3) {
                // Give up
            }
        }
    }
}

// Test logging immediately when script loads (before with statement)
// Use fully qualified class names to avoid any import issues
try {
    var logFile = new java.io.File(LOG_FILE_PATH);
    var parent = logFile.getParentFile();
    if (parent !== null && !parent.exists()) {
        parent.mkdirs();
    }
    var writer = new java.io.PrintWriter(new java.io.FileWriter(logFile, true));
    writer.println("=== Script file loaded (top level) ===");
    writer.flush();
    writer.close();
} catch (e) {
    // Try fallback location
    try {
        var userHome = java.lang.System.getProperty("user.home");
        var fallbackLog = new java.io.File(userHome, "BulkFeederScript_js_top_level.log");
        var fallbackWriter = new java.io.FileWriter(fallbackLog, true);
        fallbackWriter.write("=== Script file loaded (top level, fallback) ===\n");
        fallbackWriter.write("Error: " + String(e) + "\n");
        fallbackWriter.close();
    } catch (e2) {
        // Last resort: stderr
        try {
            java.lang.System.err.println("BulkFeederScript.js top level error: " + String(e));
        } catch (e3) {
            // Give up
        }
    }
}

// Parse arguments
function parseArgs(argsStr) {
    // Use dynamic script directory for default model path
    var defaultModelPath = new java.io.File(scriptDir, "best.pt").getAbsolutePath();
    var params = {
        yolo_model_path: defaultModelPath,
        yolo_confidence: 0.25,
        python_exe: "python",
        yolo_server_host: "127.0.0.1",
        yolo_server_port: 8765
    };
    
    if (argsStr && argsStr.trim()) {
        var pairs = argsStr.split(",");
        for (var i = 0; i < pairs.length; i++) {
            var pair = pairs[i];
            if (pair.indexOf("=") >= 0) {
                var parts = pair.split("=", 2);
                var key = parts[0].trim();
                var value = parts[1].trim();
                
                if (key === "yolo_model_path") {
                    params.yolo_model_path = value;
                } else if (key === "yolo_confidence") {
                    params.yolo_confidence = parseFloat(value);
                } else if (key === "python_exe") {
                    params.python_exe = value;
                } else if (key === "yolo_server_host") {
                    params.yolo_server_host = value;
                } else if (key === "yolo_server_port") {
                    params.yolo_server_port = parseInt(value, 10);
                }
            }
        }
    }
    
    return params;
}

function readStreamFully(stream) {
    var reader = new java.io.BufferedReader(new java.io.InputStreamReader(stream, "UTF-8"));
    var lines = new java.util.ArrayList();
    var line;
    while ((line = reader.readLine()) !== null) {
        lines.add(line);
    }
    reader.close();
    var text = "";
    for (var i = 0; i < lines.size(); i++) {
        if (i > 0) text += "\n";
        text += lines.get(i);
    }
    return text;
}

function sleepMillis(ms) {
    java.lang.Thread.sleep(ms);
}

function isServerHealthy(params) {
    var url = new java.net.URL("http://" + params.yolo_server_host + ":" + params.yolo_server_port + "/health");
    var connection = null;
    try {
        connection = url.openConnection();
        connection.setConnectTimeout(300);
        connection.setReadTimeout(500);
        if (connection instanceof java.net.HttpURLConnection) {
            connection.setRequestMethod("GET");
            var code = connection.getResponseCode();
            if (code === 200) {
                return true;
            }
        }
    } catch (e) {
        return false;
    } finally {
        try {
            if (connection !== null && connection.disconnect) {
                connection.disconnect();
            }
        } catch (e2) {
        }
    }
    return false;
}

function ensureYoloServer(params, yoloScript) {
    if (isServerHealthy(params)) {
        logMessage("YOLO server already healthy at http://" + params.yolo_server_host + ":" + params.yolo_server_port);
        return true;
    }

    logMessage("YOLO server not running, starting persistent server process...");
    var serverCommand = [
        params.python_exe,
        yoloScript.getAbsolutePath(),
        "--server",
        String(params.yolo_server_host),
        String(params.yolo_server_port)
    ];
    logMessage("Starting YOLO server: " + serverCommand.join(" "));

    var processBuilder = new java.lang.ProcessBuilder(serverCommand);
    processBuilder.directory(scriptDir);
    processBuilder.redirectErrorStream(true);
    processBuilder.start();

    for (var attempt = 0; attempt < 20; attempt++) {
        sleepMillis(250);
        if (isServerHealthy(params)) {
            logMessage("YOLO server started successfully");
            return true;
        }
    }

    logMessage("Error: YOLO server failed to become healthy in time");
    return false;
}

function encodeImageToBase64(image) {
    var buffer = new org.opencv.core.MatOfByte();
    var ok = org.opencv.imgcodecs.Imgcodecs.imencode(".jpg", image, buffer);
    if (!ok) {
        throw new Error("Failed to encode image to JPEG in memory");
    }
    var bytes = buffer.toArray();
    return java.util.Base64.getEncoder().encodeToString(bytes);
}

function postJson(urlText, jsonText) {
    var url = new java.net.URL(urlText);
    var connection = url.openConnection();
    connection.setConnectTimeout(2000);
    connection.setReadTimeout(60000);
    connection.setDoOutput(true);
    connection.setRequestProperty("Content-Type", "application/json; charset=UTF-8");
    connection.setRequestProperty("Accept", "application/json");
    connection.setRequestMethod("POST");

    var output = new java.io.OutputStreamWriter(connection.getOutputStream(), "UTF-8");
    output.write(jsonText);
    output.flush();
    output.close();

    var statusCode = connection.getResponseCode();
    var responseText = "";
    try {
        responseText = readStreamFully(statusCode >= 400 ? connection.getErrorStream() : connection.getInputStream());
    } finally {
        connection.disconnect();
    }

    return {
        statusCode: statusCode,
        body: responseText
    };
}

// Detect components using YOLOv8
function detectWithYolo(image, params) {
    var detectedParts = new java.util.ArrayList();
    var detectionDebugInfo = [];
    
    try {
        logMessage("Using YOLOv8 model for detection");
        logMessage("YOLOv8 params: model_path=" + params.yolo_model_path + 
                   ", confidence=" + params.yolo_confidence + 
                   ", python_exe=" + params.python_exe);
        
        // Use global scriptDir (already set at top of script)
        var yoloScript = new java.io.File(scriptDir, "yolo_inference.py");
        var modelFile = new java.io.File(params.yolo_model_path);
        
        if (!yoloScript.exists()) {
            logMessage("Error: YOLO script not found: " + yoloScript.getAbsolutePath());
            return { parts: detectedParts, debugInfo: detectionDebugInfo };
        }
        
        if (!modelFile.exists()) {
            logMessage("Error: YOLO model not found: " + modelFile.getAbsolutePath());
            return { parts: detectedParts, debugInfo: detectionDebugInfo };
        }

        if (!ensureYoloServer(params, yoloScript)) {
            logMessage("Error: Could not start or connect to YOLO server");
            return { parts: detectedParts, debugInfo: detectionDebugInfo };
        }
        
        logMessage("YOLO script found: " + yoloScript.getAbsolutePath());
        logMessage("YOLO model found: " + modelFile.getAbsolutePath() + 
                   " (size: " + (modelFile.length() / 1024 / 1024).toFixed(2) + " MB)");
        
        logMessage("Encoding working image to in-memory JPEG/base64...");
        var imageBase64 = encodeImageToBase64(image);
        logMessage("Encoded image length: " + imageBase64.length() + " chars");

        var payload = JSON.stringify({
            model_path: modelFile.getAbsolutePath(),
            confidence_threshold: params.yolo_confidence,
            image_base64: String(imageBase64)
        });

        var endpoint = "http://" + params.yolo_server_host + ":" + params.yolo_server_port + "/infer";
        logMessage("Calling YOLO server endpoint: " + endpoint);
        var response = postJson(endpoint, payload);
        var outputText = response.body || "";

        logMessage("YOLO server response (status " + response.statusCode + "), total length: " + outputText.length() + " chars");
        if (outputText.length() > 500) {
            logMessage("YOLO output preview (first 500 chars):\n" + outputText.substring(0, 500) + "...");
        } else {
            logMessage("YOLO output:\n" + outputText);
        }
        
        // Extract JSON from output
        var jsonText = outputText.trim();
        var firstBrace = jsonText.indexOf("{");
        if (firstBrace >= 0) {
            var braceCount = 0;
            var jsonEnd = -1;
            for (var i = firstBrace; i < jsonText.length; i++) {
                var char = jsonText.charAt(i);
                if (char === "{") {
                    braceCount++;
                } else if (char === "}") {
                    braceCount--;
                    if (braceCount === 0) {
                        jsonEnd = i + 1;
                        break;
                    }
                }
            }
            if (jsonEnd > firstBrace) {
                jsonText = jsonText.substring(firstBrace, jsonEnd);
                logMessage("Extracted JSON using brace matching: length=" + jsonText.length() + " chars");
            } else {
                jsonText = jsonText.substring(firstBrace);
                logMessage("Extracted JSON from first brace to end: length=" + jsonText.length() + " chars");
            }
        } else {
            logMessage("Warning: No '{' found in output, using full text");
        }
        
        // Parse JSON
        try {
            // In Rhino, we can use eval to parse JSON, but it's safer to use Java's JSON library
            // For simplicity, we'll use eval (Rhino supports it)
            var result = eval("(" + jsonText + ")");
            logMessage("JSON parsed successfully");
            
            if (!result.success) {
                var errorMsg = result.error || "Unknown error";
                logMessage("YOLO error: " + errorMsg);
                // Don't return, just continue with empty list
            } else {
            
            var detections = result.detections || [];
            var bottomCount = parseInt(result.bottom_count || 0, 10);
            var markingCount = parseInt(result.marking_count || 0, 10);
            var polarizedCount = parseInt(result.polarized_count || 0, 10);
            var bottomOnlyDetected = !!result.bottom_only_detected;
            logMessage("YOLO polarized workflow summary: detections=" + detections.length + 
                       ", bottom_count=" + bottomCount + 
                       ", marking_count=" + markingCount + 
                       ", polarized_count=" + polarizedCount + 
                       ", bottom_only_detected=" + bottomOnlyDetected);
            if (bottomOnlyDetected) {
                logMessage("Bottom-only scene detected. Reserved hook point for future external vibrator signal.");
            }
            
            // Convert to RotatedRect
            for (var i = 0; i < detections.length; i++) {
                var det = detections[i];
                var centerX = parseFloat(det.center_x);
                var centerY = parseFloat(det.center_y);
                var width = parseFloat(det.width);
                var height = parseFloat(det.height);
                var angle = parseFloat(det.angle || 0.0);
                var conf = parseFloat(det.confidence || 0.0);
                var markerCenterX = parseFloat(det.marker_center_x || 0.0);
                var markerCenterY = parseFloat(det.marker_center_y || 0.0);
                var markerBoxX1 = parseFloat(det.marker_box_x1 || 0.0);
                var markerBoxY1 = parseFloat(det.marker_box_y1 || 0.0);
                var markerBoxX2 = parseFloat(det.marker_box_x2 || 0.0);
                var markerBoxY2 = parseFloat(det.marker_box_y2 || 0.0);
                
                // Preserve the angle from Python because it already encodes the marker-derived orientation.
                var center = new org.opencv.core.Point(centerX, centerY);
                var size = new org.opencv.core.Size(width, height);
                var rect = new org.opencv.core.RotatedRect(center, size, angle);
                
                detectedParts.add(rect);
                detectionDebugInfo.push({
                    centerX: centerX,
                    centerY: centerY,
                    markerCenterX: markerCenterX,
                    markerCenterY: markerCenterY,
                    markerBoxX1: markerBoxX1,
                    markerBoxY1: markerBoxY1,
                    markerBoxX2: markerBoxX2,
                    markerBoxY2: markerBoxY2
                });
                logMessage("  -> Added polarized component: center=(" + centerX.toFixed(1) + ", " + centerY.toFixed(1) + 
                          "), angle=" + angle.toFixed(1) + ", size=(" + width.toFixed(1) + ", " + 
                          height.toFixed(1) + "), conf=" + conf.toFixed(3) + 
                          ", marker=(" + markerCenterX.toFixed(1) + ", " + markerCenterY.toFixed(1) + ")");
            }
            } // end else (result.success)
        } catch (e) {
            logMessage("Error parsing YOLO JSON output: " + e);
            logMessage("Raw output: " + outputText);
        }
        
    } catch (e) {
        logMessage("Error in detectWithYolo: " + e);
        if (e.javaException) {
            logMessage("Java exception: " + e.javaException);
        }
    }
    
    return {
        parts: detectedParts,
        debugInfo: detectionDebugInfo
    };
}

// Main script execution
with (imports) {
    try {
        logMessage("=== Script main body starting ===");
        
        // Parse parameters
        var argsStr = typeof args !== "undefined" ? args : "";
        var params = parseArgs(argsStr);
        logMessage("Parsed parameters: yolo_model_path=" + params.yolo_model_path + 
                   ", yolo_confidence=" + params.yolo_confidence + 
                   ", python_exe=" + params.python_exe);
        
        // Check global variables
        var hasPipeline = typeof pipeline !== "undefined" && pipeline !== null;
        var hasStage = typeof stage !== "undefined" && stage !== null;
        logMessage("Global variable check: pipeline=" + hasPipeline + ", stage=" + hasStage);
        
        var result = null;
        
        if (!hasPipeline) {
            logMessage("Error: pipeline global variable does not exist");
            result = new CvStage.Result(null, new java.util.ArrayList());
        } else {
        
        // Get working image
        logMessage("Preparing to get working image...");
        var workingImage = pipeline.getWorkingImage();
        
        if (workingImage === null) {
            logMessage("Error: pipeline.getWorkingImage() returned null");
            result = new CvStage.Result(null, new java.util.ArrayList());
        } else {
        
        logMessage("Successfully got image: width=" + workingImage.width() + 
                   ", height=" + workingImage.height() + 
                   ", channels=" + workingImage.channels());
        
        logMessage("Starting image processing...");
        logMessage("Image info: width=" + workingImage.width() + 
                   ", height=" + workingImage.height() + 
                   ", channels=" + workingImage.channels());
        
        // Store recognized components
        var detectedParts = new java.util.ArrayList();
        var detectedPartDebugInfo = [];
        
        // Use YOLOv8 for detection
        logMessage("Using YOLOv8 model for detection");
        var detectionResult = detectWithYolo(workingImage, params);
        detectedParts = detectionResult.parts || new java.util.ArrayList();
        detectedPartDebugInfo = detectionResult.debugInfo || [];
        logMessage("YOLOv8 detection completed: found " + detectedParts.size() + " components");
        
        // Log recognition results
        logMessage("Recognition completed: Found " + detectedParts.size() + " components");
        if (detectedParts.size() > 0) {
            for (var i = 0; i < detectedParts.size(); i++) {
                var rect = detectedParts.get(i);
                logMessage("Component " + i + ": center=(" + rect.center.x.toFixed(1) + ", " + 
                          rect.center.y.toFixed(1) + "), angle=" + rect.angle.toFixed(1) + 
                          ", size=(" + rect.size.width.toFixed(1) + ", " + rect.size.height.toFixed(1) + ")");
            }
        } else {
            logMessage("Warning: No components recognized, please check parameter settings");
        }
        
        // Get result image (from capture stage for drawing)
        var resultImage = null;
        try {
            var captureResult = pipeline.getExpectedResult("capture");
            if (captureResult !== null && captureResult.image !== null) {
                resultImage = captureResult.image.clone();
                logMessage("Got capture image: " + resultImage.width() + "x" + resultImage.height() + 
                          ", " + resultImage.channels() + " channels");
                
                // Convert to color if grayscale
                if (resultImage.channels() === 1) {
                    var colorImage = new Mat();
                    Imgproc.cvtColor(resultImage, colorImage, Imgproc.COLOR_GRAY2BGR);
                    resultImage = colorImage;
                    logMessage("Converted grayscale to color: " + resultImage.width() + "x" + 
                              resultImage.height() + ", " + resultImage.channels() + " channels");
                }
                
                // Draw detection boxes
                if (detectedParts !== null && detectedParts.size() > 0) {
                    var redColor = new java.awt.Color(255, 0, 0);
                    var greenColor = new java.awt.Color(0, 255, 0);
                    var blueColor = new java.awt.Color(0, 128, 255);
                    var thickness = 8;
                    logMessage("Drawing " + detectedParts.size() + " detection boxes on image...");
                    
                    for (var i = 0; i < detectedParts.size(); i++) {
                        var rect = detectedParts.get(i);
                        try {
                            FluentCv.drawRotatedRect(resultImage, rect, redColor, thickness);
                            logMessage("  -> Drew box " + (i + 1) + " successfully");
                        } catch (e) {
                            logMessage("  -> Failed to draw box " + (i + 1) + ": " + e);
                        }

                        try {
                            if (i < detectedPartDebugInfo.length) {
                                var dbg = detectedPartDebugInfo[i];
                                var markerPoint = new org.opencv.core.Point(dbg.markerCenterX, dbg.markerCenterY);
                                var partCenter = new org.opencv.core.Point(dbg.centerX, dbg.centerY);
                                var markerRectP1 = new org.opencv.core.Point(dbg.markerBoxX1, dbg.markerBoxY1);
                                var markerRectP2 = new org.opencv.core.Point(dbg.markerBoxX2, dbg.markerBoxY2);
                                Imgproc.circle(resultImage, markerPoint, 14, new org.opencv.core.Scalar(0, 255, 0, 255), 3);
                                Imgproc.rectangle(resultImage, markerRectP1, markerRectP2, new org.opencv.core.Scalar(0, 255, 0, 255), 2);
                                Imgproc.line(resultImage, partCenter, markerPoint, new org.opencv.core.Scalar(255, 128, 0, 255), 2);
                                Imgproc.circle(resultImage, partCenter, 8, new org.opencv.core.Scalar(255, 128, 0, 255), 2);
                                logMessage("  -> Drew marker debug for box " + (i + 1) + " successfully");
                            }
                        } catch (e2) {
                            logMessage("  -> Failed to draw marker debug for box " + (i + 1) + ": " + e2);
                        }
                    }
                    
                    logMessage("Finished drawing all detection boxes");
                }
            }
        } catch (e) {
            logMessage("Error getting capture image or drawing: " + e);
            resultImage = workingImage.clone();
        }
        
        if (resultImage === null) {
            resultImage = workingImage.clone();
        }
        
        // Create final model list (ensure it's a pure Java ArrayList)
        var finalModel = new java.util.ArrayList();
        for (var i = 0; i < detectedParts.size(); i++) {
            var rect = detectedParts.get(i);
            if (rect instanceof org.opencv.core.RotatedRect) {
                finalModel.add(rect);
            }
        }
        
        logMessage("Created final Java ArrayList with " + finalModel.size() + " RotatedRect(s)");
        logMessage("Returning result with " + finalModel.size() + " RotatedRect(s) in model");
        
        // Get color space
        var colorSpace = pipeline.getWorkingColorSpace();
        
        // Create and return Result object
        // JavaScript-Rhino has better Java interoperability than Jython
        // The model should be properly accessible when CvPipeline.process() extracts it
        result = new CvStage.Result(resultImage, colorSpace, finalModel);
        
        logMessage("Result created: image=" + (result.image !== null ? "not null" : "null") + 
                   ", model=" + (result.model !== null ? "not null" : "null") + 
                   ", model.size=" + (result.model !== null ? result.model.size() : 0));
        
        // Verify model is accessible (JavaScript-Rhino should preserve Java objects correctly)
        if (result.model !== null) {
            var modelClass = result.model.getClass();
            var isList = result.model instanceof java.util.List;
            logMessage("Result.model verification: type=" + modelClass.getName() + 
                       ", is List=" + isList + 
                       ", size=" + result.model.size());
            
            // Verify interfaces
            var interfaces = modelClass.getInterfaces();
            var interfaceNames = [];
            for (var i = 0; i < interfaces.length; i++) {
                interfaceNames.push(interfaces[i].getName());
            }
            logMessage("Result.model interfaces: " + interfaceNames.join(", "));
            
            if (result.model.size() > 0) {
                var firstRect = result.model.get(0);
                logMessage("Verified model accessibility: first element type=" + firstRect.getClass().getSimpleName());
            }
        }
        
        logMessage("=== Script execution ended ===");
        logMessage("FINAL: Returning Result with model type=" + (result.model !== null ? result.model.getClass().getName() : "null") + 
                   ", size=" + (result.model !== null ? result.model.size() : 0) + 
                   ", is List=" + (result.model !== null ? (result.model instanceof java.util.List) : false));
        
        } // end else (workingImage !== null)
        } // end else (hasPipeline)
        
        // Return the result - this is what OpenPnP's ScriptRun stage will use
        // In JavaScript/Rhino, the last expression is the return value (no return statement needed)
        // JavaScript-Rhino should properly preserve the model field when Java accesses it
        if (result === null) {
            result = new CvStage.Result(null, new java.util.ArrayList());
        }
        result;
        
    } catch (e) {
        logMessage("CRITICAL ERROR in script: " + e);
        if (e.javaException) {
            logMessage("Java exception: " + e.javaException);
        }
        // Return empty result on error - last expression is return value
        new CvStage.Result(null, new java.util.ArrayList());
    }
}
